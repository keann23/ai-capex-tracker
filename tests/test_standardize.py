"""Hand-checked toy examples for each gotcha in docs/SEC_DATA_NOTES.md."""

import pandas as pd
import pytest

from capex_tracker.data.standardize import (
    add_period_labels, dedupe, extract_facts, fiscal_year_totals, quarterize_flow,
    standardize_company, to_wide,
)
from tests.helpers import companyfacts, fact

FY23 = ("2023-01-01", "2023-12-31")

TAG_MAP = {
    "revenue": {"type": "flow", "tags": ["RevenueFromContractWithCustomerExcludingAssessedTax", "Revenues"]},
    "cost_of_revenue": {"type": "flow", "tags": ["CostOfRevenue"]},
    "gross_profit": {"type": "flow", "tags": ["GrossProfit"], "derive": "revenue - cost_of_revenue"},
    "depreciation_amortization": {"type": "flow", "tags": ["DepreciationDepletionAndAmortization",
                                                           "DepreciationAndAmortization"]},
    "cfo": {"type": "flow", "tags": ["NetCashProvidedByUsedInOperatingActivities"]},
    "capex": {"type": "flow", "tags": ["PaymentsToAcquirePropertyPlantAndEquipment"]},
    "ppe_net": {"type": "instant", "tags": ["PropertyPlantAndEquipmentNet"]},
    "free_cash_flow": {"type": "flow", "tags": [], "derive": "cfo - capex"},
}


def toy_facts():
    return companyfacts({
        # Income statement: 3-month quarters, plus a 6-month YTD, plus FY. Q1 restated later.
        "RevenueFromContractWithCustomerExcludingAssessedTax": [
            fact("2023-01-01", "2023-03-31", 100, "2023-04-25"),
            fact("2023-01-01", "2023-03-31", 101, "2024-04-25"),  # comparative, restated
            fact("2023-04-01", "2023-06-30", 110, "2023-07-25"),
            fact("2023-01-01", "2023-06-30", 210, "2023-07-25"),
            fact("2023-07-01", "2023-09-30", 120, "2023-10-25"),
            fact(*FY23, 460, "2024-02-01", form="10-K"),
            fact("2023-01-01", "2023-03-31", 999, "2023-05-01", form="8-K"),  # ignored form
        ],
        "CostOfRevenue": [
            fact("2023-01-01", "2023-03-31", 40, "2023-04-25"),
            fact("2023-04-01", "2023-06-30", 45, "2023-07-25"),
        ],
        # Cash flow: YTD only in 10-Qs.
        "PaymentsToAcquirePropertyPlantAndEquipment": [
            fact("2023-01-01", "2023-03-31", 50, "2023-04-25"),
            fact("2023-01-01", "2023-06-30", 120, "2023-07-25"),
            fact("2023-01-01", "2023-09-30", 200, "2023-10-25"),
            fact(*FY23, 300, "2024-02-01", form="10-K"),
        ],
        "NetCashProvidedByUsedInOperatingActivities": [
            fact("2023-01-01", "2023-03-31", 80, "2023-04-25"),
            fact("2023-01-01", "2023-06-30", 170, "2023-07-25"),
        ],
        # Tag drift: Q1-Q2 under the first tag, Q2-Q3 under the second.
        "DepreciationDepletionAndAmortization": [
            fact("2023-01-01", "2023-03-31", 10, "2023-04-25"),
            fact("2023-04-01", "2023-06-30", 11, "2023-07-25"),
        ],
        "DepreciationAndAmortization": [
            fact("2023-04-01", "2023-06-30", 99, "2023-07-25"),
            fact("2023-07-01", "2023-09-30", 12, "2023-10-25"),
        ],
        "PropertyPlantAndEquipmentNet": [
            fact(None, "2022-06-30", 500, "2023-04-25"),  # no flow quarter there: dropped
            fact(None, "2023-03-31", 600, "2023-04-25"),
            fact(None, "2023-06-30", 650, "2023-07-25"),
        ],
    })


def series(long, item):
    s = long[long["item"] == item].set_index("period_end")
    s.index = s.index.strftime("%Y-%m-%d")
    return s


def test_dedupe_latest_vs_earliest():
    f = extract_facts(toy_facts(), "RevenueFromContractWithCustomerExcludingAssessedTax")
    q1 = lambda d: d[d["end"] == "2023-03-31"]["val"].tolist()
    assert sorted(q1(dedupe(f, "latest"))) == [101.0]      # only the 3-month row ends 3/31
    assert sorted(q1(dedupe(f, "earliest"))) == [100.0]
    with pytest.raises(ValueError):
        dedupe(f, "newest")


