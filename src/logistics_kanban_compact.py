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
    _sort_latest,
    _stage_series,
    _text,
)
from src.logistics_links import doubletick_chat_link, threecx_webclient_url


KANBAN_STAGES = (*BOARD_STAGES, "RTO Converted")

STAGE_META = {
    "New": {"icon": "🆕", "accent": "#3b82f6", "hint": "Not started"},
    "In Progress": {"icon": "⚙️", "accent": "#f59e0b", "hint": "Being handled"},
    "Follow-up": {"icon": "⏰", "accent": "#8b5cf6", "hint": "Needs follow-up"},
    "RTO": {"icon": "↩️", "accent": "#ef4444", "hint": "Return recovery"},
    "Delivered Review": {"icon": "✅", "accent": "#10b981", "hint": "Confirm recovery"},
    "RTO Converted": {"icon": "🏆", "accent": "#0f766e", "hint": "Converted RTO"},
}

RTO_WORK_STATUS_OPTIONS = [
    "IN PROGRESS",
    "FOLLOW-UP DUE",
    "CUSTOMER CONTACTED",
    "AWAITING COURIER",
    "ESCALATED",
    "UNRESOLVED",
]

STANDARD_RESPONSES = [
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
]

RTO_RESPONSES = [
    "",
    "Will Receive",
    "Customer Unavailable",
    "Location Changed",
    "Payment Issue",
    "Not Interested",
    "Order Cancelled",
    "Already Delivered",
]

EXPORT_COLUMNS = [
    "Portal",
    "AWB",
    "Customer Name",
    "Mobile",
    "Source Courier Status",
    "Latest Courier Status",
    "Courier Remarks",
    "Original Agent",
    "Logistics Agent",
    "Assigned At",
    "Total Call Attempts",
    "Last Call At",
    "Last Call Status",
    "Customer Response",
    "Agent Remark",
    "Logistics Final Outcome",
    "Delivered After Coordination",
    "Logistics Delivered Date",
    "Closed At",
    "Updated At",
]


def _slug(value: str) -> str:
    return "".join(
        character.lower() if character.isalnum() else "_" for character in value
    ).strip("_")


def _error_text(exc: Exception) -> str:
    text = str(exc).strip()
    return f"{type(exc).__name__}: {text}" if text else type(exc).__name__


