from __future__ import annotations

import pandas as pd
import plotly.express as px
import streamlit as st

from src.data_loader import load_all_data
from src.metrics import add_derived_columns, portal_summary
from src.ui import apply_filters, page_header

st.set_page_config(page_title="Tawseel Control Tower", page_icon="🚚", layout="wide")

page_header("Tawseel Multi-Portal Control Tower", "Live consolidated view from all configured Tawseel Google Sheets")

try:
    data, health = load_all_data()
except Exception as exc:
    st.error(f"Dashboard configuration error: {exc}")
    st.stop()

if not health.empty and health["State"].eq("Failed").any():
    st.warning("One or more portals failed to load. Check Data Quality for details.")

filtered = apply_filters(data)
work = add_derived_columns(filtered) if not filtered.empty else filtered

if not work.empty:
    if "Revenue" not in work.columns:
        work["Revenue"] = 0.0
    work["Revenue"] = pd.to_numeric(work["Revenue"], errors="coerce").fillna(0.0)

total = len(work)
delivered = int(work["Is Delivered"].sum()) if total else 0
critical = int(work["Is Critical"].sum()) if total else 0
follow_up = int(work["Is Follow Up"].sum()) if total else 0
ofd = int(work["Status Group"].eq("Out for Delivery").sum()) if total else 0
rto = int(work["Status Group"].eq("RTO").sum()) if total else 0

cols = st.columns(6)
cols[0].metric("Total Orders", f"{total:,}")
cols[1].metric("Delivered", f"{delivered:,}", f"{(delivered / total * 100 if total else 0):.1f}%")
cols[2].metric("Out for Delivery", f"{ofd:,}")
cols[3].metric("RTO", f"{rto:,}")
cols[4].metric("Critical", f"{critical:,}")
cols[5].metric("Follow-up", f"{follow_up:,}")

st.subheader("Revenue overview")

total_revenue = float(work["Revenue"].sum()) if total else 0.0
delivered_revenue = float(work.loc[work["Is Delivered"], "Revenue"].sum()) if total else 0.0
pending_revenue = float(work.loc[~work["Is Delivered"], "Revenue"].sum()) if total else 0.0
delivered_revenue_share = delivered_revenue / total_revenue if total_revenue else 0.0
pending_revenue_share = pending_revenue / total_revenue if total_revenue else 0.0

revenue_cols = st.columns(3)
revenue_cols[0].metric("Total Revenue", f"AED {total_revenue:,.2f}")
revenue_cols[1].metric(
    "Delivered Revenue",
    f"AED {delivered_revenue:,.2f}",
    f"{delivered_revenue_share:.1%} of total",
)
revenue_cols[2].metric(
    "Pending Delivery Revenue",
    f"AED {pending_revenue:,.2f}",
    f"{pending_revenue_share:.1%} of total",
)

st.caption("Pending Delivery Revenue includes every order that is not currently classified as Delivered.")

left, right = st.columns([1.05, 1])
with left:
    st.subheader("Portal comparison")
    summary = portal_summary(filtered)
    if not summary.empty:
        fig = px.bar(summary, x="Portal", y=["Delivered", "OFD", "RTO"], barmode="group")
        st.plotly_chart(fig, use_container_width=True)
        st.dataframe(summary.style.format({"Delivery Rate": "{:.1%}"}), use_container_width=True, hide_index=True)
    else:
        st.info("No data for the selected filters.")

with right:
    st.subheader("Current status mix")
    if not work.empty:
        status = work["Status Group"].value_counts().rename_axis("Status").reset_index(name="Count")
        fig = px.pie(status, names="Status", values="Count", hole=0.55)
        st.plotly_chart(fig, use_container_width=True)
    else:
        st.info("No data for the selected filters.")

st.subheader("Immediate action queue")
queue = work[work["Is Critical"] | work["Is Follow Up"]].copy() if not work.empty else work
if not queue.empty:
    display_columns = [
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
    if "Revenue" in queue.columns:
        display_columns.append("Revenue")
    st.dataframe(
        queue[display_columns],
        use_container_width=True,
        hide_index=True,
    )
else:
    st.success("No critical or follow-up records in the selected view.")

with st.expander("Portal refresh health", expanded=False):
    st.dataframe(health.style.format({"Fetch Rate": "{:.1%}"}), use_container_width=True, hide_index=True)
