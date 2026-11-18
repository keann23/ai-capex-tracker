"""Helpers for building toy companyfacts JSON in tests."""

from __future__ import annotations


def fact(start, end, val, filed, form="10-Q", accn=None):
    row = {"end": end, "val": val, "filed": filed, "form": form,
           "accn": accn or f"acc-{filed}", "fy": 0, "fp": "X"}
    if start is not None:
        row["start"] = start
    return row


def companyfacts(tags: dict[str, list[dict]]) -> dict:
    return {"facts": {"us-gaap": {t: {"units": {"USD": rows}} for t, rows in tags.items()}}}
