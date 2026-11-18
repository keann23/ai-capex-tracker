"""Sensitivity: which assumptions change the answer?"""

import numpy as np
import pandas as pd
import streamlit as st

from capex_tracker.data.panel import companies, run_sensitivity
from capex_tracker.models.sensitivity import DEFAULT, flips
from capex_tracker.ui import footer, page_setup

page_setup('Sensitivity')


@st.cache_data(show_spinner='Rerunning every company under 12 sets of assumptions…')
def results() -> pd.DataFrame:
    return run_sensitivity()


res = results()
fl = flips(res).set_index("variant")
names = [c["name"] for c in companies().values()]
order = list(dict.fromkeys(res["variant"]))
groups = res.drop_duplicates("variant").set_index("variant")["group"]

st.title("Sensitivity: what changes the answer?")
st.caption("Each row changes **one** assumption from the default and reruns every company. "
           "A row is flagged when a conclusion flips: a company's payback status, whether it shows any AI "
           "revenue at all, or which company pays back fastest or slowest. All figures are **estimates**.")

flipped = fl[fl["flips"]]
if flipped.empty:
    st.success("No conclusion flips under any of these alternatives.")
else:
    for v, row in flipped.iterrows():
        st.warning(f"**{v}** flips a conclusion: {row['what_changes']}.")


def fmt_years(y):
    return "never at current rate" if y == np.inf else ("—" if pd.isna(y) else f"{y:.1f}")


def table(value_col, fmt, depreciation_rows: bool):
    pv = res.pivot(index="variant", columns="company", values=value_col).reindex(order)[names]
    keep = [v for v in order if (groups[v] == "Depreciation") == depreciation_rows or v == DEFAULT.label]
    pv = pv.loc[keep]
    out = pv.apply(lambda col: col.map(fmt))
    out.insert(0, "Assumption", [groups[v] for v in keep])
    out.insert(1, "Variant", keep)
    if not depreciation_rows:
        out["Conclusion flips?"] = ["—" if v == DEFAULT.label else ("yes" if fl.loc[v, "flips"] else "no")
                                    for v in keep]
    return out


st.subheader("Implied payback, years")
st.dataframe(table("payback_years", fmt_years, False), hide_index=True, width="stretch")
st.caption("Years of today's excess profit needed to cover excess capex so far. Depreciation choices don't "
           "enter this number, so they're in the next table.")

st.subheader("Operating margin change in 2 years from extra depreciation, points")
st.dataframe(table("margin_change_2y", lambda v: f"{v:+.1f}", True), hide_index=True, width="stretch")
st.caption("With calibration on, the model is scaled to each company's reported depreciation, which absorbs much "
           "of the effect of server life and split. Turn calibration off on the Depreciation Wave page to see "
           "the raw effect.")

footer()