def _inject_styles() -> None:
    st.markdown(
        """
        <style>
        /* Keep Streamlit's native outside-click and ESC dismissal, but display it as a right drawer. */
        div[data-testid="stModal"],
        div[data-testid="stDialog"] {
            align-items: stretch !important;
            justify-content: flex-end !important;
            padding: 0 !important;
        }
        div[data-testid="stModal"] div[role="dialog"],
        div[data-testid="stDialog"] div[role="dialog"],
        div[role="dialog"][aria-modal="true"] {
            position: fixed !important;
            top: 0 !important;
            right: 0 !important;
            bottom: 0 !important;
            left: auto !important;
            transform: none !important;
            width: min(430px, 100vw) !important;
            min-width: 0 !important;
            max-width: 430px !important;
            height: 100vh !important;
            min-height: 100vh !important;
            max-height: 100vh !important;
            margin: 0 !important;
            border-radius: 18px 0 0 18px !important;
            overflow: hidden !important;
            box-shadow: -24px 0 70px rgba(15, 23, 42, 0.30) !important;
            animation: lk-drawer-in 120ms ease-out !important;
        }
        @keyframes lk-drawer-in {
            from { transform: translateX(20px); opacity: 0.72; }
            to { transform: translateX(0); opacity: 1; }
        }
        div[data-testid="stModal"] div[role="dialog"] > div,
        div[data-testid="stDialog"] div[role="dialog"] > div,
        div[role="dialog"][aria-modal="true"] > div {
            height: 100% !important;
            max-height: 100% !important;
            overflow-y: auto !important;
            padding: 0.72rem 0.78rem 1rem 0.78rem !important;
            scrollbar-width: thin;
        }
        div[data-testid="stModal"] [data-testid="stDialogHeader"],
        div[data-testid="stDialog"] [data-testid="stDialogHeader"] {
            position: sticky !important;
            top: -0.72rem !important;
            z-index: 30 !important;
            margin: -0.72rem -0.78rem 0.5rem -0.78rem !important;
            padding: 0.62rem 0.78rem 0.5rem 0.78rem !important;
            background: var(--background-color, #ffffff) !important;
            border-bottom: 1px solid rgba(100, 116, 139, 0.14) !important;
        }
        div[data-testid="stModal"] h2,
        div[data-testid="stDialog"] h2 {
            font-size: 0.98rem !important;
            letter-spacing: -0.02em !important;
        }
        div[data-testid="stModal"] label,
        div[data-testid="stDialog"] label {
            font-size: 0.71rem !important;
            font-weight: 650 !important;
        }
        div[data-testid="stModal"] [data-testid="stForm"],
        div[data-testid="stDialog"] [data-testid="stForm"] {
            border: 0 !important;
            padding: 0.08rem 0 0 0 !important;
        }
        div[data-testid="stModal"] textarea,
        div[data-testid="stDialog"] textarea {
            min-height: 66px !important;
        }
        div[data-testid="stModal"] [data-testid="stExpander"],
        div[data-testid="stDialog"] [data-testid="stExpander"] {
            margin-top: 0.45rem !important;
            border-radius: 10px !important;
        }
        div[data-testid="stModal"] [data-testid="stExpander"] summary,
        div[data-testid="stDialog"] [data-testid="stExpander"] summary {
            min-height: 2.45rem !important;
            font-size: 0.76rem !important;
            font-weight: 700 !important;
        }
        .lk-rto-guidance {
            margin: 0.42rem 0 0.55rem 0;
            padding: 0.55rem 0.62rem;
            border: 1px solid rgba(239, 68, 68, 0.16);
            border-radius: 9px;
            background: rgba(239, 68, 68, 0.055);
            color: #991b1b;
            font-size: 0.72rem;
            line-height: 1.3;
        }
        .lk-drawer-title {
            color: #0f172a;
            font-size: 1.04rem;
            line-height: 1.15;
            font-weight: 790;
            letter-spacing: -0.025em;
            overflow-wrap: anywhere;
        }
        .lk-drawer-awb {
            margin-top: 0.1rem;
            color: #64748b;
            font-size: 0.7rem;
            font-weight: 620;
        }
        .lk-order-summary {
            display: grid;
            grid-template-columns: 1fr 1fr;
            gap: 0.38rem;
            margin: 0.48rem 0;
        }
        .lk-summary-item {
            min-width: 0;
            padding: 0.44rem 0.5rem;
            border: 1px solid rgba(100, 116, 139, 0.12);
            border-radius: 9px;
            background: rgba(148, 163, 184, 0.055);
        }
        .lk-summary-label {
            color: #64748b;
            font-size: 0.59rem;
            font-weight: 700;
            text-transform: uppercase;
            letter-spacing: 0.045em;
        }
        .lk-summary-value {
            margin-top: 0.1rem;
            color: #0f172a;
            font-size: 0.73rem;
            line-height: 1.18;
            font-weight: 690;
            overflow-wrap: anywhere;
        }
        .lk-issue-box {
            margin: 0 0 0.48rem 0;
            padding: 0.46rem 0.54rem;
            border-radius: 8px;
            background: rgba(245, 158, 11, 0.075);
            color: #78350f;
            font-size: 0.7rem;
            line-height: 1.25;
        }
        .lk-section-title {
            margin: 0.55rem 0 0.05rem 0;
            color: #0f172a;
            font-size: 0.86rem;
            font-weight: 760;
            letter-spacing: -0.015em;
        }
        .lk-section-help {
            margin-bottom: 0.25rem;
            color: #64748b;
            font-size: 0.67rem;
        }
        .lk-workspace-head { margin: 0.1rem 0 0.65rem 0; }
        .lk-workspace-title {
            font-size: 1.5rem;
            font-weight: 780;
            letter-spacing: -0.03em;
        }
        .lk-workspace-subtitle {
            margin-top: 0.12rem;
            color: #64748b;
            font-size: 0.8rem;
        }
        .lk-metric-card {
            position: relative;
            overflow: hidden;
            min-height: 82px;
            padding: 0.7rem 0.82rem;
            border: 1px solid rgba(100, 116, 139, 0.14);
            border-radius: 13px;
            background: linear-gradient(145deg, rgba(255,255,255,0.86), rgba(148,163,184,0.05));
            box-shadow: 0 4px 14px rgba(15, 23, 42, 0.04);
        }
        .lk-metric-card::before {
            content: "";
            position: absolute;
            inset: 0 auto 0 0;
            width: 4px;
            background: var(--lk-accent);
        }
        .lk-metric-label {
            color: #64748b;
            font-size: 0.7rem;
            font-weight: 680;
            text-transform: uppercase;
            letter-spacing: 0.035em;
        }
        .lk-metric-value {
            margin-top: 0.18rem;
            font-size: 1.6rem;
            line-height: 1;
            font-weight: 790;
            letter-spacing: -0.04em;
            color: #0f172a;
        }
        .lk-secondary-strip {
            display: grid;
            grid-template-columns: repeat(4, minmax(0, 1fr));
            gap: 0.42rem;
            margin: 0.5rem 0 0.68rem 0;
        }
        .lk-secondary-item {
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
        }
        .lk-secondary-item strong { color: #0f172a; font-size: 0.84rem; }
        [class*="st-key-kanban_filters_"] {
            margin: 0.2rem 0 0.75rem 0;
            padding: 0.65rem 0.75rem 0.08rem 0.75rem;
            border: 1px solid rgba(100, 116, 139, 0.16);
            border-radius: 13px;
            background: rgba(148, 163, 184, 0.05);
        }
        [class*="st-key-kanban_filters_"] label {
            font-size: 0.73rem !important;
            font-weight: 650 !important;
        }
        .lk-stage-header {
            display: flex;
            align-items: center;
            justify-content: space-between;
            gap: 0.4rem;
            padding: 0.08rem 0.12rem 0.42rem 0.12rem;
        }
        .lk-stage-title {
            display: flex;
            align-items: center;
            gap: 0.32rem;
            min-width: 0;
            font-weight: 760;
            font-size: 0.82rem;
            white-space: nowrap;
        }
        .lk-stage-count {
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
        }
        [class*="st-key-kanban_column_"] {
            border: 1px solid rgba(100, 116, 139, 0.13);
            border-top: 3px solid var(--stage-accent, #64748b);
            border-radius: 13px;
            background: rgba(148, 163, 184, 0.032);
            box-shadow: 0 3px 12px rgba(15, 23, 42, 0.03);
        }
        .st-key-kanban_column_new { --stage-accent: #3b82f6; background: rgba(59,130,246,.03); }
        .st-key-kanban_column_in_progress { --stage-accent: #f59e0b; background: rgba(245,158,11,.03); }
        .st-key-kanban_column_follow_up { --stage-accent: #8b5cf6; background: rgba(139,92,246,.03); }
        .st-key-kanban_column_rto { --stage-accent: #ef4444; background: rgba(239,68,68,.03); }
        .st-key-kanban_column_delivered_review { --stage-accent: #10b981; background: rgba(16,185,129,.03); }
        .st-key-kanban_column_rto_converted { --stage-accent: #0f766e; background: rgba(15,118,110,.035); }
        [class*="st-key-kanban_column_"] > div { padding: 0.42rem !important; }
        [class*="st-key-kanban_card_"] {
            margin-bottom: 0.4rem;
            border: 1px solid rgba(100, 116, 139, 0.15);
            border-radius: 11px;
            background: var(--background-color, #ffffff);
            box-shadow: 0 2px 9px rgba(15, 23, 42, 0.045);
            transition: transform .15s ease, box-shadow .15s ease, border-color .15s ease;
        }
        [class*="st-key-kanban_card_"]:hover {
            transform: translateY(-1px);
            border-color: rgba(15, 118, 110, 0.38);
            box-shadow: 0 7px 18px rgba(15, 23, 42, 0.085);
        }
        [class*="st-key-kanban_card_"] > div { padding: 0.5rem 0.55rem 0.46rem !important; }
        .lk-card-top {
            display: flex;
            align-items: center;
            justify-content: space-between;
            gap: 0.3rem;
            margin-bottom: 0.3rem;
        }
        .lk-badge {
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
        }
        .lk-call-chip {
            color: #64748b;
            font-size: 0.63rem;
            font-weight: 650;
            white-space: nowrap;
        }
        .lk-customer {
            color: #0f172a;
            font-size: 0.86rem;
            line-height: 1.15;
            font-weight: 770;
            overflow-wrap: anywhere;
        }
        .lk-awb {
            margin-top: 0.17rem;
            color: #334155;
            font-size: 0.66rem;
            font-weight: 650;
            white-space: nowrap;
            overflow: hidden;
            text-overflow: ellipsis;
        }
        .lk-card-sub {
            margin-top: 0.2rem;
            color: #64748b;
            font-size: 0.63rem;
            white-space: nowrap;
            overflow: hidden;
            text-overflow: ellipsis;
        }
        .lk-follow-chip {
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
        }
        [class*="st-key-kanban_card_"] .stButton { margin-top: 0.34rem !important; }
        [class*="st-key-kanban_card_"] .stButton button {
            min-height: 1.65rem !important;
            padding: 0.08rem 0.35rem !important;
            border-radius: 7px !important;
            font-size: 0.67rem !important;
            font-weight: 690 !important;
        }
        .lk-empty-column {
            display: flex;
            min-height: 78px;
            align-items: center;
            justify-content: center;
            text-align: center;
            color: #94a3b8;
            font-size: 0.7rem;
        }
        @media (max-width: 1100px) {
            .lk-secondary-strip { grid-template-columns: repeat(2, minmax(0, 1fr)); }
        }
        </style>
        """,
        unsafe_allow_html=True,
    )


