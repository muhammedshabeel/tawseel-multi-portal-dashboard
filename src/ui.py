from __future__ import annotations

import streamlit as st


def page_header(title: str, subtitle: str = "") -> None:
    st.title(title)
    if subtitle:
        st.caption(subtitle)


def metric_card(label: str, value: str, help_text: str | None = None) -> None:
    st.metric(label, value, help=help_text)


def apply_filters(df):
    if df.empty:
        return df
    with st.sidebar:
        st.header("Filters")
        portals = sorted(df["Portal"].dropna().unique().tolist())
        selected_portals = st.multiselect("Portal", portals, default=portals)
        agents = sorted(df[df["Portal"].isin(selected_portals)]["Agent"].dropna().unique().tolist())
        selected_agents = st.multiselect("Agent", agents)
        statuses = sorted(df[df["Portal"].isin(selected_portals)]["Status"].dropna().unique().tolist())
        selected_statuses = st.multiselect("Status", statuses)
    out = df[df["Portal"].isin(selected_portals)]
    if selected_agents:
        out = out[out["Agent"].isin(selected_agents)]
    if selected_statuses:
        out = out[out["Status"].isin(selected_statuses)]
    return out
