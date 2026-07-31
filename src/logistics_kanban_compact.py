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
    "New": {"accent": "#3b82f6", "hint": "new"},
    "In Progress": {"accent": "#f59e0b", "hint": "in-progress"},
    "Follow-up": {"accent": "#8b5cf6", "hint": "follow-up"},
    "RTO": {"accent": "#ef4444", "hint": "RTO recovery"},
    "Delivered Review": {"accent": "#10b981", "hint": "delivered-review"},
    "RTO Converted": {"accent": "#0f766e", "hint": "converted RTO"},
}

RTO_WORK_STATUS_OPTIONS = [
    "IN PROGRESS",
    "FOLLOW-UP DUE",
    "CUSTOMER CONTACTED",
    "AWAITING COURIER",
    "ESCALATED",
    "UNRESOLVED",
    "RTO WON / CONVERTED",
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
    "Replacement Order Confirmed",
]

EXPORT_COLUMNS = [
    "Portal",
    "AWB",
    "Customer Name",
    "Mobile",
    "Source Courier Status",
    "Previous Courier Status",
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


def _mask(masks: dict[str, pd.Series], name: str, index: pd.Index) -> pd.Series:
    value = masks.get(name)
    if value is None:
        return pd.Series(False, index=index, dtype=bool)
    return value.reindex(index, fill_value=False).astype(bool)


def _inject_styles() -> None:
    st.markdown(
        """
        <style>
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
            width: min(440px, 100vw) !important;
            min-width: 0 !important;
            max-width: 440px !important;
            height: 100vh !important;
            min-height: 100vh !important;
            max-height: 100vh !important;
            margin: 0 !important;
            border-radius: 18px 0 0 18px !important;
            overflow: hidden !important;
            box-shadow: -24px 0 70px rgba(15, 23, 42, 0.30) !important;
            animation: lk-drawer-in 110ms ease-out !important;
        }
        @keyframes lk-drawer-in {
            from { transform: translateX(18px); opacity: 0.75; }
            to { transform: translateX(0); opacity: 1; }
        }
        div[data-testid="stModal"] div[role="dialog"] > div,
        div[data-testid="stDialog"] div[role="dialog"] > div,
        div[role="dialog"][aria-modal="true"] > div {
            height: 100% !important;
            max-height: 100% !important;
            overflow: hidden !important;
            padding: 0.62rem 0.72rem 0.72rem 0.72rem !important;
        }
        div[data-testid="stModal"] [data-testid="stDialogHeader"],
        div[data-testid="stDialog"] [data-testid="stDialogHeader"] {
            margin-bottom: 0.25rem !important;
            padding-bottom: 0.42rem !important;
            border-bottom: 1px solid rgba(100, 116, 139, 0.13) !important;
        }
        div[data-testid="stModal"] h2,
        div[data-testid="stDialog"] h2 {
            font-size: 0.98rem !important;
            letter-spacing: -0.02em !important;
        }
        div[data-testid="stModal"] label,
        div[data-testid="stDialog"] label {
            font-size: 0.7rem !important;
            font-weight: 650 !important;
        }
        [class*="st-key-drawer_scroll_"] {
            height: calc(100vh - 190px) !important;
            max-height: calc(100vh - 190px) !important;
            overflow-y: auto !important;
            overflow-x: hidden !important;
            overscroll-behavior: contain;
            padding-right: 0.2rem;
            scrollbar-width: thin;
        }
        [class*="st-key-drawer_scroll_"] > div {
            height: auto !important;
            max-height: none !important;
            overflow: visible !important;
        }
        [class*="st-key-drawer_footer_"] {
            flex: 0 0 auto;
            position: relative;
            z-index: 50;
            margin: 0.45rem -0.15rem 0 -0.15rem;
            padding: 0.55rem 0.15rem 0.05rem 0.15rem;
            border-top: 1px solid rgba(100, 116, 139, 0.15);
            background: var(--background-color, #ffffff);
            box-shadow: 0 -8px 20px rgba(15, 23, 42, 0.04);
        }
        [class*="st-key-drawer_footer_"] button {
            min-height: 2.35rem !important;
            font-weight: 720 !important;
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
            margin-top: 0.08rem;
            color: #64748b;
            font-size: 0.68rem;
            font-weight: 620;
        }
        .lk-order-summary {
            display: grid;
            grid-template-columns: 1fr 1fr;
            gap: 0.36rem;
            margin: 0.42rem 0;
        }
        .lk-summary-item {
            min-width: 0;
            padding: 0.4rem 0.46rem;
            border: 1px solid rgba(100, 116, 139, 0.12);
            border-radius: 8px;
            background: rgba(148, 163, 184, 0.055);
        }
        .lk-summary-label {
            color: #64748b;
            font-size: 0.57rem;
            font-weight: 700;
            text-transform: uppercase;
            letter-spacing: 0.04em;
        }
        .lk-summary-value {
            margin-top: 0.08rem;
            color: #0f172a;
            font-size: 0.71rem;
            line-height: 1.17;
            font-weight: 690;
            overflow-wrap: anywhere;
        }
        .lk-issue-box,
        .lk-rto-guidance {
            margin: 0 0 0.42rem 0;
            padding: 0.43rem 0.5rem;
            border-radius: 8px;
            font-size: 0.68rem;
            line-height: 1.25;
        }
        .lk-issue-box {
            background: rgba(245, 158, 11, 0.075);
            color: #78350f;
        }
        .lk-rto-guidance {
            border: 1px solid rgba(239, 68, 68, 0.16);
            background: rgba(239, 68, 68, 0.055);
            color: #991b1b;
        }
        .lk-section-title {
            margin: 0.48rem 0 0.02rem 0;
            color: #0f172a;
            font-size: 0.84rem;
            font-weight: 760;
        }
        .lk-section-help {
            margin-bottom: 0.2rem;
            color: #64748b;
            font-size: 0.65rem;
        }
        [class*="st-key-drawer_scroll_"] textarea {
            min-height: 62px !important;
        }
        [class*="st-key-drawer_scroll_"] [data-testid="stExpander"] {
            margin-top: 0.38rem !important;
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
            min-height: 80px;
            padding: 0.68rem 0.8rem;
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
            font-size: 0.68rem;
            font-weight: 680;
            text-transform: uppercase;
            letter-spacing: 0.035em;
        }
        .lk-metric-value {
            margin-top: 0.16rem;
            font-size: 1.58rem;
            line-height: 1;
            font-weight: 790;
            color: #0f172a;
        }
        .lk-secondary-strip {
            display: grid;
            grid-template-columns: repeat(4, minmax(0, 1fr));
            gap: 0.4rem;
            margin: 0.48rem 0 0.65rem 0;
        }
        .lk-secondary-item {
            display: flex;
            align-items: center;
            justify-content: space-between;
            gap: 0.4rem;
            padding: 0.42rem 0.56rem;
            border-radius: 9px;
            background: rgba(148, 163, 184, 0.065);
            border: 1px solid rgba(100, 116, 139, 0.09);
            font-size: 0.7rem;
            color: #475569;
        }
        .lk-secondary-item strong { color: #0f172a; font-size: 0.82rem; }
        [class*="st-key-kanban_filters_"] {
            margin: 0.2rem 0 0.7rem 0;
            padding: 0.62rem 0.72rem 0.05rem 0.72rem;
            border: 1px solid rgba(100, 116, 139, 0.16);
            border-radius: 13px;
            background: rgba(148, 163, 184, 0.05);
        }
        [class*="st-key-kanban_filters_"] label {
            font-size: 0.71rem !important;
            font-weight: 650 !important;
        }
        .lk-stage-header {
            display: flex;
            align-items: center;
            justify-content: space-between;
            gap: 0.38rem;
            padding: 0.08rem 0.1rem 0.4rem 0.1rem;
        }
        .lk-stage-title {
            font-weight: 760;
            font-size: 0.83rem;
            white-space: nowrap;
        }
        .lk-stage-count {
            display: inline-flex;
            align-items: center;
            justify-content: center;
            min-width: 1.55rem;
            height: 1.3rem;
            padding: 0 0.35rem;
            border-radius: 999px;
            color: white;
            background: var(--stage-accent);
            font-size: 0.66rem;
            font-weight: 760;
        }
        [class*="st-key-kanban_column_"] {
            border: 1px solid rgba(100, 116, 139, 0.13);
            border-top: 3px solid var(--stage-accent, #64748b);
            border-radius: 13px;
            background: rgba(148, 163, 184, 0.032);
            box-shadow: 0 3px 12px rgba(15, 23, 42, 0.03);
        }
        .st-key-kanban_column_new { --stage-accent: #3b82f6; }
        .st-key-kanban_column_in_progress { --stage-accent: #f59e0b; }
        .st-key-kanban_column_follow_up { --stage-accent: #8b5cf6; }
        .st-key-kanban_column_rto { --stage-accent: #ef4444; }
        .st-key-kanban_column_delivered_review { --stage-accent: #10b981; }
        .st-key-kanban_column_rto_converted { --stage-accent: #0f766e; }
        [class*="st-key-kanban_column_"] > div { padding: 0.4rem !important; }
        [class*="st-key-kanban_card_"] {
            margin-bottom: 0.38rem;
            border: 1px solid rgba(100, 116, 139, 0.15);
            border-radius: 10px;
            background: var(--background-color, #ffffff);
            box-shadow: 0 2px 9px rgba(15, 23, 42, 0.045);
        }
        [class*="st-key-kanban_card_"] > div { padding: 0.48rem 0.52rem 0.44rem !important; }
        .lk-card-top {
            display: flex;
            align-items: center;
            justify-content: space-between;
            gap: 0.3rem;
            margin-bottom: 0.28rem;
        }
        .lk-badge {
            max-width: 76%;
            padding: 0.11rem 0.32rem;
            border-radius: 999px;
            background: rgba(148, 163, 184, 0.11);
            color: #475569;
            font-size: 0.61rem;
            font-weight: 740;
            white-space: nowrap;
            overflow: hidden;
            text-overflow: ellipsis;
        }
        .lk-call-chip { color: #64748b; font-size: 0.61rem; font-weight: 650; }
        .lk-customer {
            color: #0f172a;
            font-size: 0.84rem;
            line-height: 1.14;
            font-weight: 770;
            overflow-wrap: anywhere;
        }
        .lk-awb {
            margin-top: 0.15rem;
            color: #334155;
            font-size: 0.64rem;
            font-weight: 650;
            white-space: nowrap;
            overflow: hidden;
            text-overflow: ellipsis;
        }
        .lk-card-sub {
            margin-top: 0.18rem;
            color: #64748b;
            font-size: 0.61rem;
            white-space: nowrap;
            overflow: hidden;
            text-overflow: ellipsis;
        }
        .lk-follow-chip {
            margin-top: 0.25rem;
            padding: 0.18rem 0.28rem;
            border-radius: 6px;
            background: rgba(139, 92, 246, 0.07);
            color: #6d28d9;
            font-size: 0.59rem;
            font-weight: 650;
            white-space: nowrap;
            overflow: hidden;
            text-overflow: ellipsis;
        }
        [class*="st-key-kanban_card_"] .stButton { margin-top: 0.3rem !important; }
        [class*="st-key-kanban_card_"] .stButton button {
            min-height: 1.6rem !important;
            padding: 0.06rem 0.32rem !important;
            border-radius: 7px !important;
            font-size: 0.65rem !important;
            font-weight: 690 !important;
        }
        .lk-empty-column {
            display: flex;
            min-height: 74px;
            align-items: center;
            justify-content: center;
            text-align: center;
            color: #94a3b8;
            font-size: 0.68rem;
        }
        @media (max-width: 1100px) {
            .lk-secondary-strip { grid-template-columns: repeat(2, minmax(0, 1fr)); }
        }
        </style>
        """,
        unsafe_allow_html=True,
    )


def _priority_badge(row: pd.Series, stage: str) -> str:
    priority = _text(row.get("Priority")).upper()
    if "CRITICAL" in priority:
        return "Critical"
    if "FOLLOW" in priority:
        return "Follow-up"
    if stage == "RTO":
        return "RTO"
    if stage == "RTO Converted":
        return "Converted"
    if stage == "Delivered Review":
        return "Delivered"
    return stage


def _compact_text(value: Any, limit: int) -> str:
    text = _text(value)
    return text if len(text) <= limit else text[: max(0, limit - 1)].rstrip() + "..."


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
        bool(_mask(masks, "current_rto", frame.index).iloc[0]),
        bool(_mask(masks, "rto_origin", frame.index).iloc[0]),
        bool(_mask(masks, "tawseel_delivered", frame.index).iloc[0]),
    )


