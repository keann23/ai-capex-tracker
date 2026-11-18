"""Segment revenue from each filing's XBRL instance.

SEC's companyfacts API drops dimensional facts, so segment revenue (AWS, Google
Cloud, ...) isn't in it. Every 10-Q/10-K's XBRL instance has it, tagged with a
dimension such as us-gaap:StatementBusinessSegmentsAxis = amzn:AmazonWebServicesSegmentMember.

Pipeline:
  parse_instance()     XML -> revenue facts with their dimensions
  fetch_revenue_facts  every filing since 2018 -> one trimmed table per company
                       (saved as a fixture so tests and rebuilds never call SEC)
  segment_quarters()   pick the configured segment, then reuse the companyfacts
                       quarterizing (dedupe, YTD differencing, Q4 = FY - 9M)
"""

from __future__ import annotations

import re
import xml.etree.ElementTree as ET
from datetime import date

import pandas as pd

from capex_tracker.data.standardize import (
    dedupe, drop_10k_subannual, quarterize_flow,
)

XBRLI = "{http://www.xbrl.org/2003/instance}"
XBRLDI = "{http://xbrl.org/2006/xbrldi}"
REVENUE_CONCEPT = re.compile(r"Revenue|Sales", re.I)
EXCLUDE_CONCEPT = re.compile(r"Cost|Deferred|Percent|Receivable|Unbilled|Remaining|Proceeds|Gain|Loss", re.I)
# Segment operating income too: Phase 2 applies the segment's own margin.
OPERATING_INCOME = re.compile(r"^OperatingIncome", re.I)
MAX_DIMS = 2
DEFAULT_CONCEPTS = [
    "us-gaap:RevenueFromContractWithCustomerExcludingAssessedTax",
    "us-gaap:Revenues",
    "us-gaap:SalesRevenueNet",
]

FACT_COLUMNS = ["accn", "form", "filed", "concept", "start", "end", "value", "dims"]


def _concept_name(tag: str) -> str:
    ns, _, local = tag[1:].partition("}")
    return f"us-gaap:{local}" if "fasb.org/us-gaap" in ns else f"ext:{local}"


def parse_instance(xml_text: str | bytes) -> list[dict]:
    """Revenue-like and operating-income USD duration facts, up to MAX_DIMS dimensions.

    dims is a sorted 'axis=member;axis=member' string ('' for the company total),
    which keeps fixtures small and comparable.
    """
    root = ET.fromstring(xml_text if isinstance(xml_text, bytes) else xml_text.encode())

    usd_units = {
        u.get("id") for u in root.iter(f"{XBRLI}unit")
        if [m.text.strip() for m in u.iter(f"{XBRLI}measure")] == ["iso4217:USD"]
    }
    contexts = {}
    for c in root.iter(f"{XBRLI}context"):
        period = c.find(f"{XBRLI}period")
        start, end = period.find(f"{XBRLI}startDate"), period.find(f"{XBRLI}endDate")
        if start is None or end is None:
            continue  # instants: not revenue
        if any(True for _ in c.iter(f"{XBRLDI}typedMember")):
            continue
        dims = sorted(f"{m.get('dimension')}={m.text.strip()}" for m in c.iter(f"{XBRLDI}explicitMember"))
        if len(dims) <= MAX_DIMS:
            contexts[c.get("id")] = (start.text.strip(), end.text.strip(), ";".join(dims))

    facts, seen = [], set()
    for el in root:
        ctx = el.get("contextRef")
        if ctx not in contexts or el.get("unitRef") not in usd_units or el.text is None:
            continue
        concept = _concept_name(el.tag)
        local = concept.split(":", 1)[1]
        wanted = (REVENUE_CONCEPT.search(local) and not EXCLUDE_CONCEPT.search(local)) \
            or OPERATING_INCOME.search(local)
        if not wanted:
            continue
        start, end, dims = contexts[ctx]
        try:
            value = float(el.text.strip())
        except ValueError:
            continue
        key = (concept, start, end, dims)
        if key in seen:
            continue
        seen.add(key)
        facts.append({"concept": concept, "start": start, "end": end, "value": value, "dims": dims})
    return facts


def fetch_revenue_facts(client, ticker: str, since: str = "2018-01-01", log=print) -> pd.DataFrame:
    """Revenue facts (with dimensions) from every 10-Q/10-K filed since `since`."""
    rows = []
    filings = client.filings(ticker, since=since)
    for i, f in enumerate(filings, 1):
        try:
            facts = parse_instance(client.xbrl_instance(ticker, f["accn"]))
        except Exception as e:  # one bad filing shouldn't stop the run; it's reported
            log(f"  {ticker} {f['form']} {f['accn']} skipped: {e}")
            continue
        rows += [{"accn": f["accn"], "form": f["form"], "filed": f["filed"], **x} for x in facts]
        log(f"  {ticker} {i}/{len(filings)} {f['form']} filed {f['filed']}: {len(facts)} revenue facts")
    return pd.DataFrame(rows, columns=FACT_COLUMNS)


