"""Home: scorecard across companies and the headline finding (default assumptions)."""

import pandas as pd
import streamlit as st

from capex_tracker.data.panel import companies, company_wave, default_assumptions, load_company
from capex_tracker.format import pct, usd_b
from capex_tracker.models.excess import attribute
from capex_tracker.models.payback import headline, payback, scorecard_row

st.set_page_config(page_title="AI Capex Payback Tracker", layout="wide")


@st.cache_data
def build_scorecard(shape: str) -> pd.DataFrame:
    rows = []
    for t in companies():
        d = load_company(t)
        q = d.quarters
        att = attribute(q["capex"], q["revenue"], q["segment_revenue"], default_assumptions(d, shape))
        w = company_wave(d, horizon_quarters=16)   # same 4-year wave as the Depreciation Wave page
        rows.append(scorecard_row(t, d.name, d.segment, payback(att)) | {
            "margin": d.margin, "peak_dep_year": w.peak_increase_year(),
            "margin_change_2y": w.margin_path()["margin_change_pts"].iloc[7]})
    return pd.DataFrame(rows)


score = build_scorecard("linear")
alt = build_scorecard("log")
data_through = max(load_company(t).data_through for t in companies())

st.title("AI Capex Payback Tracker")
st.markdown(
    "Big Tech doesn't report AI spending or AI revenue. This tracker **estimates** both by comparing each "
    "company with its own pre-ChatGPT baseline, then asks how long the extra profit takes to cover the extra spend."
)

st.info(headline(score, alt, "with constant-% revenue growth"))

years = score["implied_payback_years"].map(lambda y: "never at current rate" if y == float("inf")
                                           else ("—" if pd.isna(y) else f"{y:.1f}"))
table = pd.DataFrame({
    "Company": score["company"] + " (" + score["ticker"] + ")",
    "Tracked line": score["segment"],
    "Cumulative excess capex": score["cumulative_excess_capex"].map(lambda v: usd_b(v, 0)),
    "Annualized excess revenue": score["annualized_excess_revenue"].map(usd_b),
    "Annualized excess profit": score["annualized_excess_profit"].map(usd_b),
    "Return so far": score["return_so_far"].map(lambda v: pct(v, 0)),
    "Implied payback (yrs)": years,
    "Status": score["status"],
    "Biggest depreciation rise": score["peak_dep_year"].map(lambda y: "—" if pd.isna(y) else str(int(y))),
    "Margin change in 2 yrs": score["margin_change_2y"].map(lambda v: f"{v:+.1f} pts"),
    "Through": score["as_of"].map(lambda d: d.date() if pd.notna(d) else "—"),
})
st.subheader("Scorecard (all figures are estimates)")
st.dataframe(table, hide_index=True, width="stretch")

st.caption(
    "**Excess capex**: capex above the 2019–22 capex-to-revenue ratio, summed since Q4 2022. "
    "**Excess revenue**: tracked line above its 2019–22 trend (constant-$ growth, seasonal), latest quarter × 4. "
    "**Excess profit**: excess revenue × the line's operating margin. "
    "**Return so far**: cumulative excess profit ÷ cumulative excess capex. "
    "**Implied payback**: years of today's excess profit needed to cover the excess capex spent so far "
    "(ignores further spend). **Biggest depreciation rise**: year modeled depreciation rises most, from actual "
    "capex plus management guidance. **Margin change in 2 yrs**: operating margin change from extra depreciation "
    "alone, revenue and other costs held flat."
)
st.page_link("pages/1_Company_Deep_Dive.py", label="Change the assumptions for one company →")
st.page_link("pages/2_Depreciation_Wave.py", label="See when the spending hits margins →")
st.page_link("pages/3_Scenarios.py", label="Bull, base and bear: when does it pay back? →")
st.page_link("pages/4_Sensitivity.py", label="Which assumptions change the answer? →")
st.page_link("pages/5_Methodology.py", label="How the estimates work, step by step →")
st.caption(f"Data: SEC EDGAR (companyfacts and each 10-Q/10-K's XBRL). Latest filing used: {data_through.date()}.")
