import pandas as pd
import plotly.express as px
import streamlit as st

from src.data_loader import load_all_data
from src.metrics import add_derived_columns, agent_summary
from src.ui import highlight_performance_rows, page_header, performance_style

st.set_page_config(page_title="Agent Performance", page_icon="👥", layout="wide")
page_header(
    "Agent Performance",
    "Consolidated performance for each actual agent across all selected portals",
)

data, _ = load_all_data()
if data.empty:
    st.info("No agent performance data is available.")
    st.stop()

portal_options = sorted(data["Portal"].fillna("Unknown").astype(str).unique().tolist())
filter1, filter2, filter3 = st.columns([1.5, 1, 1.3])

with filter1:
    selected_portals = st.multiselect(
        "Portals included",
        portal_options,
        default=portal_options,
        help="Agents are consolidated across all selected portals.",
    )

filtered_orders = data[data["Portal"].fillna("Unknown").astype(str).isin(selected_portals)].copy()
summary = agent_summary(filtered_orders)

if summary.empty:
    st.info("No agents match the selected portal selection.")
    st.stop()

with filter2:
    maximum = max(int(summary["Total"].max()), 1)
    minimum = st.number_input("Minimum orders", 1, maximum, 1)

with filter3:
    rank_by = st.selectbox(
        "Rank agents by",
        ["Delivery Rate", "Total Orders", "Delivered", "Critical Orders", "RTO"],
    )

summary = summary[summary["Total"].ge(minimum)].copy()
if summary.empty:
    st.info("No agents match the selected filters.")
    st.stop()

numeric_columns = [
    "Total",
    "Delivered",
    "Critical",
    "Follow-up",
    "OFD",
    "RTO",
    "RTO Prepared",
    "Back to Store",
    "Portal Count",
    "Delivery Rate",
]
for column in numeric_columns:
    summary[column] = pd.to_numeric(summary[column], errors="coerce").fillna(0)

summary["Agent"] = summary["Agent"].fillna("Unassigned").astype(str)
summary["Performance"] = summary.apply(
    lambda row: performance_style(float(row["Delivery Rate"]), int(row["Total"])),
    axis=1,
)

sort_map = {
    "Delivery Rate": ("Delivery Rate", False),
    "Total Orders": ("Total", False),
    "Delivered": ("Delivered", False),
    "Critical Orders": ("Critical", False),
    "RTO": ("RTO", False),
}
sort_column, ascending = sort_map[rank_by]
summary = summary.sort_values(
    [sort_column, "Total"],
    ascending=[ascending, False],
).reset_index(drop=True)
summary.insert(0, "Rank", range(1, len(summary) + 1))

work = add_derived_columns(filtered_orders)
total_orders = len(work)
total_delivered = int(work["Is Delivered"].sum()) if total_orders else 0
total_undelivered = total_orders - total_delivered
total_ofd = int(work["Status Group"].eq("Out for Delivery").sum()) if total_orders else 0
total_rto = int(work["Status Group"].eq("RTO").sum()) if total_orders else 0
total_critical = int(work["Is Critical"].sum()) if total_orders else 0
overall_rate = total_delivered / total_orders if total_orders else 0

cards = st.columns(7)
cards[0].metric("Actual Agents", f"{len(summary):,}")
cards[1].metric("All Orders", f"{total_orders:,}")
cards[2].metric("Delivered", f"{total_delivered:,}")
cards[3].metric("Undelivered", f"{total_undelivered:,}")
cards[4].metric("Out for Delivery", f"{total_ofd:,}")
cards[5].metric("RTO", f"{total_rto:,}")
cards[6].metric("Signing Rate", f"{overall_rate:.1%}")

st.caption(
    "Each agent appears once. All selected portal orders are combined into one total, one delivered count, and one signing rate."
)

left, right = st.columns([1.35, 1])

with left:
    st.subheader("Consolidated agent signing rate")
    chart_data = summary.copy().sort_values("Delivery Rate")
    figure = px.bar(
        chart_data,
        x="Delivery Rate",
        y="Agent",
        color="Performance",
        orientation="h",
        text="Delivery Rate",
        color_discrete_map={
            "Good": "#22c55e",
            "Average": "#f59e0b",
            "Needs Improvement": "#ef4444",
            "Low Sample": "#94a3b8",
        },
        hover_data={
            "Total": True,
            "Delivered": True,
            "OFD": True,
            "RTO": True,
            "Critical": True,
            "Follow-up": True,
            "Portals": True,
            "Delivery Rate": ":.1%",
        },
    )
    figure.update_traces(texttemplate="%{x:.1%}", textposition="outside", cliponaxis=False)
    figure.update_layout(
        height=max(430, len(chart_data) * 34),
        margin=dict(l=10, r=50, t=10, b=10),
        xaxis_tickformat=".0%",
        xaxis_range=[0, 1],
        yaxis_title="",
        legend_title="Performance",
    )
    st.plotly_chart(figure, width="stretch")

with right:
    st.subheader("All order status insights")
    status_counts = (
        work["Status"]
        .fillna("Unknown")
        .astype(str)
        .str.strip()
        .replace("", "Unknown")
        .value_counts()
        .rename_axis("Status")
        .reset_index(name="Orders")
    )
    status_figure = px.bar(
        status_counts.head(15).sort_values("Orders"),
        x="Orders",
        y="Status",
        orientation="h",
        text="Orders",
    )
    status_figure.update_traces(textposition="outside", cliponaxis=False)
    status_figure.update_layout(
        height=max(430, min(len(status_counts), 15) * 34),
        margin=dict(l=10, r=40, t=10, b=10),
        yaxis_title="",
    )
    st.plotly_chart(status_figure, width="stretch")

    status_group_counts = (
        work["Status Group"]
        .value_counts()
        .rename_axis("Status Group")
        .reset_index(name="Orders")
    )
    st.dataframe(status_group_counts, hide_index=True, width="stretch")

st.subheader("Complete consolidated agent ranking")
columns = [
    "Rank",
    "Agent",
    "Portals",
    "Portal Count",
    "Total",
    "Delivered",
    "Delivery Rate",
    "OFD",
    "RTO",
    "RTO Prepared",
    "Back to Store",
    "Critical",
    "Follow-up",
    "Performance",
]
table = summary[columns].copy()
st.dataframe(
    table.style.apply(highlight_performance_rows, axis=1).format({"Delivery Rate": "{:.1%}"}),
    width="stretch",
    hide_index=True,
    height=min(950, 40 + len(table) * 35),
)

with st.expander("View all filtered orders"):
    order_columns = [
        column
        for column in [
            "Portal",
            "AWB",
            "Customer Name",
            "Mobile",
            "Scheduled Date",
            "Status",
            "Remarks",
            "Agent",
            "Priority",
        ]
        if column in filtered_orders.columns
    ]
    st.dataframe(
        filtered_orders[order_columns],
        width="stretch",
        hide_index=True,
        height=650,
    )
