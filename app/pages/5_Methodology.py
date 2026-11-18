"""Methodology: each step in plain English, its formula, and the selected company's real numbers."""

import math
import re

import pandas as pd
import streamlit as st

from capex_tracker.config import REPO_ROOT
from capex_tracker.data.panel import companies, load_company, run_sensitivity
from capex_tracker.format import pct, usd_b
from capex_tracker.models.sensitivity import flips
from capex_tracker.worked_example import worked_example

st.set_page_config(page_title="Methodology", layout="wide")
COMPANIES = companies()

TEXT = (REPO_ROOT / "docs" / "methodology_page.md").read_text()
TEXT = re.sub(r"<!--.*?-->", "", TEXT, flags=re.S)
SECTIONS = {m.group(1): m.group(0) for m in re.finditer(r"^## (\d|Known limits)[^\n]*\n.*?(?=^## |\Z)", TEXT,
                                                         flags=re.S | re.M)}


@st.cache_data
def sensitivity_flips() -> pd.DataFrame:
    return flips(run_sensitivity())


ticker = st.sidebar.selectbox("Worked example for", list(COMPANIES),
                              format_func=lambda t: f"{COMPANIES[t]['name']} ({t})")
data = load_company(ticker)
ex = worked_example(data)
name = data.name

st.title("How the estimates work")
st.caption(f"Each step in plain words, then the same step with {name}'s actual numbers under the default "
           "assumptions. Every number on this page is computed live by the same code as the other pages.")


def step(n, lines):
    st.markdown(SECTIONS[str(n)])
    with st.container(border=True):
        st.markdown(f"**Worked example: {name}**")
        st.markdown("\n".join(f"- {line}" for line in lines))


def when(d):
    return d.strftime("%b %Y") if d is not None else "not within 6 years"


e = ex[1]
step(1, [
    f"Latest quarter: **{e['quarter']}** (fiscal {e['fiscal']}), ending {e['period_end'].date()}.",
    f"Revenue {usd_b(e['revenue'])} · source filing {e['revenue_source']}",
    f"Capex {usd_b(e['capex'])} · source filing {e['capex_source']}",
    f"{e['segment']} revenue {usd_b(e['segment_revenue'])} · source filing {e['segment_source']}",
])

e = ex[2]
step(2, [f"Baseline: **{e['first']} to {e['last']}**, {e['n_quarters']} quarters with both capex and revenue."])

e = ex[3]
step(3, [
    f"Baseline intensity = {usd_b(e['capex_sum'])} capex ÷ {usd_b(e['revenue_sum'])} revenue = **{pct(e['intensity'])}**",
    f"Latest quarter: baseline capex = {pct(e['intensity'])} × {usd_b(e['revenue'])} = {usd_b(e['baseline_capex'])}",
    f"Excess capex = {usd_b(e['capex'])} − {usd_b(e['baseline_capex'])} = **{usd_b(e['excess_capex'])}**",
    f"Cumulative excess capex since {e['since']} ({e['n_after']} quarters): **{usd_b(e['cumulative'], 0)}**",
])

e = ex[4]
trend_desc = (f"+{usd_b(e['per_year'])} a year" if e["shape"] == "linear" else "constant % growth")
step(4, [
    f"Pre-AI trend for {data.segment}: {trend_desc}, fitted with R² {e['r_squared']:.3f}; this quarter's "
    f"seasonal adjustment {usd_b(e['seasonal'], sign=True)}",
    f"Latest quarter: actual {usd_b(e['actual'])} − trend {usd_b(e['trend'])} = **{usd_b(e['excess'])} excess revenue**",
    f"Excess profit = {usd_b(e['excess'])} × {pct(e['margin'])} = **{usd_b(e['excess_profit'])}** "
    f"(margin: {e['margin_label'].lower()})",
])

e = ex[5]
years = ("never at the current rate" if e["payback_years"] == math.inf
         else f"**{e['payback_years']:.1f} years**")
step(5, [
    f"Return so far = {usd_b(e['cumulative_profit'])} cumulative excess profit ÷ {usd_b(e['cumulative_capex'], 0)} "
    f"cumulative excess capex = **{pct(e['return_so_far'], 0)}**",
    f"Annualized excess profit = latest quarter × 4 = {usd_b(e['annualized_profit'])}",
    f"Implied payback = {usd_b(e['cumulative_capex'], 0)} ÷ {usd_b(e['annualized_profit'])} = {years}",
])

e = ex[6]
step(6, [
    f"Latest quarter's capex {usd_b(e['capex'])}: servers {pct(e['server_share'], 0)} over {e['server_life']:g} years "
    f"= {usd_b(e['server_per_q'], 2)} a quarter; buildings {pct(1 - e['server_share'], 0)} over "
    f"{e['building_life']:g} years = {usd_b(e['building_per_q'], 2)} a quarter, starting next quarter",
    f"Calibration: model scaled by **{e['calibration']:.2f}** to match reported depreciation",
    f"In 2 years, depreciation runs {usd_b(e['extra_dep_2y'])} a year above today's; ÷ {usd_b(e['revenue_ttm'], 0)} "
    f"annual revenue = **{e['change_2y']:+.1f} margin points** ({pct(e['margin_today'])} → {pct(e['margin_2y'])})",
    f"Biggest rise in depreciation: **{e['peak_year']}**",
])

e = ex[7]
step(7, [
    f"**{k}**: growth {pct(v['start'], 0)} → {pct(v['end'], 0)} over {v['fade']:g} years; pays back spend to date "
    f"{when(v['payback'])}, including further spend {when(v['payback_with_spend'])}; operating margin in 6 years "
    f"{pct(v['margin_end'], 0)}"
    for k, v in e.items()
])

fl = sensitivity_flips()
flipped = fl[fl["flips"]]
step(8, [f"**{r.variant}**: {r.what_changes}" for r in flipped.itertuples()] or
     ["No conclusion flips under the alternatives tested."])

st.markdown(SECTIONS["Known limits"])