def _priority_badge(row: pd.Series, stage: str) -> str:
    if stage == "RTO Converted":
        return "🏆 Converted"
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
    return text if len(text) <= limit else text[: max(0, limit - 1)].rstrip() + "…"


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


def _follow_up_due_mask(cases: pd.DataFrame) -> pd.Series:
    if cases.empty or "Next Follow-up" not in cases.columns:
        return pd.Series(False, index=cases.index, dtype=bool)
    follow_up = pd.to_datetime(cases["Next Follow-up"], errors="coerce", format="mixed")
    return follow_up.dt.date.le(date.today()).fillna(False)


def _rto_context(selected: pd.Series) -> tuple[bool, bool, bool]:
    frame = selected.to_frame().T
    masks = logistics_case_masks(frame)
    return (
        bool(masks["current_rto"].iloc[0]),
        bool(masks["rto_origin"].iloc[0]),
        bool(masks["tawseel_delivered"].iloc[0]),
    )


def _render_quick_update(agent: str, selected: pd.Series) -> None:
    case_id = _text(selected.get("Case ID"))
    current_status = _text(selected.get("Logistics Work Status")).upper()
    is_current_rto, _, _ = _rto_context(selected)
    status_options = RTO_WORK_STATUS_OPTIONS if is_current_rto else WORK_STATUS_OPTIONS
    response_options = RTO_RESPONSES if is_current_rto else STANDARD_RESPONSES
    status_index = status_options.index(current_status) if current_status in status_options else 0

    if is_current_rto:
        st.markdown(
            '<div class="lk-rto-guidance"><strong>RTO conversion workflow:</strong> continue customer and courier follow-up until Tawseel confirms delivery. Reschedule and generic “Other” outcomes are disabled for this case.</div>',
            unsafe_allow_html=True,
        )

    st.markdown(
        '<div class="lk-section-title">Update activity</div><div class="lk-section-help">Log the latest customer or courier coordination.</div>',
        unsafe_allow_html=True,
    )
    with st.form(f"drawer_update_{agent}_{case_id}", clear_on_submit=True):
        action_col, status_col = st.columns(2, gap="small")
        action = action_col.selectbox(
            "Action",
            ["CALL", "WHATSAPP", "COURIER_COORDINATION", "NOTE", "ESCALATION"],
        )
        work_status = status_col.selectbox(
            "Work status", status_options, index=status_index
        )
        result_col, response_col = st.columns(2, gap="small")
        call_result = result_col.selectbox(
            "Call result",
            ["", "Answered", "No Answer", "Switched Off", "Busy", "Invalid Number", "Call Back Later"],
        )
        customer_response = response_col.selectbox(
            "Customer response", response_options
        )
        follow_col, time_col = st.columns(2, gap="small")
        follow_date = follow_col.date_input(
            "Next date", value=None, key=f"drawer_follow_date_{agent}_{case_id}"
        )
        follow_time = time_col.time_input(
            "Next time", value=None, key=f"drawer_follow_time_{agent}_{case_id}"
        )
        remark = st.text_area("Remark", height=66, placeholder="Add a short update...")
        save = st.form_submit_button("Save activity", type="primary", width="stretch")

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
            st.toast("Activity saved", icon="✅")
            st.rerun()
        except Exception as exc:
            st.error(f"Could not save update — {_error_text(exc)}")


