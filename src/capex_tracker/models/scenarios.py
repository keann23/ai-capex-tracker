"""Bull / base / bear scenarios (METHODOLOGY step 7) and forward payback (step 5).

A scenario is a path for the tracked line's revenue growth: annual growth starts
at `start`, moves in a straight line to `end` over `fade_years`, then stays there.
Revenue grows from the latest quarter, one quarter at a time, with the pre-AI
trend's seasonal pattern taken out first and put back after, so 0% growth means
flat at today's level (not back to last year's).

  Bull: today's growth continues, fading to half of it over 4 years
  Base: today's growth fades to the pre-AI trend's growth over 3 years
  Bear: revenue flattens at today's level

Excess revenue = projected revenue - pre-AI trend (same definition as history),
excess profit = excess revenue x margin. Forward capex comes from the depreciation
wave (guidance, then held). Everything is an estimate.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd

from capex_tracker.models.excess import Attribution
from capex_tracker.models.baseline import TrendFit, season
from capex_tracker.models.depreciation import Wave, next_quarter_ends


@dataclass(frozen=True)
class Scenario:
    name: str
    start: float          # annual growth now
    end: float            # annual growth after fading
    fade_years: float

    def growth(self, k: int) -> float:
        """Annual growth applied in projected quarter k (1-based)."""
        n = self.fade_years * 4
        if n <= 0 or k >= n:
            return self.end
        return self.start + (self.end - self.start) * k / n


def ttm_growth(series: pd.Series) -> float:
    """Last 4 quarters vs the 4 before, as a growth rate."""
    s = series.dropna()
    if len(s) < 8 or s.iloc[-8:-4].sum() <= 0:
        return np.nan
    return float(s.iloc[-4:].sum() / s.iloc[-8:-4].sum() - 1)


def trend_growth(att: Attribution) -> float:
    """Annual growth the pre-AI trend implies at the latest quarter."""
    s = att.revenue["segment_revenue"].dropna()
    idx = s.index[-4:]
    now = att.trend.predict(idx).sum()
    year_ago = att.trend.predict(s.index[-8:-4]).sum()
    return float(now / year_ago - 1) if year_ago > 0 else 0.0


def default_scenarios(att: Attribution) -> list[Scenario]:
    g = ttm_growth(att.revenue["segment_revenue"])
    g = 0.0 if np.isnan(g) else g
    return [
        Scenario("Bull", g, g / 2, 4.0),
        Scenario("Base", g, trend_growth(att), 3.0),
        Scenario("Bear", 0.0, 0.0, 0.0),
    ]


def project_revenue(history: pd.Series, scenario: Scenario, quarters: int,
                    fit: TrendFit | None = None) -> pd.Series:
    """Quarterly revenue from the latest quarter: level x (1 + annual growth)^(1/4) each
    quarter, with the fit's seasonal offsets removed and re-applied (none if fit is None)."""
    h = history.dropna()
    idx = next_quarter_ends(h.index[-1], quarters)
    off = np.array(fit.seasonal) if fit is not None else np.zeros(4)
    log = fit is not None and fit.shape == "log"

    def deseason(v, d):
        k = season(pd.DatetimeIndex([d]))[0]
        return v / np.exp(off[k]) if log else v - off[k]

    def reseason(v, d):
        k = season(pd.DatetimeIndex([d]))[0]
        return v * np.exp(off[k]) if log else v + off[k]

    level = deseason(float(h.iloc[-1]), h.index[-1])
    out = []
    for k, d in enumerate(idx, start=1):
        level *= (1 + scenario.growth(k)) ** 0.25
        out.append(reseason(level, d))
    return pd.Series(out, index=idx)


@dataclass(frozen=True)
class ScenarioResult:
    scenario: Scenario
    path: pd.DataFrame                    # per projected quarter
    payback_ignoring_spend: pd.Timestamp | None
    payback_with_spend: pd.Timestamp | None
    already_paid_back: bool


def _first_cross(profit: pd.Series, capex: pd.Series) -> pd.Timestamp | None:
    hit = profit.index[(profit >= capex).to_numpy()]
    return hit[0] if len(hit) else None


def run_scenario(att: Attribution, wave: Wave, scenario: Scenario, quarters: int) -> ScenarioResult:
    """Project one scenario: excess revenue/profit, cumulative payback and operating margin.

    payback_ignoring_spend: cumulative excess profit catches today's cumulative excess capex.
    payback_with_spend: it catches cumulative excess capex that keeps growing with guided capex
    (baseline capex = pre-AI intensity x projected total revenue).
    Margin: today's operating income and revenue, plus the change in excess profit and
    excess revenue, minus the change in (calibrated) depreciation.
    """
    a = att.assumptions
    hist = att.revenue
    seg = project_revenue(hist["segment_revenue"], scenario, quarters, att.trend)
    df = pd.DataFrame({"segment_revenue": seg, "trend_revenue": att.trend.predict(seg.index)})
    df["excess_revenue"] = df["segment_revenue"] - df["trend_revenue"]
    df["excess_profit"] = df["excess_revenue"] * a.margin

    cum_profit_now = float(hist["cumulative_excess_profit"].dropna().iloc[-1])
    cum_capex_now = float(att.capex["cumulative_excess_capex"].dropna().iloc[-1])
    df["cumulative_excess_profit"] = cum_profit_now + df["excess_profit"].cumsum()

    # Capex: the wave's projection (guidance, then held). Total revenue: latest quarter's,
    # moved by the change in the tracked line's revenue.
    capex = wave.schedule.loc[wave.schedule["projected"], "capex"].reindex(df.index)
    if capex.isna().any():
        raise ValueError("The depreciation wave must be projected at least as far as the scenario")
    last_rev = float(att.capex["revenue"].dropna().iloc[-1])
    last_seg = float(hist["segment_revenue"].dropna().iloc[-1])
    total_rev = last_rev + (df["segment_revenue"] - last_seg)
    df["capex"] = capex
    df["excess_capex"] = capex - att.intensity * total_rev
    df["cumulative_excess_capex_fixed"] = cum_capex_now
    df["cumulative_excess_capex_with_spend"] = cum_capex_now + df["excess_capex"].cumsum()

    # Operating margin path (TTM)
    last4_profit = float(hist["excess_profit"].dropna().iloc[-4:].sum())
    last4_rev = float(hist["excess_revenue"].dropna().iloc[-4:].sum())
    ttm_profit = pd.concat([hist["excess_profit"].dropna().iloc[-3:], df["excess_profit"]]).rolling(4).sum()
    ttm_exrev = pd.concat([hist["excess_revenue"].dropna().iloc[-3:], df["excess_revenue"]]).rolling(4).sum()
    dep = wave.ttm().reindex(df.index) - wave.depreciation_today_ttm * wave.calibration
    d_oi = ttm_profit.reindex(df.index) - last4_profit - dep
    d_rev = ttm_exrev.reindex(df.index) - last4_rev
    df["operating_margin"] = (wave.operating_income_ttm + d_oi) / (wave.revenue_ttm + d_rev)

    already = cum_profit_now >= cum_capex_now > 0
    return ScenarioResult(
        scenario, df,
        _first_cross(df["cumulative_excess_profit"], df["cumulative_excess_capex_fixed"]),
        _first_cross(df["cumulative_excess_profit"], df["cumulative_excess_capex_with_spend"]),
        already,
    )
