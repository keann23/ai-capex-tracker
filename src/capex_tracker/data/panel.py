"""Everything the models need for one company, read from committed snapshots.

The app never calls SEC: scripts/fetch_*.py refresh snapshots/ and
config/segments.csv each quarter, and every number on screen is reproducible
from the repo.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from functools import lru_cache

import pandas as pd

from capex_tracker.config import SNAPSHOT_DIR, fiscal_year_end_month, load_companies, load_tag_map
from capex_tracker.data.manual_inputs import load_segments
from capex_tracker.data.segments_xbrl import load_facts, segment_quarters
from capex_tracker.data.standardize import add_period_labels, standardize_company, to_wide
from capex_tracker.models.excess import ttm_margin

OP_INCOME = ["us-gaap:OperatingIncomeLoss"]


@dataclass(frozen=True)
class CompanyData:
    ticker: str
    name: str
    segment: str
    segment_note: str
    quarters: pd.DataFrame        # index period_end; raw USD columns + labels
    long: pd.DataFrame            # standardized companyfacts with tag/method/accn per value
    segments: pd.DataFrame        # segments.csv rows for this company
    margin: float                 # default margin applied to excess revenue
    margin_label: str
    margin_as_of: pd.Timestamp
    data_through: pd.Timestamp    # filing date of the newest companyfacts value


@lru_cache(maxsize=None)
def load_company(ticker: str) -> CompanyData:
    company = load_companies()["companies"][ticker]
    facts = json.loads((SNAPSHOT_DIR / "companyfacts" / f"{ticker}.json").read_text())
    long = standardize_company(facts, load_tag_map(), fiscal_year_end_month(company))
    q = to_wide(long).set_index("period_end")

    segs = load_segments()
    segs = segs[segs["company"] == ticker].set_index("period_end")
    q = q.join(segs["revenue_usd"].rename("segment_revenue"), how="outer")
    # Label every row, including segment quarters with no companyfacts row.
    labels = add_period_labels(pd.DataFrame({"period_end": q.index}), fiscal_year_end_month(company))
    q["calendar_label"] = labels["calendar_label"].values
    q["fiscal_label"] = labels["fiscal_label"].values

    margin, label, as_of = _default_margin(ticker, company, q)
    return CompanyData(
        ticker=ticker, name=company["name"], segment=company["segment"],
        segment_note=company.get("segment_note", ""), quarters=q.sort_index(), long=long,
        segments=segs, margin=margin, margin_label=label, margin_as_of=as_of,
        data_through=long["filed"].max(),
    )


def _default_margin(ticker: str, company: dict, q: pd.DataFrame) -> tuple[float, str, pd.Timestamp]:
    """TTM segment operating margin if the company reports one, else company-wide."""
    spec = company.get("margin_xbrl")
    path = SNAPSHOT_DIR / "segment_facts" / f"{ticker}.csv.gz"
    if spec and path.exists():
        facts = load_facts(path)
        oi = segment_quarters(facts, {**spec["op_income"], "concepts": OP_INCOME}).set_index("end")["val"]
        rev = segment_quarters(facts, spec["revenue"]).set_index("end")["val"]
        m, as_of = ttm_margin(oi, rev)
        return m, spec["label"], as_of
    m, as_of = ttm_margin(q["operating_income"], q["revenue"])
    return m, "Company-wide operating margin (no segment margin reported)", as_of


def companies() -> dict:
    return load_companies()["companies"]
