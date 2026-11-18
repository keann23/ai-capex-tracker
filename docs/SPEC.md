# AI Capex Payback Tracker: Product Spec

## Goal
An interactive, public, quarterly-updated tracker answering: how much are the hyperscalers spending on AI beyond their normal pace, how much extra revenue is showing up, when does it pay back, and when does the depreciation hit margins? Method in `docs/METHODOLOGY.md`.

## Pages

### Home: Scorecard
- One row per company: cumulative excess capex, annualized excess revenue, return so far, implied payback (years), peak depreciation year, projected margin hit (pts).
- Headline sentence generated from the data (e.g. "At current trends, X pays back fastest at N years; Y slowest at M").
- "Last updated" date and data sources.

### Company Deep Dive
- Pick a company. Charts: capex vs baseline-implied capex (shaded gap = excess capex); segment revenue vs baseline trend (shaded gap = excess revenue); cumulative excess capex vs cumulative excess profit (crossover = payback).
- Table of the underlying quarterly numbers with sources.

### Depreciation Wave
- Vintage depreciation schedule, historical modeled vs actual D&A, projection using guidance.
- Operating margin today vs projected, with the depreciation drag isolated.
- Sliders: server life, building life, server/building split.

### Scenarios
- Bull / Base / Bear excess revenue paths (editable). Payback year and margin path per scenario, per company.

### Sensitivity
- Payback under alternative baseline windows, margins, useful lives. Highlight when conclusions flip.

### Methodology
- Plain-English walkthrough of each step, formula, worked example using the selected company's real numbers, and known limits. (This is the learning element.)

## Data
- SEC companyfacts: capex, revenue, gross profit, operating income, D&A, CFO, PP&E (gross and net).
- `config/segments.csv`: company, period_end, segment, revenue_usd, source_accession, entered_date.
- `config/guidance.csv`: company, period (FY/quarter), capex_guidance_low, capex_guidance_high, source_url_or_accession, date_given.

## Out of scope (v1)
Private AI labs, chipmakers, non-US companies, valuation/stock price targets.

## Definition of done (v1)
- 5 companies load end to end; numbers spot-checked against 10-Ks.
- All pages work; every estimate labeled; assumptions adjustable.
- pytest passes; deployed with a public URL; README states the method and limits.
