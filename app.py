from __future__ import annotations

import plotly.express as px
import streamlit as st

from src.data_loader import load_all_data
from src.metrics import add_derived_columns, portal_summary
from src.ui import apply_filters, report_date_filter, show_report_period

st.set_page_config(
    page_title="Tawseel UAE Portal",
    page_icon="🚚",
    layout="wide",
)

try:
    data, health = load_all_data()
except Exception as exc:
    st.error(f"Dashboard configuration error: {exc}")
    st.stop()

if not health.empty and health["State"].eq("Failed").any():
    st.warning("One or more portals failed to load. Check Data Quality for details.")

header_left, header_right = st.columns([2.6, 1])

with header_left:
    st.title("Tawseel UAE Portal")
    st.caption("Live consolidated view from all configured Tawseel Google Sheets")

filtered = apply_filters(data)

with header_right:
    filtered, report_start, report_end, missing_dates = report_date_filter(
        filtered,
        key_prefix="overview",
    )
    show_report_period(
        report_start,
        report_end,
        len(filtered),
        missing_dates,
    )

if filtered.empty:
    st.info("No records match the selected filters.")
    st.stop()

work = add_derived_columns(filtered)
total = len(work)
delivered = int(work["Is Delivered"].sum()) if total else 0
critical = int(work["Is Critical"].sum()) if total else 0
follow_up = int(work["Is Follow Up"].sum()) if total else 0
ofd = int(work["Status Group"].eq("Out for Delivery").sum()) if total else 0
rto = int(work["Status Group"].eq("RTO").sum()) if total else 0
signing_rate = delivered / total if total else 0

cols = st.columns(7)
cols[0].metric("Total Orders", f"{total:,}")
cols[1].metric("Delivered", f"{delivered:,}")
cols[2].metric("Signing Rate", f"{signing_rate:.1%}")
cols[3].metric("Out for Delivery", f"{ofd:,}")
cols[4].metric("RTO", f"{rto:,}")
cols[5].metric("Critical", f"{critical:,}")
cols[6].metric("Follow-up", f"{follow_up:,}")

left, right = st.columns([1.05, 1])

with left:
    st.subheader("Portal comparison")
    summary = portal_summary(filtered)

    if not summary.empty:
        fig = px.bar(
            summary,
            x="Portal",
            y=["Delivered", "OFD", "RTO"],
            barmode="group",
        )
        fig.update_layout(height=390, margin=dict(t=20, b=20))
        st.plotly_chart(fig, width="stretch")

        st.dataframe(
            summary.style.format({"Delivery Rate": "{:.1%}"}),
            width="stretch",
            hide_index=True,
        )
    else:
        st.info("No data for the selected filters.")

with right:
    st.subheader("Current status mix")

    if not work.empty:
        status = (
            work["Status Group"]
            .value_counts()
            .rename_axis("Status")
            .reset_index(name="Count")
        )

        fig = px.pie(
            status,
            names="Status",
            values="Count",
            hole=0.55,
        )
        fig.update_layout(height=390, margin=dict(t=20, b=20))
        st.plotly_chart(fig, width="stretch")
    else:
        st.info("No data for the selected filters.")

st.subheader("Immediate action queue")
queue = work[work["Is Critical"] | work["Is Follow Up"]].copy()

if not queue.empty:
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
        height=520,
    )
else:
    st.success("No critical or follow-up records in the selected view.")

with st.expander("Portal refresh health", expanded=False):
    st.dataframe(
        health.style.format({"Fetch Rate": "{:.1%}"}),
        width="stretch",
        hide_index=True,
    )
