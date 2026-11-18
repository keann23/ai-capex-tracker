# AI Capex Payback Tracker

## Problem statement
Big Tech is spending hundreds of billions a year on AI infrastructure, but no company discloses "AI capex" or "AI revenue" separately. Investors and finance teams can see the cash going out but can't measure a clean return. This project builds a transparent, repeatable method to estimate AI-attributable spending and revenue for each hyperscaler, compute implied payback, and forecast when the resulting depreciation hits margins.

Owner: Kean Zhu (MS Business Analytics, BU Questrom). Audience: FP&A / finance hiring managers, investors, and anyone curious whether AI spending is paying off. It's an interactive public app, updated each quarter.

Read before building: `docs/SPEC.md` (what), `docs/METHODOLOGY.md` (how, in plain words), `docs/ROADMAP.md` (phase prompts), `docs/SEC_DATA_NOTES.md` (data gotchas).

## Companies (v1)
Microsoft (MSFT), Alphabet (GOOGL), Amazon (AMZN), Meta (META), Oracle (ORCL). Config-driven so more can be added.

## Stack
- Python 3.11+, Streamlit multipage app, pandas, numpy, statsmodels, plotly, requests, PyYAML, DuckDB cache
- Deploy: Streamlit Community Cloud (public link)
- Tests: pytest on cached fixtures; tests never hit the live SEC API

## Layout
```
app/Home.py                 Scorecard across companies + one-line headline finding
app/pages/                  Company deep dive, Depreciation wave, Scenarios, Sensitivity, Methodology
src/capex_tracker/data/     SEC fetch + cache, statement standardization, manual-input loaders
src/capex_tracker/models/   baseline, excess (AI attribution), payback, depreciation, scenarios
config/companies.yaml       Tickers, segment to track, fiscal calendar notes
config/tag_map.yaml         Standard line items -> candidate us-gaap tags
config/segments.csv         Segment revenue from filing XBRL (scripts/fetch_segments.py), with source accession numbers
config/guidance.csv         Hand-entered forward capex guidance with source and date
snapshots/                  Saved SEC data (companyfacts, segment XBRL facts) the app and tests read; refresh with scripts/fetch_*.py each quarter
```

## Rules
- Keep logic in `src/`, keep `app/` thin. Every model function testable without Streamlit.
- SEC API: `User-Agent` from env var `SEC_USER_AGENT` (never hardcode). Under 10 req/s. Cache in DuckDB, 24h TTL. Only scripts/ call SEC; the app reads committed snapshots.
- Never invent data. Every hand-entered number in `config/*.csv` must carry a source (accession number or URL) and date. Missing data is shown as missing.
- Every estimate is labeled as an estimate in the UI. Every key assumption (baseline window, useful life, margin applied, server vs building split) is visible and adjustable.
- Every chart and headline number must be reproducible from config + cached data. No randomness.
- Units: store raw USD; format in UI only.
- Methodology page explains each step in plain English, with the formula and the loaded company's actual numbers as the worked example.
- Tests for every model function, including hand-calculated toy examples (e.g. a 3-quarter capex schedule with known depreciation).
- Small commits. Run `pytest` before calling a phase done.

## Commands
```
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
streamlit run app/Home.py          # reads committed snapshots; no SEC access needed
pytest
python scripts/fetch_companyfacts.py   # quarterly refresh; asks for SEC contact or reads SEC_USER_AGENT
python scripts/fetch_segments.py       # quarterly refresh of segment revenue (--offline to rebuild only)
```
