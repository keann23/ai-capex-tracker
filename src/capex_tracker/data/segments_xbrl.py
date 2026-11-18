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
    which keeps snapshots small and comparable.
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


EMPTY_Q = ["start", "end", "val", "tag", "method", "filed", "accn"]


def _sources(spec: dict) -> list[dict]:
    """Normalize a segment_xbrl spec into a list of sources (old single-member form allowed)."""
    if "sources" in spec:
        return spec["sources"]
    return [{"members": [spec["member"]], "axes": spec["axes"], **(
        {"concepts": spec["concepts"]} if "concepts" in spec else {})}]


def _matcher(member: str, axes: list[str], with_dim: str | None):
    """True for dims with `member` on an allowed axis, plus exactly one other
    dimension matching `with_dim` if given, otherwise no other dimension."""
    mem_re, axes, with_re = re.compile(member), set(axes), re.compile(with_dim) if with_dim else None

    def matches(dims: str) -> bool:
        parts = dims.split(";") if dims else []
        hits = [p for p in parts if p.partition("=")[0] in axes and mem_re.search(p.partition("=")[2])]
        if len(hits) != 1:
            return False
        others = [p for p in parts if p != hits[0]]
        return (not others) if with_re is None else (len(others) == 1 and bool(with_re.search(others[0])))
    return matches


def _member_quarters(facts, member, axes, with_dim, concepts, keep) -> pd.DataFrame:
    f = facts[facts["dims"].map(_matcher(member, axes, with_dim))]
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
        return pd.DataFrame(columns=EMPTY_Q)
    allq = pd.concat(pieces).sort_values(["end", "priority"], kind="stable")
    return allq.drop_duplicates("end").drop(columns="priority").reset_index(drop=True)


def segment_quarters(facts: pd.DataFrame, spec: dict, keep: str = "latest") -> pd.DataFrame:
    """Quarterly values for one tracked line, from the sources in its spec.

    spec (companies.yaml segment_xbrl) has `sources`, tried in order per quarter:
      members:  regexes on member names; more than one are summed (e.g. Oracle's
                FY2026 'Cloud' + 'Software support' = the old line it replaced)
      axes:     allowed dimension axes
      with:     optional regex for one extra dimension the fact also carries
                (Alphabet tagged 2019 Google Cloud revenue inside 'Google Inc.')
      concepts: optional; defaults to the standard revenue concepts
    The first source with a value for a quarter wins, like tag drift in companyfacts.
    """
    pieces = []
    for priority, src in enumerate(_sources(spec)):
        concepts = src.get("concepts", spec.get("concepts", DEFAULT_CONCEPTS))
        parts = [_member_quarters(facts, m, src["axes"], src.get("with"), concepts, keep)
                 for m in src["members"]]
        if any(p.empty for p in parts):
            continue
        q = parts[0]
        if len(parts) > 1:
            idx = [p.set_index("end") for p in parts]
            common = sorted(set.intersection(*(set(i.index) for i in idx)))
            if not common:
                continue
            first = idx[0].loc[common]
            q = pd.DataFrame({
                "start": first["start"].values, "end": common,
                "val": sum(i.loc[common, "val"].values for i in idx),
                "tag": first["tag"].values,
                "method": ["+".join(sorted(set(ms))) for ms in zip(*(i.loc[common, "method"] for i in idx))],
                "filed": pd.concat([i.loc[common, "filed"] for i in idx], axis=1).max(axis=1).values,
                "accn": first["accn"].values,
            })
        pieces.append(q.assign(priority=priority))
    if not pieces:
        return pd.DataFrame(columns=EMPTY_Q)
    allq = pd.concat(pieces).sort_values(["end", "priority"], kind="stable")
    return allq.drop_duplicates("end").drop(columns="priority").reset_index(drop=True)


def suspicious_quarters(q: pd.DataFrame, drop: float = 0.3) -> pd.DataFrame:
    """Quarters more than `drop` below both neighbours: the signature of a Q4 computed
    from a restated full year minus a non-restated 9 months. Shown, not hidden."""
    v = q.set_index("end")["val"]
    prev, nxt = v.shift(1), v.shift(-1)
    bad = (v < prev * (1 - drop)) & (v < nxt * (1 - drop))
    return q[bad.values]


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