def _follow_up_value(follow_date: Any, follow_time: Any) -> str:
    if not follow_date:
        return ""
    value = str(follow_date)
    if follow_time:
        value += f" {follow_time.strftime('%H:%M')}"
    return value


def _save_activity(
    *,
    case_id: str,
    action: str,
    call_result: str,
    customer_response: str,
    remark: str,
    follow_date: Any,
    follow_time: Any,
    work_status: str,
    is_rto_origin: bool,
) -> None:
    follow_up = _follow_up_value(follow_date, follow_time)
    converted = work_status == "RTO WON / CONVERTED"
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
        if converted:
            close_case(
                case_id,
                outcome="RTO Won / Converted",
                delivered_after_coordination=True,
                delivered_date=str(date.today()),
                remark=remark or "RTO converted by logistics follow-up.",
            )
            st.toast("RTO converted and moved to RTO Converted", icon="✅")
        else:
            st.toast("Activity saved", icon="✅")
        st.rerun()
    except Exception as exc:
        st.error(f"Could not save update - {_error_text(exc)}")


def _render_history(selected_id: str, activity: pd.DataFrame) -> None:
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
        height=280,
    )


def _render_close_popover(
    *,
    agent: str,
    selected: pd.Series,
    is_current_rto: bool,
    is_rto_origin: bool,
) -> None:
    case_id = _text(selected.get("Case ID"))
    if is_current_rto or is_rto_origin:
        outcomes = [
            "RTO Won / Converted",
            "Confirmed RTO",
            "Customer Cancelled",
            "Unresolved",
            "Escalated",
        ]
    else:
        outcomes = [
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

    outcome = st.selectbox(
        "Final outcome",
        outcomes,
        key=f"drawer_close_outcome_{agent}_{case_id}",
    )
    converted = outcome == "RTO Won / Converted"
    recovered = st.checkbox(
        "Delivered after logistics coordination",
        value=converted,
        disabled=converted,
        key=f"drawer_close_recovered_{agent}_{case_id}",
    )
    delivered_date = st.date_input(
        "Delivered date",
        value=date.today() if converted else None,
        key=f"drawer_close_date_{agent}_{case_id}",
    )
    closing_remark = st.text_area(
        "Closure remark",
        height=70,
        placeholder="Add the final result...",
        key=f"drawer_close_remark_{agent}_{case_id}",
    )
    if st.button(
        "Confirm and close",
        type="primary",
        width="stretch",
        key=f"drawer_confirm_close_{agent}_{case_id}",
    ):
        try:
            close_case(
                case_id,
                outcome=outcome,
                delivered_after_coordination=True if converted else recovered,
                delivered_date=str(delivered_date or ""),
                remark=closing_remark,
            )
            st.toast("Case closed", icon="✅")
            st.rerun()
        except Exception as exc:
            st.error(f"Could not close case - {_error_text(exc)}")


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
    selected_masks = logistics_case_masks(match)
    is_closed = bool(_mask(selected_masks, "closed", match.index).iloc[0])
    is_converted = bool(_mask(selected_masks, "rto_converted", match.index).iloc[0])
    is_current_rto, is_rto_origin, _ = _rto_context(selected)

    customer = _text(selected.get("Customer Name")) or "Unknown customer"
    awb = _text(selected.get("AWB")) or "Unavailable"
    courier_status = _text(selected.get("Latest Courier Status")) or "Unavailable"
    current_work_status = _text(selected.get("Logistics Work Status")).upper() or "NEW"
    portal = _text(selected.get("Portal")) or "Unavailable"
    mobile = phone_display(selected.get("Mobile", ""))
    issue = _text(selected.get("Courier Remarks")) or "No courier remark"
    valid_phone = normalize_phone(selected.get("Mobile", ""))

    with st.container(height=440, border=False, key=f"drawer_scroll_{case_id}"):
        st.markdown(
            f'<div class="lk-drawer-title">{escape(customer)}</div>'
            f'<div class="lk-drawer-awb">AWB {escape(awb)}</div>',
            unsafe_allow_html=True,
        )
        st.markdown(
            f"""
            <div class="lk-order-summary">
                <div class="lk-summary-item"><div class="lk-summary-label">Courier</div><div class="lk-summary-value">{escape(courier_status)}</div></div>
                <div class="lk-summary-item"><div class="lk-summary-label">Work status</div><div class="lk-summary-value">{escape(current_work_status)}</div></div>
                <div class="lk-summary-item"><div class="lk-summary-label">Portal</div><div class="lk-summary-value">{escape(portal)}</div></div>
                <div class="lk-summary-item"><div class="lk-summary-label">Mobile</div><div class="lk-summary-value">{escape(mobile)}</div></div>
            </div>
            <div class="lk-issue-box"><strong>Issue:</strong> {escape(issue)}</div>
            """,
            unsafe_allow_html=True,
        )

        call_col, chat_col = st.columns(2, gap="small")
        if valid_phone:
            call_col.link_button("3CX", threecx_webclient_url(), width="stretch")
            chat_col.link_button(
                "DoubleTick", doubletick_chat_link(valid_phone), width="stretch"
            )
        else:
            call_col.button("3CX", disabled=True, width="stretch")
            chat_col.button("DoubleTick", disabled=True, width="stretch")
            st.warning("No valid mobile number is available for this order.")

        if is_converted:
            st.success("This order is recorded under RTO Converted.")
        elif is_current_rto or is_rto_origin:
            st.markdown(
                '<div class="lk-rto-guidance"><strong>RTO recovery:</strong> continue follow-up. Select <strong>RTO WON / CONVERTED</strong> when the customer confirms the replacement or converted order.</div>',
                unsafe_allow_html=True,
            )

        if not is_closed:
            st.markdown(
                '<div class="lk-section-title">Update activity</div>'
                '<div class="lk-section-help">Save the latest call or coordination result.</div>',
                unsafe_allow_html=True,
            )

            status_options = (
                RTO_WORK_STATUS_OPTIONS
                if (is_current_rto or is_rto_origin)
                else WORK_STATUS_OPTIONS
            )
            if current_work_status not in status_options:
                status_options = [current_work_status, *status_options]
            response_options = (
                RTO_RESPONSES
                if (is_current_rto or is_rto_origin)
                else STANDARD_RESPONSES
            )

            action_col, status_col = st.columns(2, gap="small")
            action = action_col.selectbox(
                "Action",
                ["CALL", "WHATSAPP", "COURIER_COORDINATION", "NOTE", "ESCALATION"],
                key=f"drawer_action_{agent}_{case_id}",
            )
            work_status = status_col.selectbox(
                "Work status",
                status_options,
                index=status_options.index(current_work_status),
                key=f"drawer_status_{agent}_{case_id}",
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
                key=f"drawer_call_result_{agent}_{case_id}",
            )
            customer_response = response_col.selectbox(
                "Customer response",
                response_options,
                key=f"drawer_response_{agent}_{case_id}",
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
                height=62,
                placeholder="Add a short update...",
                key=f"drawer_remark_{agent}_{case_id}",
            )
        else:
            action = "NOTE"
            work_status = current_work_status
            call_result = ""
            customer_response = ""
            follow_date = None
            follow_time = None
            remark = ""
            st.caption("This case is closed. Its history is available below.")

        with st.expander("Activity history", expanded=False):
            _render_history(case_id, activity)

    with st.container(key=f"drawer_footer_{case_id}"):
        if not is_closed:
            save_col, close_col = st.columns([1.65, 1], gap="small")
            if save_col.button(
                "Save activity",
                type="primary",
                width="stretch",
                key=f"drawer_save_{agent}_{case_id}",
            ):
                _save_activity(
                    case_id=case_id,
                    action=action,
                    call_result=call_result,
                    customer_response=customer_response,
                    remark=remark,
                    follow_date=follow_date,
                    follow_time=follow_time,
                    work_status=work_status,
                    is_rto_origin=is_rto_origin,
                )
            with close_col.popover("Close case", width="stretch"):
                _render_close_popover(
                    agent=agent,
                    selected=selected,
                    is_current_rto=is_current_rto,
                    is_rto_origin=is_rto_origin,
                )
        else:
            st.caption("Closed case - use the X above to return to the board.")


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
            follow_html = (
                f'<div class="lk-follow-chip">Next: '
                f'{escape(_compact_text(next_follow_up, 22))}</div>'
            )
        st.markdown(
            f"""
            <div class="lk-card-top">
                <span class="lk-badge">{escape(_priority_badge(row, stage))}</span>
                <span class="lk-call-chip">Calls {calls}</span>
            </div>
            <div class="lk-customer">{escape(customer)}</div>
            <div class="lk-awb">AWB {escape(awb)}</div>
            <div class="lk-card-sub">{escape(portal)}</div>
            {follow_html}
            """,
            unsafe_allow_html=True,
        )
        if st.button(
            "View" if stage == "RTO Converted" else "Open",
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

    closed_mask = _mask(masks, "closed", assigned_all.index)
    converted_mask = _mask(masks, "rto_converted", assigned_all.index)
    visible_all = _sort_latest(
        assigned_all[(~closed_mask) | converted_mask].copy()
    )
    converted_all = _sort_latest(assigned_all[converted_mask].copy())

    st.markdown(
        f"""
        <div class="lk-workspace-head">
            <div class="lk-workspace-title">{escape(agent.title())} Workspace</div>
            <div class="lk-workspace-subtitle">RTO follow-up and converted-order recovery workspace.</div>
        </div>
        """,
        unsafe_allow_html=True,
    )

    primary = st.columns(4, gap="small")
    _metric_card(primary[0], label="Assigned", value=len(assigned_all), accent="#3b82f6")
    _metric_card(
        primary[1],
        label="Active",
        value=int(_mask(masks, "active", assigned_all.index).sum()),
        accent="#f59e0b",
    )
    _metric_card(
        primary[2],
        label="RTO",
        value=int(_mask(masks, "current_rto", assigned_all.index).sum()),
        accent="#ef4444",
    )
    _metric_card(
        primary[3],
        label="RTO Converted",
        value=int(converted_mask.sum()),
        accent="#0f766e",
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
            <div class="lk-secondary-item"><span>Tawseel Delivered</span><strong>{int(_mask(masks, 'tawseel_delivered', assigned_all.index).sum()):,}</strong></div>
            <div class="lk-secondary-item"><span>Pending Review</span><strong>{int(_mask(masks, 'pending_review', assigned_all.index).sum()):,}</strong></div>
            <div class="lk-secondary-item"><span>Calls Logged</span><strong>{total_calls:,}</strong></div>
            <div class="lk-secondary-item"><span>Total Recovered</span><strong>{int(_mask(masks, 'recovered', assigned_all.index).sum()):,}</strong></div>
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
            [
                "All visible",
                "Critical",
                "Uncontacted",
                "Follow-up due",
                "RTO",
                "RTO Converted",
            ],
            key=f"kanban_focus_{agent}",
        )
        portals = sorted(
            value for value in visible_all["Portal"].astype(str).unique() if value
        )
        portal = portal_col.selectbox(
            "Portal",
            ["All Portals", *portals],
            key=f"kanban_portal_{agent}",
        )
        available_dates = _available_status_dates(visible_all)
        status_date = date_col.selectbox(
            "Status date",
            ["All Dates", *available_dates],
            key=f"kanban_status_date_{agent}",
        )
        export_col.markdown("<div style='height:1.72rem'></div>", unsafe_allow_html=True)
        export_col.download_button(
            "Download RTO Converted",
            data=_export_frame(converted_all).to_csv(index=False).encode("utf-8-sig"),
            file_name=f"{agent.lower()}_rto_converted_{date.today().isoformat()}.csv",
            mime="text/csv",
            disabled=converted_all.empty,
            width="stretch",
            key=f"download_rto_converted_{agent}",
        )

    board_cases = _filter_status_date(visible_all, status_date)
    if portal != "All Portals":
        board_cases = board_cases[
            board_cases["Portal"].astype(str).eq(portal)
        ].copy()

    board_masks = logistics_case_masks(board_cases)
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
    elif focus == "RTO":
        board_cases = board_cases[
            _mask(board_masks, "rto_open", board_cases.index)
        ].copy()
    elif focus == "RTO Converted":
        board_cases = board_cases[
            _mask(board_masks, "rto_converted", board_cases.index)
        ].copy()

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
    stage_masks = logistics_case_masks(board_cases)
    board_cases.loc[
        _mask(stage_masks, "rto_converted", board_cases.index),
        "_kanban_stage",
    ] = "RTO Converted"

    stage_columns = st.columns(len(KANBAN_STAGES), gap="small")
    for stage, column in zip(KANBAN_STAGES, stage_columns):
        stage_cases = board_cases[board_cases["_kanban_stage"].eq(stage)].copy()
        stage_key = _slug(stage)
        meta = STAGE_META[stage]
        with column:
            st.markdown(
                f"""
                <div class="lk-stage-header" style="--stage-accent:{meta['accent']}">
                    <div class="lk-stage-title">{escape(stage)}</div>
                    <span class="lk-stage-count">{len(stage_cases)}</span>
                </div>
                """,
                unsafe_allow_html=True,
            )
            with st.container(
                height=640,
                border=False,
                key=f"kanban_column_{stage_key}",
            ):
                if stage_cases.empty:
                    st.markdown(
                        f'<div class="lk-empty-column">No {escape(meta["hint"])} orders</div>',
                        unsafe_allow_html=True,
                    )
                else:
                    for _, row in stage_cases.iterrows():
                        _render_card(agent, row, stage, assigned_all, activity)
