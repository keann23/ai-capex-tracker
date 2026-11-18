"""Return and payback (METHODOLOGY step 5).

  return so far   = cumulative excess profit / cumulative excess capex
  implied payback = cumulative excess capex / current annualized excess profit
                    (years of today's excess profit needed to cover the excess
                    capex spent so far; ignores further spend; forward paths
                    come with the scenarios in Phase 5)

'Current annualized' = latest quarter x 4, a run-rate. The seasonal pattern is
already in the trend, so a Q4 peak isn't counted as excess.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

import numpy as np
import pandas as pd

from capex_tracker.models.excess import Attribution


@dataclass(frozen=True)
class Payback:
    cumulative_excess_capex: float
    cumulative_excess_profit: float
    annualized_excess_revenue: float
    annualized_excess_profit: float
    return_so_far: float          # NaN when there's no excess capex to compare with
    implied_payback_years: float  # inf when excess profit isn't positive
    status: str                   # paid back / paying back / not at current rate / no excess capex
    as_of: pd.Timestamp | None


def payback(att: Attribution) -> Payback:
    latest = att.latest()
    capex = float(latest["cumulative_excess_capex"])
    profit = float(latest["cumulative_excess_profit"])
    r = att.revenue.dropna(subset=["excess_profit"])
    annual_profit = 4 * float(r["excess_profit"].iloc[-1]) if len(r) else np.nan
    annual_rev = float(latest["annualized_excess_revenue"])

    if not capex > 0:
        ret, years, status = np.nan, np.nan, "no excess capex"
    else:
        ret = profit / capex
        if profit >= capex:
            years, status = capex / annual_profit if annual_profit > 0 else np.nan, "paid back"
        elif annual_profit > 0:
            years, status = capex / annual_profit, "paying back"
        else:
            years, status = math.inf, "not at current rate"
    return Payback(capex, profit, annual_rev, annual_profit, ret, years, status, latest["capex_as_of"])


def crossover(att: Attribution) -> pd.DataFrame:
    """Cumulative excess capex vs cumulative excess profit after the baseline (payback = crossing)."""
    df = pd.concat({
        "cumulative_excess_capex": att.capex["cumulative_excess_capex"],
        "cumulative_excess_profit": att.revenue["cumulative_excess_profit"],
    }, axis=1).sort_index()
    return df[df.index > att.assumptions.baseline_end].dropna(how="all")


def scorecard_row(ticker: str, name: str, segment: str, p: Payback) -> dict:
    return {
        "ticker": ticker, "company": name, "segment": segment,
        "cumulative_excess_capex": p.cumulative_excess_capex,
        "annualized_excess_revenue": p.annualized_excess_revenue,
        "annualized_excess_profit": p.annualized_excess_profit,
        "return_so_far": p.return_so_far,
        "implied_payback_years": p.implied_payback_years,
        "status": p.status, "as_of": p.as_of,
    }


def _years(y: float) -> str:
    return f"{y:.1f} years"


def headline(score: pd.DataFrame, alt_score: pd.DataFrame | None = None, alt_label: str = "") -> str:
    """One-sentence finding generated from the scorecard (plus a caveat if the alternative flips it)."""
    finite = score[np.isfinite(score["implied_payback_years"].astype(float))].sort_values("implied_payback_years")
    never = score[score["status"] == "not at current rate"]["company"].tolist()
    parts = []
    if len(finite) >= 2:
        fast, slow = finite.iloc[0], finite.iloc[-1]
        parts.append(f"At current run-rates, {fast['company']} pays back its estimated AI capex fastest "
                     f"({_years(fast['implied_payback_years'])} of today's excess profit); "
                     f"{slow['company']} slowest ({_years(slow['implied_payback_years'])}).")
    elif len(finite) == 1:
        one = finite.iloc[0]
        parts.append(f"At current run-rates, only {one['company']} is on a path to pay back its estimated "
                     f"AI capex ({_years(one['implied_payback_years'])}).")
    if never:
        parts.append(f"{_join(never)} {'is' if len(never) == 1 else 'are'} not earning excess profit yet.")
    if alt_score is not None:
        neg = alt_score[alt_score["annualized_excess_revenue"] <= 0]["company"].tolist()
        if neg:
            parts.append(f"Caveat: {alt_label}, {_join(neg)} show{'s' if len(neg) == 1 else ''} "
                         f"no AI revenue at all.")
    return " ".join(parts) if parts else "Not enough data for a headline yet."


def _join(names: list[str]) -> str:
    return names[0] if len(names) == 1 else ", ".join(names[:-1]) + " and " + names[-1]
