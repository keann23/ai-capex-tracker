"""The depreciation wave (METHODOLOGY step 6).

Capex doesn't hit profit when it's spent. It sits on the balance sheet and is
expensed over its useful life. Each quarter's capex (a 'vintage') is split into
servers/network equipment and buildings, each depreciated straight-line starting
the quarter after it's spent.

Forward: future capex comes from management guidance (config/guidance.csv). After
the last guided period, capex is held at the last guided run-rate. With no
guidance, it's held at the latest four quarters' run-rate. Both are labelled.

All values raw USD per quarter, Series indexed by period_end. No Streamlit here.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd


@dataclass(frozen=True)
class DepreciationAssumptions:
    server_share: float = 0.60       # share of capex that is servers / network equipment
    server_life_years: float = 6.0
    building_life_years: float = 15.0


def straight_line(capex: pd.Series, life_years: float) -> pd.Series:
    """Quarterly depreciation from a capex series: each vintage spreads evenly over
    life_years*4 quarters, starting the quarter after it's spent. Missing capex = 0."""
    n_life = max(int(round(life_years * 4)), 1)
    c = capex.fillna(0.0).to_numpy(dtype=float)
    kernel = np.r_[0.0, np.full(n_life, 1.0 / n_life)]   # lag one quarter, then 1/n each quarter
    return pd.Series(np.convolve(c, kernel)[: len(c)], index=capex.index)


def depreciation_schedule(capex: pd.Series, a: DepreciationAssumptions) -> pd.DataFrame:
    """Per quarter: servers, buildings and total modeled depreciation."""
    servers = straight_line(capex * a.server_share, a.server_life_years)
    buildings = straight_line(capex * (1 - a.server_share), a.building_life_years)
    return pd.DataFrame({"capex": capex, "servers": servers, "buildings": buildings,
                         "total": servers + buildings})


def next_quarter_ends(last: pd.Timestamp, n: int) -> pd.DatetimeIndex:
    """n quarter-ends after `last`, keeping the company's month-end calendar (Oracle: Aug/Nov/Feb/May)."""
    return pd.DatetimeIndex([last + pd.offsets.MonthEnd(3 * k) for k in range(1, n + 1)])


def fiscal_year_of(index: pd.DatetimeIndex, fy_end_month: int) -> np.ndarray:
    idx = pd.DatetimeIndex(index)
    return np.asarray(idx.year + (idx.month > fy_end_month).astype(int))


