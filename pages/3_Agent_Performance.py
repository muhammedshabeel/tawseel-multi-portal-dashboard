import pandas as pd
import plotly.express as px
import streamlit as st

from src.data_loader import load_all_data
from src.metrics import agent_summary
from src.ui import highlight_performance_rows, page_header, performance_style

st.set_page_config(page_title="Agent Performance", page_icon="👥", layout="wide")
page_header("Agent Performance", "Compact complete ranking with signing rate, workload and operational exposure")
data, _ = load_all_data()
summary = agent_summary(data)
if summary.empty or "Total" not in summary.columns:
    st.info("No agent performance data is available.")
    st.stop()

summary = summary.copy()
for column in ["Total", "Delivered", "Critical", "Follow-up", "OFD", "RTO", "Delivery Rate"]:
    summary[column] = pd.to_numeric(summary[column], errors="coerce").fillna(0)
summary["Portal"] = summary["Portal"].fillna("Unknown").astype(str)
summary["Agent"] = summary["Agent"].fillna("Unassigned").astype(str)

f1, f2, f3 = st.columns([1.4, 1, 1.2])
with f1:
    options = sorted(summary["Portal"].unique().tolist())
    selected = st.multiselect("Portal", options, default=options)
with f2:
    maximum = max(int(summary["Total"].max()), 1)
    minimum = st.number_input("Minimum orders", 1, maximum, 1)
with f3:
    rank_by = st.selectbox("Rank agents by", ["Delivery Rate", "Total Orders", "Delivered", "Critical Orders"])

filtered = summary[summary["Portal"].isin(selected) & summary["Total"].ge(minimum)].copy()
if filtered.empty:
    st.info("No agents match the selected filters.")
    st.stop()
filtered["Performance"] = filtered.apply(lambda r: performance_style(float(r["Delivery Rate"]), int(r["Total"])), axis=1)

sort_map = {
    "Delivery Rate": ("Delivery Rate", False),
    "Total Orders": ("Total", False),
    "Delivered": ("Delivered", False),
    "Critical Orders": ("Critical", True),
}
sort_col, ascending = sort_map[rank_by]
filtered = filtered.sort_values([sort_col, "Total"], ascending=[ascending, False]).reset_index(drop=True)
filtered.insert(0, "Rank", range(1, len(filtered) + 1))

weighted = filtered["Delivered"].sum() / filtered["Total"].sum() if filtered["Total"].sum() else 0
cards = st.columns(5)
actual_agent_count = (
    filtered["Agent"]
    .fillna("")
    .astype(str)
    .str.strip()
    .str.replace(r"\\s+", " ", regex=True)
    .str.casefold()
)

actual_agent_count = actual_agent_count[
    actual_agent_count.ne("")
    & actual_agent_count.ne("unassigned")
].nunique()

cards[0].metric("Agents", f"{actual_agent_count:,}")
cards[1].metric("Good", int(filtered["Performance"].eq("Good").sum()))
cards[2].metric("Average", int(filtered["Performance"].eq("Average").sum()))
cards[3].metric("Needs Improvement", int(filtered["Performance"].eq("Needs Improvement").sum()))
cards[4].metric("Total Delivery Signing Rate", f"{weighted:.1%}")
st.caption("Good ≥ 70% • Average 55–69.9% • Needs Improvement < 55% • Low Sample < 10 orders")

chart_data = filtered.copy()
chart_data["Agent Label"] = chart_data["Agent"] + " · " + chart_data["Portal"]
fig = px.bar(
    chart_data.sort_values("Delivery Rate"),
    x="Delivery Rate",
    y="Agent Label",
    color="Performance",
    orientation="h",
    text="Delivery Rate",
    color_discrete_map={"Good": "#22c55e", "Average": "#f59e0b", "Needs Improvement": "#ef4444", "Low Sample": "#94a3b8"},
    hover_data={"Total": True, "Delivered": True, "Critical": True, "Follow-up": True, "OFD": True, "RTO": True, "Delivery Rate": ":.1%", "Agent Label": False},
)
fig.update_traces(texttemplate="%{x:.1%}", textposition="outside", cliponaxis=False)
fig.update_layout(height=max(380, len(chart_data) * 30), margin=dict(l=10, r=40, t=10, b=10), xaxis_tickformat=".0%", xaxis_range=[0, 1], yaxis_title="", legend_title="Performance")
st.plotly_chart(fig, width="stretch")

st.subheader("Complete agent ranking")
columns = ["Rank", "Portal", "Agent", "Total", "Delivered", "Delivery Rate", "OFD", "RTO", "Critical", "Follow-up", "Performance"]
table = filtered[columns].copy()
st.dataframe(
    table.style.apply(highlight_performance_rows, axis=1).format({"Delivery Rate": "{:.1%}"}),
    width="stretch",
    hide_index=True,
    height=min(900, 40 + len(table) * 35)
)
