# AI Capex Payback Tracker

Microsoft, Alphabet, Amazon, Meta and Oracle are spending hundreds of billions a year on AI infrastructure, but none of them reports AI spending or AI revenue as its own line. This tracker estimates both by comparing each company with its own pre-ChatGPT baseline: spending and revenue above the old pace count as "excess", attributed to AI. From those estimates it calculates the return so far, the payback period, and when the resulting depreciation will squeeze operating margins.

**Finding (data through Q3 2026):** at current run-rates, Meta pays back its estimated AI capex fastest (about 3 years of today's excess profit) and Oracle slowest (about 11). Depreciation from spending already guided takes 5–11 margin points off the four hyperscalers within two years, and about 28 off Oracle, with revenue held flat. The answer depends heavily on one assumption: if pre-AI cloud revenue had kept growing at its 2019–22 boom pace, four of the five would show no AI revenue at all. The app says so wherever it matters.

## What's in the app

| Page | What it shows |
|---|---|
| Home | Scorecard for all five companies and a generated one-line finding |
| Company Deep Dive | Capex vs the pre-AI intensity, tracked revenue vs its pre-AI trend, payback crossover; every assumption adjustable |
| Depreciation Wave | Capex and depreciation, actual and projected from guidance; operating margin if only depreciation changes; modeled vs reported check |
| Scenarios | Bull / base / bear revenue paths (editable), payback dates and margin paths |
| Sensitivity | Every company rerun under one changed assumption at a time; flags any conclusion that flips |
| Methodology | Each step in plain English with the selected company's actual numbers |

## Method in brief

1. **Data.** Quarterly figures from SEC filings. Company-wide items come from SEC companyfacts. Segment revenue is read from each 10-Q/10-K's XBRL. Every value keeps its source filing.
2. **Baseline.** 2019 Q1 to 2022 Q3, the 15 quarters before ChatGPT.
3. **Excess capex** = actual capex − (baseline capex ÷ revenue ratio × revenue).
4. **Excess revenue** = tracked line's revenue − its baseline trend (constant dollar growth plus a seasonal pattern). **Excess profit** = excess revenue × the line's operating margin.
5. **Payback.** Return so far = cumulative excess profit ÷ cumulative excess capex. Implied payback = cumulative excess capex ÷ (latest quarter's excess profit × 4).
6. **Depreciation wave.** Each quarter's capex is split 60% servers (6-year life) and 40% buildings (15 years), depreciated straight-line, with future capex from management guidance. The model is calibrated to each company's reported depreciation.
7. **Scenarios** for the tracked line's revenue growth. **Sensitivity** to the trend shape, baseline window, margin, server life and server/building split.

Tracked lines: Microsoft Cloud, Google Cloud, AWS, Meta advertising, and Oracle cloud services & license support. `config/companies.yaml` explains why each was chosen. The full method is in [`docs/METHODOLOGY.md`](docs/METHODOLOGY.md).

## Limits

- These are estimates, not true AI figures. Some extra spending and growth would have happened anyway.
- Results depend on the baseline window and especially the trend shape. The Sensitivity page shows which choices flip a conclusion.
- Capex is cash spent on property and equipment. It excludes finance leases, which are large for Microsoft and were large for Amazon before 2022.
- Meta's AI payoff is inside ad revenue, and Microsoft Cloud includes Microsoft 365 and Dynamics as well as Azure, so attribution is fuzzier for both.
- Margin projections hold revenue and other costs flat. They isolate the depreciation drag; they are not margin forecasts.
- Capex guidance doesn't always measure the same thing as reported capex. Each row in `config/guidance.csv` says how. Microsoft's is left out.

## Run locally

```
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
streamlit run app/Home.py
pytest
```

The app reads the committed data in `snapshots/` and `config/`, so it never calls SEC and needs no API key.

## Update each quarter

After all five companies have filed their 10-Q or 10-K:

1. Refresh company-wide data: `python scripts/fetch_companyfacts.py`. It asks for your SEC contact ("Name email"), or reads `SEC_USER_AGENT`.
2. Refresh segment revenue: `python scripts/fetch_segments.py`. Read the summary. It lists restated quarters, any quarter flagged `CHECK`, and any company whose segment wasn't found (with the segment names in its latest 10-K, so `config/companies.yaml` can be fixed and rebuilt offline with `--offline`).
3. Update `config/guidance.csv` from the latest earnings releases or calls. Each row needs a source URL, the date given, and a note if the figure isn't cash purchases of property & equipment.
4. Run `pytest`, then `streamlit run app/Home.py` and read the new headline.
5. Commit and push. The deployed app redeploys from `main`.

## Deploy (Streamlit Community Cloud)

At [share.streamlit.io](https://share.streamlit.io), sign in with GitHub and create an app from this repository: branch `main`, main file `app/Home.py`, Python 3.12. No secrets are needed.

## Project layout

```
app/                    Streamlit pages (thin; no logic)
src/capex_tracker/      data loading, models, worked examples (all testable without Streamlit)
config/                 companies, tag map, segment revenue, capex guidance
snapshots/              saved SEC data the app and tests read
scripts/                quarterly data refresh
docs/                   spec, methodology, SEC data notes, methodology page text
tests/                  pytest, including hand-calculated toy examples
```
