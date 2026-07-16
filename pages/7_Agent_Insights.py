from __future__ import annotations

import re

import pandas as pd
import streamlit as st

from src.data_loader import load_all_data
from src.metrics import add_derived_columns
from src.ui import page_header


st.set_page_config(
    page_title="Agent Insights",
    page_icon="👤",
    layout="wide",
)

page_header(
    "Agent Insights",
    "Individual agent performance with exact delivery status counts",
)


def clean_text(value) -> str:
    if pd.isna(value):
        return ""

    return re.sub(
        r"\s+",
        " ",
        str(value).strip(),
    )


def agent_key(value) -> str:
    return clean_text(value).casefold()


def agent_display(value) -> str:
    text = clean_text(value)

    if not text:
        return "Unassigned"

    return text


def safe_rate(delivered: int, total: int) -> float:
    if total <= 0:
        return 0.0

    return delivered / total


def performance_label(rate: float, total: int) -> str:
    if total < 10:
        return "Low Sample"

    if rate >= 0.70:
        return "Good"

    if rate >= 0.55:
        return "Average"

    return "Needs Improvement"


def performance_icon(label: str) -> str:
    icons = {
        "Good": "🟢",
        "Average": "🟠",
        "Needs Improvement": "🔴",
        "Low Sample": "⚪",
    }

    return icons.get(label, "⚪")


def status_counts(agent_data: pd.DataFrame) -> pd.DataFrame:
    result = (
        agent_data.assign(
            Status_Display=agent_data["Status"]
            .fillna("Unknown Status")
            .astype(str)
            .str.strip()
            .replace("", "Unknown Status")
        )
        .groupby("Status_Display", dropna=False)
        .size()
        .reset_index(name="Count")
        .rename(columns={"Status_Display": "Status"})
        .sort_values(
            ["Count", "Status"],
            ascending=[False, True],
        )
    )

    total = int(result["Count"].sum())

    result["Percentage"] = result["Count"].map(
        lambda count: f"{(count / total * 100):.1f}%"
        if total
        else "0.0%"
    )

    return result


def portal_counts(agent_data: pd.DataFrame) -> pd.DataFrame:
    rows: list[dict] = []

    for portal, group in agent_data.groupby(
        "Portal",
        dropna=False,
    ):
        total = len(group)

        delivered = int(
            group["Is Delivered"].sum()
        )

        ofd = int(
            group["Status Group"]
            .eq("Out for Delivery")
            .sum()
        )

        rto = int(
            group["Status Group"]
            .eq("RTO")
            .sum()
        )

        rto_prepared = int(
            group["Status Group"]
            .eq("RTO Prepared")
            .sum()
        )

        back_to_store = int(
            group["Status Group"]
            .eq("Back to Store")
            .sum()
        )

        critical = int(
            group["Is Critical"].sum()
        )

        follow_up = int(
            group["Is Follow Up"].sum()
        )

        rows.append(
            {
                "Portal": clean_text(portal) or "Unknown Portal",
                "Total": total,
                "Delivered": delivered,
                "Signing Rate": safe_rate(
                    delivered,
                    total,
                ),
                "OFD": ofd,
                "RTO": rto,
                "RTO Prepared": rto_prepared,
                "Back to Store": back_to_store,
                "Critical": critical,
                "Follow-up": follow_up,
            }
        )

    result = pd.DataFrame(rows)

    if result.empty:
        return result

    return result.sort_values(
        ["Signing Rate", "Total"],
        ascending=[False, False],
    )


