"""Pull segment revenue (and segment operating income) from every 10-Q/10-K XBRL.

    python scripts/fetch_segments.py            # download (asks for SEC contact) + rebuild
    python scripts/fetch_segments.py --offline  # rebuild config/segments.csv from saved facts
    python scripts/fetch_segments.py MSFT       # just one company

Downloads ~30 filings per company. Saves the trimmed facts to
tests/fixtures/segment_facts/<TICKER>.csv.gz, then writes config/segments.csv
with each value's source accession number.
"""

from __future__ import annotations

import argparse
import os
import sys
from datetime import date

from capex_tracker.config import CONFIG_DIR, REPO_ROOT, load_companies
from capex_tracker.data.sec_client import SecClient
from capex_tracker.data.segments_xbrl import (
    build_segments_table, fetch_revenue_facts, load_facts, restatements, segment_members,
    segment_quarters, suspicious_quarters,
)

FACT_DIR = REPO_ROOT / "tests" / "fixtures" / "segment_facts"


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("tickers", nargs="*")
    ap.add_argument("--offline", action="store_true", help="skip downloading; rebuild from saved facts")
    args = ap.parse_args()
    companies = load_companies()["companies"]
    tickers = args.tickers or list(companies)

    if not args.offline:
        ua = os.environ.get("SEC_USER_AGENT", "").strip()
        if not ua and sys.stdin.isatty():
            ua = input('SEC contact, e.g. "Your Name your-email": ').strip()
        client = SecClient(user_agent=ua or None)
        FACT_DIR.mkdir(parents=True, exist_ok=True)
        for t in tickers:
            print(f"{t}: downloading filings")
            facts = fetch_revenue_facts(client, t)
            facts.to_csv(FACT_DIR / f"{t}.csv.gz", index=False)
            print(f"{t}: saved {len(facts)} facts")

    table = build_segments_table(companies, FACT_DIR, date.today())
    table.to_csv(CONFIG_DIR / "segments.csv", index=False)
    print(f"\nWrote {len(table)} rows to config/segments.csv\n")

    for t in tickers:
        path = FACT_DIR / f"{t}.csv.gz"
        if not path.exists():
            print(f"{t}: no saved facts")
            continue
        facts = load_facts(path)
        rows = table[table["company"] == t] if not table.empty else table
        print(f"{t}: {len(rows)} quarters"
              + (f", {rows['period_end'].min()} .. {rows['period_end'].max()}" if len(rows) else ""))
        if len(rows) == 0:
            print("  segment not matched. Revenue members in latest 10-K:")
            print(segment_members(facts).to_string(index=False))
        spec = companies[t]["segment_xbrl"]
        r = restatements(facts, spec)
        if len(r):
            print(f"  {len(r)} quarter(s) restated between filings (latest value used)")
        bad = suspicious_quarters(segment_quarters(facts, spec))
        if len(bad):
            print(f"  CHECK: quarters far below both neighbours: {bad['end'].dt.date.tolist()}")


if __name__ == "__main__":
    main()
