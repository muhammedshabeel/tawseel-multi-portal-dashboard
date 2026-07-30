from __future__ import annotations

from typing import Any

import pandas as pd
import streamlit as st

from src.logistics_dashboard_metrics import logistics_case_masks
from src.logistics_kanban_workspace import (
    BOARD_STAGES,
    _available_status_dates,
    _filter_status_date,
    _render_drawer,
    _selected_key,
    _sort_latest,
    _stage_series,
    _text,
)


def _inject_compact_styles(drawer_open: bool) -> None:
    drawer_css = """
    .st-key-logistics_order_drawer {
        position: fixed;
        top: 4.7rem;
        right: 0.8rem;
        width: min(430px, calc(100vw - 1.6rem));
        max-height: calc(100vh - 5.6rem);
        overflow-y: auto;
        z-index: 9999;
        padding: 0.55rem;
        border: 1px solid rgba(128, 128, 128, 0.28);
        border-radius: 14px;
        background: var(--background-color, #ffffff);
        box-shadow: 0 18px 48px rgba(0, 0, 0, 0.22);
    }
    .st-key-logistics_order_drawer [data-testid="stVerticalBlockBorderWrapper"] {
        border: 0 !important;
        padding: 0 !important;
    }
    """ if drawer_open else ""

    st.markdown(
        f"""
        <style>
        .st-key-logistics_kanban_board {{
            width: 100%;
        }}
        [class*="st-key-kanban_column_"] {{
            background: rgba(128, 128, 128, 0.045);
            border-radius: 12px;
        }}
        [class*="st-key-kanban_column_"] > div {{
            padding: 0.35rem !important;
        }}
        [class*="st-key-kanban_card_"] {{
            margin-bottom: 0.4rem;
        }}
        [class*="st-key-kanban_card_"] > div {{
            padding: 0.48rem 0.52rem !important;
        }}
        [class*="st-key-kanban_card_"] p {{
            margin: 0 !important;
            line-height: 1.18 !important;
        }}
        [class*="st-key-kanban_card_"] [data-testid="stCaptionContainer"] {{
            margin-top: 0.12rem !important;
            margin-bottom: 0.12rem !important;
        }}
        [class*="st-key-kanban_card_"] .stButton {{
            margin-top: 0.28rem !important;
        }}
        [class*="st-key-kanban_card_"] .stButton button {{
            min-height: 1.85rem !important;
            padding: 0.15rem 0.45rem !important;
            font-size: 0.78rem !important;
        }}
        {drawer_css}
        </style>
        """,
        unsafe_allow_html=True,
    )


def _priority_badge(row: pd.Series, stage: str) -> str:
    priority = _text(row.get("Priority")).upper()
    if "CRITICAL" in priority:
        return "🔥 Critical"
    if "FOLLOW" in priority:
        return "⏰ Follow-up"
    if stage == "RTO":
        return "↩ RTO"
    if stage == "Delivered Review":
        return "✅ Delivered"
    return stage


def _compact_text(value: Any, limit: int) -> str:
    text = _text(value)
    if len(text) <= limit:
        return text
    return text[: max(0, limit - 1)].rstrip() + "…"


def _render_compact_card(agent: str, row: pd.Series, stage: str) -> None:
    case_id = _text(row.get("Case ID"))
    customer = _compact_text(row.get("Customer Name"), 24) or "Unknown customer"
    awb = _text(row.get("AWB")) or "No AWB"
    portal = _compact_text(row.get("Portal"), 18) or "Unknown portal"
    work_status = _compact_text(row.get("Logistics Work Status"), 18) or "NEW"
    calls = pd.to_numeric(row.get("Total Call Attempts", 0), errors="coerce")
    calls = 0 if pd.isna(calls) else int(calls)
    next_follow_up = _text(row.get("Next Follow-up"))

    with st.container(border=True, key=f"kanban_card_{agent}_{case_id}"):
        st.caption(_priority_badge(row, stage))
        st.markdown(f"**{customer}**")
        st.caption(f"AWB {awb}")
        st.caption(f"{portal} · {work_status}")
        footer = f"Calls {calls}"
        if next_follow_up:
            footer += f" · Next {_compact_text(next_follow_up, 17)}"
        st.caption(footer)
        if st.button(
            "Open →",
            key=f"kanban_open_compact_{agent}_{case_id}",
            width="stretch",
        ):
            st.session_state[_selected_key(agent)] = case_id
            st.rerun()


