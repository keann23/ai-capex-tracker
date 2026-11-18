"""Hand-calculated toy examples for models/depreciation.py."""

import numpy as np
import pandas as pd
import pytest

from capex_tracker.data.standardize import annual_flow
from capex_tracker.models.depreciation import (
    DepreciationAssumptions, depreciation_schedule, depreciation_wave, fiscal_quarter_of,
    calibration_factor, fiscal_year_of, future_capex, modeled_vs_reported, next_quarter_ends, straight_line,
)
from tests.helpers import companyfacts, fact

IDX = pd.date_range("2024-03-31", periods=8, freq="QE")


def test_three_vintage_straight_line_by_hand():
    # Vintages: 400 in Q1, 0 in Q2, 800 in Q3. Life 1 year = 4 quarters, starting next quarter.
    # Q1 vintage: 100/q in Q2..Q5.  Q3 vintage: 200/q in Q4..Q7.
    capex = pd.Series([400, 0, 800, 0, 0, 0, 0, 0], IDX, dtype=float)
    assert straight_line(capex, 1.0).tolist() == [0, 100, 100, 300, 300, 200, 200, 0]


def test_split_between_servers_and_buildings():
    capex = pd.Series([800, 0, 0, 0, 0, 0, 0, 0], IDX, dtype=float)
    s = depreciation_schedule(capex, DepreciationAssumptions(0.5, server_life_years=1, building_life_years=2))
    assert s["servers"].tolist() == [0, 100, 100, 100, 100, 0, 0, 0]      # 400 over 4 quarters
    assert s["buildings"].tolist() == [0, 50, 50, 50, 50, 50, 50, 50]     # 400 over 8 quarters
    assert s["total"].sum() == pytest.approx(400 + 350)                   # 1 building quarter left


def test_missing_capex_counts_as_zero():
    capex = pd.Series([400, np.nan, 0, 0, 0, 0, 0, 0], IDX)
    assert straight_line(capex, 1.0).tolist() == [0, 100, 100, 100, 100, 0, 0, 0]


def test_fiscal_calendar_helpers():
    idx = pd.to_datetime(["2026-08-31", "2026-11-30", "2027-02-28", "2027-05-31"])
    assert fiscal_year_of(idx, 5).tolist() == [2027] * 4                  # Oracle FY ends May
    assert fiscal_quarter_of(idx, 5).tolist() == [1, 2, 3, 4]
    assert [d.strftime("%Y-%m-%d") for d in next_quarter_ends(pd.Timestamp("2026-05-31"), 3)] == \
        ["2026-08-31", "2026-11-30", "2027-02-28"]


def guidance(rows):
    return pd.DataFrame(rows, columns=["period", "capex_guidance_low_usd", "capex_guidance_high_usd"])


def test_future_capex_from_guidance_then_held():
    hist = pd.Series([10.0, 10, 10, 10], pd.date_range("2025-03-31", periods=4, freq="QE"))
    # FY2026 guided 360-440 (mid 400 -> 100/q); FY2026Q4 guided separately at 130.
    g = guidance([("FY2026", 360, 440), ("FY2026Q4", 130, 130)])
    f = future_capex(hist, g, 12, quarters=6)
    assert f["capex"].tolist() == [100, 100, 100, 130, 130, 130]
    assert f["basis"].tolist() == ["guidance"] * 4 + ["held at last guidance"] * 2


def test_future_capex_spreads_what_is_left_of_a_year_under_way():
    # FY2026 (calendar) guided 200; Q1-Q3 actual 30 + 40 + 50 = 120 -> Q4 = 80,
    # then held at the year's average rate 200 / 4 = 50 (not the leftover 80)
    hist = pd.Series([30.0, 40, 50], pd.date_range("2026-03-31", periods=3, freq="QE"))
    f = future_capex(hist, guidance([("FY2026", 190, 210)]), 12, quarters=3)
    assert f["capex"].tolist() == [80, 50, 50]
    assert f["basis"].tolist() == ["guidance", "held at last guidance", "held at last guidance"]
    # Oracle-style fiscal year (ends May): FY2027 Q1 actual 28.5, guided 90-95 -> 64/3 per quarter
    orcl = pd.Series([28.5], pd.to_datetime(["2026-08-31"]))
    f = future_capex(orcl, guidance([("FY2027", 90, 95)]), 5, quarters=4)
    assert f["capex"].tolist() == pytest.approx([64 / 3] * 3 + [92.5 / 4])
    assert f.index[-1] == pd.Timestamp("2027-08-31")


