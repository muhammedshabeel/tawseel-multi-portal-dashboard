from __future__ import annotations

from datetime import date
from html import escape
from typing import Any

import pandas as pd
import streamlit as st

from src.logistics import add_activity, close_case
from src.logistics_dashboard_metrics import logistics_case_masks
from src.logistics_integrations import normalize_phone, phone_display
from src.logistics_kanban_workspace import (
    BOARD_STAGES,
    WORK_STATUS_OPTIONS,
    _available_status_dates,
    _filter_status_date,
    _selected_key,
    _sort_latest,
    _stage_series,
    _text,
)
from src.logistics_links import doubletick_chat_link, threecx_webclient_url


STAGE_META = {
    "New": {"icon": "🆕", "accent": "#3b82f6", "hint": "Not started"},
    "In Progress": {"icon": "⚙️", "accent": "#f59e0b", "hint": "Being handled"},
    "Follow-up": {"icon": "⏰", "accent": "#8b5cf6", "hint": "Needs follow-up"},
    "RTO": {"icon": "↩️", "accent": "#ef4444", "hint": "Return recovery"},
    "Delivered Review": {"icon": "✅", "accent": "#10b981", "hint": "Confirm recovery"},
}


def _slug(value: str) -> str:
    return "".join(
        character.lower() if character.isalnum() else "_" for character in value
    ).strip("_")


def _error_text(exc: Exception) -> str:
    text = str(exc).strip()
    return f"{type(exc).__name__}: {text}" if text else type(exc).__name__


