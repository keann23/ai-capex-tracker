"""Segment extraction from XBRL. Toy XML and toy facts; real files only if fetched."""

from pathlib import Path

import pandas as pd
import pytest

from capex_tracker.config import SNAPSHOT_DIR, load_companies
from capex_tracker.data.sec_client import pick_instance
from capex_tracker.data.segments_xbrl import (
    load_facts, parse_instance, restatements, segment_quarters, suspicious_quarters,
    to_segments_csv_rows,
)

SEG = "us-gaap:StatementBusinessSegmentsAxis"
SPEC = {"member": "AmazonWebServices", "axes": [SEG]}

TOY_XML = f"""<?xml version="1.0"?>
<xbrl xmlns="http://www.xbrl.org/2003/instance" xmlns:xbrli="http://www.xbrl.org/2003/instance"
      xmlns:xbrldi="http://xbrl.org/2006/xbrldi" xmlns:iso4217="http://www.xbrl.org/2003/iso4217"
      xmlns:us-gaap="http://fasb.org/us-gaap/2024" xmlns:amzn="http://www.amazon.com/20240331">
  <xbrli:unit id="usd"><xbrli:measure>iso4217:USD</xbrli:measure></xbrli:unit>
  <xbrli:unit id="eur"><xbrli:measure>iso4217:EUR</xbrli:measure></xbrli:unit>
  <xbrli:context id="total"><xbrli:entity><xbrli:identifier scheme="x">1</xbrli:identifier></xbrli:entity>
    <xbrli:period><xbrli:startDate>2024-01-01</xbrli:startDate><xbrli:endDate>2024-03-31</xbrli:endDate></xbrli:period></xbrli:context>
  <xbrli:context id="aws"><xbrli:entity><xbrli:identifier scheme="x">1</xbrli:identifier>
    <xbrli:segment><xbrldi:explicitMember dimension="{SEG}">amzn:AmazonWebServicesSegmentMember</xbrldi:explicitMember></xbrli:segment></xbrli:entity>
    <xbrli:period><xbrli:startDate>2024-01-01</xbrli:startDate><xbrli:endDate>2024-03-31</xbrli:endDate></xbrli:period></xbrli:context>
  <xbrli:context id="three"><xbrli:entity><xbrli:identifier scheme="x">1</xbrli:identifier>
    <xbrli:segment><xbrldi:explicitMember dimension="a:A">a:X</xbrldi:explicitMember>
      <xbrldi:explicitMember dimension="b:B">b:Y</xbrldi:explicitMember>
      <xbrldi:explicitMember dimension="c:C">c:Z</xbrldi:explicitMember></xbrli:segment></xbrli:entity>
    <xbrli:period><xbrli:startDate>2024-01-01</xbrli:startDate><xbrli:endDate>2024-03-31</xbrli:endDate></xbrli:period></xbrli:context>
  <xbrli:context id="inst"><xbrli:entity><xbrli:identifier scheme="x">1</xbrli:identifier></xbrli:entity>
    <xbrli:period><xbrli:instant>2024-03-31</xbrli:instant></xbrli:period></xbrli:context>
  <us-gaap:RevenueFromContractWithCustomerExcludingAssessedTax contextRef="total" unitRef="usd" decimals="-6">143313000000</us-gaap:RevenueFromContractWithCustomerExcludingAssessedTax>
  <us-gaap:RevenueFromContractWithCustomerExcludingAssessedTax contextRef="aws" unitRef="usd" decimals="-6">25037000000</us-gaap:RevenueFromContractWithCustomerExcludingAssessedTax>
  <us-gaap:RevenueFromContractWithCustomerExcludingAssessedTax contextRef="aws" unitRef="usd" decimals="-6">25037000000</us-gaap:RevenueFromContractWithCustomerExcludingAssessedTax>
  <us-gaap:OperatingIncomeLoss contextRef="aws" unitRef="usd" decimals="-6">9421000000</us-gaap:OperatingIncomeLoss>
  <us-gaap:CostOfRevenue contextRef="aws" unitRef="usd">1</us-gaap:CostOfRevenue>
  <us-gaap:Revenues contextRef="aws" unitRef="eur">2</us-gaap:Revenues>
  <us-gaap:Revenues contextRef="three" unitRef="usd">3</us-gaap:Revenues>
  <us-gaap:Revenues contextRef="inst" unitRef="usd">4</us-gaap:Revenues>
</xbrl>"""


def test_parse_instance_keeps_usd_revenue_and_operating_income_by_segment():
    facts = parse_instance(TOY_XML)
    got = {(f["concept"], f["dims"], f["value"]) for f in facts}
    aws = f"{SEG}=amzn:AmazonWebServicesSegmentMember"
    assert got == {
        ("us-gaap:RevenueFromContractWithCustomerExcludingAssessedTax", "", 143313000000.0),
        ("us-gaap:RevenueFromContractWithCustomerExcludingAssessedTax", aws, 25037000000.0),
        ("us-gaap:OperatingIncomeLoss", aws, 9421000000.0),
    }  # duplicate dropped; cost, EUR, 3-dim and instant facts skipped


