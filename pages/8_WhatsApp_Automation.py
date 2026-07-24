from __future__ import annotations

from datetime import date

import plotly.express as px
import streamlit as st

from src.notification_loader import load_notification_reports


st.set_page_config(
    page_title="WhatsApp Automation",
    page_icon="💬",
    layout="wide",
)

st.title("WhatsApp Automation")
st.caption(
    "DoubleTick API acceptance, final delivery statuses, and RTO tagging for critical Tawseel orders"
)

if st.button("Refresh report data", type="secondary"):
    load_notification_reports.clear()
    st.rerun()

data = load_notification_reports()

if data.empty:
    st.info("No DoubleTick notification report data is available yet.")
    st.stop()

portal_options = sorted(data["Portal"].dropna().astype(str).unique())
template_options = sorted(
    data["Template Result"].dropna().astype(str).str.upper().unique()
)
tag_options = sorted(data["Tag Result"].dropna().astype(str).str.upper().unique())

filter_1, filter_2, filter_3, filter_4 = st.columns(4)

with filter_1:
    selected_portals = st.multiselect(
        "Portal",
        options=portal_options,
        default=portal_options,
    )

with filter_2:
    selected_templates = st.multiselect(
        "Message status",
        options=template_options,
        default=template_options,
    )

with filter_3:
    selected_tags = st.multiselect(
        "RTO tag result",
        options=tag_options,
        default=tag_options,
    )

valid_dates = data["Timestamp"].dropna()
default_start = valid_dates.min().date() if not valid_dates.empty else date.today()

with filter_4:
    start_date = st.date_input("Start date", value=default_start)

filtered = data.copy()
filtered["Template Result"] = filtered["Template Result"].str.upper()
filtered["Tag Result"] = filtered["Tag Result"].str.upper()

if selected_portals:
    filtered = filtered[filtered["Portal"].isin(selected_portals)]

if selected_templates:
    filtered = filtered[filtered["Template Result"].isin(selected_templates)]

if selected_tags:
    filtered = filtered[filtered["Tag Result"].isin(selected_tags)]

filtered = filtered[
    filtered["Timestamp"].isna()
    | (filtered["Timestamp"].dt.date >= start_date)
]

total = len(filtered)
api_accepted = int(filtered["Template Result"].eq("API_ACCEPTED").sum())
sent = int(filtered["Template Result"].eq("SENT").sum())
delivered = int(filtered["Template Result"].eq("DELIVERED").sum())
read = int(filtered["Template Result"].eq("READ").sum())
failed = int(filtered["Template Result"].eq("FAILED").sum())
tagged = int(filtered["Tag Result"].eq("TAGGED").sum())

metric_columns = st.columns(7)
metric_columns[0].metric("Report Records", f"{total:,}")
metric_columns[1].metric(
    "API Accepted (Pending)",
    f"{api_accepted:,}",
    help="DoubleTick accepted the request, but no final webhook status has been received yet.",
)
metric_columns[2].metric("Sent", f"{sent:,}")
metric_columns[3].metric("Delivered", f"{delivered:,}")
metric_columns[4].metric("Read", f"{read:,}")
metric_columns[5].metric("Failed", f"{failed:,}")
metric_columns[6].metric("RTO Tagged", f"{tagged:,}")

chart_left, chart_right = st.columns(2)

with chart_left:
    st.subheader("Message status results")
    template_summary = (
        filtered["Template Result"]
        .replace("", "UNKNOWN")
        .value_counts()
        .rename_axis("Result")
        .reset_index(name="Count")
    )

    if not template_summary.empty:
        figure = px.bar(
            template_summary,
            x="Result",
            y="Count",
            text_auto=True,
        )
        figure.update_layout(height=350, margin=dict(t=20, b=20))
        st.plotly_chart(figure, width="stretch")

with chart_right:
    st.subheader("RTO tag results")
    tag_summary = (
        filtered["Tag Result"]
        .replace("", "UNKNOWN")
        .value_counts()
        .rename_axis("Result")
        .reset_index(name="Count")
    )

    if not tag_summary.empty:
        figure = px.bar(
            tag_summary,
            x="Result",
            y="Count",
            text_auto=True,
        )
        figure.update_layout(height=350, margin=dict(t=20, b=20))
        st.plotly_chart(figure, width="stretch")

portal_summary = (
    filtered.groupby(["Portal", "Template Result"], dropna=False)
    .size()
    .reset_index(name="Count")
)

st.subheader("Portal summary")
if not portal_summary.empty:
    figure = px.bar(
        portal_summary,
        x="Portal",
        y="Count",
        color="Template Result",
        barmode="group",
    )
    figure.update_layout(height=380, margin=dict(t=20, b=20))
    st.plotly_chart(figure, width="stretch")

st.subheader("Notification details")

display = filtered.copy()
display["Timestamp"] = (
    display["Timestamp"]
    .dt.strftime("%d-%m-%Y %I:%M %p")
    .fillna("")
)

st.dataframe(
    display[
        [
            "Timestamp",
            "Portal",
            "AWB",
            "Customer Name",
            "Phone",
            "Product",
            "Tawseel Status",
            "Priority",
            "Template Result",
            "Template HTTP",
            "Template Message ID",
            "Tag",
            "Tag Result",
            "Tag HTTP",
            "Error",
        ]
    ],
    width="stretch",
    hide_index=True,
    height=620,
)

st.caption(
    "API Accepted means DoubleTick accepted the request. Sent, Delivered, Read, and Failed are final webhook statuses. Data refreshes every three minutes."
)