def _inject_compact_styles(drawer_open: bool) -> None:
    drawer_css = """
    .st-key-logistics_order_drawer {
        position: fixed;
        top: 4.65rem;
        right: 0.7rem;
        width: min(420px, calc(100vw - 1.4rem));
        max-height: calc(100vh - 5.35rem);
        overflow-y: auto;
        overscroll-behavior: contain;
        z-index: 9999;
        padding: 0.45rem;
        border: 1px solid rgba(100, 116, 139, 0.25);
        border-radius: 18px;
        background: var(--background-color, #ffffff);
        box-shadow: 0 26px 80px rgba(15, 23, 42, 0.32);
        scrollbar-width: thin;
    }
    .st-key-logistics_order_drawer [data-testid="stVerticalBlockBorderWrapper"] {
        border: 0 !important;
        padding: 0 !important;
    }
    [class*="st-key-drawer_header_"] {
        position: sticky;
        top: -0.45rem;
        z-index: 20;
        margin: -0.45rem -0.45rem 0.55rem -0.45rem;
        padding: 0.65rem 0.65rem 0.55rem 0.65rem;
        background: var(--background-color, #ffffff);
        border-bottom: 1px solid rgba(100, 116, 139, 0.15);
        border-radius: 18px 18px 0 0;
    }
    [class*="st-key-drawer_close_"] button {
        min-height: 2rem !important;
        padding: 0.16rem 0.5rem !important;
        border-radius: 9px !important;
        font-size: 0.76rem !important;
        font-weight: 700 !important;
    }
    .lk-drawer-kicker {
        color: #64748b;
        font-size: 0.69rem;
        font-weight: 700;
        text-transform: uppercase;
        letter-spacing: 0.055em;
    }
    .lk-drawer-title {
        margin-top: 0.1rem;
        color: #0f172a;
        font-size: 1.08rem;
        line-height: 1.12;
        font-weight: 790;
        letter-spacing: -0.025em;
        overflow-wrap: anywhere;
    }
    .lk-drawer-awb {
        margin-top: 0.15rem;
        color: #64748b;
        font-size: 0.72rem;
        font-weight: 620;
    }
    .lk-order-summary {
        display: grid;
        grid-template-columns: 1fr 1fr;
        gap: 0.45rem;
        margin: 0 0 0.65rem 0;
    }
    .lk-summary-item {
        min-width: 0;
        padding: 0.52rem 0.58rem;
        border: 1px solid rgba(100, 116, 139, 0.12);
        border-radius: 10px;
        background: rgba(148, 163, 184, 0.055);
    }
    .lk-summary-label {
        color: #64748b;
        font-size: 0.65rem;
        font-weight: 700;
        text-transform: uppercase;
        letter-spacing: 0.045em;
    }
    .lk-summary-value {
        margin-top: 0.15rem;
        color: #0f172a;
        font-size: 0.78rem;
        line-height: 1.22;
        font-weight: 690;
        overflow-wrap: anywhere;
    }
    .lk-issue-box {
        margin: 0 0 0.6rem 0;
        padding: 0.55rem 0.62rem;
        border-radius: 10px;
        background: rgba(245, 158, 11, 0.075);
        color: #78350f;
        font-size: 0.75rem;
        line-height: 1.3;
    }
    .st-key-logistics_order_drawer [data-testid="stTabs"] button {
        min-height: 2.2rem !important;
        padding: 0.3rem 0.55rem !important;
        font-size: 0.77rem !important;
        font-weight: 680 !important;
    }
    .st-key-logistics_order_drawer [data-testid="stForm"] {
        border: 0 !important;
        padding: 0.15rem 0 0 0 !important;
    }
    .st-key-logistics_order_drawer label {
        font-size: 0.73rem !important;
        font-weight: 650 !important;
    }
    .st-key-logistics_order_drawer textarea {
        min-height: 72px !important;
    }
    """ if drawer_open else ""

    st.markdown(
        f"""
        <style>
        .st-key-logistics_kanban_board {{
            width: 100%;
            margin-top: 0.45rem;
        }}
        [class*="st-key-kanban_filters_"] {{
            margin: 0.2rem 0 0.75rem 0;
            padding: 0.65rem 0.75rem 0.08rem 0.75rem;
            border: 1px solid rgba(100, 116, 139, 0.16);
            border-radius: 13px;
            background: rgba(148, 163, 184, 0.05);
        }}
        [class*="st-key-kanban_filters_"] label {{
            font-size: 0.73rem !important;
            font-weight: 650 !important;
        }}
        .lk-workspace-head {{
            margin: 0.1rem 0 0.65rem 0;
        }}
        .lk-workspace-title {{
            margin: 0;
            font-size: 1.5rem;
            font-weight: 780;
            letter-spacing: -0.03em;
        }}
        .lk-workspace-subtitle {{
            margin-top: 0.12rem;
            color: #64748b;
            font-size: 0.8rem;
        }}
        .lk-metric-card {{
            position: relative;
            overflow: hidden;
            min-height: 82px;
            padding: 0.7rem 0.82rem;
            border: 1px solid rgba(100, 116, 139, 0.14);
            border-radius: 13px;
            background: linear-gradient(145deg, rgba(255,255,255,0.86), rgba(148,163,184,0.05));
            box-shadow: 0 4px 14px rgba(15, 23, 42, 0.04);
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
            font-size: 0.7rem;
            font-weight: 680;
            text-transform: uppercase;
            letter-spacing: 0.035em;
        }}
        .lk-metric-value {{
            margin-top: 0.18rem;
            font-size: 1.6rem;
            line-height: 1;
            font-weight: 790;
            letter-spacing: -0.04em;
            color: #0f172a;
        }}
        .lk-secondary-strip {{
            display: grid;
            grid-template-columns: repeat(4, minmax(0, 1fr));
            gap: 0.42rem;
            margin: 0.5rem 0 0.68rem 0;
        }}
        .lk-secondary-item {{
            display: flex;
            align-items: center;
            justify-content: space-between;
            gap: 0.45rem;
            padding: 0.43rem 0.58rem;
            border-radius: 9px;
            background: rgba(148, 163, 184, 0.065);
            border: 1px solid rgba(100, 116, 139, 0.09);
            font-size: 0.72rem;
            color: #475569;
        }}
        .lk-secondary-item strong {{
            color: #0f172a;
            font-size: 0.84rem;
        }}
        .lk-stage-header {{
            display: flex;
            align-items: center;
            justify-content: space-between;
            gap: 0.4rem;
            padding: 0.08rem 0.12rem 0.42rem 0.12rem;
        }}
        .lk-stage-title {{
            display: flex;
            align-items: center;
            gap: 0.32rem;
            min-width: 0;
            font-weight: 760;
            font-size: 0.86rem;
            white-space: nowrap;
        }}
        .lk-stage-count {{
            display: inline-flex;
            align-items: center;
            justify-content: center;
            min-width: 1.62rem;
            height: 1.35rem;
            padding: 0 0.38rem;
            border-radius: 999px;
            color: white;
            background: var(--stage-accent);
            font-size: 0.68rem;
            font-weight: 760;
        }}
        [class*="st-key-kanban_column_"] {{
            border: 1px solid rgba(100, 116, 139, 0.13);
            border-top: 3px solid var(--stage-accent, #64748b);
            border-radius: 13px;
            background: rgba(148, 163, 184, 0.032);
            box-shadow: 0 3px 12px rgba(15, 23, 42, 0.03);
        }}
        .st-key-kanban_column_new {{ --stage-accent: #3b82f6; background: rgba(59, 130, 246, 0.03); }}
        .st-key-kanban_column_in_progress {{ --stage-accent: #f59e0b; background: rgba(245, 158, 11, 0.03); }}
        .st-key-kanban_column_follow_up {{ --stage-accent: #8b5cf6; background: rgba(139, 92, 246, 0.03); }}
        .st-key-kanban_column_rto {{ --stage-accent: #ef4444; background: rgba(239, 68, 68, 0.03); }}
        .st-key-kanban_column_delivered_review {{ --stage-accent: #10b981; background: rgba(16, 185, 129, 0.03); }}
        [class*="st-key-kanban_column_"] > div {{
            padding: 0.42rem !important;
        }}
        [class*="st-key-kanban_card_"] {{
            margin-bottom: 0.4rem;
            border: 1px solid rgba(100, 116, 139, 0.15);
            border-radius: 11px;
            background: var(--background-color, #ffffff);
            box-shadow: 0 2px 9px rgba(15, 23, 42, 0.045);
            transition: transform 0.15s ease, box-shadow 0.15s ease, border-color 0.15s ease;
        }}
        [class*="st-key-kanban_card_"]:hover {{
            transform: translateY(-1px);
            border-color: rgba(15, 118, 110, 0.38);
            box-shadow: 0 7px 18px rgba(15, 23, 42, 0.085);
        }}
        [class*="st-key-kanban_card_selected_"] {{
            border-color: #0f766e !important;
            box-shadow: 0 0 0 2px rgba(15, 118, 110, 0.12), 0 7px 19px rgba(15, 23, 42, 0.10) !important;
        }}
        [class*="st-key-kanban_card_"] > div {{
            padding: 0.5rem 0.55rem 0.46rem 0.55rem !important;
        }}
        .lk-card-top {{
            display: flex;
            align-items: center;
            justify-content: space-between;
            gap: 0.3rem;
            margin-bottom: 0.3rem;
        }}
        .lk-badge {{
            display: inline-flex;
            align-items: center;
            max-width: 76%;
            padding: 0.12rem 0.34rem;
            border-radius: 999px;
            background: rgba(148, 163, 184, 0.11);
            color: #475569;
            font-size: 0.62rem;
            font-weight: 740;
            white-space: nowrap;
            overflow: hidden;
            text-overflow: ellipsis;
        }}
        .lk-call-chip {{
            color: #64748b;
            font-size: 0.63rem;
            font-weight: 650;
            white-space: nowrap;
        }}
        .lk-customer {{
            color: #0f172a;
            font-size: 0.86rem;
            line-height: 1.15;
            font-weight: 770;
            letter-spacing: -0.012em;
            overflow-wrap: anywhere;
        }}
        .lk-awb {{
            margin-top: 0.17rem;
            color: #334155;
            font-size: 0.66rem;
            font-weight: 650;
            white-space: nowrap;
            overflow: hidden;
            text-overflow: ellipsis;
        }}
        .lk-card-sub {{
            margin-top: 0.2rem;
            color: #64748b;
            font-size: 0.63rem;
            line-height: 1.18;
            white-space: nowrap;
            overflow: hidden;
            text-overflow: ellipsis;
        }}
        .lk-follow-chip {{
            margin-top: 0.28rem;
            padding: 0.2rem 0.3rem;
            border-radius: 6px;
            background: rgba(139, 92, 246, 0.07);
            color: #6d28d9;
            font-size: 0.61rem;
            font-weight: 650;
            white-space: nowrap;
            overflow: hidden;
            text-overflow: ellipsis;
        }}
        [class*="st-key-kanban_card_"] .stButton {{
            margin-top: 0.34rem !important;
        }}
        [class*="st-key-kanban_card_"] .stButton button {{
            min-height: 1.65rem !important;
            padding: 0.08rem 0.35rem !important;
            border-radius: 7px !important;
            font-size: 0.67rem !important;
            font-weight: 690 !important;
        }}
        .lk-empty-column {{
            display: flex;
            min-height: 78px;
            align-items: center;
            justify-content: center;
            text-align: center;
            color: #94a3b8;
            font-size: 0.7rem;
        }}
        .lk-more-count {{
            padding: 0.32rem;
            text-align: center;
            color: #64748b;
            font-size: 0.65rem;
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
    customer = _compact_text(row.get("Customer Name"), 25) or "Unknown customer"
    awb = _text(row.get("AWB")) or "No AWB"
    portal = _compact_text(row.get("Portal"), 16) or "Unknown portal"
    calls = pd.to_numeric(row.get("Total Call Attempts", 0), errors="coerce")
    calls = 0 if pd.isna(calls) else int(calls)
    next_follow_up = _text(row.get("Next Follow-up"))
    selected = _text(st.session_state.get(_selected_key(agent), "")) == case_id
    card_prefix = "kanban_card_selected" if selected else "kanban_card"

    with st.container(border=False, key=f"{card_prefix}_{_slug(agent)}_{case_id}"):
        follow_html = ""
        if next_follow_up:
            follow_html = (
                f'<div class="lk-follow-chip">Next: {escape(_compact_text(next_follow_up, 22))}</div>'
            )
        st.markdown(
            f"""
            <div class="lk-card-top">
                <span class="lk-badge">{escape(_priority_badge(row, stage))}</span>
                <span class="lk-call-chip">☎ {calls}</span>
            </div>
            <div class="lk-customer">{escape(customer)}</div>
            <div class="lk-awb">AWB {escape(awb)}</div>
            <div class="lk-card-sub">{escape(portal)}</div>
            {follow_html}
            """,
            unsafe_allow_html=True,
        )
        if st.button(
            "Open →",
            key=f"kanban_open_compact_{agent}_{case_id}",
            width="stretch",
        ):
            st.session_state[_selected_key(agent)] = case_id
            st.rerun()


def _follow_up_due_mask(cases: pd.DataFrame) -> pd.Series:
    if cases.empty or "Next Follow-up" not in cases.columns:
        return pd.Series(False, index=cases.index, dtype=bool)
    follow_up = pd.to_datetime(
        cases["Next Follow-up"], errors="coerce", format="mixed"
    )
    return follow_up.dt.date.le(date.today()).fillna(False)


def _render_quick_update(agent: str, selected: pd.Series) -> None:
    case_id = _text(selected.get("Case ID"))
    current_status = _text(selected.get("Logistics Work Status")).upper()
    status_index = (
        WORK_STATUS_OPTIONS.index(current_status)
        if current_status in WORK_STATUS_OPTIONS
        else 0
    )

    with st.form(f"drawer_update_{agent}_{case_id}", clear_on_submit=True):
        action_col, status_col = st.columns(2, gap="small")
        action = action_col.selectbox(
            "Action",
            ["CALL", "WHATSAPP", "COURIER_COORDINATION", "NOTE", "ESCALATION"],
        )
        work_status = status_col.selectbox(
            "Work status",
            WORK_STATUS_OPTIONS,
            index=status_index,
        )

        result_col, response_col = st.columns(2, gap="small")
        call_result = result_col.selectbox(
            "Call result",
            [
                "",
                "Answered",
                "No Answer",
                "Switched Off",
                "Busy",
                "Invalid Number",
                "Call Back Later",
            ],
        )
        customer_response = response_col.selectbox(
            "Customer response",
            [
                "",
                "Will Receive",
                "Requested Reschedule",
                "Customer Unavailable",
                "Location Changed",
                "Payment Issue",
                "Not Interested",
                "Order Cancelled",
                "Already Delivered",
                "Other",
            ],
        )

        follow_col, time_col = st.columns(2, gap="small")
        follow_date = follow_col.date_input(
            "Next date",
            value=None,
            key=f"drawer_follow_date_{agent}_{case_id}",
        )
        follow_time = time_col.time_input(
            "Next time",
            value=None,
            key=f"drawer_follow_time_{agent}_{case_id}",
        )
        remark = st.text_area(
            "Remark",
            height=72,
            placeholder="Add a short update...",
        )
        save = st.form_submit_button(
            "Save update",
            type="primary",
            width="stretch",
        )

    if save:
        follow_up = ""
        if follow_date:
            follow_up = str(follow_date)
            if follow_time:
                follow_up += f" {follow_time.strftime('%H:%M')}"
        try:
            add_activity(
                case_id,
                action_type=action,
                call_result=call_result,
                customer_response=customer_response,
                remark=remark,
                next_follow_up=follow_up,
                new_status=work_status,
            )
            st.success("Order updated.")
            st.rerun()
        except Exception as exc:
            st.error(f"Could not save update — {_error_text(exc)}")


def _render_compact_history(selected_id: str, activity: pd.DataFrame) -> None:
    case_history = activity[
        activity.get("Case ID", pd.Series("", index=activity.index))
        .astype(str)
        .eq(selected_id)
    ].copy()
    if case_history.empty:
        st.info("No activity has been logged yet.")
        return

    if "Action At" in case_history.columns:
        case_history = case_history.sort_values("Action At", ascending=False)
    columns = [
        "Action At",
        "Action Type",
        "Call Result",
        "Customer Response",
        "Remark",
        "Next Follow-up",
        "New Status",
    ]
    available = [column for column in columns if column in case_history.columns]
    st.dataframe(
        case_history[available].head(20),
        width="stretch",
        hide_index=True,
        height=310,
    )


def _render_quick_close(agent: str, selected: pd.Series) -> None:
    case_id = _text(selected.get("Case ID"))
    st.caption("Close only after confirming the final result.")
    with st.form(f"drawer_close_{agent}_{case_id}"):
        outcome = st.selectbox(
            "Final outcome",
            [
                "Delivered After Logistics Follow-up",
                "Delivered - No Recovery Credit",
                "Rescheduled",
                "Customer Cancelled",
                "Confirmed RTO",
                "Back to Store",
                "Invalid Customer",
                "Duplicate",
                "Unresolved",
                "Escalated",
            ],
        )
        recovered = st.checkbox("Delivered after logistics coordination")
        delivered_date = st.date_input(
            "Delivered date",
            value=None,
            key=f"drawer_delivered_date_{agent}_{case_id}",
        )
        closing_remark = st.text_area(
            "Closure remark",
            height=72,
            placeholder="Reason or final coordination result...",
        )
        close_clicked = st.form_submit_button(
            "Close case",
            width="stretch",
        )

    if close_clicked:
        try:
            close_case(
                case_id,
                outcome=outcome,
                delivered_after_coordination=recovered,
                delivered_date=str(delivered_date or ""),
                remark=closing_remark,
            )
            st.session_state.pop(_selected_key(agent), None)
            st.success("Case closed.")
            st.rerun()
        except Exception as exc:
            st.error(f"Could not close case — {_error_text(exc)}")


def _render_fast_drawer(
    agent: str,
    assigned_all: pd.DataFrame,
    activity: pd.DataFrame,
) -> None:
    selected_id = _text(st.session_state.get(_selected_key(agent), ""))
    if not selected_id:
        return

    match = assigned_all[assigned_all["Case ID"].astype(str).eq(selected_id)]
    if match.empty:
        st.session_state.pop(_selected_key(agent), None)
        st.warning("The selected order is no longer assigned to this workspace.")
        return

    selected = match.iloc[0]
    customer = _text(selected.get("Customer Name")) or "Unknown customer"
    awb = _text(selected.get("AWB")) or "Unavailable"
    valid_phone = normalize_phone(selected.get("Mobile", ""))
    selected_masks = logistics_case_masks(match)

    with st.container(key=f"drawer_header_{_slug(agent)}"):
        title_col, close_col = st.columns([4.4, 1.25], gap="small")
        title_col.markdown(
            f"""
            <div class="lk-drawer-kicker">Order workspace</div>
            <div class="lk-drawer-title">{escape(customer)}</div>
            <div class="lk-drawer-awb">AWB {escape(awb)}</div>
            """,
            unsafe_allow_html=True,
        )
        with close_col:
            if st.button(
                "✕ Close",
                key=f"drawer_close_panel_{agent}",
                width="stretch",
            ):
                st.session_state.pop(_selected_key(agent), None)
                st.rerun()

    courier_status = _text(selected.get("Latest Courier Status")) or "Unavailable"
    work_status = _text(selected.get("Logistics Work Status")) or "NEW"
    portal = _text(selected.get("Portal")) or "Unavailable"
    mobile = phone_display(selected.get("Mobile", ""))
    issue = _text(selected.get("Courier Remarks")) or "No courier remark"

    st.markdown(
        f"""
        <div class="lk-order-summary">
            <div class="lk-summary-item"><div class="lk-summary-label">Courier</div><div class="lk-summary-value">{escape(courier_status)}</div></div>
            <div class="lk-summary-item"><div class="lk-summary-label">Work status</div><div class="lk-summary-value">{escape(work_status)}</div></div>
            <div class="lk-summary-item"><div class="lk-summary-label">Portal</div><div class="lk-summary-value">{escape(portal)}</div></div>
            <div class="lk-summary-item"><div class="lk-summary-label">Mobile</div><div class="lk-summary-value">{escape(mobile)}</div></div>
        </div>
        <div class="lk-issue-box"><strong>Issue:</strong> {escape(issue)}</div>
        """,
        unsafe_allow_html=True,
    )

    if bool(selected_masks["pending_review"].iloc[0]):
        st.info("Delivered by Tawseel. Confirm recovery credit, then close the case.")

    action_left, action_right = st.columns(2, gap="small")
    if valid_phone:
        action_left.link_button(
            "📞 3CX",
            threecx_webclient_url(),
            width="stretch",
        )
        action_right.link_button(
            "💬 DoubleTick",
            doubletick_chat_link(valid_phone),
            width="stretch",
        )
    else:
        action_left.button("📞 3CX", disabled=True, width="stretch")
        action_right.button("💬 DoubleTick", disabled=True, width="stretch")
        st.warning("No valid mobile number is available for this order.")

    update_tab, history_tab, close_tab = st.tabs(["Update", "History", "Close"])
    with update_tab:
        _render_quick_update(agent, selected)
    with history_tab:
        _render_compact_history(selected_id, activity)
    with close_tab:
        _render_quick_close(agent, selected)


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
            <div class="lk-workspace-title">{escape(agent.title())} Workspace</div>
            <div class="lk-workspace-subtitle">Prioritised recovery queue · latest Tawseel updates first</div>
        </div>
        """,
        unsafe_allow_html=True,
    )

    primary = st.columns(4, gap="small")
    _metric_card(primary[0], label="Assigned", value=len(assigned_all), accent="#3b82f6")
    _metric_card(
        primary[1], label="Active", value=int(masks["active"].sum()), accent="#f59e0b"
    )
    _metric_card(
        primary[2], label="RTO", value=int(masks["current_rto"].sum()), accent="#ef4444"
    )
    _metric_card(
        primary[3], label="Recovered", value=int(masks["recovered"].sum()), accent="#10b981"
    )

    total_calls = int(
        pd.to_numeric(
            assigned_all.get("Total Call Attempts", pd.Series(dtype=float)),
            errors="coerce",
        )
        .fillna(0)
        .sum()
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
        portals = sorted(
            value for value in open_all["Portal"].astype(str).unique() if value
        )
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
        board_cases = board_cases[
            board_cases["Portal"].astype(str).eq(portal)
        ].copy()
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
            board_cases.get(
                "Total Call Attempts", pd.Series(0, index=board_cases.index)
            ),
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
            stage_cases = board_cases[
                board_cases["_kanban_stage"].eq(stage)
            ].copy()
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
                    height=540,
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
            _render_fast_drawer(agent, assigned_all, activity)
