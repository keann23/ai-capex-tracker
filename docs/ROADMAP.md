# Roadmap + Claude Code prompts

How to use: open this folder in Claude Code. For each phase switch to plan mode (Shift+Tab), paste the prompt, review the plan, then build. Don't start a phase until the last one's tests pass and you've checked the numbers yourself.

After each phase ask: "Explain what you built and the key judgment calls like I'll be asked about them in an interview."

---

## Phase 0: Setup
```
Read CLAUDE.md and all of docs/. Create a minimal app/Home.py with the title and a placeholder scorecard, and make the README explain the problem statement in 3 sentences. Init git. No data logic yet.
```

## Phase 1: Data layer (most important)
```
Read docs/SEC_DATA_NOTES.md, config/tag_map.yaml, config/companies.yaml. Build src/capex_tracker/data/:
1. sec_client.py: ticker->CIK, companyfacts fetch, User-Agent from SEC_USER_AGENT, rate limit, DuckDB cache.
2. standardize.py: quarterly DataFrame per company for every item in tag_map.yaml, handling all gotchas in SEC_DATA_NOTES.md (dedupe, YTD vs quarter, derived Q4, tag drift per period). Calendar-align fiscal quarters (MSFT and ORCL have non-calendar fiscal years) so companies are comparable.
3. manual_inputs.py: load and validate config/segments.csv and config/guidance.csv (every row must have a source).
Save fixtures for all 5 companies; tests check annual capex and revenue against figures I'll provide from the 10-Ks.
```
You: fill in `config/segments.csv` (cloud segment revenue per quarter, from each 10-Q segment note) and `config/guidance.csv` (latest capex guidance). This is tedious but it's real analyst work; you can have Claude Code draft rows from filings you paste in, then check them.

## Phase 2: Baseline + excess (the attribution engine)
```
Build models/baseline.py and models/excess.py per docs/METHODOLOGY.md steps 2-4: baseline capex intensity, excess capex, log-linear segment trend, excess revenue and excess profit. Baseline window and margin are parameters. Tests with toy data where the answer is hand-calculated. Then build pages/1_Company_Deep_Dive.py with the shaded-gap charts.
```

## Phase 3: Payback + scorecard (MVP: start applying with this)
```
Build models/payback.py per METHODOLOGY step 5 (return so far, implied payback, crossover chart). Fill Home.py scorecard and auto-generated headline sentence. Tests.
```

## Phase 4: Depreciation wave
```
Build models/depreciation.py per METHODOLOGY step 6: vintage straight-line schedule with server/building split and lives as parameters, historical modeled vs actual D&A check, forward projection using guidance.csv, margin impact. Build pages/2_Depreciation_Wave.py with sliders. Tests: a toy 3-vintage schedule with known output.
```

## Phase 5: Scenarios + sensitivity
```
Build models/scenarios.py (bull/base/bear excess revenue paths, editable) and a sensitivity runner over baseline window, margin, useful life, split. Pages 3_Scenarios.py and 4_Sensitivity.py. Flag in the UI when a conclusion flips.
```

## Phase 6: Methodology page
```
Build pages/5_Methodology.py from docs/METHODOLOGY.md: each step in plain English, formula, worked example filled with the selected company's real numbers, known limits.
```
Write or rewrite this text yourself. Being able to explain it is the point.

## Phase 7: Polish + deploy
```
Run all 5 companies, fix anything wrong. Consistent styling, loading states, "last updated" and sources on every page. README with method summary, limits, and how to update each quarter. Prep Streamlit Community Cloud deploy with SEC_USER_AGENT as a secret.
```

## Every quarter after launch
Add new segment rows and guidance, rerun, and post the updated headline finding on LinkedIn. A live, updating finding is your interview opener.
