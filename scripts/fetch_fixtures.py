"""Download companyfacts for each company and save trimmed test fixtures.

Run once (and whenever you want fresher fixtures):
    export SEC_USER_AGENT="Your Name your-email"
    python scripts/fetch_fixtures.py

Fixtures keep only the us-gaap tags listed in config/tag_map.yaml, which turns
several MB per company into a few hundred KB. Tests read these files and never
call SEC.
"""

from __future__ import annotations

import json
import os
import sys

from capex_tracker.config import REPO_ROOT, load_companies, load_tag_map
from capex_tracker.data.sec_client import SecClient

FIXTURE_DIR = REPO_ROOT / "tests" / "fixtures" / "companyfacts"


def trim(facts: dict, tags: set[str]) -> dict:
    us_gaap = facts.get("facts", {}).get("us-gaap", {})
    return {
        "cik": facts.get("cik"),
        "entityName": facts.get("entityName"),
        "facts": {"us-gaap": {t: {"units": {"USD": us_gaap[t]["units"].get("USD", [])}}
                              for t in sorted(tags) if t in us_gaap}},
    }


def main() -> None:
    tags = {t for spec in load_tag_map().values() for t in (spec.get("tags") or [])}
    ua = os.environ.get("SEC_USER_AGENT", "").strip()
    if not ua and sys.stdin.isatty():
        ua = input('SEC contact, e.g. "Your Name your-email": ').strip()
    client = SecClient(user_agent=ua or None)
    FIXTURE_DIR.mkdir(parents=True, exist_ok=True)
    for ticker in load_companies()["companies"]:
        trimmed = trim(client.company_facts(ticker), tags)
        path = FIXTURE_DIR / f"{ticker}.json"
        path.write_text(json.dumps(trimmed, separators=(",", ":"), sort_keys=True))
        found = sorted(trimmed["facts"]["us-gaap"])
        print(f"{ticker}: {path.stat().st_size // 1024} KB, tags: {', '.join(found)}")


if __name__ == "__main__":
    main()
