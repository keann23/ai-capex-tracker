"""Company deep dive: excess capex and excess revenue vs the pre-AI baseline."""

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from capex_tracker.data.panel import companies, default_assumptions, load_company
from capex_tracker.format import pct, usd_b
from capex_tracker.models.excess import Assumptions, attribute
from capex_tracker.models.payback import crossover, payback

st.set_page_config(page_title="Company Deep Dive", layout="wide")

COMPANIES = companies()
SHAPES = {"Constant $ growth": "linear", "Constant % growth": "log"}

# ---------- assumptions (all visible, all adjustable) ----------
with st.sidebar:
    ticker = st.selectbox("Company", list(COMPANIES), format_func=lambda t: f"{COMPANIES[t]['name']} ({t})")
    data = load_company(ticker)
    q = data.quarters
    ends = [d for d in q.index if d.year >= 2016]
    labels = q["calendar_label"].to_dict()

    st.subheader("Assumptions")
    base = default_assumptions(data)
    defaults = (base.baseline_start, base.baseline_end)
    first = next(d for d in ends if d >= defaults[0])
    last = max(d for d in ends if d <= defaults[1])
    b_start, b_end = st.select_slider(
        "Pre-AI baseline window", options=ends, value=(first, last),
        format_func=lambda d: labels.get(d) or str(d.date()), key=f"baseline_{ticker}",
        help="Quarters used to learn 'normal' capex intensity and revenue trend. Default ends before ChatGPT (Nov 2022).")
    shape_label = st.radio("Revenue trend without AI", list(SHAPES),
                           help="Constant $: adds the same dollars each quarter as in the baseline, so % growth "
                                "slows with scale. Constant %: keeps the baseline growth rate forever.")
    seasonal = st.checkbox("Seasonal pattern", value=True,
                           help="Learn a fixed quarter-of-year pattern (e.g. Q4 ad peak) so it isn't counted as excess.")
    margin = st.slider("Margin applied to excess revenue", 0.0, 0.8, round(data.margin, 3), 0.005,
                       key=f"margin_{ticker}",
                       help=f"Default: {data.margin_label}, trailing 4 quarters to {data.margin_as_of.date()} "
                            f"({pct(data.margin)}).")
    st.caption(f"Default margin: {data.margin_label} ({pct(data.margin)}).")

a = Assumptions(pd.Timestamp(b_start), pd.Timestamp(b_end), margin, seasonal, SHAPES[shape_label])
try:
    res = attribute(q["capex"], q["revenue"], q["segment_revenue"], a)
except ValueError as e:
    st.error(f"Can't run the model with this baseline window: {e}")
    st.stop()
latest = res.latest()
pb = payback(res)

# ---------- header ----------
st.title(f"{data.name}: {data.segment}")
st.caption("All 'excess' figures are **estimates**: actual minus what the pre-AI baseline implies. "
           "Companies don't report AI spend or AI revenue.")
if data.segment_note:
    st.caption(f"Tracked line: {data.segment_note}")

c1, c2, c3, c4 = st.columns(4)
c5, c6, c7, c8 = st.columns(4)
c1.metric("Cumulative excess capex (est.)", usd_b(latest["cumulative_excess_capex"], 0),
          help=f"Since {res.capex.index[res.capex.index > a.baseline_end][0].date()}, to {latest['capex_as_of'].date()}")
c2.metric("Annualized excess revenue (est.)", usd_b(latest["annualized_excess_revenue"]),
          help="Latest quarter's excess revenue x 4")
c3.metric("Cumulative excess profit (est.)", usd_b(latest["cumulative_excess_profit"]),
          help=f"Cumulative excess revenue x {pct(margin)} margin")
c4.metric("Baseline capex intensity", pct(res.intensity), help="Baseline capex / revenue")
c5.metric("Return so far (est.)", pct(pb.return_so_far, 0),
          help="Cumulative excess profit / cumulative excess capex")
c6.metric("Implied payback (est.)",
          "never at current rate" if pb.implied_payback_years == float("inf")
          else ("—" if pd.isna(pb.implied_payback_years) else f"{pb.implied_payback_years:.1f} yrs"),
          help="Cumulative excess capex / annualized excess profit (latest quarter x 4). Ignores further spend.")
c7.metric("Annualized excess profit (est.)", usd_b(pb.annualized_excess_profit))
c8.metric("Status", pb.status)

# Does the trend-shape choice flip the answer? Say so.
other_shape = "log" if a.trend_shape == "linear" else "linear"
try:
    other = attribute(q["capex"], q["revenue"], q["segment_revenue"],
                      Assumptions(a.baseline_start, a.baseline_end, margin, seasonal, other_shape)).latest()
    mine, theirs = latest["annualized_excess_revenue"], other["annualized_excess_revenue"]
    if pd.notna(mine) and pd.notna(theirs) and (mine > 0) != (theirs > 0):
        other_label = next(k for k, v in SHAPES.items() if v == other_shape)
        st.warning(f"**The conclusion flips with the trend assumption.** With '{other_label}', annualized excess "
                   f"revenue is {usd_b(theirs)} instead of {usd_b(mine)}. The 2019–22 baseline was a cloud boom; "
                   "constant % growth assumes that pace would have continued.")
