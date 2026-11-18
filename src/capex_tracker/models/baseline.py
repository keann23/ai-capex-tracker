"""The 'before AI' baseline (METHODOLOGY steps 2-4).

Two baselines, both fitted only on the baseline window (default 2019 Q1 to 2022 Q3,
before ChatGPT launched on 2022-11-30):
  - capex intensity: how much capex the company spent per dollar of revenue
  - segment revenue trend, optionally with a fixed seasonal pattern by quarter:
      'linear' (default): constant dollar growth per quarter, so % growth slows
                as the business gets bigger
      'log':    constant % growth. Extends the 2019-22 cloud boom pace forever,
                which puts the 'no AI' line above actual revenue for most
                companies. Kept as the alternative; the app warns that the
                conclusion flips between the two.

All inputs are pandas Series indexed by period_end (raw USD). No Streamlit here.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

import numpy as np
import pandas as pd

MIN_TREND_QUARTERS = 6
MIN_SEASONAL_QUARTERS = 8
TrendShape = Literal["linear", "log"]


def in_window(index: pd.DatetimeIndex, start, end) -> np.ndarray:
    """True for quarters whose period_end falls inside [start, end]."""
    idx = pd.DatetimeIndex(index)
    return np.asarray((idx >= pd.Timestamp(start)) & (idx <= pd.Timestamp(end)))


def capex_intensity(capex: pd.Series, revenue: pd.Series, start, end) -> float:
    """Baseline capex / revenue: total capex over total revenue in the window.

    Totals rather than an average of quarterly ratios, so big quarters weigh more
    and one odd quarter can't swing it. Quarters missing either value are skipped.
    """
    df = pd.concat({"capex": capex, "revenue": revenue}, axis=1).dropna()
    df = df[in_window(df.index, start, end)]
    if df.empty:
        raise ValueError(f"No quarters with capex and revenue between {start} and {end}")
    return float(df["capex"].sum() / df["revenue"].sum())


def quarter_number(index: pd.DatetimeIndex) -> np.ndarray:
    """Running quarter count from period_end (works for any month-end calendar)."""
    idx = pd.DatetimeIndex(index)
    return np.asarray(idx.year * 4 + (idx.month - 1) // 3)


def season(index: pd.DatetimeIndex) -> np.ndarray:
    """0-3: which quarter of the year a period_end is (fiscal or calendar alike)."""
    return np.asarray((pd.DatetimeIndex(index).month - 1) // 3)


@dataclass(frozen=True)
class TrendFit:
    """f(revenue) = intercept + slope * quarter_number + seasonal[season]

    f is revenue itself for shape='linear' (slope and offsets in USD) and
    ln(revenue) for shape='log' (slope = log growth per quarter).
    """

    shape: TrendShape
    intercept: float
    slope: float
    seasonal: tuple[float, ...]      # 4 offsets averaging zero; all zero if not seasonal
    start: pd.Timestamp
    end: pd.Timestamp
    n_quarters: int
    r_squared: float

    def predict(self, index: pd.DatetimeIndex) -> pd.Series:
        t = quarter_number(index)
        v = self.intercept + self.slope * t + np.array(self.seasonal)[season(index)]
        return pd.Series(np.exp(v) if self.shape == "log" else v, index=pd.DatetimeIndex(index))

    def describe(self) -> str:
        if self.shape == "log":
            return f"{np.exp(4 * self.slope) - 1:.1%} a year (constant %)"
        return f"+${4 * self.slope / 1e9:,.1f}B a year (constant $)"


def fit_trend(revenue: pd.Series, start, end, seasonal: bool = True,
              shape: TrendShape = "linear") -> TrendFit:
    """Fit the pre-AI trend on the baseline window (see module docstring for shapes).

    With seasonal=True the model also learns a fixed quarter-of-year pattern
    (e.g. Meta's Q4 ad peak), so the projection doesn't call every Q4 'excess'.
    Needs at least 8 quarters for seasonal, 6 otherwise.
    """
    y = revenue.dropna()
    y = y[in_window(y.index, start, end) & (y > 0).to_numpy()]
    n = len(y)
    if n < MIN_TREND_QUARTERS:
        raise ValueError(f"Need {MIN_TREND_QUARTERS}+ quarters to fit a trend, got {n}")
    seasonal = seasonal and n >= MIN_SEASONAL_QUARTERS

    t = quarter_number(y.index).astype(float)
    t0 = t.mean()  # centre for numerical stability; folded back into the intercept
    cols = [np.ones(n), t - t0]
    s = season(y.index)
    if seasonal:
        cols += [(s == k).astype(float) for k in (1, 2, 3)]
    X = np.column_stack(cols)
    if shape not in ("linear", "log"):
        raise ValueError("shape must be 'linear' or 'log'")
    target = y.to_numpy(dtype=float)
    if shape == "log":
        target = np.log(target)
    coef, *_ = np.linalg.lstsq(X, target, rcond=None)

    raw = np.zeros(4)                       # season 0 is the reference
    if seasonal:
        raw[1:] = coef[2:5]
    offsets = raw - raw.mean()              # seasons average to zero...
    intercept = coef[0] - coef[1] * t0 + raw.mean()   # ...and the level absorbs the mean

    resid = target - X @ coef
    ss_tot = ((target - target.mean()) ** 2).sum()
    r2 = 1 - (resid ** 2).sum() / ss_tot if ss_tot > 0 else 1.0
    return TrendFit(shape, float(intercept), float(coef[1]), tuple(float(o) for o in offsets),
                    pd.Timestamp(start), pd.Timestamp(end), n, float(r2))
