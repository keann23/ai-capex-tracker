"""Home: scorecard across companies. Phase 0 placeholder, no data logic yet."""

from pathlib import Path

import pandas as pd
import streamlit as st
import yaml

CONFIG = Path(__file__).resolve().parent.parent / "config" / "companies.yaml"

st.set_page_config(page_title="AI Capex Payback Tracker", layout="wide")

st.title("AI Capex Payback Tracker")
st.caption(
    "Estimates of AI-attributable capex, revenue, payback and depreciation "
    "for the hyperscalers. All figures are estimates."
)

st.info("Headline finding will appear here once the data layer is built.")

companies = yaml.safe_load(CONFIG.read_text())["companies"]

columns = [
    "Cumulative excess capex",
    "Annualized excess revenue",
    "Return so far",
    "Implied payback (yrs)",
    "Peak depreciation year",
    "Projected margin hit (pts)",
]
scorecard = pd.DataFrame(
    [
        {"Ticker": t, "Company": c["name"], "Tracked segment": c["segment"]}
        | {col: None for col in columns}
        for t, c in companies.items()
    ]
)

st.subheader("Scorecard (estimates)")
st.dataframe(scorecard, hide_index=True, width="stretch")
st.caption("Empty cells are missing data, not zero. Last updated: not yet run. Source: SEC EDGAR companyfacts.")