def test_non_10k_10q_forms_ignored():
    f = extract_facts(toy_facts(), "RevenueFromContractWithCustomerExcludingAssessedTax")
    assert 999 not in f["val"].tolist()


def test_q4_derived_from_fy_minus_three_quarters():
    s = series(standardize_company(toy_facts(), TAG_MAP, 12), "revenue")
    # FY 460 - (101 + 110 + 120) = 129 with restated Q1 (latest view)
    assert s.loc["2023-12-31", "value"] == 129
    assert s.loc["2023-12-31", "method"] == "q4_derived"
    assert s.loc["2023-12-31", "period_start"] == pd.Timestamp("2023-10-01")
    assert s.loc["2023-06-30", "method"] == "reported"  # 3-month value beats YTD diff


def test_earliest_view_uses_first_reported_values():
    s = series(standardize_company(toy_facts(), TAG_MAP, 12, keep="earliest"), "revenue")
    assert s.loc["2023-03-31", "value"] == 100
    assert s.loc["2023-12-31", "value"] == 130  # 460 - (100 + 110 + 120)


def test_ytd_cash_flow_differenced_into_quarters():
    s = series(standardize_company(toy_facts(), TAG_MAP, 12), "capex")
    assert s["value"].tolist() == [50, 70, 80, 100]
    assert s["method"].tolist() == ["reported", "ytd_diff", "ytd_diff", "ytd_diff"]


def test_tag_drift_picks_first_tag_with_value_per_period():
    s = series(standardize_company(toy_facts(), TAG_MAP, 12), "depreciation_amortization")
    assert s["value"].tolist() == [10, 11, 12]
    assert s["tag"].tolist() == ["DepreciationDepletionAndAmortization"] * 2 + ["DepreciationAndAmortization"]


def test_instants_kept_only_at_quarter_ends():
    s = series(standardize_company(toy_facts(), TAG_MAP, 12), "ppe_net")
    assert list(s.index) == ["2023-03-31", "2023-06-30"]
    assert s["value"].tolist() == [600, 650]


def test_formula_items_derived_and_marked():
    long = standardize_company(toy_facts(), TAG_MAP, 12)
    gp = series(long, "gross_profit")
    assert gp["value"].tolist() == [101 - 40, 110 - 45]
    assert set(gp["method"]) == {"formula"}
    fcf = series(long, "free_cash_flow")
    assert fcf["value"].tolist() == [80 - 50, 90 - 70]


def test_reported_gross_profit_not_overwritten_by_formula():
    facts = toy_facts()
    facts["facts"]["us-gaap"]["GrossProfit"] = {"units": {"USD": [
        fact("2023-01-01", "2023-03-31", 55, "2023-04-25")]}}
    gp = series(standardize_company(facts, TAG_MAP, 12), "gross_profit")
    assert gp.loc["2023-03-31", "value"] == 55 and gp.loc["2023-03-31", "method"] == "reported"
    assert gp.loc["2023-06-30", "method"] == "formula"


def test_q4_not_derived_without_three_contiguous_quarters():
    q = quarterize_flow(dedupe(extract_facts(companyfacts({"Revenues": [
        fact("2023-01-01", "2023-03-31", 100, "2023-04-25"),
        fact("2023-07-01", "2023-09-30", 120, "2023-10-25"),
        fact(*FY23, 460, "2024-02-01", form="10-K"),
    ]}), "Revenues")))
    assert q["end"].dt.strftime("%m-%d").tolist() == ["03-31", "09-30"]


def test_fiscal_and_calendar_labels():
    df = pd.DataFrame({"period_end": pd.to_datetime(["2023-09-30", "2024-06-30"])})
    msft = add_period_labels(df, 6)  # FY ends June
    assert msft["fiscal_label"].tolist() == ["FY2024Q1", "FY2024Q4"]
    assert msft["calendar_label"].tolist() == ["2023Q3", "2024Q2"]

    df = pd.DataFrame({"period_end": pd.to_datetime(["2023-08-31", "2024-02-29", "2024-05-31"])})
    orcl = add_period_labels(df, 5)  # FY ends May; quarters a month off calendar
    assert orcl["fiscal_label"].tolist() == ["FY2024Q1", "FY2024Q3", "FY2024Q4"]
    assert orcl["calendar_label"].tolist() == ["2023Q3", "2024Q1", "2024Q2"]


def test_wide_and_fiscal_year_totals():
    long = standardize_company(toy_facts(), TAG_MAP, 12)
    wide = to_wide(long)
    assert len(wide) == 4 and wide["capex"].tolist() == [50, 70, 80, 100]
    assert pd.isna(wide.loc[3, "cfo"])  # missing stays missing
    assert fiscal_year_totals(long, "capex").to_dict() == {2023: 300}
    assert fiscal_year_totals(long, "cfo").empty  # only 2 quarters
