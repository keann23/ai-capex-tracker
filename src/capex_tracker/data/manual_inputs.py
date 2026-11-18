"""Load and validate the hand-entered CSVs in config/.

Rule: every hand-entered number carries a source and a date. A row without one
is rejected, not silently dropped.
"""

from __future__ import annotations

import re
from pathlib import Path

import pandas as pd

from capex_tracker.config import CONFIG_DIR, load_companies

SEGMENT_COLUMNS = ["company", "period_end", "segment", "revenue_usd", "source_accession", "entered_date"]
GUIDANCE_COLUMNS = ["company", "period", "capex_guidance_low_usd", "capex_guidance_high_usd",
                    "source", "date_given"]

# Guidance period, in the company's fiscal calendar: FY2026 or FY2026Q3.
GUIDANCE_PERIOD = re.compile(r"^FY\d{4}(Q[1-4])?$")


class ManualInputError(ValueError):
    """Raised with every bad row listed, so all problems can be fixed in one pass."""


def _read(path: Path, expected: list[str]) -> pd.DataFrame:
    df = pd.read_csv(path, dtype=str, keep_default_na=False)
    missing = [c for c in expected if c not in df.columns]
    if missing:
        raise ManualInputError(f"{path.name}: missing columns {missing}")
    return df[expected].apply(lambda col: col.str.strip())


def _row(i: int) -> str:
    return f"row {i + 2}"  # +1 header, +1 for 1-based line numbers


def _check(errors: list[str], name: str) -> None:
    if errors:
        raise ManualInputError(f"{name} has {len(errors)} problem(s):\n  " + "\n  ".join(errors))


def _date(value: str, label: str, i: int, errors: list[str]):
    ts = pd.to_datetime(value, errors="coerce", format="%Y-%m-%d")
    if pd.isna(ts):
        errors.append(f"{_row(i)}: {label} {value!r} is not a YYYY-MM-DD date")
    return ts


def _usd(value: str, label: str, i: int, errors: list[str]):
    v = pd.to_numeric(value, errors="coerce")
    if pd.isna(v):
        errors.append(f"{_row(i)}: {label} {value!r} is not a number")
    elif v < 0:
        errors.append(f"{_row(i)}: {label} is negative")
    return v


def load_segments(path: Path = CONFIG_DIR / "segments.csv", companies: dict | None = None) -> pd.DataFrame:
    """Hand-entered segment revenue. Values are raw USD (not millions)."""
    companies = companies if companies is not None else load_companies()["companies"]
    df = _read(path, SEGMENT_COLUMNS)
    errors: list[str] = []
    out = []
    for i, r in df.iterrows():
        if r["company"] not in companies:
            errors.append(f"{_row(i)}: unknown company {r['company']!r}")
        if not r["segment"]:
            errors.append(f"{_row(i)}: segment is empty")
        if not r["source_accession"]:
            errors.append(f"{_row(i)}: source_accession is empty (every number needs a source)")
        out.append({
            "company": r["company"],
            "period_end": _date(r["period_end"], "period_end", i, errors),
            "segment": r["segment"],
            "revenue_usd": _usd(r["revenue_usd"], "revenue_usd", i, errors),
            "source_accession": r["source_accession"],
            "entered_date": _date(r["entered_date"], "entered_date", i, errors),
        })
    result = pd.DataFrame(out, columns=SEGMENT_COLUMNS)
    dupes = result.duplicated(["company", "period_end", "segment"], keep=False)
    for i in result.index[dupes]:
        errors.append(f"{_row(i)}: duplicate company/period_end/segment")
    _check(errors, path.name)
    return result.astype({"revenue_usd": float}).sort_values(["company", "period_end"]).reset_index(drop=True)


def load_guidance(path: Path = CONFIG_DIR / "guidance.csv", companies: dict | None = None) -> pd.DataFrame:
    """Hand-entered forward capex guidance (raw USD). Period uses the company's fiscal calendar."""
    companies = companies if companies is not None else load_companies()["companies"]
    df = _read(path, GUIDANCE_COLUMNS)
    errors: list[str] = []
    out = []
    for i, r in df.iterrows():
        if r["company"] not in companies:
            errors.append(f"{_row(i)}: unknown company {r['company']!r}")
        if not GUIDANCE_PERIOD.match(r["period"]):
            errors.append(f"{_row(i)}: period {r['period']!r} must look like FY2026 or FY2026Q3")
        if not r["source"]:
            errors.append(f"{_row(i)}: source is empty (every number needs a source)")
        low = _usd(r["capex_guidance_low_usd"], "capex_guidance_low_usd", i, errors)
        high = _usd(r["capex_guidance_high_usd"], "capex_guidance_high_usd", i, errors)
        if pd.notna(low) and pd.notna(high) and low > high:
            errors.append(f"{_row(i)}: low guidance is above high guidance")
        out.append({
            "company": r["company"], "period": r["period"],
            "capex_guidance_low_usd": low, "capex_guidance_high_usd": high,
            "source": r["source"],
            "date_given": _date(r["date_given"], "date_given", i, errors),
        })
    _check(errors, path.name)
    result = pd.DataFrame(out, columns=GUIDANCE_COLUMNS)
    return result.astype({"capex_guidance_low_usd": float, "capex_guidance_high_usd": float})