def test_future_capex_without_guidance_uses_run_rate():
    hist = pd.Series([8.0, 10, 12, 14], pd.date_range("2025-03-31", periods=4, freq="QE"))
    f = future_capex(hist, guidance([]), 12, quarters=2)
    assert f["capex"].tolist() == [11, 11] and set(f["basis"]) == {"held at last 4 quarters"}


def test_wave_margin_path_and_peak_year():
    # 8 quarters of 40 capex, 4-quarter life, all servers -> modeled dep 40/q at steady state.
    hist_idx = pd.date_range("2024-03-31", periods=8, freq="QE")
    capex = pd.Series([40.0] * 8, hist_idx)
    revenue = pd.Series([1000.0] * 8, hist_idx)
    oi = pd.Series([300.0] * 8, hist_idx)
    # guidance triples capex for FY2026 (calendar): 4 x 120, then held at 120
    w = depreciation_wave(capex, revenue, oi, guidance([("FY2026", 480, 480)]), 12,
                          DepreciationAssumptions(1.0, 1.0, 15.0), horizon_quarters=8)
    assert w.depreciation_today_ttm == pytest.approx(160)        # 4 x 40
    assert w.margin_today == pytest.approx(0.30)
    path = w.margin_path()
    # each quarter's dep = previous 4 quarters' capex / 4:
    # 2026 Q1..Q4 = 160/4, (120+120)/4, (80+240)/4, (40+360)/4 = 40, 60, 80, 100 -> TTM 280
    assert path.loc["2026-12-31", "depreciation_ttm"] == pytest.approx(280)
    assert path.loc["2026-12-31", "operating_margin"] == pytest.approx((1200 - 120) / 4000)
    assert path.loc["2026-12-31", "margin_change_pts"] == pytest.approx(-3.0)
    # annual dep: 2024 60, 2025 160 (+100), 2026 280 (+120), 2027 4 x 120 = 480 (+200)
    assert w.peak_increase_year() == 2027


def test_modeled_vs_reported_full_fiscal_years_only():
    idx = pd.date_range("2024-03-31", periods=6, freq="QE")
    sched = pd.DataFrame({"total": [10.0] * 6, "projected": [False] * 6}, idx)
    df = modeled_vs_reported(sched, pd.Series({2024: 50.0, 2025: 99.0}), 12)
    assert df.index.tolist() == [2024]                            # 2025 has only 2 quarters
    assert df.loc[2024, "gap_pct"] == pytest.approx((40 - 50) / 50)


def test_annual_flow_reads_10k_values_with_tag_priority():
    cf = companyfacts({
        "Depreciation": [fact("2023-01-01", "2023-12-31", 50, "2024-02-01", form="10-K"),
                         fact("2023-01-01", "2023-03-31", 12, "2023-04-30")],     # quarter ignored
        "DepreciationDepletionAndAmortization": [
            fact("2022-01-01", "2022-12-31", 70, "2023-02-01", form="10-K"),
            fact("2023-01-01", "2023-12-31", 99, "2024-02-01", form="10-K")],
    })
    s = annual_flow(cf, ["Depreciation", "DepreciationDepletionAndAmortization"], 12)
    assert s.to_dict() == {2022: 70.0, 2023: 50.0}


def test_calibration_scales_the_margin_drag():
    hist_idx = pd.date_range("2024-03-31", periods=8, freq="QE")
    capex = pd.Series([40.0] * 8, hist_idx)
    revenue, oi = pd.Series([1000.0] * 8, hist_idx), pd.Series([300.0] * 8, hist_idx)
    # modeled FY2025 depreciation is 160; company reported 200 -> factor 1.25
    reported = pd.Series({2025: 200.0})
    w = depreciation_wave(capex, revenue, oi, guidance([("FY2026", 480, 480)]), 12,
                          DepreciationAssumptions(1.0, 1.0, 15.0), 8, reported)
    assert w.calibration == pytest.approx(1.25)
    assert calibration_factor(w.schedule, reported, 12) == (pytest.approx(1.25), 2025)
    # uncalibrated drag at 2026Q4 was 120 -> 150; margin change -3.0 -> -3.75 pts
    assert w.margin_path().loc["2026-12-31", "margin_change_pts"] == pytest.approx(-3.75)
    assert calibration_factor(w.schedule, pd.Series(dtype=float), 12) == (1.0, None)
