"""Turn SEC companyfacts JSON into one clean quarterly series per line item.

Handles the gotchas in docs/SEC_DATA_NOTES.md:
  1. duplicates            -> dedupe(), keep earliest or latest filing
  2. YTD vs quarter        -> durations classified by length; YTD chains differenced
  3. Q4 not filed          -> Q4 = FY - 9M YTD, or FY - (Q1+Q2+Q3)
  4. tag drift             -> per period, first tag in priority order with a value
  5. fiscal years          -> periods placed by start/end dates, never fy/fp
  7. derived items         -> tag_map 'derive' formulas, marked method="formula"

Output is "long": one row per (item, quarter) with the tag and method that
produced it, so every number can be traced back to a filing.
"""

from __future__ import annotations

from typing import Literal

import pandas as pd

Keep = Literal["earliest", "latest"]

QUARTER_DAYS = (80, 100)
ANNUAL_DAYS = (350, 380)
ONE_DAY = pd.Timedelta(days=1)

# Lower number wins when several methods give the same quarter.
METHOD_RANK = {"reported": 0, "ytd_diff": 1, "q4_derived": 2}

LONG_COLUMNS = ["item", "period_start", "period_end", "value", "tag", "method", "filed", "accn"]


def _is_quarter(days) -> pd.Series | bool:
    return (days >= QUARTER_DAYS[0]) & (days <= QUARTER_DAYS[1])


def _is_annual(days) -> pd.Series | bool:
    return (days >= ANNUAL_DAYS[0]) & (days <= ANNUAL_DAYS[1])


def extract_facts(companyfacts: dict, tag: str) -> pd.DataFrame:
    """All USD facts for one us-gaap tag from 10-K/10-Q filings (and amendments)."""
    rows = (
        companyfacts.get("facts", {}).get("us-gaap", {}).get(tag, {}).get("units", {}).get("USD", [])
    )
    df = pd.DataFrame(rows, columns=["start", "end", "val", "filed", "form", "accn"])
    if df.empty:
        return df.assign(tag=pd.Series(dtype=str))
    df = df[df["form"].astype(str).str.match(r"10-[KQ]")].copy()
    for col in ("start", "end", "filed"):
        df[col] = pd.to_datetime(df[col])
    df["val"] = df["val"].astype(float)
    df["tag"] = tag
    return df.reset_index(drop=True)


def dedupe(df: pd.DataFrame, keep: Keep = "latest") -> pd.DataFrame:
    """One value per (tag, start, end).

    'earliest' = first filing that reported it (what was known then, for backtests).
    'latest'   = most recent filing, including restatements (current view).
    """
    if keep not in ("earliest", "latest"):
        raise ValueError("keep must be 'earliest' or 'latest'")
    keys = ["tag", "end"] if "start" not in df or df["start"].isna().all() else ["tag", "start", "end"]
    ordered = df.sort_values(["filed", "accn"], kind="stable")
    out = ordered.drop_duplicates(subset=keys, keep="first" if keep == "earliest" else "last")
    return out.sort_values(keys).reset_index(drop=True)