def fiscal_quarter_of(index: pd.DatetimeIndex, fy_end_month: int) -> np.ndarray:
    idx = pd.DatetimeIndex(index)
    return np.asarray(((idx.month - fy_end_month - 1) % 12) // 3 + 1)


def future_capex(history: pd.Series, guidance: pd.DataFrame, fy_end_month: int,
                 quarters: int) -> pd.DataFrame:
    """Projected quarterly capex for `quarters` quarters after the last actual.

    guidance: rows with period (FY2027 or FY2027Q2) and capex_guidance_low/high_usd.
    The midpoint is used. For a fiscal year already under way, what's left of the
    guided amount after the actual year-to-date capex is spread evenly over the
    remaining quarters (never below zero). After the last guided period, capex is
    held at that period's average quarterly rate (fiscal-year midpoint / 4), not at
    a leftover quarter, so one unusual quarter isn't repeated forever.
    Returns columns capex and basis ('guidance' / 'held at last guidance' /
    'held at last 4 quarters').
    """
    hist = history.dropna()
    idx = next_quarter_ends(hist.index[-1], quarters)
    fy, fq = fiscal_year_of(idx, fy_end_month), fiscal_quarter_of(idx, fy_end_month)

    guided = {}                                    # (fiscal year, quarter) -> (capex, rate to hold after)
    if len(guidance):
        mid = (guidance["capex_guidance_low_usd"] + guidance["capex_guidance_high_usd"]) / 2
        periods = guidance["period"].tolist()
        hist_fy = fiscal_year_of(hist.index, fy_end_month)
        for period, m in zip(periods, mid):        # fiscal-year rows: spread what's left evenly
            if len(period) == 6:
                year = int(period[2:])
                done = hist[hist_fy == year]
                left = 4 - len(done)
                if left <= 0:
                    continue
                per_q = max(m - done.sum(), 0.0) / left
                for qn in range(5 - left, 5):
                    guided[(year, qn)] = (per_q, m / 4)
        for period, m in zip(periods, mid):        # quarter rows override
            if len(period) == 8:
                guided[(int(period[2:6]), int(period[-1]))] = (m, m)

    run_rate = hist.iloc[-4:].mean()
    values, basis, last_guided = [], [], None
    for y, q in zip(fy, fq):
        if (y, q) in guided:
            value, last_guided = guided[(y, q)]
            values.append(value)
            basis.append("guidance")
        elif last_guided is not None:
            values.append(last_guided)
            basis.append("held at last guidance")
        else:
            values.append(run_rate)
            basis.append("held at last 4 quarters")
    return pd.DataFrame({"capex": values, "basis": basis}, index=idx)


@dataclass(frozen=True)
class Wave:
    schedule: pd.DataFrame          # history + projection: capex, servers, buildings, total, projected
    today: pd.Timestamp             # last actual quarter
    depreciation_today_ttm: float   # modeled, last 4 actual quarters
    revenue_ttm: float
    operating_income_ttm: float
    calibration: float = 1.0        # reported / modeled depreciation, latest full fiscal year

    @property
    def margin_today(self) -> float:
        return self.operating_income_ttm / self.revenue_ttm

    def ttm(self) -> pd.Series:
        """Calibrated modeled depreciation, trailing four quarters."""
        return self.schedule["total"].rolling(4).sum() * self.calibration

    def margin_path(self) -> pd.DataFrame:
        """Projected operating margin if revenue and all other costs stay at today's level
        and only depreciation changes ('holding other things equal'). The change in
        modeled depreciation is scaled by the calibration factor."""
        ttm = self.ttm()
        future = ttm[ttm.index > self.today]
        drag = future - self.depreciation_today_ttm * self.calibration
        return pd.DataFrame({
            "depreciation_ttm": future,
            "extra_depreciation": drag,
            "operating_margin": (self.operating_income_ttm - drag) / self.revenue_ttm,
            "margin_change_pts": -drag / self.revenue_ttm * 100,
        })

    def peak_increase_year(self) -> int | None:
        """Calendar year with the largest rise in modeled depreciation vs the year before."""
        s = self.schedule["total"]
        annual = s.groupby(s.index.year).sum()
        counts = s.groupby(s.index.year).count()
        annual = annual[counts == 4]
        inc = annual.diff().dropna()
        inc = inc[inc.index >= self.today.year]
        return int(inc.idxmax()) if len(inc) else None


def depreciation_wave(capex: pd.Series, revenue: pd.Series, operating_income: pd.Series,
                      guidance: pd.DataFrame, fy_end_month: int,
                      a: DepreciationAssumptions, horizon_quarters: int = 16,
                      reported_annual: pd.Series | None = None) -> Wave:
    """Modeled depreciation for actual + projected capex, and the margin path.

    With reported_annual given, the margin path is calibrated to reported depreciation.
    """
    hist = capex.dropna().sort_index()
    fut = future_capex(hist, guidance, fy_end_month, horizon_quarters)
    all_capex = pd.concat([hist, fut["capex"]])
    sched = depreciation_schedule(all_capex, a)
    sched["projected"] = sched.index > hist.index[-1]
    sched["basis"] = fut["basis"].reindex(sched.index).fillna("actual")

    today = hist.index[-1]
    both = pd.concat({"rev": revenue, "oi": operating_income}, axis=1).dropna()
    both = both[both.index <= today].iloc[-4:]
    factor = 1.0
    if reported_annual is not None:
        factor, _ = calibration_factor(sched, reported_annual, fy_end_month)
    return Wave(sched, today, float(sched.loc[:today, "total"].iloc[-4:].sum()),
                float(both["rev"].sum()), float(both["oi"].sum()), factor)


def modeled_vs_reported(schedule: pd.DataFrame, reported_annual: pd.Series,
                        fy_end_month: int) -> pd.DataFrame:
    """Fiscal-year modeled depreciation (actual capex only) vs reported depreciation."""
    s = schedule.loc[~schedule["projected"], "total"]
    fy = fiscal_year_of(s.index, fy_end_month)
    full = s.groupby(fy).count() == 4
    modeled = s.groupby(fy).sum()[full]
    df = pd.concat({"modeled": modeled, "reported": reported_annual}, axis=1).dropna()
    df["gap_pct"] = (df["modeled"] - df["reported"]) / df["reported"]
    return df


def calibration_factor(schedule: pd.DataFrame, reported_annual: pd.Series, fy_end_month: int) -> tuple[float, int | None]:
    """reported / modeled depreciation for the latest fiscal year with both (1.0 if none).

    Scales the model to the company's actual books: capex timing, construction in
    progress, finance leases and useful-life changes all move reported depreciation
    in ways a simple vintage model can't see.
    """
    cmp = modeled_vs_reported(schedule, reported_annual, fy_end_month)
    if cmp.empty or cmp["modeled"].iloc[-1] <= 0:
        return 1.0, None
    return float(cmp["reported"].iloc[-1] / cmp["modeled"].iloc[-1]), int(cmp.index[-1])
