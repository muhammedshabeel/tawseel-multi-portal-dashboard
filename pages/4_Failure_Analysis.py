import plotly.express as px
import streamlit as st

from src.data_loader import load_all_data
from src.metrics import failure_summary, overall_metrics
from src.ui import apply_report_period_panel, page_header, render_kpis

st.set_page_config(page_title="Failure Analysis", page_icon="⚠️", layout="wide")
page_header("Failure Analysis", "Actionable remarks and failure reasons across all portals")
data, _ = load_all_data()
data, _, _ = apply_report_period_panel(data, key_prefix="failure_analysis")
render_kpis(overall_metrics(data), include_unassigned=True)

failures = failure_summary(data)
if failures.empty:
    st.info("No failure remarks found for the selected report period.")
    st.stop()

limit = st.slider("Top reasons", 5, 50, 20)
top = failures.head(limit)
fig = px.bar(
    top.sort_values("Count"),
    x="Count",
    y="Remarks Clean",
    color="Portal",
    orientation="h",
    text="Count",
    title="Main failure reasons",
)
fig.update_traces(textposition="outside")
fig.update_layout(height=max(420, len(top) * 30), yaxis_title="")
st.plotly_chart(fig, width="stretch")
st.dataframe(failures, width="stretch", hide_index=True, height=520)