def segment_quarters(facts: pd.DataFrame, spec: dict, keep: str = "latest") -> pd.DataFrame:
    """Quarterly revenue for one segment.

    spec (from companies.yaml segment_xbrl):
      member: regex on the member name, e.g. 'AmazonWebServices'
      axes:   allowed dimension axes, e.g. [us-gaap:StatementBusinessSegmentsAxis]
      concepts: revenue concepts in priority order
    Facts must have exactly one dimension: that segment on an allowed axis.
    """
    member = re.compile(spec["member"])
    axes = set(spec["axes"])
    concepts = spec.get("concepts", DEFAULT_CONCEPTS)

    def matches(dims: str) -> bool:
        if not dims or ";" in dims:
            return False
        axis, _, mem = dims.partition("=")
        return axis in axes and bool(member.search(mem))

    f = facts[facts["dims"].map(matches)].copy()
    pieces = []
    for priority, concept in enumerate(concepts):
        c = f[f["concept"] == concept]
        if c.empty:
            continue
        c = pd.DataFrame({
            "start": pd.to_datetime(c["start"]), "end": pd.to_datetime(c["end"]),
            "val": c["value"].astype(float), "filed": pd.to_datetime(c["filed"]),
            "form": c["form"], "accn": c["accn"], "tag": concept,
        })
        q = quarterize_flow(dedupe(drop_10k_subannual(c), keep))
        if not q.empty:
            pieces.append(q.assign(priority=priority))
    if not pieces:
        return pd.DataFrame(columns=["start", "end", "val", "tag", "method", "filed", "accn"])
    allq = pd.concat(pieces).sort_values(["end", "priority"], kind="stable")
    return allq.drop_duplicates("end").drop(columns="priority").reset_index(drop=True)


def restatements(facts: pd.DataFrame, spec: dict, rel_tol: float = 0.005) -> pd.DataFrame:
    """Quarters whose value changed between filings (segment recasts). Shown, not hidden."""
    q = segment_quarters(facts, spec, "earliest").set_index("end")["val"]
    l = segment_quarters(facts, spec, "latest").set_index("end")["val"]
    both = pd.concat([q.rename("first_reported"), l.rename("latest")], axis=1).dropna()
    changed = (both["latest"] - both["first_reported"]).abs() > both["first_reported"].abs() * rel_tol
    return both[changed]


def to_segments_csv_rows(q: pd.DataFrame, ticker: str, segment: str, entered: date) -> pd.DataFrame:
    """Rows in config/segments.csv format, sourced to the filing that gave each value."""
    return pd.DataFrame({
        "company": ticker,
        "period_end": q["end"].dt.strftime("%Y-%m-%d"),
        "segment": segment,
        "revenue_usd": q["val"].round().astype("int64"),
        "source_accession": q["accn"],
        "entered_date": entered.isoformat(),
        "method": q["method"],
    })


def load_facts(path) -> pd.DataFrame:
    return pd.read_csv(path, dtype={"dims": str}, keep_default_na=False,
                       converters={"value": float})


def build_segments_table(companies: dict, fact_dir, entered: date) -> pd.DataFrame:
    """segments.csv rows for every company that has a saved facts file and a segment_xbrl spec."""
    from pathlib import Path
    out = []
    for ticker, c in companies.items():
        path = Path(fact_dir) / f"{ticker}.csv.gz"
        if "segment_xbrl" not in c or not path.exists():
            continue
        q = segment_quarters(load_facts(path), c["segment_xbrl"])
        out.append(to_segments_csv_rows(q, ticker, c["segment"], entered))
    return pd.concat(out, ignore_index=True) if out else pd.DataFrame()


def segment_members(facts: pd.DataFrame, form: str = "10-K") -> pd.DataFrame:
    """Discovery aid: single-dimension revenue members in a company's latest 10-K."""
    f = facts[(facts["form"] == form) & facts["dims"].ne("") & ~facts["dims"].str.contains(";")]
    f = f[f["accn"] == f.sort_values("filed")["accn"].iloc[-1]] if not f.empty else f
    return (f.assign(days=(pd.to_datetime(f["end"]) - pd.to_datetime(f["start"])).dt.days)
             .query("days > 350").sort_values("end")
             .drop_duplicates(["concept", "dims"], keep="last")[["concept", "dims", "end", "value"]])
