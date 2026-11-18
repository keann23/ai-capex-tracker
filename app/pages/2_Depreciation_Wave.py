"""Depreciation wave: when today's capex hits the income statement."""

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from capex_tracker.data.panel import (
    companies, company_guidance, company_wave, default_depreciation, load_company,
)
from capex_tracker.format import pct, usd_b
from capex_tracker.models.depreciation import DepreciationAssumptions, modeled_vs_reported
from capex_tracker.ui import footer, page_setup

page_setup('Depreciation Wave')
COMPANIES = companies()
base = default_depreciation()

with st.sidebar:
    ticker = st.selectbox("Company", list(COMPANIES), format_func=lambda t: f"{COMPANIES[t]['name']} ({t})")
    st.subheader("Assumptions")
    share = st.slider("Servers & network share of capex", 0.0, 1.0, base.server_share, 0.05,
                      help="The rest is buildings and infrastructure.")
    server_life = st.slider("Server life (years)", 3.0, 8.0, base.server_life_years, 0.5,
                            help="Companies have stretched server lives from 3-4 to 5-6 years, "
                                 "which lowers reported depreciation a lot.")
    building_life = st.slider("Building life (years)", 10.0, 30.0, base.building_life_years, 1.0)
    years = st.slider("Projection (years)", 1, 4, 4)
    calibrate = st.checkbox("Calibrate to reported depreciation", value=True,
                            help="Scale the model so the latest full fiscal year matches what the company reported.")

data = load_company(ticker)
a = DepreciationAssumptions(share, server_life, building_life)
w = company_wave(data, a, years * 4, calibrate)
sched = w.schedule
path = w.margin_path()
guid = company_guidance(ticker)

st.title(f"{data.name}: the depreciation wave")
st.caption("Capex is expensed over its useful life, so today's spending lands in profit over the next years. "
           "All projections are **estimates** holding revenue and other costs at today's level.")

end = path.iloc[-1]
two = path.iloc[min(7, len(path) - 1)]
c1, c2, c3, c4 = st.columns(4)
c1.metric("Operating margin today", pct(w.margin_today), help="Last 4 reported quarters")
c2.metric(f"Margin in 2 years (est.)", pct(two["operating_margin"]), f"{two['margin_change_pts']:+.1f} pts",
          delta_color="normal")
c3.metric(f"Margin in {years} years (est.)", pct(end["operating_margin"]), f"{end['margin_change_pts']:+.1f} pts")
c4.metric("Biggest depreciation rise", str(w.peak_increase_year() or "—"),
          help="Calendar year with the largest increase in modeled depreciation vs the year before")

# ---- capex and depreciation, actual + projected
st.markdown("**Capex and modeled depreciation per quarter** · shaded = projected (estimate)")
s = sched[sched.index >= pd.Timestamp("2018-01-01")]
k = w.calibration
fig = go.Figure()
fig.add_trace(go.Bar(x=s.index, y=s["capex"] / 1e9, name="Capex (actual, then guidance)",
                     marker_color=["#c9d6f2" if p else "#3b6fd8" for p in s["projected"]]))
fig.add_trace(go.Scatter(x=s.index, y=s["servers"] * k / 1e9, name="Depreciation: servers", stackgroup="dep",
                         line=dict(color="#c2532f")))
fig.add_trace(go.Scatter(x=s.index, y=s["buildings"] * k / 1e9, name="Depreciation: buildings", stackgroup="dep",
                         line=dict(color="#e0a43a")))
fig.add_vrect(x0=w.today, x1=s.index[-1], fillcolor="rgba(140,140,140,0.12)", line_width=0,
              annotation_text="projected", annotation_position="top left")
fig.update_layout(yaxis_title="$B per quarter", hovermode="x unified", height=400, barmode="overlay",
                  legend=dict(orientation="h", y=-0.15), margin=dict(t=20, b=10, l=10, r=10))
st.plotly_chart(fig, width="stretch")
if calibrate and k != 1:
    st.caption(f"Depreciation scaled by {k:.2f} so the latest full fiscal year matches reported depreciation.")

# ---- margin path
st.markdown("**Operating margin if only depreciation changes** (estimate)")
fig2 = go.Figure()
fig2.add_trace(go.Scatter(x=path.index, y=path["operating_margin"] * 100, mode="lines+markers",
                          name="Projected operating margin", line=dict(color="#c2532f", width=2.5)))
fig2.add_hline(y=w.margin_today * 100, line_dash="dash", line_color="#8a8f98",
               annotation_text=f"today {pct(w.margin_today)}")
fig2.update_layout(yaxis_title="Operating margin, %", height=320, margin=dict(t=20, b=10, l=10, r=10),
                   showlegend=False)
st.plotly_chart(fig2, width="stretch")
st.caption("Revenue and every other cost held at the last 4 quarters' level; only the change in depreciation "
           "is applied. Real margins will also move with revenue growth.")

# ---- guidance used
st.subheader("Capex guidance used")
if guid.empty:
    st.info("No guidance on file for this company, so future capex is held at the last 4 quarters' average "
            f"({usd_b(data.quarters['capex'].dropna().iloc[-4:].mean())} a quarter).")
else:
    st.dataframe(pd.DataFrame({
        "Period": guid["period"],
        "Low": guid["capex_guidance_low_usd"].map(lambda v: usd_b(v, 0)),
        "High": guid["capex_guidance_high_usd"].map(lambda v: usd_b(v, 0)),
        "Given": guid["date_given"].dt.date, "Note": guid["note"], "Source": guid["source"],
    }), hide_index=True, width="stretch", column_config={"Source": st.column_config.LinkColumn()})
    st.caption("Midpoint used. Quarters left in a guided year get what's left after actual spend; after the "
               "guidance period, capex is held at the guided year's average rate.")

# ---- sanity check
st.subheader("Check: modeled vs reported depreciation")
cmp = modeled_vs_reported(sched, data.depreciation_reported, data.fy_end_month)
cmp = cmp[cmp.index >= 2016]
if cmp.empty:
    st.info("No reported depreciation to compare with.")
else:
    st.dataframe(pd.DataFrame({
        "Fiscal year": cmp.index.astype(str), "Modeled (uncalibrated)": cmp["modeled"].map(usd_b),
        "Reported": cmp["reported"].map(usd_b), "Gap": cmp["gap_pct"].map(lambda v: pct(v, 0)),
    }), hide_index=True, width="stretch")
    st.caption("Why gaps happen: capex here excludes finance leases (large for Amazon and Microsoft before 2022); "
               "buildings sit in construction-in-progress before they depreciate; companies changed server "
               "lives (e.g. 4 to 6 years in 2022-23); land isn't depreciated. Reported figures are depreciation "
               "of property and equipment from each 10-K.")

footer()