def quarterize_flow(facts: pd.DataFrame) -> pd.DataFrame:
    """Discrete quarters for one tag's deduped flow facts.

    Uses, in order of preference: 3-month values as reported; differences of
    consecutive year-to-date values sharing a start date (cash flow statements in
    10-Qs are YTD only); and Q4 = FY - (Q1+Q2+Q3) when nothing else gives Q4.
    """
    cols = ["tag", "start", "end", "val", "filed", "accn", "method"]
    if facts.empty:
        return pd.DataFrame(columns=cols)
    facts = facts.dropna(subset=["start"]).copy()
    facts["days"] = (facts["end"] - facts["start"]).dt.days

    parts = [facts[_is_quarter(facts["days"])].assign(method="reported")]

    # Year-to-date chains: same start, increasing end. Each step is one quarter.
    ytd_rows = []
    for _, chain in facts.groupby("start"):
        chain = chain.sort_values("end")
        for prev, cur in zip(chain.itertuples(), chain.iloc[1:].itertuples()):
            q_start = prev.end + ONE_DAY
            if _is_quarter((cur.end - q_start).days):
                ytd_rows.append(
                    dict(tag=cur.tag, start=q_start, end=cur.end, val=cur.val - prev.val,
                         filed=max(prev.filed, cur.filed), accn=cur.accn, method="ytd_diff")
                )
    parts.append(pd.DataFrame(ytd_rows, columns=cols))
    quarters = _best_per_end(pd.concat(parts, ignore_index=True)[cols])

    # Q4 fallback: FY minus three contiguous quarters inside that year.
    q4_rows = []
    for fy in facts[_is_annual(facts["days"])].itertuples():
        if (quarters["end"] == fy.end).any():
            continue
        inside = quarters[(quarters["start"] >= fy.start) & (quarters["end"] < fy.end)].sort_values("end")
        if len(inside) != 3 or inside["start"].iloc[0] != fy.start:
            continue
        contiguous = all(
            inside["start"].iloc[i] == inside["end"].iloc[i - 1] + ONE_DAY for i in (1, 2)
        )
        q4_start = inside["end"].iloc[-1] + ONE_DAY
        if contiguous and _is_quarter((fy.end - q4_start).days):
            q4_rows.append(
                dict(tag=fy.tag, start=q4_start, end=fy.end, val=fy.val - inside["val"].sum(),
                     filed=max(fy.filed, inside["filed"].max()), accn=fy.accn, method="q4_derived")
            )
    if q4_rows:
        quarters = _best_per_end(pd.concat([quarters, pd.DataFrame(q4_rows, columns=cols)], ignore_index=True))
    return quarters


def _best_per_end(df: pd.DataFrame) -> pd.DataFrame:
    if df.empty:
        return df
    df = df.astype({"val": float})
    for col in ("start", "end", "filed"):
        df[col] = pd.to_datetime(df[col])
    df = df.assign(_rank=df["method"].map(METHOD_RANK))
    df = df.sort_values(["end", "_rank"], kind="stable").drop_duplicates("end", keep="first")
    return df.drop(columns="_rank").reset_index(drop=True)


def _item_series(companyfacts: dict, spec: dict, keep: Keep) -> pd.DataFrame:
    """One row per period for an item, picking per period the first tag in priority order."""
    pieces = []
    for priority, tag in enumerate(spec.get("tags") or []):
        facts = extract_facts(companyfacts, tag)
        if facts.empty:
            continue
        if spec["type"] == "flow":
            q = quarterize_flow(dedupe(facts[facts["start"].notna()], keep))
        else:
            inst = facts[facts["start"].isna()].drop(columns="start")
            q = dedupe(inst, keep).assign(start=pd.NaT, method="reported")
        if not q.empty:
            pieces.append(q.assign(priority=priority))
    if not pieces:
        return pd.DataFrame(columns=["start", "end", "val", "tag", "method", "filed", "accn"])
    allq = pd.concat(pieces, ignore_index=True).sort_values(["end", "priority"], kind="stable")
    return allq.drop_duplicates("end", keep="first").drop(columns="priority")


def _parse_formula(expr: str) -> tuple[str, str, str]:
    parts = expr.split()
    if len(parts) != 3 or parts[1] not in "+-":
        raise ValueError(f"Unsupported derive formula {expr!r}; use 'a - b' or 'a + b'")
    return parts[0], parts[1], parts[2]


