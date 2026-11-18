"""The Methodology page's worked examples must add up, for every company."""

import math

import pytest

from capex_tracker.config import CONFIG_DIR
from capex_tracker.data.panel import companies, load_company
from capex_tracker.worked_example import worked_example

TICKERS = list(companies())


@pytest.fixture(scope="module", params=TICKERS)
def ex(request):
    return worked_example(load_company(request.param))


def test_capex_example_adds_up(ex):
    e = ex[3]
    assert e["intensity"] == pytest.approx(e["capex_sum"] / e["revenue_sum"])
    assert e["baseline_capex"] == pytest.approx(e["intensity"] * e["revenue"])
    assert e["excess_capex"] == pytest.approx(e["capex"] - e["baseline_capex"])
    assert ex[1]["capex"] == e["capex"] and ex[1]["revenue"] == e["revenue"]


def test_revenue_example_adds_up(ex):
    e = ex[4]
    assert e["excess"] == pytest.approx(e["actual"] - e["trend"])
    assert e["excess_profit"] == pytest.approx(e["excess"] * e["margin"])
    assert e["actual"] == ex[1]["segment_revenue"]


def test_payback_example_adds_up(ex):
    e = ex[5]
    assert e["return_so_far"] == pytest.approx(e["cumulative_profit"] / e["cumulative_capex"])
    if math.isfinite(e["payback_years"]):
        assert e["payback_years"] == pytest.approx(e["cumulative_capex"] / e["annualized_profit"])


def test_depreciation_example_adds_up(ex):
    e = ex[6]
    assert e["server_per_q"] == pytest.approx(e["capex"] * 0.6 / 24)
    assert e["building_per_q"] == pytest.approx(e["capex"] * 0.4 / 60)
    assert e["change_2y"] == pytest.approx(-e["extra_dep_2y"] / e["revenue_ttm"] * 100)
    assert e["margin_2y"] == pytest.approx(e["margin_today"] + e["change_2y"] / 100)


def test_baseline_and_sources(ex):
    assert ex[2]["n_quarters"] >= 14
    assert ex[1]["revenue_source"] and ex[1]["segment_source"]
    assert set(ex[7]) == {"Bull", "Base", "Bear"}


def test_page_text_has_every_step():
    text = (CONFIG_DIR.parent / "docs" / "methodology_page.md").read_text()
    for n in range(1, 9):
        assert f"\n## {n}. " in text
    assert "\n## Known limits" in text
