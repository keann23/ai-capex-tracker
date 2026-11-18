# AI Capex Payback Tracker

Microsoft, Alphabet, Amazon, Meta and Oracle are spending hundreds of billions a year on AI infrastructure, but none of them reports AI spending or AI revenue as its own line. This tracker estimates both by comparing each company with its own pre-ChatGPT baseline: spending and segment revenue above the old trend count as "excess", attributed to AI. From those estimates it calculates the return so far, the implied payback period, and when the resulting depreciation will start to squeeze operating margins.

Status: in development. Method: `docs/METHODOLOGY.md`. Spec: `docs/SPEC.md`.

## Run locally
```
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
export SEC_USER_AGENT="Your Name your-email"
streamlit run app/Home.py
```