except ValueError:
    pass


# ---------- charts ----------
def gap_chart(df, actual, baseline, actual_name, baseline_name):
    df = df.dropna(subset=[actual, baseline])
    df = df[df.index >= pd.Timestamp("2017-01-01")]   # earlier years only add clutter
    labels = q["calendar_label"].reindex(df.index)
    fig = go.Figure()
    fig.add_trace(go.Scatter(x=df.index, y=df[baseline] / 1e9, name=baseline_name, mode="lines",
                             line=dict(dash="dash", color="#8a8f98"), customdata=labels,
                             hovertemplate="%{customdata}: $%{y:.1f}B"))
    fig.add_trace(go.Scatter(x=df.index, y=df[actual] / 1e9, name=actual_name, mode="lines",
                             line=dict(color="#3b6fd8", width=2.5), fill="tonexty",
                             fillcolor="rgba(59,111,216,0.18)", customdata=labels,
                             hovertemplate="%{customdata}: $%{y:.1f}B"))
    fig.add_vrect(x0=a.baseline_start, x1=a.baseline_end, fillcolor="rgba(140,140,140,0.12)",
                  line_width=0, annotation_text="baseline", annotation_position="top left")
    fig.update_layout(yaxis_title="$B per quarter", hovermode="x unified", height=380,
                      legend=dict(orientation="h", y=-0.12), margin=dict(t=20, b=10, l=10, r=10))
    return fig


st.markdown("**Capex vs what the pre-AI intensity implies** · shaded gap = excess capex (estimate)")
st.plotly_chart(gap_chart(res.capex, "capex", "baseline_capex", "Actual capex",
                          "Baseline capex (intensity x revenue)"), width="stretch")
st.markdown(f"**{data.segment} revenue vs pre-AI trend** · shaded gap = excess revenue (estimate)")
st.plotly_chart(gap_chart(res.revenue, "segment_revenue", "trend_revenue", f"Actual {data.segment} revenue",
                          f"Pre-AI trend ({res.trend.describe()})"), width="stretch")
st.caption(f"Trend fit on {res.trend.n_quarters} baseline quarters, R² {res.trend.r_squared:.3f}.")

st.markdown("**Cumulative excess capex vs cumulative excess profit** · payback is where the lines cross (estimate)")
xo = crossover(res)
fig = go.Figure()
fig.add_trace(go.Scatter(x=xo.index, y=xo["cumulative_excess_capex"] / 1e9, name="Cumulative excess capex",
                         mode="lines", line=dict(color="#c2532f", width=2.5)))
fig.add_trace(go.Scatter(x=xo.index, y=xo["cumulative_excess_profit"] / 1e9, name="Cumulative excess profit",
                         mode="lines", line=dict(color="#2f8f5b", width=2.5)))
fig.update_layout(yaxis_title="$B, cumulative since baseline", hovermode="x unified", height=360,
                  legend=dict(orientation="h", y=-0.15), margin=dict(t=20, b=10, l=10, r=10))
st.plotly_chart(fig, width="stretch")

# ---------- numbers with sources ----------
st.subheader("Quarterly numbers")
capex_src = data.long[data.long["item"] == "capex"].set_index("period_end")
table = pd.DataFrame({
    "Quarter (calendar)": q["calendar_label"], "Fiscal": q["fiscal_label"],
    "Revenue": q["revenue"], "Capex": q["capex"],
    "Baseline capex (est.)": res.capex["baseline_capex"], "Excess capex (est.)": res.capex["excess_capex"],
    f"{data.segment} revenue": q["segment_revenue"],
    "Trend (est.)": res.revenue["trend_revenue"], "Excess revenue (est.)": res.revenue["excess_revenue"],
    "Capex source": capex_src["accn"].fillna("") + " (" + capex_src["method"] + ")",
    "Segment source": data.segments["source_accession"] + " (" + data.segments["method"] + ")",
}).loc[lambda d: d.index >= pd.Timestamp("2018-01-01")].sort_index(ascending=False)
money = [c for c in table.columns if c not in ("Quarter (calendar)", "Fiscal", "Capex source", "Segment source")]
st.dataframe(table.style.format({c: usd_b for c in money}), width="stretch", hide_index=True)
st.caption(f"Raw values are SEC filings (companyfacts and each filing's XBRL); methods: reported, ytd_diff "
           f"(year-to-date difference), q4_derived. Data through filings dated {data.data_through.date()}.")