def f(accn, form, filed, start, end, value, member="amzn:AmazonWebServicesSegmentMember",
      concept="us-gaap:RevenueFromContractWithCustomerExcludingAssessedTax", axis=SEG):
    return dict(accn=accn, form=form, filed=filed, concept=concept, start=start, end=end,
                value=value, dims=f"{axis}={member}" if member else "")


def toy_facts():
    return pd.DataFrame([
        f("q1", "10-Q", "2024-04-30", "2024-01-01", "2024-03-31", 100),
        f("q2", "10-Q", "2024-08-01", "2024-04-01", "2024-06-30", 110),
        f("q2", "10-Q", "2024-08-01", "2024-01-01", "2024-06-30", 210),
        f("q3", "10-Q", "2024-10-31", "2024-01-01", "2024-09-30", 330),   # YTD only
        f("k", "10-K", "2025-02-07", "2024-01-01", "2024-12-31", 460),
        f("k", "10-K", "2025-02-07", "2024-01-01", "2024-03-31", 999),    # 10-K quarter table: ignored
        f("q1", "10-Q", "2024-04-30", "2024-01-01", "2024-03-31", 7, member="amzn:NorthAmericaSegmentMember"),
        f("q1", "10-Q", "2024-04-30", "2024-01-01", "2024-03-31", 8, member=None),
        f("q1", "10-Q", "2024-04-30", "2024-01-01", "2024-03-31", 9, concept="us-gaap:OperatingIncomeLoss"),
    ])


def test_segment_quarters_reuses_ytd_and_q4_logic():
    q = segment_quarters(toy_facts(), SPEC)
    assert q["val"].tolist() == [100, 110, 120, 130]
    assert q["method"].tolist() == ["reported", "reported", "ytd_diff", "ytd_diff"]
    assert q["accn"].tolist() == ["q1", "q2", "q3", "k"]


def test_segment_operating_income_via_concepts():
    q = segment_quarters(toy_facts(), {**SPEC, "concepts": ["us-gaap:OperatingIncomeLoss"]})
    assert q["val"].tolist() == [9]


def test_member_prefix_change_is_one_series():
    facts = pd.DataFrame([
        f("a", "10-Q", "2021-04-29", "2021-01-01", "2021-03-31", 50, member="fb:FamilyOfAppsMember"),
        f("b", "10-Q", "2022-04-28", "2022-01-01", "2022-03-31", 60, member="meta:FamilyOfAppsMember"),
        f("b", "10-Q", "2022-04-28", "2021-01-01", "2021-03-31", 50, member="meta:FamilyOfAppsMember"),
    ])
    q = segment_quarters(facts, {"member": "FamilyOfApps", "axes": [SEG]})
    assert q["val"].tolist() == [50, 60]


def test_sources_tried_in_order_with_extra_dimension_and_sums():
    facts = pd.DataFrame([
        # old line, 2023 Q1-Q2
        f("a", "10-Q", "2023-04-30", "2023-01-01", "2023-03-31", 100, member="orcl:OldLineMember", axis="srt:ProductOrServiceAxis"),
        f("b", "10-Q", "2023-07-30", "2023-04-01", "2023-06-30", 110, member="orcl:OldLineMember", axis="srt:ProductOrServiceAxis"),
        # new lines replace it from Q2 (overlap) to Q3: summed
        f("b", "10-Q", "2023-07-30", "2023-04-01", "2023-06-30", 60, member="orcl:CloudMember", axis="srt:ProductOrServiceAxis"),
        f("b", "10-Q", "2023-07-30", "2023-04-01", "2023-06-30", 50, member="orcl:SupportMember", axis="srt:ProductOrServiceAxis"),
        f("c", "10-Q", "2023-10-30", "2023-07-01", "2023-09-30", 70, member="orcl:CloudMember", axis="srt:ProductOrServiceAxis"),
        f("c", "10-Q", "2023-10-30", "2023-07-01", "2023-09-30", 55, member="orcl:SupportMember", axis="srt:ProductOrServiceAxis"),
    ])
    spec = {"sources": [
        {"members": [":OldLineMember$"], "axes": ["srt:ProductOrServiceAxis"]},
        {"members": [":CloudMember$", ":SupportMember$"], "axes": ["srt:ProductOrServiceAxis"]},
    ]}
    assert segment_quarters(facts, spec)["val"].tolist() == [100, 110, 125]

    two_dim = pd.DataFrame([dict(
        accn="a", form="10-Q", filed="2020-04-29", concept="us-gaap:Revenues", start="2019-01-01",
        end="2019-03-31", value=1825.0,
        dims=f"srt:ProductOrServiceAxis=goog:GoogleCloudMember;{SEG}=goog:GoogleInc.Member")])
    with_spec = {"sources": [{"members": [":GoogleCloudMember$"], "axes": ["srt:ProductOrServiceAxis"],
                              "with": "GoogleInc"}]}
    assert segment_quarters(two_dim, with_spec)["val"].tolist() == [1825]
    no_with = {"sources": [{"members": [":GoogleCloudMember$"], "axes": ["srt:ProductOrServiceAxis"]}]}
    assert segment_quarters(two_dim, no_with).empty  # extra dimension not allowed unless named


