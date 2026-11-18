"""Hand-calculated toy examples for models/payback.py."""

import math

import numpy as np
import pandas as pd
import pytest

from capex_tracker.models.excess import Assumptions, attribute
from capex_tracker.models.payback import crossover, headline, payback

IDX = pd.date_range("2019-03-31", periods=10, freq="QE")


def run(capex_tail, seg_bump, margin=0.5):
    """8 baseline quarters (revenue 1000, capex 100 -> intensity 10%), then 2 more.
    Segment revenue is a straight line 100, 110, ... plus seg_bump in the last quarter."""
    revenue = pd.Series([1000.0] * 10, IDX)
    capex = pd.Series([100.0] * 8 + list(capex_tail), IDX)
    seg = pd.Series([100 + 10 * k for k in range(10)], IDX, dtype=float)
    seg.iloc[9] += seg_bump
    return attribute(capex, revenue, seg, Assumptions(IDX[0], IDX[7], margin, seasonal=False))


def test_paying_back():
    # excess capex 50 + 150 = 200; last-quarter excess profit 0.5 x 20 = 10 -> 40 a year
    p = payback(run([150, 250], seg_bump=20))
    assert p.cumulative_excess_capex == pytest.approx(200)
    assert p.cumulative_excess_profit == pytest.approx(10)
    assert p.annualized_excess_profit == pytest.approx(40)
    assert p.annualized_excess_revenue == pytest.approx(80)
    assert p.return_so_far == pytest.approx(10 / 200)
    assert p.implied_payback_years == pytest.approx(200 / 40)   # 5 years
    assert p.status == "paying back" and p.as_of == IDX[-1]


def test_not_paying_back_when_no_excess_profit():
    p = payback(run([150, 250], seg_bump=0))
    assert math.isinf(p.implied_payback_years) and p.status == "not at current rate"
    assert p.return_so_far == pytest.approx(0)


def test_paid_back():
    # excess profit 0.5 x 500 = 250 >= excess capex 200
    p = payback(run([150, 250], seg_bump=500))
    assert p.status == "paid back" and p.return_so_far == pytest.approx(250 / 200)


def test_no_excess_capex():
    p = payback(run([100, 100], seg_bump=20))
    assert p.status == "no excess capex" and np.isnan(p.return_so_far) and np.isnan(p.implied_payback_years)


def test_crossover_only_after_baseline():
    df = crossover(run([150, 250], seg_bump=20))
    assert list(df.index) == list(IDX[8:])
    assert df["cumulative_excess_capex"].tolist() == pytest.approx([50, 200])
    assert df["cumulative_excess_profit"].tolist() == pytest.approx([0, 10])


def score(rows):
    return pd.DataFrame(rows, columns=["company", "implied_payback_years", "status", "annualized_excess_revenue"])


def test_headline_fastest_slowest_never_and_caveat():
    s = score([("Oracle", 3.0, "paying back", 1), ("Amazon", 12.0, "paying back", 1),
               ("Meta", 6.0, "paying back", 1), ("Acme", math.inf, "not at current rate", -1)])
    alt = score([("Oracle", 3.0, "", 5), ("Amazon", math.inf, "", -2), ("Meta", math.inf, "", -1),
                 ("Acme", math.inf, "", -1)])
    h = headline(s, alt, "with constant-% revenue growth")
    assert h == ("At current run-rates, Oracle pays back its estimated AI capex fastest (3.0 years of "
                 "today's excess profit); Amazon slowest (12.0 years). Acme is not earning excess profit yet. "
                 "Caveat: with constant-% revenue growth, Amazon, Meta and Acme show no AI revenue at all.")


def test_headline_edge_cases():
    assert headline(score([("A", math.inf, "not at current rate", 0)])) == "A is not earning excess profit yet."
    assert "only B" in headline(score([("B", 4.0, "paying back", 1)]))
    assert headline(score([])) == "Not enough data for a headline yet."
