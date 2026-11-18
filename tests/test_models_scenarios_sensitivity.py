"""Hand-calculated toy examples for models/scenarios.py and models/sensitivity.py."""

import math

import numpy as np
import pandas as pd
import pytest

from capex_tracker.models.depreciation import DepreciationAssumptions, depreciation_wave
from capex_tracker.models.excess import Assumptions, attribute
from capex_tracker.models.scenarios import (
    Scenario, default_scenarios, project_revenue, run_scenario, trend_growth, ttm_growth,
)
from capex_tracker.models.sensitivity import DEFAULT, Variant, apply_variant, fastest_slowest, flips

IDX = pd.date_range("2019-03-31", periods=10, freq="QE")
NO_GUIDANCE = pd.DataFrame(columns=["period", "capex_guidance_low_usd", "capex_guidance_high_usd"])


def test_growth_fades_in_a_straight_line():
    s = Scenario("x", 0.4, 0.0, 1.0)        # fade over 4 quarters
    assert [s.growth(k) for k in (1, 2, 4, 6)] == pytest.approx([0.3, 0.2, 0.0, 0.0])
    assert Scenario("flat", 0.1, 0.1, 0).growth(3) == 0.1


def test_projection_grows_from_latest_quarter():
    h = pd.Series([100.0, 110, 120, 130], pd.date_range("2025-03-31", periods=4, freq="QE"))
    p = project_revenue(h, Scenario("x", 0.1, 0.1, 0), 4)
    assert p.tolist() == pytest.approx([130 * 1.1 ** (k / 4) for k in range(1, 5)])
    assert p.index[0] == pd.Timestamp("2026-03-31")
    assert project_revenue(h, Scenario("flat", 0, 0, 0), 3).tolist() == [130, 130, 130]


def test_projection_keeps_seasonal_pattern():
    from capex_tracker.models.baseline import TrendFit
    fit = TrendFit("linear", 0, 0, (-6, 2, 2, 2), IDX[0], IDX[7], 8, 1.0)
    h = pd.Series([100.0, 110, 120, 132], pd.date_range("2025-03-31", periods=4, freq="QE"))
    # latest is Q4 (+2): level 130, flat -> Q1 124, Q2 132, Q3 132, Q4 132
    p = project_revenue(h, Scenario("flat", 0, 0, 0), 4, fit)
    assert p.tolist() == pytest.approx([124, 132, 132, 132])


def test_ttm_growth():
    s = pd.Series([10.0] * 4 + [15.0] * 4)
    assert ttm_growth(s) == pytest.approx(0.5)
    assert np.isnan(ttm_growth(s.iloc[:6]))


def toy():
    revenue = pd.Series([1000.0] * 10, IDX)
    capex = pd.Series([100.0] * 8 + [150.0, 250.0], IDX)
    seg = pd.Series([100 + 10 * k for k in range(10)], IDX, dtype=float)
    seg.iloc[9] += 20
    att = attribute(capex, revenue, seg, Assumptions(IDX[0], IDX[7], margin=0.5, seasonal=False))
    wave = depreciation_wave(capex, revenue, pd.Series([300.0] * 10, IDX), NO_GUIDANCE, 12,
                             DepreciationAssumptions(1.0, 1.0, 15.0), horizon_quarters=8)
    return att, wave