def _render_history(selected_id: str, activity: pd.DataFrame) -> None:
    case_history = activity[
        activity.get("Case ID", pd.Series("", index=activity.index)).astype(str).eq(selected_id)
    ].copy()
    if case_history.empty:
        st.info("No activity has been logged yet.")
        return
    if "Action At" in case_history.columns:
        case_history = case_history.sort_values("Action At", ascending=False)
    columns = ["Action At", "Action Type", "Call Result", "Customer Response", "Remark", "Next Follow-up", "New Status"]
    available = [column for column in columns if column in case_history.columns]
    st.dataframe(case_history[available].head(20), width="stretch", hide_index=True, height=300)


def _render_quick_close(agent: str, selected: pd.Series) -> None:
    case_id = _text(selected.get("Case ID"))
    is_current_rto, is_rto_origin, is_delivered = _rto_context(selected)

    if is_current_rto and not is_delivered:
        st.info(
            "This RTO case must remain open for recovery follow-up. Close and conversion credit become available only after Tawseel changes the order to Delivered."
        )
        return

    st.caption("Close only after confirming the final result.")
    if is_rto_origin:
        outcome_options = ["Delivered After Logistics Follow-up"]
        recovered_default = True
        recovered_disabled = True
    else:
        outcome_options = [
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
        ]
        recovered_default = False
        recovered_disabled = False

    with st.form(f"drawer_close_{agent}_{case_id}"):
        outcome = st.selectbox("Final outcome", outcome_options)
        recovered = st.checkbox(
            "Delivered after logistics coordination",
            value=recovered_default,
            disabled=recovered_disabled,
        )
        delivered_date = st.date_input(
            "Delivered date", value=None, key=f"drawer_delivered_date_{agent}_{case_id}"
        )
        closing_remark = st.text_area(
            "Closure remark", height=66, placeholder="Reason or final coordination result..."
        )
        close_clicked = st.form_submit_button("Confirm RTO conversion" if is_rto_origin else "Confirm and close case", width="stretch")

    if close_clicked:
        if is_rto_origin and not is_delivered:
            st.error("Tawseel must show Delivered before an RTO conversion can be confirmed.")
            return
        try:
            close_case(
                case_id,
                outcome=outcome,
                delivered_after_coordination=True if is_rto_origin else recovered,
                delivered_date=str(delivered_date or ""),
                remark=closing_remark,
            )
            st.toast("RTO converted" if is_rto_origin else "Case closed", icon="✅")
            st.rerun()
        except Exception as exc:
            st.error(f"Could not close case — {_error_text(exc)}")


