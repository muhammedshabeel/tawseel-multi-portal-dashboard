from __future__ import annotations

from datetime import date
from html import escape
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


STAGE_META = {
    "New": {"icon": "🆕", "accent": "#3b82f6", "hint": "Not started"},
    "In Progress": {"icon": "⚙️", "accent": "#f59e0b", "hint": "Being handled"},
    "Follow-up": {"icon": "⏰", "accent": "#8b5cf6", "hint": "Needs follow-up"},
    "RTO": {"icon": "↩️", "accent": "#ef4444", "hint": "Return recovery"},
    "Delivered Review": {"icon": "✅", "accent": "#10b981", "hint": "Confirm recovery"},
}


def _slug(value: str) -> str:
    return "".join(character.lower() if character.isalnum() else "_" for character in value).strip("_")


def _inject_compact_styles(drawer_open: bool) -> None:
    drawer_css = """
    .st-key-logistics_order_drawer {
        position: fixed;
        top: 4.9rem;
        right: 0.9rem;
        width: min(440px, calc(100vw - 1.8rem));
        max-height: calc(100vh - 5.8rem);
        overflow-y: auto;
        z-index: 9999;
        padding: 0.55rem;
        border: 1px solid rgba(100, 116, 139, 0.28);
        border-radius: 18px;
        background: var(--background-color, #ffffff);
        box-shadow: 0 24px 70px rgba(15, 23, 42, 0.30);
        backdrop-filter: blur(14px);
    }
    .st-key-logistics_order_drawer [data-testid="stVerticalBlockBorderWrapper"] {
        border: 0 !important;
        padding: 0 !important;
    }
    .st-key-logistics_order_drawer h3,
    .st-key-logistics_order_drawer h4 {
        letter-spacing: -0.02em;
    }
    """ if drawer_open else ""

    st.markdown(
        f"""
        <style>
        .st-key-logistics_kanban_board {{
            width: 100%;
            margin-top: 0.55rem;
        }}

        [class*="st-key-kanban_filters_"] {{
            margin: 0.25rem 0 0.85rem 0;
            padding: 0.7rem 0.8rem 0.15rem 0.8rem;
            border: 1px solid rgba(100, 116, 139, 0.18);
            border-radius: 14px;
            background: rgba(148, 163, 184, 0.055);
        }}
        [class*="st-key-kanban_filters_"] label {{
            font-size: 0.76rem !important;
            font-weight: 650 !important;
            color: rgba(71, 85, 105, 0.95) !important;
        }}

        .lk-workspace-head {{
            display: flex;
            align-items: flex-end;
            justify-content: space-between;
            gap: 1rem;
            margin: 0.15rem 0 0.8rem 0;
        }}
        .lk-workspace-title {{
            margin: 0;
            font-size: 1.55rem;
            font-weight: 760;
            letter-spacing: -0.03em;
        }}
        .lk-workspace-subtitle {{
            margin-top: 0.15rem;
            color: #64748b;
            font-size: 0.84rem;
        }}

        .lk-metric-card {{
            position: relative;
            overflow: hidden;
            min-height: 88px;
            padding: 0.78rem 0.9rem;
            border: 1px solid rgba(100, 116, 139, 0.16);
            border-radius: 14px;
            background: linear-gradient(145deg, rgba(255,255,255,0.85), rgba(148,163,184,0.055));
            box-shadow: 0 5px 18px rgba(15, 23, 42, 0.045);
        }}
        .lk-metric-card::before {{
            content: "";
            position: absolute;
            inset: 0 auto 0 0;
            width: 4px;
            background: var(--lk-accent);
        }}
        .lk-metric-label {{
            color: #64748b;
            font-size: 0.76rem;
            font-weight: 650;
            text-transform: uppercase;
            letter-spacing: 0.035em;
        }}
        .lk-metric-value {{
            margin-top: 0.2rem;
            font-size: 1.72rem;
            line-height: 1;
            font-weight: 780;
            letter-spacing: -0.04em;
            color: #0f172a;
        }}
        .lk-secondary-strip {{
            display: grid;
            grid-template-columns: repeat(4, minmax(0, 1fr));
            gap: 0.45rem;
            margin: 0.55rem 0 0.75rem 0;
        }}
        .lk-secondary-item {{
            display: flex;
            align-items: center;
            justify-content: space-between;
            gap: 0.5rem;
            padding: 0.48rem 0.65rem;
            border-radius: 10px;
            background: rgba(148, 163, 184, 0.075);
            border: 1px solid rgba(100, 116, 139, 0.10);
            font-size: 0.78rem;
            color: #475569;
        }}
        .lk-secondary-item strong {{
            color: #0f172a;
            font-size: 0.92rem;
        }}

        .lk-stage-header {{
            display: flex;
            align-items: center;
            justify-content: space-between;
            gap: 0.45rem;
            padding: 0.12rem 0.16rem 0.5rem 0.16rem;
        }}
        .lk-stage-title {{
            display: flex;
            align-items: center;
            gap: 0.38rem;
            min-width: 0;
            font-weight: 750;
            font-size: 0.91rem;
            letter-spacing: -0.015em;
            white-space: nowrap;
        }}
        .lk-stage-count {{
            display: inline-flex;
            align-items: center;
            justify-content: center;
            min-width: 1.72rem;
            height: 1.45rem;
            padding: 0 0.42rem;
            border-radius: 999px;
            color: white;
            background: var(--stage-accent);
            font-size: 0.72rem;
            font-weight: 750;
        }}

        [class*="st-key-kanban_column_"] {{
            border: 1px solid rgba(100, 116, 139, 0.15);
            border-top: 3px solid var(--stage-accent, #64748b);
            border-radius: 14px;
            background: rgba(148, 163, 184, 0.038);
            box-shadow: 0 4px 16px rgba(15, 23, 42, 0.035);
        }}
        .st-key-kanban_column_new {{ --stage-accent: #3b82f6; background: rgba(59, 130, 246, 0.035); }}
        .st-key-kanban_column_in_progress {{ --stage-accent: #f59e0b; background: rgba(245, 158, 11, 0.035); }}
        .st-key-kanban_column_follow_up {{ --stage-accent: #8b5cf6; background: rgba(139, 92, 246, 0.035); }}
        .st-key-kanban_column_rto {{ --stage-accent: #ef4444; background: rgba(239, 68, 68, 0.035); }}
        .st-key-kanban_column_delivered_review {{ --stage-accent: #10b981; background: rgba(16, 185, 129, 0.035); }}
        [class*="st-key-kanban_column_"] > div {{
            padding: 0.5rem !important;
        }}

        [class*="st-key-kanban_card_"] {{
            margin-bottom: 0.48rem;
            border: 1px solid rgba(100, 116, 139, 0.17);
            border-radius: 12px;
            background: var(--background-color, #ffffff);
            box-shadow: 0 3px 12px rgba(15, 23, 42, 0.055);
            transition: transform 0.16s ease, box-shadow 0.16s ease, border-color 0.16s ease;
        }}
        [class*="st-key-kanban_card_"]:hover {{
            transform: translateY(-2px);
            border-color: rgba(15, 118, 110, 0.42);
            box-shadow: 0 9px 22px rgba(15, 23, 42, 0.10);
        }}
        [class*="st-key-kanban_card_selected_"] {{
            border-color: #0f766e !important;
            box-shadow: 0 0 0 2px rgba(15, 118, 110, 0.13), 0 9px 24px rgba(15, 23, 42, 0.11) !important;
        }}
        [class*="st-key-kanban_card_"] > div {{
            padding: 0.62rem 0.66rem 0.58rem 0.66rem !important;
        }}
        .lk-card-top {{
            display: flex;
            align-items: center;
            justify-content: space-between;
            gap: 0.35rem;
            margin-bottom: 0.42rem;
        }}
        .lk-badge {{
            display: inline-flex;
            align-items: center;
            max-width: 76%;
            padding: 0.16rem 0.42rem;
            border-radius: 999px;
            background: rgba(148, 163, 184, 0.12);
            color: #475569;
            font-size: 0.68rem;
            font-weight: 740;
            white-space: nowrap;
            overflow: hidden;
            text-overflow: ellipsis;
        }}
        .lk-call-chip {{
            color: #64748b;
            font-size: 0.68rem;
            font-weight: 650;
            white-space: nowrap;
        }}
        .lk-customer {{
            color: #0f172a;
            font-size: 0.92rem;
            line-height: 1.22;
            font-weight: 760;
            letter-spacing: -0.015em;
            overflow-wrap: anywhere;
        }}
        .lk-awb {{
            margin-top: 0.24rem;
            color: #334155;
            font-size: 0.72rem;
            font-weight: 650;
            white-space: nowrap;
            overflow: hidden;
            text-overflow: ellipsis;
        }}
        .lk-card-sub {{
            margin-top: 0.32rem;
            color: #64748b;
            font-size: 0.69rem;
            line-height: 1.22;
            overflow-wrap: anywhere;
        }}
        .lk-follow-chip {{
            margin-top: 0.42rem;
            padding: 0.26rem 0.38rem;
            border-radius: 7px;
            background: rgba(139, 92, 246, 0.075);
            color: #6d28d9;
            font-size: 0.67rem;
            font-weight: 650;
            white-space: nowrap;
            overflow: hidden;
            text-overflow: ellipsis;
        }}
        [class*="st-key-kanban_card_"] .stButton {{
            margin-top: 0.48rem !important;
        }}
        [class*="st-key-kanban_card_"] .stButton button {{
            min-height: 1.82rem !important;
            padding: 0.12rem 0.42rem !important;
            border-radius: 8px !important;
            font-size: 0.73rem !important;
            font-weight: 680 !important;
        }}

        .lk-empty-column {{
            display: flex;
            min-height: 88px;
            align-items: center;
            justify-content: center;
            text-align: center;
            color: #94a3b8;
            font-size: 0.76rem;
        }}
        .lk-more-count {{
            padding: 0.38rem;
            text-align: center;
            color: #64748b;
            font-size: 0.7rem;
            font-weight: 650;
        }}

        @media (max-width: 1100px) {{
            .lk-secondary-strip {{ grid-template-columns: repeat(2, minmax(0, 1fr)); }}
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


def _metric_card(column: Any, *, label: str, value: int, accent: str) -> None:
    column.markdown(
        f"""
        <div class="lk-metric-card" style="--lk-accent:{accent}">
            <div class="lk-metric-label">{escape(label)}</div>
            <div class="lk-metric-value">{int(value):,}</div>
        </div>
        """,
        unsafe_allow_html=True,
    )


def _render_compact_card(agent: str, row: pd.Series, stage: str) -> None:
    case_id = _text(row.get("Case ID"))
    customer = _compact_text(row.get("Customer Name"), 28) or "Unknown customer"
    awb = _text(row.get("AWB")) or "No AWB"
    portal = _compact_text(row.get("Portal"), 18) or "Unknown portal"
    work_status = _compact_text(row.get("Logistics Work Status"), 19) or "NEW"
    courier_status = _compact_text(row.get("Latest Courier Status"), 18)
    calls = pd.to_numeric(row.get("Total Call Attempts", 0), errors="coerce")
    calls = 0 if pd.isna(calls) else int(calls)
    next_follow_up = _text(row.get("Next Follow-up"))
    selected = _text(st.session_state.get(_selected_key(agent), "")) == case_id
    card_prefix = "kanban_card_selected" if selected else "kanban_card"

    with st.container(border=False, key=f"{card_prefix}_{_slug(agent)}_{case_id}"):
        follow_html = ""
        if next_follow_up:
            follow_html = (
                f'<div class="lk-follow-chip">Next: {escape(_compact_text(next_follow_up, 24))}</div>'
            )
        st.markdown(
            f"""
            <div class="lk-card-top">
                <span class="lk-badge">{escape(_priority_badge(row, stage))}</span>
                <span class="lk-call-chip">☎ {calls}</span>
            </div>
            <div class="lk-customer">{escape(customer)}</div>
            <div class="lk-awb">AWB {escape(awb)}</div>
            <div class="lk-card-sub">{escape(portal)} · {escape(work_status)}{(' · ' + escape(courier_status)) if courier_status else ''}</div>
            {follow_html}
            """,
            unsafe_allow_html=True,
        )
        if st.button(
            "Open details →",
            key=f"kanban_open_compact_{agent}_{case_id}",
            width="stretch",
        ):
            st.session_state[_selected_key(agent)] = case_id
            st.rerun()


def _follow_up_due_mask(cases: pd.DataFrame) -> pd.Series:
    if cases.empty or "Next Follow-up" not in cases.columns:
        return pd.Series(False, index=cases.index, dtype=bool)
    follow_up = pd.to_datetime(cases["Next Follow-up"], errors="coerce", format="mixed")
    return follow_up.dt.date.le(date.today()).fillna(False)


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

    st.markdown(
        f"""
        <div class="lk-workspace-head">
            <div>
                <div class="lk-workspace-title">{escape(agent.title())} Workspace</div>
                <div class="lk-workspace-subtitle">Prioritised recovery queue · latest Tawseel updates first</div>
            </div>
        </div>
        """,
        unsafe_allow_html=True,
    )

    primary = st.columns(4, gap="small")
    _metric_card(primary[0], label="Assigned", value=len(assigned_all), accent="#3b82f6")
    _metric_card(primary[1], label="Active", value=int(masks["active"].sum()), accent="#f59e0b")
    _metric_card(primary[2], label="RTO", value=int(masks["current_rto"].sum()), accent="#ef4444")
    _metric_card(primary[3], label="Recovered", value=int(masks["recovered"].sum()), accent="#10b981")

    total_calls = int(
        pd.to_numeric(
            assigned_all.get("Total Call Attempts", pd.Series(dtype=float)),
            errors="coerce",
        ).fillna(0).sum()
    )
    st.markdown(
        f"""
        <div class="lk-secondary-strip">
            <div class="lk-secondary-item"><span>Tawseel Delivered</span><strong>{int(masks['tawseel_delivered'].sum()):,}</strong></div>
            <div class="lk-secondary-item"><span>Pending Review</span><strong>{int(masks['pending_review'].sum()):,}</strong></div>
            <div class="lk-secondary-item"><span>Calls Logged</span><strong>{total_calls:,}</strong></div>
            <div class="lk-secondary-item"><span>Recovered from RTO</span><strong>{int(masks['rto_recovered'].sum()):,}</strong></div>
        </div>
        """,
        unsafe_allow_html=True,
    )

    if open_all.empty:
        st.info("No open cases assigned.")
        return

    with st.container(key=f"kanban_filters_{_slug(agent)}"):
        search_col, focus_col, portal_col, date_col, limit_col = st.columns(
            [2.3, 1.25, 1.1, 1.05, 0.72], gap="small"
        )
        query = search_col.text_input(
            "Search orders",
            placeholder="AWB, customer, mobile or remark",
            key=f"kanban_search_compact_{agent}",
        )
        focus = focus_col.selectbox(
            "Focus",
            ["All open", "Critical", "Uncontacted", "Follow-up due"],
            key=f"kanban_focus_compact_{agent}",
        )
        portals = sorted(value for value in open_all["Portal"].astype(str).unique() if value)
        portal = portal_col.selectbox(
            "Portal",
            ["All Portals", *portals],
            key=f"kanban_portal_compact_{agent}",
        )
        available_dates = _available_status_dates(open_all)
        status_date = date_col.selectbox(
            "Status date",
            ["All Dates", *available_dates],
            key=f"kanban_status_date_compact_{agent}",
        )
        card_limit = limit_col.selectbox(
            "Cards",
            [8, 12, 20, 30],
            index=1,
            key=f"kanban_limit_compact_{agent}",
        )

    board_cases = _filter_status_date(open_all, status_date)
    if portal != "All Portals":
        board_cases = board_cases[board_cases["Portal"].astype(str).eq(portal)].copy()
    if focus == "Critical":
        board_cases = board_cases[
            board_cases.get("Priority", pd.Series("", index=board_cases.index))
            .fillna("")
            .astype(str)
            .str.upper()
            .str.contains("CRITICAL", regex=False)
        ].copy()
    elif focus == "Uncontacted":
        attempts = pd.to_numeric(
            board_cases.get("Total Call Attempts", pd.Series(0, index=board_cases.index)),
            errors="coerce",
        ).fillna(0)
        board_cases = board_cases[attempts.eq(0)].copy()
    elif focus == "Follow-up due":
        board_cases = board_cases[_follow_up_due_mask(board_cases)].copy()

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
            stage_key = _slug(stage)
            meta = STAGE_META[stage]
            with column:
                st.markdown(
                    f"""
                    <div class="lk-stage-header" style="--stage-accent:{meta['accent']}">
                        <div class="lk-stage-title"><span>{meta['icon']}</span><span>{escape(stage)}</span></div>
                        <span class="lk-stage-count">{len(stage_cases)}</span>
                    </div>
                    """,
                    unsafe_allow_html=True,
                )
                with st.container(
                    height=560,
                    border=False,
                    key=f"kanban_column_{stage_key}",
                ):
                    if stage_cases.empty:
                        st.markdown(
                            f'<div class="lk-empty-column">No {escape(meta["hint"].lower())} orders</div>',
                            unsafe_allow_html=True,
                        )
                    else:
                        for _, row in stage_cases.head(card_limit).iterrows():
                            _render_compact_card(agent, row, stage)
                        hidden = len(stage_cases) - min(len(stage_cases), card_limit)
                        if hidden > 0:
                            st.markdown(
                                f'<div class="lk-more-count">+{hidden} more · increase Cards or use filters</div>',
                                unsafe_allow_html=True,
                            )

    if drawer_open:
        with st.container(key="logistics_order_drawer"):
            _render_drawer(agent, assigned_all, activity)
