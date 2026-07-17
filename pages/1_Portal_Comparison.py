import plotly.express as px
import streamlit as st

from src.data_loader import load_all_data
from src.metrics import overall_metrics, portal_summary
from src.ui import apply_report_period_panel, page_header, render_kpis

st.set_page_config(page_title="Portal Comparison", page_icon="📊", layout="wide")
page_header("Portal Comparison", "Compare signing rate, delivery outcomes and operational pressure across portals")
data, _ = load_all_data()
data, _, _ = apply_report_period_panel(data, key_prefix="portal_comparison")
summary = portal_summary(data)
if summary.empty:
    st.info("No data available.")
    st.stop()

render_kpis(overall_metrics(data), include_unassigned=True)
st.caption("Use the charts and table below to identify the strongest portal and the portals requiring immediate operational attention.")

c1, c2 = st.columns(2)
with c1:
    fig = px.bar(
        summary,
        x="Portal",
        y="Delivery Rate",
        text_auto=".1%",
        color="Delivery Rate",
        color_continuous_scale=["#ef4444", "#f59e0b", "#22c55e"],
        range_color=[0, 1],
        title="Delivery signing rate by portal",
    )
    fig.update_layout(coloraxis_showscale=False, yaxis_tickformat=".0%", yaxis_range=[0, 1])
    st.plotly_chart(fig, width="stretch")
with c2:
    fig = px.bar(
        summary,
        x="Portal",
        y=["Critical", "Follow-up", "Unassigned"],
        barmode="group",
        title="Operational pressure by portal",
    )
    st.plotly_chart(fig, width="stretch")

st.subheader("Portal scorecard")
st.dataframe(
    summary.style.format({"Delivery Rate": "{:.1%}"}),
    width="stretch",
    hide_index=True,
    height=360,
)