@st.dialog("Order details", width="small")
def _order_drawer(
    agent: str,
    case_id: str,
    assigned_all: pd.DataFrame,
    activity: pd.DataFrame,
) -> None:
    match = assigned_all[assigned_all["Case ID"].astype(str).eq(case_id)]
    if match.empty:
        st.warning("This order is no longer assigned to this workspace.")
        return

    selected = match.iloc[0]
    customer = _text(selected.get("Customer Name")) or "Unknown customer"
    awb = _text(selected.get("AWB")) or "Unavailable"
    courier_status = _text(selected.get("Latest Courier Status")) or "Unavailable"
    work_status = _text(selected.get("Logistics Work Status")) or "NEW"
    portal = _text(selected.get("Portal")) or "Unavailable"
    mobile = phone_display(selected.get("Mobile", ""))
    issue = _text(selected.get("Courier Remarks")) or "No courier remark"
    valid_phone = normalize_phone(selected.get("Mobile", ""))
    selected_masks = logistics_case_masks(match)

    st.markdown(
        f'<div class="lk-drawer-title">{escape(customer)}</div><div class="lk-drawer-awb">AWB {escape(awb)}</div>',
        unsafe_allow_html=True,
    )
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

    if bool(selected_masks["rto_converted"].iloc[0]):
        st.success("This order was converted from RTO and delivered after logistics follow-up.")
    elif bool(selected_masks["pending_review"].iloc[0]):
        st.info("Delivered by Tawseel. Confirm recovery credit, then close the case.")

    left, right = st.columns(2, gap="small")
    if valid_phone:
        left.link_button("📞 3CX", threecx_webclient_url(), width="stretch")
        right.link_button("💬 DoubleTick", doubletick_chat_link(valid_phone), width="stretch")
    else:
        left.button("📞 3CX", disabled=True, width="stretch")
        right.button("💬 DoubleTick", disabled=True, width="stretch")
        st.warning("No valid mobile number is available for this order.")

    if not bool(selected_masks["closed"].iloc[0]):
        _render_quick_update(agent, selected)
        with st.expander("Close case", expanded=False):
            _render_quick_close(agent, selected)
    else:
        st.caption("This case is closed. Activity history remains available below.")

    with st.expander("Activity history", expanded=False):
        _render_history(case_id, activity)


