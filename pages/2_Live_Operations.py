import streamlit as st

from src.data_loader import load_all_data
from src.metrics import overall_metrics
from src.ui import apply_filters, apply_report_period_panel, page_header, render_kpis

st.set_page_config(page_title="Live Operations", page_icon="🔎", layout="wide")
page_header("Live Operations", "Search, filter and review the complete current-state operational order table")
data, _ = load_all_data()
filtered = apply_filters(data)
filtered, _, _ = apply_report_period_panel(filtered, key_prefix="live_operations")

query = st.text_input("Search AWB, customer, mobile, remark or agent")
if query:
    mask = filtered.astype(str).apply(
        lambda col: col.str.contains(query, case=False, na=False)
    ).any(axis=1)
    filtered = filtered[mask]

render_kpis(overall_metrics(filtered), include_unassigned=True)
st.caption(f"Showing {len(filtered):,} matching orders. Use the sidebar filters to narrow the view.")

st.dataframe(
    filtered,
    width="stretch",
    hide_index=True,
    height=680,
    column_config={
        "Scheduled Date": st.column_config.DatetimeColumn("Scheduled Date", format="DD MMM YYYY"),
        "PDF": st.column_config.LinkColumn("PDF"),
    },
)
