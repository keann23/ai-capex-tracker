"""Display formatting. Values are stored as raw USD; only the UI formats them."""

from __future__ import annotations

import math


def usd_b(value: float | None, digits: int = 1, sign: bool = False) -> str:
    """$12.3B; '—' for missing."""
    if value is None or (isinstance(value, float) and math.isnan(value)):
        return "—"
    s = f"{value / 1e9:+,.{digits}f}" if sign else f"{value / 1e9:,.{digits}f}"
    if sign:
        return s.replace("+", "+$").replace("-", "−$") + "B"
    return ("−$" + s[1:] if s.startswith("-") else "$" + s) + "B"


def pct(value: float | None, digits: int = 1) -> str:
    if value is None or (isinstance(value, float) and math.isnan(value)):
        return "—"
    return f"{value:.{digits}%}".replace("-", "−")
