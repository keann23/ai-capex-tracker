"""SEC EDGAR client: ticker -> CIK, companyfacts fetch, rate limit, DuckDB cache.

The User-Agent comes from the SEC_USER_AGENT env var and is never hardcoded.
Responses are cached in DuckDB for 24 hours so the app and reruns don't hit SEC.
"""

from __future__ import annotations

import json
import os
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Callable

import duckdb
import requests

from capex_tracker.config import REPO_ROOT

TICKERS_URL = "https://www.sec.gov/files/company_tickers.json"
COMPANYFACTS_URL = "https://data.sec.gov/api/xbrl/companyfacts/CIK{cik}.json"
SUBMISSIONS_URL = "https://data.sec.gov/submissions/{name}"
FILING_INDEX_URL = "https://www.sec.gov/Archives/edgar/data/{cik}/{accn}/index.json"
FILING_FILE_URL = "https://www.sec.gov/Archives/edgar/data/{cik}/{accn}/{name}"

DEFAULT_CACHE_PATH = REPO_ROOT / "data" / "sec_cache.duckdb"
DEFAULT_TTL = timedelta(hours=24)
MAX_REQUESTS_PER_SECOND = 8  # SEC allows 10; stay under it


class SecUserAgentMissing(RuntimeError):
    pass


def user_agent_from_env() -> str:
    ua = os.environ.get("SEC_USER_AGENT", "").strip()
    if not ua:
        raise SecUserAgentMissing(
            'Set SEC_USER_AGENT, e.g. export SEC_USER_AGENT="Your Name your-email". '
            "SEC rejects requests without it."
        )
    return ua


def pad_cik(cik: int | str) -> str:
    return str(int(cik)).zfill(10)


class RateLimiter:
    """Spaces calls at least 1/max_per_second apart."""

    def __init__(
        self,
        max_per_second: float = MAX_REQUESTS_PER_SECOND,
        clock: Callable[[], float] = time.monotonic,
        sleep: Callable[[float], None] = time.sleep,
    ):
        self.min_interval = 1.0 / max_per_second
        self.clock = clock
        self.sleep = sleep
        self._last: float | None = None

    def wait(self) -> None:
        now = self.clock()
        if self._last is not None:
            gap = self.min_interval - (now - self._last)
            if gap > 0:
                self.sleep(gap)
                now = self.clock()
        self._last = now


class HttpCache:
    """URL -> JSON body cache in a DuckDB file."""

    def __init__(self, path: Path | str = DEFAULT_CACHE_PATH):
        if str(path) != ":memory:":
            Path(path).parent.mkdir(parents=True, exist_ok=True)
        self.con = duckdb.connect(str(path))
        self.con.execute(
            "CREATE TABLE IF NOT EXISTS http_cache ("
            " url VARCHAR PRIMARY KEY, fetched_at_epoch DOUBLE, body VARCHAR)"
        )

    def get(self, url: str, max_age: timedelta, now: datetime) -> dict | None:
        row = self.con.execute(
            "SELECT fetched_at_epoch, body FROM http_cache WHERE url = ?", [url]
        ).fetchone()
        if row is None:
            return None
        fetched_at, body = row
        if now.timestamp() - fetched_at > max_age.total_seconds():
            return None
        return json.loads(body)

    def put(self, url: str, payload: dict, now: datetime) -> None:
        self.con.execute(
            "INSERT OR REPLACE INTO http_cache VALUES (?, ?, ?)",
            [url, now.timestamp(), json.dumps(payload)],
        )


class SecClient:
    def __init__(
        self,
        user_agent: str | None = None,
        cache: HttpCache | None = None,
        ttl: timedelta = DEFAULT_TTL,
        session: requests.Session | None = None,
        rate_limiter: RateLimiter | None = None,
        now: Callable[[], datetime] = lambda: datetime.now(timezone.utc),
    ):
        self.user_agent = user_agent or user_agent_from_env()
        self.cache = cache if cache is not None else HttpCache()
        self.ttl = ttl
        self.session = session or requests.Session()
        self.rate_limiter = rate_limiter or RateLimiter()
        self.now = now

    def get_json(self, url: str) -> dict:
        now = self.now()
        cached = self.cache.get(url, self.ttl, now)
        if cached is not None:
            return cached
        payload = self._request(url).json()
        self.cache.put(url, payload, now)
        return payload

    def get_text(self, url: str) -> str:
        """Uncached text download (XBRL instances are large; callers keep what they need)."""
        return self._request(url).text

    def _request(self, url: str):
        self.rate_limiter.wait()
        resp = self.session.get(
            url,
            headers={"User-Agent": self.user_agent, "Accept-Encoding": "gzip, deflate"},
            timeout=60,
        )
        resp.raise_for_status()
        return resp

    def ticker_to_cik(self, ticker: str) -> str:
        """10-digit zero-padded CIK for a ticker."""
        table = self.get_json(TICKERS_URL)
        for row in table.values():
            if row["ticker"].upper() == ticker.upper():
                return pad_cik(row["cik_str"])
        raise KeyError(f"Ticker {ticker!r} not found in SEC company_tickers.json")

    def company_facts(self, ticker: str) -> dict:
        return self.get_json(COMPANYFACTS_URL.format(cik=self.ticker_to_cik(ticker)))

    def filings(self, ticker: str, forms=("10-Q", "10-K"), since: str = "2018-01-01") -> list[dict]:
        """10-Q/10-K filings (no amendments) filed on or after `since`, oldest first.

        Reads the submissions feed, including its older overflow pages, since
        companies with many Form 4s push 2018 filings out of the 'recent' block.
        """
        cik = self.ticker_to_cik(ticker)
        sub = self.get_json(SUBMISSIONS_URL.format(name=f"CIK{cik}.json"))
        blocks = [sub["filings"]["recent"]]
        for page in sub["filings"].get("files", []):
            if page.get("filingTo", "9999") >= since:
                blocks.append(self.get_json(SUBMISSIONS_URL.format(name=page["name"])))
        out = {}
        for b in blocks:
            for i, form in enumerate(b["form"]):
                if form in forms and b["filingDate"][i] >= since:
                    out[b["accessionNumber"][i]] = {
                        "accn": b["accessionNumber"][i], "form": form,
                        "filed": b["filingDate"][i], "report_date": b["reportDate"][i],
                    }
        return sorted(out.values(), key=lambda f: f["filed"])

    def xbrl_instance(self, ticker: str, accn: str) -> str:
        """The XBRL instance document (XML text) of one filing."""
        cik = str(int(self.ticker_to_cik(ticker)))
        folder = accn.replace("-", "")
        names = [i["name"] for i in self.get_json(
            FILING_INDEX_URL.format(cik=cik, accn=folder))["directory"]["item"]]
        name = pick_instance(names)
        if name is None:
            raise FileNotFoundError(f"No XBRL instance in filing {accn}")
        return self.get_text(FILING_FILE_URL.format(cik=cik, accn=folder, name=name))


def pick_instance(names: list[str]) -> str | None:
    """Choose the instance file from a filing folder listing.

    Inline-XBRL filings (2019+) have an SEC-extracted '<doc>_htm.xml'; older ones
    have '<ticker>-<date>.xml' next to the _cal/_def/_lab/_pre linkbases.
    """
    htm = [n for n in names if n.endswith("_htm.xml")]
    if htm:
        return htm[0]
    skip = ("_cal.xml", "_def.xml", "_lab.xml", "_pre.xml")
    xml = [n for n in names if n.endswith(".xml") and not n.endswith(skip)
           and n != "FilingSummary.xml" and not n.startswith("R")]
    return xml[0] if len(xml) == 1 else None
