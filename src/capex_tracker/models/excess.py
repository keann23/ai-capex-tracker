"""Excess capex, excess revenue and excess profit (METHODOLOGY steps 3-4).

'Excess' = actual minus what the pre-AI baseline implies. These are estimates of
AI-attributable spend and revenue, not reported figures.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd

from capex_tracker.models.baseline import TrendFit, TrendShape, capex_intensity, fit_trend


def excess_capex(capex: pd.Series, revenue: pd.Series, intensity: float, baseline_end) -> pd.DataFrame:
    """Per quarter: baseline capex = intensity x revenue; excess = actual - baseline.

    Cumulative excess starts the quarter after the baseline window ends.
    """
    df = pd.concat({"capex": capex, "revenue": revenue}, axis=1).sort_index()
    df["baseline_capex"] = intensity * df["revenue"]
    df["excess_capex"] = df["capex"] - df["baseline_capex"]
    after = df.index > pd.Timestamp(baseline_end)
    df["cumulative_excess_capex"] = np.where(after, df["excess_capex"].where(after).cumsum(), np.nan)
    return df


def excess_revenue(segment_revenue: pd.Series, fit: TrendFit, baseline_end) -> pd.DataFrame:
    """Per quarter: trend = baseline growth projected forward; excess = actual - trend."""
    s = segment_revenue.dropna().sort_index()
    df = pd.DataFrame({"segment_revenue": s, "trend_revenue": fit.predict(s.index)})
    df["excess_revenue"] = df["segment_revenue"] - df["trend_revenue"]
    after = df.index > pd.Timestamp(baseline_end)
    df["cumulative_excess_revenue"] = np.where(after, df["excess_revenue"].where(after).cumsum(), np.nan)
    return df


def excess_profit(excess_rev: pd.DataFrame, margin: float) -> pd.DataFrame:
    """Excess profit = excess revenue x margin (an operating margin, as a fraction)."""
    df = excess_rev.copy()
    df["excess_profit"] = df["excess_revenue"] * margin
    df["cumulative_excess_profit"] = df["cumulative_excess_revenue"] * margin
    return df


def ttm_margin(operating_income: pd.Series, revenue: pd.Series) -> tuple[float, pd.Timestamp]:
    """Trailing-four-quarter operating margin at the latest quarter with both values."""
    df = pd.concat({"oi": operating_income, "rev": revenue}, axis=1).dropna().sort_index()
    if len(df) < 4:
        raise ValueError("Need 4 quarters of operating income and revenue for a TTM margin")
    last4 = df.iloc[-4:]
    return float(last4["oi"].sum() / last4["rev"].sum()), last4.index[-1]


@dataclass(frozen=True)
class Assumptions:
    baseline_start: pd.Timestamp
    baseline_end: pd.Timestamp
    margin: float
    seasonal: bool = True
    trend_shape: TrendShape = "linear"


@dataclass(frozen=True)
class Attribution:
    assumptions: Assumptions
    intensity: float
    trend: TrendFit
    capex: pd.DataFrame      # excess_capex() output
    revenue: pd.DataFrame    # excess_revenue() + excess_profit() output

    def latest(self) -> dict:
        """Headline numbers at the latest quarter with data."""
        c = self.capex.dropna(subset=["cumulative_excess_capex"])
        r = self.revenue.dropna(subset=["cumulative_excess_revenue"])
        return {
            "cumulative_excess_capex": c["cumulative_excess_capex"].iloc[-1] if len(c) else np.nan,
            "capex_as_of": c.index[-1] if len(c) else None,
            "annualized_excess_revenue": 4 * r["excess_revenue"].iloc[-1] if len(r) else np.nan,
            "cumulative_excess_profit": r["cumulative_excess_profit"].iloc[-1] if len(r) else np.nan,
            "revenue_as_of": r.index[-1] if len(r) else None,
        }


def attribute(capex: pd.Series, revenue: pd.Series, segment_revenue: pd.Series,
              a: Assumptions) -> Attribution:
    """Run steps 2-4 for one company under one set of assumptions."""
    intensity = capex_intensity(capex, revenue, a.baseline_start, a.baseline_end)
    fit = fit_trend(segment_revenue, a.baseline_start, a.baseline_end, a.seasonal, a.trend_shape)
    return Attribution(
        assumptions=a, intensity=intensity, trend=fit,
        capex=excess_capex(capex, revenue, intensity, a.baseline_end),
        revenue=excess_profit(excess_revenue(segment_revenue, fit, a.baseline_end), a.margin),
    )
