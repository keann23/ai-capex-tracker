"""Sensitivity (METHODOLOGY step 8): rerun every company under one changed
assumption at a time and flag where a conclusion flips.

Conclusions checked against the default run:
  - a company's payback status (e.g. 'paying back' -> 'not at current rate')
  - which company pays back fastest / slowest
  - the sign of a company's excess revenue (is there any AI revenue at all?)
"""

from __future__ import annotations

from dataclasses import dataclass, field, replace

import numpy as np
import pandas as pd

from capex_tracker.models.depreciation import DepreciationAssumptions
from capex_tracker.models.excess import Assumptions, attribute
from capex_tracker.models.payback import payback


@dataclass(frozen=True)
class Variant:
    group: str
    label: str
    excess: dict = field(default_factory=dict)        # Assumptions overrides; 'margin_scale' multiplies
    depreciation: dict = field(default_factory=dict)  # DepreciationAssumptions overrides


DEFAULT = Variant("Default", "Default assumptions")

VARIANTS = [
    DEFAULT,
    Variant("Revenue trend", "Constant % growth", {"trend_shape": "log"}),
    Variant("Revenue trend", "No seasonal pattern", {"seasonal": False}),
    Variant("Baseline window", "2017 Q1 – 2022 Q3", {"baseline_start": pd.Timestamp("2017-01-01")}),
    Variant("Baseline window", "2020 Q1 – 2022 Q3", {"baseline_start": pd.Timestamp("2020-01-01")}),
    Variant("Baseline window", "2019 Q1 – 2021 Q4", {"baseline_end": pd.Timestamp("2021-12-31")}),
    Variant("Margin", "Margin x 0.75", {"margin_scale": 0.75}),
    Variant("Margin", "Margin x 1.25", {"margin_scale": 1.25}),
    Variant("Depreciation", "Server life 4 years", depreciation={"server_life_years": 4.0}),
    Variant("Depreciation", "Server life 8 years", depreciation={"server_life_years": 8.0}),
    Variant("Depreciation", "Servers 40% of capex", depreciation={"server_share": 0.4}),
    Variant("Depreciation", "Servers 80% of capex", depreciation={"server_share": 0.8}),
]


def apply_variant(a: Assumptions, d: DepreciationAssumptions, v: Variant):
    over = dict(v.excess)
    scale = over.pop("margin_scale", 1.0)
    return replace(a, **over, margin=a.margin * scale), replace(d, **v.depreciation)


def evaluate(capex, revenue, segment_revenue, a: Assumptions, wave_fn, d: DepreciationAssumptions) -> dict:
    """Headline numbers for one company under one set of assumptions.
    wave_fn(d) -> Wave, so depreciation variants rebuild only what they change."""
    try:
        p = payback(attribute(capex, revenue, segment_revenue, a))
        pay = dict(payback_years=p.implied_payback_years, status=p.status,
                   annualized_excess_revenue=p.annualized_excess_revenue)
    except ValueError:      # e.g. too few quarters in a baseline window
        pay = dict(payback_years=np.nan, status="not enough data", annualized_excess_revenue=np.nan)
    w = wave_fn(d)
    path = w.margin_path()
    return pay | dict(margin_change_2y=path["margin_change_pts"].iloc[min(7, len(path) - 1)],
                      peak_dep_year=w.peak_increase_year())


def fastest_slowest(df: pd.DataFrame) -> tuple[str | None, str | None]:
    finite = df[np.isfinite(df["payback_years"].astype(float))]
    if finite.empty:
        return None, None
    s = finite.sort_values("payback_years")
    return s["company"].iloc[0], s["company"].iloc[-1]


def flips(results: pd.DataFrame) -> pd.DataFrame:
    """One row per variant: what changed vs the default run, in plain words.

    results: columns variant, company, payback_years, status, annualized_excess_revenue.
    """
    base = results[results["variant"] == DEFAULT.label].set_index("company")
    f0, s0 = fastest_slowest(base.reset_index())
    rows = []
    for variant, df in results.groupby("variant", sort=False):
        if variant == DEFAULT.label:
            continue
        d = df.set_index("company")
        notes = []
        for c in d.index:
            if d.loc[c, "status"] != base.loc[c, "status"]:
                notes.append(f"{c}: {base.loc[c, 'status']} → {d.loc[c, 'status']}")
            b, v = base.loc[c, "annualized_excess_revenue"], d.loc[c, "annualized_excess_revenue"]
            if pd.notna(b) and pd.notna(v) and (b > 0) != (v > 0):
                notes.append(f"{c}: AI revenue {'positive' if b > 0 else 'negative'} → "
                             f"{'positive' if v > 0 else 'negative'}")
        f, s = fastest_slowest(df)
        if f != f0:
            notes.append(f"fastest payback: {f0} → {f}")
        if s != s0:
            notes.append(f"slowest payback: {s0} → {s}")
        rows.append({"variant": variant, "flips": bool(notes), "what_changes": "; ".join(notes)})
    return pd.DataFrame(rows, columns=["variant", "flips", "what_changes"])