def build_agent_summary(data: pd.DataFrame) -> pd.DataFrame:
    rows: list[dict] = []

    for key, group in data.groupby(
        "Agent Key",
        dropna=False,
    ):
        total = len(group)

        delivered = int(
            group["Is Delivered"].sum()
        )

        ofd = int(
            group["Status Group"]
            .eq("Out for Delivery")
            .sum()
        )

        rto = int(
            group["Status Group"]
            .eq("RTO")
            .sum()
        )

        rto_prepared = int(
            group["Status Group"]
            .eq("RTO Prepared")
            .sum()
        )

        back_to_store = int(
            group["Status Group"]
            .eq("Back to Store")
            .sum()
        )

        critical = int(
            group["Is Critical"].sum()
        )

        follow_up = int(
            group["Is Follow Up"].sum()
        )

        rate = safe_rate(
            delivered,
            total,
        )

        portals = portal_counts(group)

        best_portal = (
            portals.iloc[0]["Portal"]
            if not portals.empty
            else "N/A"
        )

        lowest_portal = (
            portals.iloc[-1]["Portal"]
            if not portals.empty
            else "N/A"
        )

        failed_statuses = group[
            ~group["Is Delivered"]
        ]["Status"].fillna("Unknown Status").astype(str).str.strip()

        failed_statuses = failed_statuses[
            failed_statuses.ne("")
        ]

        top_non_delivered_status = (
            failed_statuses.value_counts().index[0]
            if not failed_statuses.empty
            else "None"
        )

        rows.append(
            {
                "Agent Key": key,
                "Agent": group["Agent Display"].iloc[0],
                "Total": total,
                "Delivered": delivered,
                "Signing Rate": rate,
                "OFD": ofd,
                "RTO": rto,
                "RTO Prepared": rto_prepared,
                "Back to Store": back_to_store,
                "Critical": critical,
                "Follow-up": follow_up,
                "Performance": performance_label(
                    rate,
                    total,
                ),
                "Top Non-delivered Status": (
                    top_non_delivered_status
                ),
                "Best Portal": best_portal,
                "Lowest Portal": lowest_portal,
            }
        )

    return pd.DataFrame(rows)


data, _ = load_all_data()

if data.empty:
    st.info(
        "No agent performance data is available."
    )
    st.stop()

required_columns = {
    "Agent",
    "Portal",
    "Status",
    "AWB",
    "Priority",
}

missing_columns = sorted(
    required_columns.difference(data.columns)
)

if missing_columns:
    st.error(
        "Missing required columns: "
        + ", ".join(missing_columns)
    )
    st.stop()

work = add_derived_columns(data)

work["Agent Display"] = (
    work["Agent"]
    .fillna("Unassigned")
    .astype(str)
    .map(agent_display)
)

work["Agent Key"] = (
    work["Agent Display"]
    .map(agent_key)
)

work["Portal"] = (
    work["Portal"]
    .fillna("Unknown Portal")
    .astype(str)
    .str.strip()
    .replace("", "Unknown Portal")
)

work = work[
    work["Agent Key"].ne("")
    & work["Agent Key"].ne("unassigned")
].copy()

if work.empty:
    st.info(
        "No assigned agent records are available."
    )
    st.stop()

available_portals = sorted(
    work["Portal"].dropna().unique().tolist()
)

filter_col1, filter_col2, filter_col3 = st.columns(
    [2, 1, 2]
)

with filter_col1:
    selected_portals = st.multiselect(
        "Portal",
        options=available_portals,
        default=available_portals,
    )

with filter_col2:
    minimum_orders = st.number_input(
        "Minimum orders",
        min_value=1,
        value=1,
        step=1,
    )

with filter_col3:
    sort_option = st.selectbox(
        "Sort agents by",
        options=[
            "Signing Rate — High to Low",
            "Signing Rate — Low to High",
            "Total Orders — High to Low",
            "Delivered — High to Low",
            "Critical Orders — High to Low",
            "RTO — High to Low",
        ],
    )

filtered = work[
    work["Portal"].isin(selected_portals)
].copy()

summary = build_agent_summary(filtered)

summary = summary[
    summary["Total"] >= minimum_orders
].copy()

sort_rules = {
    "Signing Rate — High to Low": (
        ["Signing Rate", "Total"],
        [False, False],
    ),
    "Signing Rate — Low to High": (
        ["Signing Rate", "Total"],
        [True, False],
    ),
    "Total Orders — High to Low": (
        ["Total", "Signing Rate"],
        [False, False],
    ),
    "Delivered — High to Low": (
        ["Delivered", "Signing Rate"],
        [False, False],
    ),
    "Critical Orders — High to Low": (
        ["Critical", "Total"],
        [False, False],
    ),
    "RTO — High to Low": (
        ["RTO", "Total"],
        [False, False],
    ),
}