def _render_card(
    agent: str,
    row: pd.Series,
    stage: str,
    assigned_all: pd.DataFrame,
    activity: pd.DataFrame,
) -> None:
    case_id = _text(row.get("Case ID"))
    customer = _compact_text(row.get("Customer Name"), 25) or "Unknown customer"
    awb = _text(row.get("AWB")) or "No AWB"
    portal = _compact_text(row.get("Portal"), 16) or "Unknown portal"
    calls = pd.to_numeric(row.get("Total Call Attempts", 0), errors="coerce")
    calls = 0 if pd.isna(calls) else int(calls)
    next_follow_up = _text(row.get("Next Follow-up"))

    with st.container(border=False, key=f"kanban_card_{_slug(agent)}_{case_id}"):
        follow_html = ""
        if next_follow_up and stage != "RTO Converted":
            follow_html = f'<div class="lk-follow-chip">Next: {escape(_compact_text(next_follow_up, 22))}</div>'
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
            "View →" if stage == "RTO Converted" else "Open →",
            key=f"kanban_open_{agent}_{case_id}",
            width="stretch",
        ):
            _order_drawer(agent, case_id, assigned_all, activity)


def _export_frame(cases: pd.DataFrame) -> pd.DataFrame:
    columns = [column for column in EXPORT_COLUMNS if column in cases.columns]
    export = cases[columns].copy()
    if "Mobile" in export.columns:
        export["Mobile"] = export["Mobile"].map(phone_display)
    return export


