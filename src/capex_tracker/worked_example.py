"""Worked examples for the Methodology page: each step's numbers for one company,
under the default assumptions, from the same functions the other pages use.

Returns raw numbers (USD, fractions) so tests can check the arithmetic adds up;
the page formats them.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from capex_tracker.data.panel import (
    CompanyData, company_scenarios, company_wave, default_assumptions, default_depreciation,
)
from capex_tracker.models.baseline import in_window, season
from capex_tracker.models.excess import attribute
from capex_tracker.models.payback import payback


def worked_example(data: CompanyData) -> dict[int, dict]:
    q = data.quarters
    a = default_assumptions(data)
    att = attribute(q["capex"], q["revenue"], q["segment_revenue"], a)
    pb = payback(att)
    d = default_depreciation()
    wave = company_wave(data, d, horizon_quarters=16)
    _, scen = company_scenarios(data)
    long = data.long.set_index(["item", "period_end"])

    # 1. latest quarter with capex, revenue and segment revenue
    both = q.dropna(subset=["capex", "revenue", "segment_revenue"])
    last = both.index[-1]
    seg_row = data.segments.loc[last]

    def src(item):
        r = long.loc[(item, last)]
        return f"{r['accn']} ({r['method']})"

    ex = {1: dict(
        quarter=q.loc[last, "calendar_label"], fiscal=q.loc[last, "fiscal_label"], period_end=last,
        revenue=q.loc[last, "revenue"], revenue_source=src("revenue"),
        capex=q.loc[last, "capex"], capex_source=src("capex"),
        segment=data.segment, segment_revenue=q.loc[last, "segment_revenue"],
        segment_source=f"{seg_row['source_accession']} ({seg_row['method']})",
    )}

    # 2. baseline window
    win = q.dropna(subset=["capex", "revenue"])
    win = win[in_window(win.index, a.baseline_start, a.baseline_end)]
    ex[2] = dict(start=a.baseline_start, end=a.baseline_end, n_quarters=len(win),
                 first=win["calendar_label"].iloc[0], last=win["calendar_label"].iloc[-1])

    # 3. excess capex
    c = att.capex
    after = c[c.index > a.baseline_end]
    ex[3] = dict(capex_sum=win["capex"].sum(), revenue_sum=win["revenue"].sum(), intensity=att.intensity,
                 capex=c.loc[last, "capex"], revenue=c.loc[last, "revenue"],
                 baseline_capex=c.loc[last, "baseline_capex"], excess_capex=c.loc[last, "excess_capex"],
                 cumulative=pb.cumulative_excess_capex, since=q.loc[after.index[0], "calendar_label"],
                 n_after=int(after["excess_capex"].notna().sum()))

    # 4. excess revenue and profit
    r = att.revenue
    s = season(pd.DatetimeIndex([last]))[0]
    ex[4] = dict(per_year=4 * att.trend.slope, seasonal=att.trend.seasonal[s], shape=att.trend.shape,
                 r_squared=att.trend.r_squared, actual=r.loc[last, "segment_revenue"],
                 trend=r.loc[last, "trend_revenue"], excess=r.loc[last, "excess_revenue"],
                 margin=a.margin, margin_label=data.margin_label, excess_profit=r.loc[last, "excess_profit"])

    # 5. payback
    ex[5] = dict(cumulative_profit=pb.cumulative_excess_profit, cumulative_capex=pb.cumulative_excess_capex,
                 return_so_far=pb.return_so_far, annualized_profit=pb.annualized_excess_profit,
                 payback_years=pb.implied_payback_years, status=pb.status)

    # 6. depreciation
    path = wave.margin_path()
    latest_capex = float(q["capex"].dropna().iloc[-1])
    ex[6] = dict(capex=latest_capex, server_share=d.server_share, server_life=d.server_life_years,
                 building_life=d.building_life_years,
                 server_per_q=latest_capex * d.server_share / (d.server_life_years * 4),
                 building_per_q=latest_capex * (1 - d.server_share) / (d.building_life_years * 4),
                 calibration=wave.calibration, margin_today=wave.margin_today,
                 margin_2y=path["operating_margin"].iloc[7], change_2y=path["margin_change_pts"].iloc[7],
                 extra_dep_2y=path["extra_depreciation"].iloc[7], revenue_ttm=wave.revenue_ttm,
                 peak_year=wave.peak_increase_year())

    # 7. scenarios
    ex[7] = {r.scenario.name: dict(start=r.scenario.start, end=r.scenario.end, fade=r.scenario.fade_years,
                                   payback=r.payback_ignoring_spend, payback_with_spend=r.payback_with_spend,
                                   margin_end=r.path["operating_margin"].iloc[-1])
             for r in scen}
    return ex
