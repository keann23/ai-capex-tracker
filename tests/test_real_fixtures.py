"""Checks on real SEC data saved by scripts/fetch_companyfacts.py.

Skipped for any company whose fixture hasn't been fetched yet.
annual_checks.csv holds annual figures typed in by hand from each 10-K.
"""

import json
from pathlib import Path

import pandas as pd
import pytest

from capex_tracker.config import SNAPSHOT_DIR, fiscal_year_end_month, load_companies, load_tag_map
from capex_tracker.data.standardize import (
    _is_annual, dedupe, extract_facts, fiscal_year_totals, standardize_company,
)

FIXTURES = Path(__file__).parent / "fixtures"
COMPANIES = load_companies()["companies"]
TAG_MAP = load_tag_map()


def load(ticker):
    path = SNAPSHOT_DIR / "companyfacts" / f"{ticker}.json"
    if not path.exists():
        pytest.skip(f"no fixture for {ticker}; run scripts/fetch_companyfacts.py")
    facts = json.loads(path.read_text())
    return facts, standardize_company(facts, TAG_MAP, fiscal_year_end_month(COMPANIES[ticker]))


def reported_fy(facts, long, item):
    """FY values as filed in 10-Ks, using the tag the quarters came from for that year."""
    out = {}
    for fy, tags in long[long["item"] == item].groupby("fiscal_year")["tag"]:
        if tags.nunique() != 1:
            continue
        f = dedupe(extract_facts(facts, tags.iloc[0]))
        f = f[_is_annual((f["end"] - f["start"]).dt.days)]
        match = long[(long["item"] == item) & (long["fiscal_year"] == fy)]["period_end"].max()
        hit = f[f["end"] == match]
        if len(hit) == 1:
            out[fy] = hit["val"].iloc[0]
    return pd.Series(out, dtype=float)


@pytest.mark.parametrize("ticker", list(COMPANIES))
@pytest.mark.parametrize("item", ["revenue", "capex"])
def test_quarters_sum_to_reported_fiscal_year(ticker, item):
    facts, long = load(ticker)
    totals = fiscal_year_totals(long, item)
    reported = reported_fy(facts, long, item)
    common = totals.index.intersection(reported.index)
    assert len(common) >= 5, f"{ticker} {item}: only {len(common)} comparable years"
    # Tolerance: companies report in rounded millions, and later restatements of
    # single quarters don't always reconcile exactly (Alphabet 2015 capex: 0.23%).
    tol = (reported[common].abs() * 0.005).clip(lower=5e6)
    diff = (totals[common] - reported[common]).abs()
    assert (diff <= tol).all(), f"{ticker} {item} quarter sums off FY:\n{diff[diff > tol]}"


@pytest.mark.parametrize("ticker", list(COMPANIES))
def test_core_items_have_eight_years(ticker):
    _, long = load(ticker)
    for item in ["revenue", "capex", "operating_income", "cfo"]:
        n = (long["item"] == item).sum()
        assert n >= 32, f"{ticker} {item}: only {n} quarters"


def test_annual_figures_match_10k():
    checks = pd.read_csv(FIXTURES / "annual_checks.csv")
    if checks.empty:
        pytest.skip("annual_checks.csv has no rows yet")
    failures = []
    for c in checks.itertuples():
        _, long = load(c.ticker)
        got = fiscal_year_totals(long, c.item).get(c.fiscal_year)
        if got is None or abs(got - c.value_usd) > 1e6:
            failures.append(f"{c.ticker} FY{c.fiscal_year} {c.item}: 10-K {c.value_usd:,.0f}, got {got}")
    assert not failures, "\n".join(failures)
