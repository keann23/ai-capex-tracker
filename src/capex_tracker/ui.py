"""Shared page chrome for the Streamlit app: page setup and the footer every page shows."""

from __future__ import annotations

import streamlit as st

from capex_tracker.data.panel import companies, load_company

APP_NAME = "AI Capex Payback Tracker"
REPO_URL = "https://github.com/keann23/ai-capex-tracker"


def page_setup(title: str | None = None) -> None:
    st.set_page_config(page_title=f"{title} · {APP_NAME}" if title else APP_NAME, layout="wide")


def latest_filing_date():
    return max(load_company(t).data_through for t in companies())


def footer() -> None:
    st.divider()
    st.caption(
        f"**Estimates, not reported figures.** Data: SEC EDGAR filings, latest used "
        f"{latest_filing_date():%d %b %Y}: company-wide figures from SEC companyfacts, segment revenue from "
        f"each 10-Q/10-K's XBRL, capex guidance from earnings releases and calls (sources listed on the "
        f"Depreciation Wave page). Updated each quarter. [Method](/Methodology) · [Code and data]({REPO_URL})"
    )
