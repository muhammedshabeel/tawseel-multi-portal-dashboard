from __future__ import annotations

import plotly.express as px
import streamlit as st

from src.data_loader import load_all_data
from src.metrics import add_derived_columns, agent_summary, overall_metrics, portal_summary
from src.ui import (
    apply_filters,
    apply_report_period_panel,
    page_header,
    performance_style,
)

st.set_page_config(
    page_title="Tawseel Operations Dashboard",
    page_icon="🚚",
    layout="wide",
)

page_header(
    "Tawseel Operations Dashboard",
    "Executive delivery, signing-rate and action insights across all configured portals",
)

try:
    data, health = load_all_data()
except Exception as exc:
    st.error(f"Dashboard configuration error: {exc}")
    st.stop()

if health["State"].eq("Failed").any():
    st.warning("One or more portals failed to load. Open Data Quality for details.")

filtered = apply_filters(data)
filtered, report_start, report_end = apply_report_period_panel(
    filtered,
    key_prefix="overview",
)

if filtered.empty:
    st.info("No records match the selected filters.")
    st.stop()

work = add_derived_columns(filtered)
metrics = overall_metrics(filtered)
portals = portal_summary(filtered)
agents = agent_summary(filtered)

k1, k2, k3, k4, k5, k6 = st.columns(6)

k1.metric("Total Orders", f"{metrics['Total']:,}", help="Total orders in the selected view")
k2.metric("Delivered", f"{metrics['Delivered']:,}", help="Orders currently signed as delivered")
k3.metric("Signing Rate", f"{metrics['Delivery Rate']:.1%}", help="Delivered orders divided by total orders")
k4.metric("Out for Delivery", f"{metrics['OFD']:,}", help="Orders currently out for delivery")
k5.metric("RTO", f"{metrics['RTO']:,}", help="Orders marked return to origin")
k6.metric("Critical Orders", f"{metrics['Critical']:,}", help="Orders marked critical by priority logic")

st.caption(
    "Traffic-light standard: Good ≥ 70% • Watch 55–69.9% • "
    "Needs action < 55% • Low sample < 10 orders"
)

best_portal = portals.sort_values("Delivery Rate", ascending=False).iloc[0] if not portals.empty else None
worst_portal = portals.sort_values("Delivery Rate", ascending=True).iloc[0] if not portals.empty else None
rankable_agents = agents[agents["Total"].ge(10)].copy() if not agents.empty else agents
best_agent = (
    rankable_agents.sort_values(["Delivery Rate", "Total"], ascending=[False, False]).iloc[0]
    if not rankable_agents.empty
    else None
)
needs_action_agents = int((rankable_agents["Delivery Rate"] < 0.55).sum()) if not rankable_agents.empty else 0
action_orders = int((work["Is Critical"] | work["Is Follow Up"]).sum())
healthy_portals = int(health["State"].eq("Healthy").sum())

st.subheader("Executive health check")
h1, h2, h3, h4, h5, h6 = st.columns(6)

if best_portal is not None:
    h1.metric("Best Portal", str(best_portal["Portal"]), f"{best_portal['Delivery Rate']:.1%} signing rate")
if worst_portal is not None:
    h2.metric("Lowest Portal", str(worst_portal["Portal"]), f"{worst_portal['Delivery Rate']:.1%} signing rate", delta_color="inverse")
if best_agent is not None:
    h3.metric("Best Agent", str(best_agent["Agent"]), f"{best_agent['Delivery Rate']:.1%} • {int(best_agent['Total'])} orders")

h4.metric("Agents Needing Action", f"{needs_action_agents:,}", "Below 55%", delta_color="inverse")
h5.metric("Action Queue", f"{action_orders:,}", f"{metrics['Follow-up']:,} follow-up")
h6.metric("Data Health", f"{healthy_portals}/{len(health)}", "portals healthy")

rate_label = performance_style(float(metrics["Delivery Rate"]), max(int(metrics["Total"]), 10))
summary_lines = [f"Overall signing rate is **{metrics['Delivery Rate']:.1%}**, classified as **{rate_label}**."]

if best_portal is not None and worst_portal is not None:
    gap = float(best_portal["Delivery Rate"] - worst_portal["Delivery Rate"])
    summary_lines.append(
        f"**{best_portal['Portal']}** leads at **{best_portal['Delivery Rate']:.1%}**, while "
        f"**{worst_portal['Portal']}** is lowest at **{worst_portal['Delivery Rate']:.1%}** "
        f"({gap:.1%} point gap)."
    )

summary_lines.append(
    f"There are **{metrics['Critical']:,} critical orders** and "
    f"**{metrics['Follow-up']:,} follow-up orders** requiring attention."
)
if needs_action_agents:
    summary_lines.append(
        f"**{needs_action_agents} agents** with at least 10 orders are below the 55% signing-rate threshold."
    )

st.info("  \n".join(summary_lines))

left, right = st.columns([1.05, 1])

with left:
    st.subheader("Portal signing-rate comparison")
    if not portals.empty:
        chart_portals = portals.copy()
        chart_portals["Health"] = chart_portals.apply(
            lambda row: performance_style(float(row["Delivery Rate"]), int(row["Total"])),
            axis=1,
        )
        fig = px.bar(
            chart_portals.sort_values("Delivery Rate", ascending=False),
            x="Portal",
            y="Delivery Rate",
            color="Health",
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
                "Critical": True,
                "RTO": True,
                "Delivery Rate": ":.1%",
            },
        )
        fig.update_traces(texttemplate="%{y:.1%}", textposition="outside")
        fig.update_layout(
            height=390,
            yaxis_tickformat=".0%",
            yaxis_range=[0, 1],
            legend_title="Health",
            margin=dict(t=20, b=20),
        )
        st.plotly_chart(fig, width="stretch")

with right:
    st.subheader("Operational status mix")
    status = work["Status Group"].value_counts().rename_axis("Status").reset_index(name="Count")
    fig = px.pie(status, names="Status", values="Count", hole=0.58)
    fig.update_traces(textposition="inside", textinfo="percent+label")
    fig.update_layout(height=390, margin=dict(t=20, b=20), legend_title="Status")
    st.plotly_chart(fig, width="stretch")

st.subheader("Portal scorecard")
portal_table = portals[
    ["Portal", "Total", "Delivered", "Delivery Rate", "OFD", "RTO", "Critical", "Follow-up"]
].copy()
portal_table["Health"] = portal_table.apply(
    lambda row: performance_style(float(row["Delivery Rate"]), int(row["Total"])),
    axis=1,
)
st.dataframe(
    portal_table.style.format({"Delivery Rate": "{:.1%}"}),
    width="stretch",
    hide_index=True,
    height=min(260, 40 + len(portal_table) * 36),
)

st.subheader("Immediate action queue")
queue = work[work["Is Critical"] | work["Is Follow Up"]].copy()

if not queue.empty:
    queue = queue.sort_values(["Is Critical", "Scheduled Date"], ascending=[False, True])
    st.dataframe(
        queue[
            [
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
        ],
        width="stretch",
        hide_index=True,
        height=420,
    )
else:
    st.success("No critical or follow-up records in the selected view.")

with st.expander("Portal refresh health", expanded=False):
    st.dataframe(
        health.style.format({"Fetch Rate": "{:.1%}"}),
        width="stretch",
        hide_index=True,
    )
