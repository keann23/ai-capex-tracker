"""Bull / base / bear: when does the AI spend pay back, and what happens to margins?"""

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from capex_tracker.data.panel import (
    SCENARIO_QUARTERS, companies, company_scenarios, default_assumptions, load_company,
)
from capex_tracker.format import pct, usd_b
from capex_tracker.models.excess import attribute
from capex_tracker.models.scenarios import Scenario, default_scenarios
from capex_tracker.ui import footer, page_setup

page_setup('Scenarios')
COMPANIES = companies()
COLORS = {"Bull": "#2f8f5b", "Base": "#3b6fd8", "Bear": "#c2532f"}
YEARS = SCENARIO_QUARTERS // 4


def when(d):
    return "already" if d == "already" else (d.strftime("%b %Y") if d is not None else f"not within {YEARS} yrs")


@st.cache_data(show_spinner='Running three scenarios for all five companies…')
def summary() -> pd.DataFrame:
    rows = []
    for t in COMPANIES:
        d = load_company(t)
        att, res = company_scenarios(d)
        for r in res:
            rows.append({"Company": d.name, "Scenario": r.scenario.name,
                         "Pays back spend to date": when("already" if r.already_paid_back else r.payback_ignoring_spend),
                         "Pays back incl. further spend": when(r.payback_with_spend),
                         "Op. margin in 2 yrs": pct(r.path["operating_margin"].iloc[7], 0),
                         f"Op. margin in {YEARS} yrs": pct(r.path["operating_margin"].iloc[-1], 0)})
    return pd.DataFrame(rows)


with st.sidebar:
    ticker = st.selectbox("Company", list(COMPANIES), format_func=lambda t: f"{COMPANIES[t]['name']} ({t})")
    data = load_company(ticker)
    q = data.quarters
    defaults = default_scenarios(attribute(q["capex"], q["revenue"], q["segment_revenue"], default_assumptions(data)))
    st.subheader(f"{data.segment} revenue growth")
    st.caption("Annual growth starts at 'now', moves in a straight line to 'later' over the fade years, then stays.")
    scenarios = []
    for s in defaults:
        with st.expander(s.name, expanded=s.name == "Base"):
            start = st.number_input("Growth now, %", value=round(s.start * 100, 1), step=1.0, key=f"{ticker}{s.name}s")
            end = st.number_input("Growth later, %", value=round(s.end * 100, 1), step=1.0, key=f"{ticker}{s.name}e")
            fade = st.number_input("Fade years", value=float(s.fade_years), min_value=0.0, max_value=6.0,
                                   step=0.5, key=f"{ticker}{s.name}f")
        scenarios.append(Scenario(s.name, start / 100, end / 100, fade))

att, results = company_scenarios(data, scenarios=scenarios)

st.title(f"{data.name}: scenarios")
st.caption(f"Defaults: **Bull** keeps today's growth ({pct(defaults[0].start, 0)}) fading to half; **Base** fades to "
           f"the pre-AI trend's growth ({pct(defaults[1].end, 0)}) over 3 years; **Bear** flattens. Excess revenue is "
           "projected revenue minus the pre-AI trend. All **estimates**; capex follows guidance, then is held.")

st.dataframe(pd.DataFrame([{
    "Scenario": r.scenario.name,
    "Growth": f"{pct(r.scenario.start, 0)} → {pct(r.scenario.end, 0)} over {r.scenario.fade_years:g} yrs",
    "Pays back spend to date": when("already" if r.already_paid_back else r.payback_ignoring_spend),
    "Pays back incl. further spend": when(r.payback_with_spend),
    f"Excess revenue in {YEARS} yrs (annualized)": usd_b(4 * r.path["excess_revenue"].iloc[-1]),
    "Op. margin in 2 yrs": pct(r.path["operating_margin"].iloc[7], 0),
    f"Op. margin in {YEARS} yrs": pct(r.path["operating_margin"].iloc[-1], 0),
} for r in results]), hide_index=True, width="stretch")


def layout(fig, ytitle, h=360):
    fig.update_layout(yaxis_title=ytitle, hovermode="x unified", height=h,
                      legend=dict(orientation="h", y=-0.15), margin=dict(t=20, b=10, l=10, r=10))
    return fig


# revenue paths
hist = att.revenue[att.revenue.index >= pd.Timestamp("2019-01-01")]
fig = go.Figure()
fig.add_trace(go.Scatter(x=hist.index, y=hist["segment_revenue"] / 1e9, name="Actual", line=dict(color="#222", width=2.5)))
future_idx = results[0].path.index
trend = att.trend.predict(hist.index.append(future_idx))
fig.add_trace(go.Scatter(x=trend.index, y=trend / 1e9, name="Pre-AI trend", line=dict(color="#8a8f98", dash="dash")))
for r in results:
    fig.add_trace(go.Scatter(x=r.path.index, y=r.path["segment_revenue"] / 1e9, name=r.scenario.name,
                             line=dict(color=COLORS[r.scenario.name])))
st.markdown(f"**{data.segment} revenue by scenario** · gap above the dashed trend = excess revenue (estimate)")
st.plotly_chart(layout(fig, "$B per quarter"), width="stretch")

# payback
fig = go.Figure()
for r in results:
    fig.add_trace(go.Scatter(x=r.path.index, y=r.path["cumulative_excess_profit"] / 1e9,
                             name=f"{r.scenario.name}: cumulative excess profit", line=dict(color=COLORS[r.scenario.name])))
base = next(r for r in results if r.scenario.name == "Base").path
fig.add_trace(go.Scatter(x=base.index, y=base["cumulative_excess_capex_fixed"] / 1e9, name="Excess capex to date",
                         line=dict(color="#555", dash="dot")))
fig.add_trace(go.Scatter(x=base.index, y=base["cumulative_excess_capex_with_spend"] / 1e9,
                         name="Excess capex incl. further spend (base)", line=dict(color="#555")))
st.markdown("**Payback** · where a profit line crosses a capex line (estimate)")
st.plotly_chart(layout(fig, "$B, cumulative since baseline"), width="stretch")

# margin
fig = go.Figure()
for r in results:
    fig.add_trace(go.Scatter(x=r.path.index, y=r.path["operating_margin"] * 100, name=r.scenario.name,
                             line=dict(color=COLORS[r.scenario.name])))
st.markdown("**Operating margin by scenario** · extra excess profit minus extra depreciation (estimate)")
st.plotly_chart(layout(fig, "Operating margin, %", 320), width="stretch")
st.caption("Margin = today's operating income and revenue, plus the change in excess profit and excess revenue, "
           "minus the change in depreciation from the depreciation wave. Other costs held at today's level.")

st.subheader("All companies, default scenarios")
st.dataframe(summary(), hide_index=True, width="stretch")

footer()