def render_logistics_kanban_compact(
    *,
    agent: str,
    all_cases: pd.DataFrame,
    activity: pd.DataFrame,
) -> None:
    assigned_all = all_cases[
        all_cases["Logistics Agent"].astype(str).str.upper().eq(agent.upper())
    ].copy()
    masks = logistics_case_masks(assigned_all)
    open_all = _sort_latest(assigned_all[~masks["closed"]].copy())
    drawer_open = bool(_text(st.session_state.get(_selected_key(agent), "")))
    _inject_compact_styles(drawer_open)

    st.subheader(f"{agent.title()} Workspace")
    metric_columns = st.columns(8)
    metric_columns[0].metric("Assigned", len(assigned_all))
    metric_columns[1].metric("Active", int(masks["active"].sum()))
    metric_columns[2].metric("RTO", int(masks["current_rto"].sum()))
    metric_columns[3].metric("Recovered from RTO", int(masks["rto_recovered"].sum()))
    metric_columns[4].metric("Tawseel Delivered", int(masks["tawseel_delivered"].sum()))
    metric_columns[5].metric("Pending Review", int(masks["pending_review"].sum()))
    metric_columns[6].metric(
        "Calls Logged",
        int(
            pd.to_numeric(
                assigned_all.get("Total Call Attempts", pd.Series(dtype=float)),
                errors="coerce",
            ).fillna(0).sum()
        ),
    )
    metric_columns[7].metric("Recovered", int(masks["recovered"].sum()))

    if open_all.empty:
        st.info("No open cases assigned.")
        return

    search_col, portal_col, date_col, limit_col = st.columns([2.4, 1.2, 1.2, 0.9])
    query = search_col.text_input(
        "Search",
        placeholder="AWB, customer, mobile or remark",
        key=f"kanban_search_compact_{agent}",
    )
    portals = sorted(value for value in open_all["Portal"].astype(str).unique() if value)
    portal = portal_col.selectbox(
        "Portal",
        ["All Portals", *portals],
        key=f"kanban_portal_compact_{agent}",
    )
    available_dates = _available_status_dates(open_all)
    status_date = date_col.selectbox(
        "Status Date",
        ["All Dates", *available_dates],
        key=f"kanban_status_date_compact_{agent}",
    )
    card_limit = limit_col.selectbox(
        "Cards",
        [10, 15, 25, 40],
        index=1,
        key=f"kanban_limit_compact_{agent}",
    )

    board_cases = _filter_status_date(open_all, status_date)
    if portal != "All Portals":
        board_cases = board_cases[board_cases["Portal"].astype(str).eq(portal)].copy()
    if query.strip():
        needle = query.strip().casefold()
        searchable = pd.Series(False, index=board_cases.index)
        for column in ["AWB", "Customer Name", "Mobile", "Courier Remarks"]:
            if column in board_cases.columns:
                searchable |= (
                    board_cases[column]
                    .fillna("")
                    .astype(str)
                    .str.casefold()
                    .str.contains(needle, regex=False)
                )
        board_cases = board_cases[searchable].copy()

    board_cases = _sort_latest(board_cases)
    board_cases["_kanban_stage"] = _stage_series(board_cases)

    with st.container(key="logistics_kanban_board"):
        stage_columns = st.columns(len(BOARD_STAGES), gap="small")
        for stage, column in zip(BOARD_STAGES, stage_columns):
            stage_cases = board_cases[board_cases["_kanban_stage"].eq(stage)].copy()
            stage_key = stage.lower().replace(" ", "_").replace("-", "_")
            with column:
                st.markdown(f"**{stage}** · `{len(stage_cases)}`")
                with st.container(
                    height=620,
                    border=True,
                    key=f"kanban_column_{stage_key}",
                ):
                    if stage_cases.empty:
                        st.caption("No orders")
                    else:
                        for _, row in stage_cases.head(card_limit).iterrows():
                            _render_compact_card(agent, row, stage)
                        hidden = len(stage_cases) - min(len(stage_cases), card_limit)
                        if hidden > 0:
                            st.caption(f"+{hidden} more — increase Cards or filter")

    if drawer_open:
        with st.container(key="logistics_order_drawer"):
            _render_drawer(agent, assigned_all, activity)
