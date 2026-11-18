"""One entry point for the app: standardized quarterly data for a ticker."""

from __future__ import annotations

import pandas as pd

from capex_tracker.config import fiscal_year_end_month, load_companies, load_tag_map
from capex_tracker.data.sec_client import SecClient
from capex_tracker.data.standardize import Keep, standardize_company


def load_company(ticker: str, client: SecClient | None = None, keep: Keep = "latest") -> pd.DataFrame:
    company = load_companies()["companies"][ticker]
    facts = (client or SecClient()).company_facts(ticker)
    return standardize_company(facts, load_tag_map(), fiscal_year_end_month(company), keep)