@st.fragment
def render_logistics_kanban_compact(
    *,
    agent: str,
    all_cases: pd.DataFrame,
    activity: pd.DataFrame,
) -> None:
    _inject_styles()
    assigned_all = all_cases[
        all_cases["Logistics Agent"].astype(str).str.upper().eq(agent.upper())
    ].copy()
    masks = logistics_case_masks(assigned_all)

    # Keep successful RTO conversions visible on the Kanban after closure.
    visible_mask = ~masks["closed"] | masks["rto_converted"]
    visible_all = _sort_latest(assigned_all[visible_mask].copy())
    converted_all = _sort_latest(assigned_all[masks["rto_converted"]].copy())

    st.markdown(
        f"""
        <div class="lk-workspace-head">
            <div class="lk-workspace-title">{escape(agent.title())} Workspace</div>
            <div class="lk-workspace-subtitle">RTO cases remain in follow-up until Tawseel confirms delivery. Successful conversions stay available in RTO Converted.</div>
        </div>
        """,
        unsafe_allow_html=True,
    )

    primary = st.columns(4, gap="small")
    _metric_card(primary[0], label="Assigned", value=len(assigned_all), accent="#3b82f6")
    _metric_card(primary[1], label="Active", value=int(masks["active"].sum()), accent="#f59e0b")
    _metric_card(primary[2], label="RTO", value=int(masks["current_rto"].sum()), accent="#ef4444")
    _metric_card(primary[3], label="RTO Converted", value=int(masks["rto_converted"].sum()), accent="#0f766e")

    total_calls = int(
        pd.to_numeric(
            assigned_all.get("Total Call Attempts", pd.Series(dtype=float)), errors="coerce"
        ).fillna(0).sum()
    )
    st.markdown(
        f"""
        <div class="lk-secondary-strip">
            <div class="lk-secondary-item"><span>Tawseel Delivered</span><strong>{int(masks['tawseel_delivered'].sum()):,}</strong></div>
            <div class="lk-secondary-item"><span>Pending Review</span><strong>{int(masks['pending_review'].sum()):,}</strong></div>
            <div class="lk-secondary-item"><span>Calls Logged</span><strong>{total_calls:,}</strong></div>
            <div class="lk-secondary-item"><span>Total Recovered</span><strong>{int(masks['recovered'].sum()):,}</strong></div>
        </div>
        """,
        unsafe_allow_html=True,
    )

    if visible_all.empty:
        st.info("No open or converted RTO cases assigned.")
        return

    with st.container(key=f"kanban_filters_{_slug(agent)}"):
        search_col, focus_col, portal_col, date_col, export_col = st.columns(
            [2.35, 1.18, 1.05, 1.05, 1.15], gap="small"
        )
        query = search_col.text_input(
            "Search orders",
            placeholder="AWB, customer, mobile or remark",
            key=f"kanban_search_{agent}",
        )
        focus = focus_col.selectbox(
            "Focus",
            ["All visible", "Critical", "Uncontacted", "Follow-up due", "RTO", "RTO Converted"],
            key=f"kanban_focus_{agent}",
        )
        portals = sorted(value for value in visible_all["Portal"].astype(str).unique() if value)
        portal = portal_col.selectbox(
            "Portal", ["All Portals", *portals], key=f"kanban_portal_{agent}"
        )
        available_dates = _available_status_dates(visible_all)
        status_date = date_col.selectbox(
            "Status date", ["All Dates", *available_dates], key=f"kanban_status_date_{agent}"
        )
        export_col.markdown("<div style='height:1.75rem'></div>", unsafe_allow_html=True)
        export_col.download_button(
            "⬇ RTO Converted",
            data=_export_frame(converted_all).to_csv(index=False).encode("utf-8-sig"),
            file_name=f"{agent.lower()}_rto_converted_{date.today().isoformat()}.csv",
            mime="text/csv",
            disabled=converted_all.empty,
            width="stretch",
            key=f"download_rto_converted_{agent}",
        )

    board_cases = _filter_status_date(visible_all, status_date)
    if portal != "All Portals":
        board_cases = board_cases[board_cases["Portal"].astype(str).eq(portal)].copy()

    board_masks = logistics_case_masks(board_cases)
    if focus == "Critical":
        board_cases = board_cases[
            board_cases.get("Priority", pd.Series("", index=board_cases.index))
            .fillna("").astype(str).str.upper().str.contains("CRITICAL", regex=False)
        ].copy()
    elif focus == "Uncontacted":
        attempts = pd.to_numeric(
            board_cases.get("Total Call Attempts", pd.Series(0, index=board_cases.index)),
            errors="coerce",
        ).fillna(0)
        board_cases = board_cases[attempts.eq(0)].copy()
    elif focus == "Follow-up due":
        board_cases = board_cases[_follow_up_due_mask(board_cases)].copy()
    elif focus == "RTO":
        board_cases = board_cases[board_masks["rto_open"]].copy()
    elif focus == "RTO Converted":
        board_cases = board_cases[board_masks["rto_converted"]].copy()

    if query.strip():
        needle = query.strip().casefold()
        searchable = pd.Series(False, index=board_cases.index)
        for column in ["AWB", "Customer Name", "Mobile", "Courier Remarks"]:
            if column in board_cases.columns:
                searchable |= (
                    board_cases[column].fillna("").astype(str).str.casefold().str.contains(needle, regex=False)
                )
        board_cases = board_cases[searchable].copy()

    board_cases = _sort_latest(board_cases)
    board_cases["_kanban_stage"] = _stage_series(board_cases)
    stage_masks = logistics_case_masks(board_cases)
    board_cases.loc[stage_masks["rto_converted"], "_kanban_stage"] = "RTO Converted"

    stage_columns = st.columns(len(KANBAN_STAGES), gap="small")
    for stage, column in zip(KANBAN_STAGES, stage_columns):
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
            with st.container(height=640, border=False, key=f"kanban_column_{stage_key}"):
                if stage_cases.empty:
                    st.markdown(
                        f'<div class="lk-empty-column">No {escape(meta["hint"].lower())} orders</div>',
                        unsafe_allow_html=True,
                    )
                else:
                    for _, row in stage_cases.iterrows():
                        _render_card(agent, row, stage, assigned_all, activity)