def test_suspicious_quarter_flagged():
    q = pd.DataFrame({"end": pd.to_datetime(["2023-03-31", "2023-06-30", "2023-09-30"]),
                      "val": [22.0, 9.0, 20.0], "method": ["reported", "ytd_diff", "reported"]})
    assert suspicious_quarters(q)["val"].tolist() == [9.0]


def test_restatements_flagged():
    facts = pd.concat([toy_facts(), pd.DataFrame([
        f("q1b", "10-Q", "2025-04-30", "2024-01-01", "2024-03-31", 90)])])  # recast next year
    r = restatements(facts, SPEC)
    assert list(r.index.strftime("%Y-%m-%d")) == ["2024-03-31"]
    assert r.iloc[0].tolist() == [100, 90]


def test_csv_rows_have_source_and_method():
    rows = to_segments_csv_rows(segment_quarters(toy_facts(), SPEC), "AMZN", "AWS",
                                pd.Timestamp("2026-11-18").date())
    assert rows.iloc[3].to_dict() == {
        "company": "AMZN", "period_end": "2024-12-31", "segment": "AWS", "revenue_usd": 130,
        "source_accession": "k", "entered_date": "2026-11-18", "method": "ytd_diff"}


def test_pick_instance():
    assert pick_instance(["amzn-20240331.htm", "amzn-20240331_htm.xml", "amzn-20240331_cal.xml"]) \
        == "amzn-20240331_htm.xml"
    assert pick_instance(["goog-20181231.xml", "goog-20181231_lab.xml", "FilingSummary.xml",
                          "goog-20181231_pre.xml"]) == "goog-20181231.xml"
    assert pick_instance(["a.htm"]) is None


# ---- real data (skipped until scripts/fetch_segments.py has run) ----

FACT_DIR = SNAPSHOT_DIR / "segment_facts"
COMPANIES = load_companies()["companies"]

# Annual segment revenue from each company's 10-K (USD).
KNOWN_ANNUAL = [
    ("AMZN", "2024-01-01", "2024-12-31", 107_556e6),   # AWS, 2024 10-K
    ("GOOGL", "2024-01-01", "2024-12-31", 43_229e6),   # Google Cloud, 2024 10-K
    ("META", "2024-01-01", "2024-12-31", 160_633e6),   # Advertising, 2024 10-K
    ("MSFT", "2023-07-01", "2024-06-30", 137_700e6),   # Microsoft Cloud FY2024: $137.4B, restated to $137.7B in FY2025 10-K
    ("ORCL", "2023-06-01", "2024-05-31", 39_383e6),    # Cloud services & license support, FY2024 10-K
]


@pytest.mark.parametrize("ticker,start,end,expected", KNOWN_ANNUAL)
def test_known_annual_segment_revenue(ticker, start, end, expected):
    path = FACT_DIR / f"{ticker}.csv.gz"
    if not path.exists():
        pytest.skip("run scripts/fetch_segments.py")
    q = segment_quarters(load_facts(path), COMPANIES[ticker]["segment_xbrl"])
    inside = q[(q["start"] >= start) & (q["end"] <= end)]
    assert len(inside) == 4, f"{ticker}: {len(inside)} quarters in the year"
    assert inside["val"].sum() == pytest.approx(expected, rel=0.002)


@pytest.mark.parametrize("ticker", list(COMPANIES))
def test_no_suspicious_drops(ticker):
    path = FACT_DIR / f"{ticker}.csv.gz"
    if not path.exists():
        pytest.skip("run scripts/fetch_segments.py")
    q = segment_quarters(load_facts(path), COMPANIES[ticker]["segment_xbrl"])
    bad = suspicious_quarters(q)
    assert bad.empty, f"{ticker}: {bad[['end', 'val', 'method']].to_string()}"


@pytest.mark.parametrize("ticker", list(COMPANIES))
def test_segment_series_covers_baseline(ticker):
    path = FACT_DIR / f"{ticker}.csv.gz"
    if not path.exists():
        pytest.skip("run scripts/fetch_segments.py")
    q = segment_quarters(load_facts(path), COMPANIES[ticker]["segment_xbrl"])
    assert q["end"].min() <= pd.Timestamp("2019-03-31"), f"{ticker} starts {q['end'].min().date()}"
    q = q[q["end"] >= "2018-01-01"].reset_index(drop=True)  # pre-baseline gaps don't matter
    gaps = q["end"].diff().dt.days.dropna()
    assert (gaps < 100).all(), f"{ticker} has gaps after {q['end'][gaps.index[gaps >= 100] - 1].dt.date.tolist()}"
