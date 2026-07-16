from __future__ import annotations

import pandas as pd
import streamlit as st


def page_header(title: str, subtitle: str = "") -> None:
    st.title(title)
    if subtitle:
        st.caption(subtitle)


def metric_card(label: str, value: str, help_text: str | None = None) -> None:
    st.metric(label, value, help=help_text)


def performance_style(delivery_rate: float, total_orders: int) -> str:
    """Return the performance bucket used across agent views."""
    if total_orders < 10:
        return "Low Sample"
    if delivery_rate >= 0.70:
        return "Good"
    if delivery_rate >= 0.55:
        return "Average"
    return "Needs Improvement"


def highlight_performance_rows(row: pd.Series) -> list[str]:
    """Apply a subtle row highlight based on the Performance column."""
    performance = str(row.get("Performance", ""))
    background = {
        "Good": "background-color: #dcfce7; color: #166534;",
        "Average": "background-color: #fef3c7; color: #92400e;",
        "Needs Improvement": "background-color: #fee2e2; color: #991b1b;",
        "Low Sample": "background-color: #f1f5f9; color: #475569;",
    }.get(performance, "")
    return [background] * len(row)


def apply_filters(df):
    if df.empty:
        return df
    with st.sidebar:
        st.header("Filters")
        portals = sorted(df["Portal"].dropna().unique().tolist())
        selected_portals = st.multiselect("Portal", portals, default=portals)
        agents = sorted(
            df[df["Portal"].isin(selected_portals)]["Agent"]
            .dropna()
            .unique()
            .tolist()
        )
        selected_agents = st.multiselect("Agent", agents)
        statuses = sorted(
            df[df["Portal"].isin(selected_portals)]["Status"]
            .dropna()
            .unique()
            .tolist()
        )
        selected_statuses = st.multiselect("Status", statuses)
    out = df[df["Portal"].isin(selected_portals)]
    if selected_agents:
        out = out[out["Agent"].isin(selected_agents)]
    if selected_statuses:
        out = out[out["Status"].isin(selected_statuses)]
    return out
