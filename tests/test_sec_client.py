"""SEC client tests. A fake session stands in for the network; nothing calls SEC."""

from datetime import datetime, timedelta, timezone

import pytest

from capex_tracker.data.sec_client import (
    HttpCache, RateLimiter, SecClient, SecUserAgentMissing, pad_cik, user_agent_from_env,
)

TICKERS = {"0": {"cik_str": 789019, "ticker": "MSFT", "title": "MICROSOFT CORP"}}


class FakeResponse:
    def __init__(self, payload):
        self.payload = payload

    def raise_for_status(self):
        pass

    def json(self):
        return self.payload


class FakeSession:
    def __init__(self):
        self.calls = []

    def get(self, url, headers, timeout):
        self.calls.append((url, headers))
        if url.endswith("company_tickers.json"):
            return FakeResponse(TICKERS)
        return FakeResponse({"cik": 789019, "facts": {}})


class Clock:
    def __init__(self):
        self.t = datetime(2026, 1, 1, tzinfo=timezone.utc)

    def __call__(self):
        return self.t


def make_client(clock=None):
    session = FakeSession()
    client = SecClient(user_agent="Test test@example.com", cache=HttpCache(":memory:"),
                       session=session, rate_limiter=RateLimiter(sleep=lambda s: None),
                       now=clock or Clock())
    return client, session


def test_user_agent_required(monkeypatch):
    monkeypatch.delenv("SEC_USER_AGENT", raising=False)
    with pytest.raises(SecUserAgentMissing):
        user_agent_from_env()
    monkeypatch.setenv("SEC_USER_AGENT", "A b@c.d")
    assert user_agent_from_env() == "A b@c.d"


def test_pad_cik():
    assert pad_cik(789019) == "0000789019"
    assert pad_cik("320193") == "0000320193"


def test_company_facts_uses_padded_cik_and_user_agent():
    client, session = make_client()
    assert client.ticker_to_cik("msft") == "0000789019"
    client.company_facts("MSFT")
    url, headers = session.calls[-1]
    assert url == "https://data.sec.gov/api/xbrl/companyfacts/CIK0000789019.json"
    assert headers["User-Agent"] == "Test test@example.com"


def test_unknown_ticker():
    client, _ = make_client()
    with pytest.raises(KeyError):
        client.ticker_to_cik("NOPE")


def test_cache_hit_within_ttl_and_refetch_after():
    clock = Clock()
    client, session = make_client(clock)
    client.company_facts("MSFT")
    client.company_facts("MSFT")
    assert len(session.calls) == 2  # tickers + facts once each

    clock.t += timedelta(hours=23)
    client.company_facts("MSFT")
    assert len(session.calls) == 2

    clock.t += timedelta(hours=2)  # 25h after first fetch
    client.company_facts("MSFT")
    assert len(session.calls) == 4


def test_rate_limiter_spaces_requests():
    t = [0.0]
    slept = []

    def sleep(s):
        slept.append(s)
        t[0] += s

    rl = RateLimiter(max_per_second=8, clock=lambda: t[0], sleep=sleep)
    rl.wait()
    rl.wait()
    t[0] += 1.0
    rl.wait()
    assert slept == [pytest.approx(0.125)]


def test_filings_reads_overflow_pages_and_filters():
    client, session = make_client()
    recent = {"accessionNumber": ["a3", "a4", "a5"], "form": ["10-Q", "4", "10-K/A"],
              "filingDate": ["2024-05-01", "2024-05-02", "2024-06-01"], "reportDate": ["2024-03-31", "", ""]}
    older = {"accessionNumber": ["a1", "a2"], "form": ["10-K", "10-Q"],
             "filingDate": ["2017-02-01", "2018-05-01"], "reportDate": ["2016-12-31", "2018-03-31"]}
    pages = {
        "CIK0000789019.json": {"filings": {"recent": recent, "files": [
            {"name": "CIK0000789019-submissions-001.json", "filingTo": "2023-12-31"},
            {"name": "CIK0000789019-submissions-000.json", "filingTo": "2016-12-31"}]}},
        "CIK0000789019-submissions-001.json": older,
    }
    def get(url, headers, timeout):
        session.calls.append((url, headers))
        if url.endswith("company_tickers.json"):
            return FakeResponse(TICKERS)
        return FakeResponse(pages[url.rsplit("/", 1)[1]])
    session.get = get
    got = client.filings("MSFT")
    assert [f["accn"] for f in got] == ["a2", "a3"]  # 2017, Form 4 and amendment dropped
    assert not any(u.endswith("-000.json") for u, _ in session.calls)  # page before 2018 not fetched