sort_columns, sort_ascending = sort_rules[
    sort_option
]

summary = summary.sort_values(
    sort_columns,
    ascending=sort_ascending,
)

actual_agents = int(
    filtered["Agent Key"].nunique()
)

total_orders = len(filtered)

total_delivered = int(
    filtered["Is Delivered"].sum()
)

overall_signing_rate = safe_rate(
    total_delivered,
    total_orders,
)

good_count = int(
    summary["Performance"].eq("Good").sum()
)

average_count = int(
    summary["Performance"].eq("Average").sum()
)

needs_improvement_count = int(
    summary["Performance"]
    .eq("Needs Improvement")
    .sum()
)

metric_cards = st.columns(5)

metric_cards[0].metric(
    "Actual Agents",
    f"{actual_agents:,}",
)

metric_cards[1].metric(
    "Good",
    f"{good_count:,}",
)

metric_cards[2].metric(
    "Average",
    f"{average_count:,}",
)

metric_cards[3].metric(
    "Needs Improvement",
    f"{needs_improvement_count:,}",
)

metric_cards[4].metric(
    "Total Delivery Signing Rate",
    f"{overall_signing_rate:.1%}",
)

st.caption(
    "Good ≥ 70% • Average 55–69.9% • "
    "Needs Improvement < 55% • "
    "Low Sample = fewer than 10 orders"
)

st.divider()

if summary.empty:
    st.warning(
        "No agents match the selected filters."
    )
    st.stop()

for rank, (_, agent_row) in enumerate(
    summary.iterrows(),
    start=1,
):
    agent_data = filtered[
        filtered["Agent Key"]
        .eq(agent_row["Agent Key"])
    ].copy()

    icon = performance_icon(
        agent_row["Performance"]
    )

    with st.container(border=True):
        header1, header2, header3 = st.columns(
            [2.5, 1, 1]
        )

        with header1:
            st.subheader(
                f"#{rank} · {agent_row['Agent']}"
            )

            st.caption(
                f"{icon} {agent_row['Performance']} • "
                f"Best portal: {agent_row['Best Portal']} • "
                f"Lowest portal: {agent_row['Lowest Portal']}"
            )

        with header2:
            st.metric(
                "Signing Rate",
                f"{agent_row['Signing Rate']:.1%}",
            )

        with header3:
            st.metric(
                "Total Orders",
                f"{int(agent_row['Total']):,}",
            )

        status_metrics = st.columns(7)

        status_metrics[0].metric(
            "Delivered",
            f"{int(agent_row['Delivered']):,}",
        )

        status_metrics[1].metric(
            "OFD",
            f"{int(agent_row['OFD']):,}",
        )

        status_metrics[2].metric(
            "RTO",
            f"{int(agent_row['RTO']):,}",
        )

        status_metrics[3].metric(
            "RTO Prepared",
            f"{int(agent_row['RTO Prepared']):,}",
        )

        status_metrics[4].metric(
            "Back to Store",
            f"{int(agent_row['Back to Store']):,}",
        )

        status_metrics[5].metric(
            "Critical",
            f"{int(agent_row['Critical']):,}",
        )

        status_metrics[6].metric(
            "Follow-up",
            f"{int(agent_row['Follow-up']):,}",
        )

        st.caption(
            "Most common non-delivered status: "
            f"**{agent_row['Top Non-delivered Status']}**"
        )

        exact_status_tab, portal_tab = st.tabs(
            [
                "Exact Status Counts",
                "Portal Breakdown",
            ]
        )

        with exact_status_tab:
            exact_statuses = status_counts(
                agent_data
            )

            st.dataframe(
                exact_statuses,
                hide_index=True,
                width="stretch",
            )

        with portal_tab:
            portals = portal_counts(
                agent_data
            )

            if not portals.empty:
                portals["Signing Rate"] = (
                    portals["Signing Rate"]
                    .map(lambda value: f"{value:.1%}")
                )

            st.dataframe(
                portals,
                hide_index=True,
                width="stretch",
            )