def standardize_company(
    companyfacts: dict,
    tag_map: dict,
    fiscal_year_end_month: int,
    keep: Keep = "latest",
) -> pd.DataFrame:
    """Long DataFrame of quarterly values for every item in tag_map, with period labels."""
    frames = []
    for item, spec in tag_map.items():
        s = _item_series(companyfacts, spec, keep)
        frames.append(
            pd.DataFrame({
                "item": item, "period_start": s["start"], "period_end": s["end"],
                "value": s["val"], "tag": s["tag"], "method": s["method"],
                "filed": s["filed"], "accn": s["accn"],
            })
        )
    long = pd.concat([f for f in frames if not f.empty], ignore_index=True) if any(
        not f.empty for f in frames) else pd.DataFrame(columns=LONG_COLUMNS)

    # Instants only at quarter ends that have flow data (drops odd comparative dates).
    flow_items = [i for i, s in tag_map.items() if s["type"] == "flow"]
    quarter_ends = set(long.loc[long["item"].isin(flow_items), "period_end"])
    is_instant = long["item"].isin([i for i, s in tag_map.items() if s["type"] == "instant"])
    long = long[~is_instant | long["period_end"].isin(quarter_ends)]

    long = _apply_formulas(long, tag_map)
    long = long.astype({"value": float, "item": str, "tag": str, "method": str})
    for col in ("period_start", "period_end", "filed"):
        long[col] = pd.to_datetime(long[col])
    return add_period_labels(long, fiscal_year_end_month).sort_values(
        ["item", "period_end"]).reset_index(drop=True)


def _apply_formulas(long: pd.DataFrame, tag_map: dict) -> pd.DataFrame:
    """Fill items with a 'derive' formula where no tag gave a value. Marked method='formula'."""
    for item, spec in tag_map.items():
        if not spec.get("derive"):
            continue
        a, op, b = _parse_formula(spec["derive"])
        va = long[long["item"] == a].set_index("period_end")
        vb = long[long["item"] == b].set_index("period_end")
        have = set(long.loc[long["item"] == item, "period_end"])
        ends = sorted(set(va.index) & set(vb.index) - have)
        if not ends:
            continue
        x, y = va.loc[ends], vb.loc[ends]
        derived = pd.DataFrame({
            "item": item,
            "period_start": x["period_start"].values,
            "period_end": ends,
            "value": (x["value"] - y["value"] if op == "-" else x["value"] + y["value"]).values,
            "tag": spec["derive"],
            "method": "formula",
            "filed": pd.concat([x["filed"], y["filed"]], axis=1).max(axis=1).values,
            "accn": None,
        })
        long = pd.concat([long, derived], ignore_index=True)
    return long


def add_period_labels(df: pd.DataFrame, fiscal_year_end_month: int) -> pd.DataFrame:
    """Add fiscal and calendar labels from period_end.

    Fiscal: the company's own calendar (MSFT FY ends June, ORCL May).
    Calendar: the calendar quarter holding the middle of the fiscal quarter, so
    companies line up. Oracle's quarters end a month after calendar quarters
    (Aug/Nov/Feb/May); its Jun-Aug quarter is labelled calendar Q3.
    """
    end = pd.to_datetime(df["period_end"])
    m = fiscal_year_end_month
    fiscal_year = end.dt.year + (end.dt.month > m).astype(int)
    fiscal_quarter = ((end.dt.month - m - 1) % 12) // 3 + 1
    mid = end - pd.Timedelta(days=45)
    return df.assign(
        fiscal_year=fiscal_year.values,
        fiscal_quarter=fiscal_quarter.values,
        fiscal_label=[f"FY{y}Q{q}" for y, q in zip(fiscal_year, fiscal_quarter)],
        calendar_year=mid.dt.year.values,
        calendar_quarter=mid.dt.quarter.values,
        calendar_label=[f"{y}Q{q}" for y, q in zip(mid.dt.year, mid.dt.quarter)],
    )


def to_wide(long: pd.DataFrame) -> pd.DataFrame:
    """One row per quarter, one column per item (raw USD). Missing stays NaN."""
    idx = ["period_end", "calendar_label", "fiscal_label"]
    wide = long.pivot_table(index=idx, columns="item", values="value", aggfunc="first")
    wide.columns.name = None
    return wide.reset_index().sort_values("period_end").reset_index(drop=True)


def fiscal_year_totals(long: pd.DataFrame, item: str) -> pd.Series:
    """Sum of an item's 4 fiscal quarters per fiscal year; years without all 4 are dropped."""
    s = long[long["item"] == item]
    g = s.groupby("fiscal_year")["value"]
    counts = g.count()
    return g.sum()[counts == 4]
