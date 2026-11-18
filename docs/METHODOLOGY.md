# Methodology (plain words)

Companies don't report AI spending or AI revenue separately. So we estimate both by comparing each company to how it looked before the AI boom.

## Step 1: Collect the numbers
Quarterly, about 8+ years, per company: capex, total revenue, tracked segment revenue (cloud, or ads for Meta), gross profit, operating income, depreciation & amortization, operating cash flow, PP&E.
- Most comes from SEC structured data (companyfacts API).
- Segment revenue is NOT in companyfacts (it's dimensional). `scripts/fetch_segments.py` reads it from each 10-Q/10-K's XBRL instance and writes `config/segments.csv`, every row with its source accession number and how it was derived. Where companies renamed or recast the line, the series is joined only where the old and new versions match in overlapping quarters (see `segment_note` in `config/companies.yaml`).
- Tracked lines: Microsoft Cloud (not Intelligent Cloud, which was recast and then replaced), Google Cloud, AWS, Meta advertising (Family of Apps quarters start only in 2021), Oracle cloud services & license support.

## Step 2: Set the "before AI" baseline
Default baseline window: 2019 Q1 to 2022 Q3 (ChatGPT launched Nov 30, 2022). Adjustable.

## Step 3: Estimate AI spending ("excess capex")
- Baseline capex intensity = average capex / revenue during the baseline window.
- Excess capex each quarter = actual capex - (baseline intensity x that quarter's revenue).
- Cumulative excess capex = running total since the baseline ends.

## Step 4: Estimate AI revenue ("excess revenue")
- Fit the tracked segment's revenue trend during the baseline (log-linear growth, i.e. constant % growth).
- Project that trend forward. Excess revenue = actual - projected trend.
- Convert to profit by applying a margin (default: the segment's operating margin; adjustable).

## Step 5: Return and payback
- Return so far = cumulative excess profit / cumulative excess capex.
- Implied payback (years) = cumulative excess capex / current annualized excess profit.
- Forward payback: under each scenario, the year cumulative excess profit catches up with cumulative excess capex (ignoring further spend, and including projected spend, both shown).

## Step 6: The depreciation wave (the FP&A core)
- Capex doesn't hit profit right away. It sits on the balance sheet, then gets expensed over its useful life.
- Split each quarter's capex into servers/network equipment (default 6-year life) and buildings/infrastructure (default 15-year life), using an adjustable split (default 60/40).
- Build a vintage schedule: each quarter's capex depreciated straight-line from the following quarter.
- Add future capex from `config/guidance.csv` (management guidance) to project forward.
- Output: projected depreciation by quarter, and projected operating margin impact vs today, holding other things equal.
- Sanity check: modeled depreciation for historical quarters vs actual reported D&A. Show the gap.
- Useful life is a slider because companies have changed server lives over time, and it moves reported profit a lot.

## Step 7: Scenarios
Excess revenue growth going forward: Bull (current growth continues), Base (decays toward trend), Bear (flattens). Each gives a payback year and margin path.

## Step 8: Sensitivity
Show how payback changes with: baseline window, margin applied, useful life, server/building split. If a conclusion flips under reasonable assumptions, say so in the UI.

## Known limits (state these in the app)
- These are estimates, not true AI numbers. Some excess spend and growth would have happened anyway (normal cloud growth, non-AI data centers).
- Meta's AI payoff mostly shows up inside ad revenue, so attribution is fuzzier.
- Results depend on the baseline window; the sensitivity page makes that visible.
- Revenue from AI that flows to other companies (e.g. model labs paying cloud bills) counts here only if it lands in the tracked segment.