def test_run_scenario_by_hand():
    att, wave = toy()
    g = 1.5 ** 4 - 1                       # x1.5 per quarter keeps the arithmetic clean
    r = run_scenario(att, wave, Scenario("x", g, g, 0), 8)
    p = r.path
    # latest 210 -> 315, 472.5, 708.75; trend 200, 210, 220 -> excess 115, 262.5, 488.75
    assert p["excess_revenue"].iloc[:3].tolist() == pytest.approx([115, 262.5, 488.75])
    # profit at 50%: 57.5, 131.25, 244.375 on top of 10 -> 67.5, 198.75, 443.125
    assert p["cumulative_excess_profit"].iloc[:3].tolist() == pytest.approx([67.5, 198.75, 443.125])
    assert r.payback_ignoring_spend == p.index[2] == pd.Timestamp("2022-03-31")   # passes 200 in Q3
    # With spend: capex held at 150/q (no guidance); baseline = 10% x (1000 + seg - 210)
    # Q1: 150 - 110.5 = 39.5 -> 239.5; Q2: 150 - 126.25 -> 263.25; Q3: 150 - 149.875 -> 263.375
    assert p["cumulative_excess_capex_with_spend"].iloc[:3].tolist() == pytest.approx([239.5, 263.25, 263.375])
    assert r.payback_with_spend == pd.Timestamp("2022-03-31")                      # 443 >= 263 in Q3
    # Margin Q1: OI 1200 + (67.5 - 10 excess profit TTM) - (462.5 - 412.5 depreciation TTM),
    #            revenue 4000 + (135 - 20 excess revenue TTM)
    assert p["operating_margin"].iloc[0] == pytest.approx(1207.5 / 4115)
    assert not r.already_paid_back
    # Flat scenario: excess shrinks as the trend keeps rising (210 vs 200, 210, 220 ...)
    flat = run_scenario(att, wave, Scenario("flat", 0, 0, 0), 8).path
    assert flat["excess_revenue"].iloc[:3].tolist() == pytest.approx([10, 0, -10])


def test_default_scenarios_and_trend_growth():
    att, _ = toy()
    # trend 160, 170, 180, 190 vs 120, 130, 140, 150 -> 700 / 540 - 1
    assert trend_growth(att) == pytest.approx(700 / 540 - 1)
    names = [s.name for s in default_scenarios(att)]
    assert names == ["Bull", "Base", "Bear"]
    bull, base, bear = default_scenarios(att)
    g = (160 + 170 + 180 + 210) / (120 + 130 + 140 + 150) - 1
    assert bull.start == pytest.approx(g) and bull.end == pytest.approx(g / 2)
    assert base.end == pytest.approx(700 / 540 - 1) and bear.start == bear.end == 0


def test_wave_shorter_than_scenario_is_an_error():
    att, wave = toy()
    with pytest.raises(ValueError):
        run_scenario(att, wave, Scenario("x", 0.1, 0.1, 0), 12)


def test_apply_variant():
    a = Assumptions(IDX[0], IDX[7], margin=0.4)
    d = DepreciationAssumptions()
    a2, d2 = apply_variant(a, d, Variant("Margin", "x", {"margin_scale": 1.25, "trend_shape": "log"},
                                         {"server_life_years": 4.0}))
    assert a2.margin == pytest.approx(0.5) and a2.trend_shape == "log" and d2.server_life_years == 4.0
    assert a.margin == 0.4                               # original untouched


def results(variant, rows):
    return pd.DataFrame([dict(variant=variant, company=c, payback_years=y, status=s,
                              annualized_excess_revenue=r) for c, y, s, r in rows])


def test_flips_detects_status_sign_and_ranking_changes():
    base = results(DEFAULT.label, [("A", 3.0, "paying back", 10), ("B", 8.0, "paying back", 5),
                                   ("C", 5.0, "paying back", 7)])
    same = results("same", [("A", 3.5, "paying back", 9), ("B", 9.0, "paying back", 4),
                            ("C", 5.5, "paying back", 6)])
    flipped = results("flip", [("A", math.inf, "not at current rate", -2), ("B", 8.0, "paying back", 5),
                               ("C", 4.0, "paying back", 7)])
    out = flips(pd.concat([base, same, flipped])).set_index("variant")
    assert not out.loc["same", "flips"] and out.loc["same", "what_changes"] == ""
    assert out.loc["flip", "flips"]
    assert out.loc["flip", "what_changes"] == ("A: paying back → not at current rate; "
                                               "A: AI revenue positive → negative; fastest payback: A → C")
    assert fastest_slowest(base) == ("A", "B")
