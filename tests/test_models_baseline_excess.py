"""Hand-calculated toy examples for models/baseline.py and models/excess.py."""

import numpy as np
import pandas as pd
import pytest

from capex_tracker.models.baseline import (
    capex_intensity, fit_trend, in_window, quarter_number, season,
)
from capex_tracker.models.excess import (
    Assumptions, attribute, excess_capex, excess_profit, excess_revenue, ttm_margin,
)

B = 1e9


def quarters(n, start="2019-03-31"):
    return pd.date_range(start, periods=n, freq="QE")


def test_window_and_quarter_numbering():
    idx = quarters(4)
    assert in_window(idx, "2019-06-01", "2019-09-30").tolist() == [False, True, True, False]
    # Oracle's Feb/May/Aug/Nov ends count as consecutive quarters with distinct seasons
    orcl = pd.to_datetime(["2023-08-31", "2023-11-30", "2024-02-29", "2024-05-31", "2024-08-31"])
    assert np.diff(quarter_number(orcl)).tolist() == [1, 1, 1, 1]
    assert season(orcl).tolist() == [2, 3, 0, 1, 2]


def test_capex_intensity_is_total_over_total():
    idx = quarters(3)
    capex = pd.Series([10, 20, 99], idx)
    revenue = pd.Series([100, 100, 100], idx)
    assert capex_intensity(capex, revenue, idx[0], idx[1]) == pytest.approx(30 / 200)
    # a quarter missing revenue is skipped, not counted as zero
    revenue2 = pd.Series([100, np.nan, 100], idx)
    assert capex_intensity(capex, revenue2, idx[0], idx[2]) == pytest.approx(109 / 200)
    with pytest.raises(ValueError):
        capex_intensity(capex, revenue, "2030-01-01", "2030-12-31")


def test_linear_trend_recovers_constant_dollar_growth():
    idx = quarters(12)
    rev = pd.Series([(100 + 10 * k) * B for k in range(12)], idx)
    fit = fit_trend(rev, idx[0], idx[7], seasonal=False)   # fit on first 8
    assert fit.predict(idx[8:]).tolist() == pytest.approx(rev[8:].tolist())
    assert fit.describe() == "+$40.0B a year (constant $)"
    assert fit.r_squared == pytest.approx(1.0)


def test_linear_trend_learns_seasonal_offsets():
    idx = quarters(12)
    offsets = {0: -6, 1: 2, 2: 2, 3: 2}  # Q1 dip, averages zero
    rev = pd.Series([100 + 10 * k + offsets[s] for k, s in enumerate(season(idx))], idx, dtype=float)
    fit = fit_trend(rev, idx[0], idx[7], seasonal=True)
    assert list(fit.seasonal) == pytest.approx([-6, 2, 2, 2])
    assert fit.predict(idx[8:]).tolist() == pytest.approx(rev[8:].tolist())


def test_log_trend_recovers_constant_percent_growth():
    idx = quarters(12)
    rev = pd.Series([100 * 1.1 ** k for k in range(12)], idx)
    fit = fit_trend(rev, idx[0], idx[7], seasonal=True, shape="log")
    assert fit.predict(idx[8:]).tolist() == pytest.approx(rev[8:].tolist())
    assert list(fit.seasonal) == pytest.approx([0, 0, 0, 0], abs=1e-9)
    assert fit.describe() == f"{1.1 ** 4 - 1:.1%} a year (constant %)"   # 46.4%


def test_trend_needs_enough_quarters_and_drops_seasonal_when_short():
    idx = quarters(7)
    rev = pd.Series(np.arange(1, 8, dtype=float), idx)
    fit = fit_trend(rev, idx[0], idx[6], seasonal=True)
    assert fit.seasonal == (0.0, 0.0, 0.0, 0.0)       # 7 < 8 quarters: no seasonal terms
    with pytest.raises(ValueError):
        fit_trend(rev, idx[0], idx[4])                 # 5 < 6 quarters
    with pytest.raises(ValueError):
        fit_trend(rev, idx[0], idx[6], shape="cubic")


def test_excess_capex_hand_calculated():
    idx = quarters(4)
    df = excess_capex(pd.Series([10, 10, 20, 30], idx, dtype=float),
                      pd.Series([100, 100, 100, 100], idx, dtype=float), 0.10, idx[1])
    assert df["baseline_capex"].tolist() == [10, 10, 10, 10]
    assert df["excess_capex"].tolist() == [0, 0, 10, 20]
    assert df["cumulative_excess_capex"].tolist()[2:] == [10, 30]
    assert df["cumulative_excess_capex"].isna().tolist()[:2] == [True, True]


def test_excess_revenue_and_profit_hand_calculated():
    idx = quarters(10)
    # trend 100, 110, ... ; actual adds 5 then 15 above trend after the baseline
    rev = pd.Series([100 + 10 * k for k in range(10)], idx, dtype=float)
    rev.iloc[8] += 5
    rev.iloc[9] += 15
    fit = fit_trend(rev, idx[0], idx[7], seasonal=False)
    df = excess_profit(excess_revenue(rev, fit, idx[7]), margin=0.4)
    assert df["excess_revenue"].tolist()[8:] == pytest.approx([5, 15])
    assert df["cumulative_excess_revenue"].tolist()[8:] == pytest.approx([5, 20])
    assert df["excess_profit"].tolist()[8:] == pytest.approx([2, 6])
    assert df["cumulative_excess_profit"].tolist()[8:] == pytest.approx([2, 8])


def test_ttm_margin():
    idx = quarters(5)
    oi = pd.Series([1, 2, 3, 4, 5], idx, dtype=float)
    rev = pd.Series([10] * 5, idx, dtype=float)
    m, as_of = ttm_margin(oi, rev)
    assert m == pytest.approx((2 + 3 + 4 + 5) / 40) and as_of == idx[-1]
    with pytest.raises(ValueError):
        ttm_margin(oi.iloc[:3], rev.iloc[:3])


def test_attribute_end_to_end():
    idx = quarters(10)
    revenue = pd.Series([1000.0] * 10, idx)
    capex = pd.Series([100.0] * 8 + [150.0, 250.0], idx)              # intensity 10%
    seg = pd.Series([100 + 10 * k for k in range(10)], idx, dtype=float)
    seg.iloc[9] += 20
    a = attribute(capex, revenue, seg, Assumptions(idx[0], idx[7], margin=0.5, seasonal=False))
    assert a.intensity == pytest.approx(0.10)
    latest = a.latest()
    assert latest["cumulative_excess_capex"] == pytest.approx(50 + 150)
    assert latest["annualized_excess_revenue"] == pytest.approx(4 * 20)
    assert latest["cumulative_excess_profit"] == pytest.approx(0.5 * 20)
    assert latest["capex_as_of"] == idx[-1]


def test_formatting():
    from capex_tracker.format import pct, usd_b
    assert usd_b(12_345_000_000) == "$12.3B"
    assert usd_b(-2_500_000_000) == "−$2.5B"
    assert usd_b(2.5e9, sign=True) == "+$2.5B" and usd_b(-2.5e9, sign=True) == "−$2.5B"
    assert usd_b(float("nan")) == "—" and usd_b(None) == "—"
    assert pct(0.1234) == "12.3%" and pct(-0.05) == "−5.0%"
