from __future__ import annotations

from datetime import date

import streamlit as st

from src import logistics_kanban_compact as _base
from src.logistics_write_backup_guard import install_write_through_backup

install_write_through_backup()

from src.logistics import add_activity, close_case


RTO_CONVERTED_STATUS = "RTO WON / CONVERTED"
_ORIGINAL_INJECT_STYLES = _base._inject_styles


def _inject_scrollable_drawer_styles() -> None:
    """Keep the native right drawer usable on every viewport height."""
    _ORIGINAL_INJECT_STYLES()
    st.markdown(
        """
        <style>
        /* The dialog shell must not grow beyond the viewport. */
        div[data-testid="stModal"] div[role="dialog"],
        div[data-testid="stDialog"] div[role="dialog"],
        div[role="dialog"][aria-modal="true"] {
            display: flex !important;
            flex-direction: column !important;
            overflow: hidden !important;
            height: 100dvh !important;
            min-height: 0 !important;
            max-height: 100dvh !important;
        }

        /* Streamlit has used both direct children and stDialogContent as the
           scroll body across releases. Support both DOM variants. */
        div[data-testid="stModal"] div[role="dialog"] > div,
        div[data-testid="stDialog"] div[role="dialog"] > div,
        div[role="dialog"][aria-modal="true"] > div,
        div[data-testid="stModal"] [data-testid="stDialogContent"],
        div[data-testid="stDialog"] [data-testid="stDialogContent"] {
            flex: 1 1 auto !important;
            min-height: 0 !important;
            height: auto !important;
            max-height: none !important;
            overflow-y: auto !important;
            overflow-x: hidden !important;
            overscroll-behavior: contain !important;
            -webkit-overflow-scrolling: touch !important;
            padding-bottom: 5rem !important;
            scrollbar-gutter: stable !important;
        }

        div[data-testid="stModal"] div[role="dialog"] [data-testid="stVerticalBlock"],
        div[data-testid="stDialog"] div[role="dialog"] [data-testid="stVerticalBlock"] {
            min-height: 0 !important;
        }

        @media (max-height: 760px) {
            div[data-testid="stModal"] div[role="dialog"],
            div[data-testid="stDialog"] div[role="dialog"],
            div[role="dialog"][aria-modal="true"] {
                border-radius: 12px 0 0 12px !important;
            }
        }
        </style>
        """,
        unsafe_allow_html=True,
    )


def _render_quick_update_with_rto_conversion(agent: str, selected) -> None:
    case_id = _base._text(selected.get("Case ID"))
    current_status = _base._text(selected.get("Logistics Work Status")).upper()
    is_current_rto, _, _ = _base._rto_context(selected)

    if is_current_rto:
        status_options = [*_base.RTO_WORK_STATUS_OPTIONS, RTO_CONVERTED_STATUS]
        response_options = _base.RTO_RESPONSES
    else:
        status_options = _base.WORK_STATUS_OPTIONS
        response_options = _base.STANDARD_RESPONSES

    status_index = (
        status_options.index(current_status) if current_status in status_options else 0
    )

    if is_current_rto:
        st.markdown(
            '<div class="lk-rto-guidance"><strong>RTO recovery:</strong> continue follow-up until the customer is recovered. Select <strong>RTO Won / Converted</strong> only after the customer confirms the replacement or converted order.</div>',
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
            "Customer response", response_options
        )

        follow_col, time_col = st.columns(2, gap="small")
        follow_date = follow_col.date_input(
            "Next date", value=None, key=f"drawer_follow_date_{agent}_{case_id}"
        )
        follow_time = time_col.time_input(
            "Next time", value=None, key=f"drawer_follow_time_{agent}_{case_id}"
        )
        remark = st.text_area(
            "Remark", height=66, placeholder="Add a short update..."
        )
        save = st.form_submit_button(
            "Save RTO conversion"
            if work_status == RTO_CONVERTED_STATUS
            else "Save activity",
            type="primary",
            width="stretch",
        )

    if not save:
        return

    follow_up = ""
    if follow_date:
        follow_up = str(follow_date)
        if follow_time:
            follow_up += f" {follow_time.strftime('%H:%M')}"

    try:
        if work_status == RTO_CONVERTED_STATUS:
            # Store the won case as a closed, recovered logistics conversion.
            # Tawseel and all non-logistics dashboards remain read-only.
            close_case(
                case_id,
                outcome="RTO Won / Converted",
                delivered_after_coordination=True,
                delivered_date=date.today().isoformat(),
                remark=remark or "RTO recovered and converted to a new order.",
            )
            add_activity(
                case_id,
                action_type=action,
                call_result=call_result,
                customer_response=customer_response or "Will Receive",
                remark=remark or "RTO won / converted to a new order.",
                next_follow_up="",
                new_status="",
            )
            st.toast("RTO moved to RTO Converted", icon="🏆")
        else:
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
        st.error(f"Could not save update — {_base._error_text(exc)}")


def render_logistics_kanban_compact(*, agent: str, all_cases, activity) -> None:
    """Render the existing Kanban with isolated runtime enhancements."""
    _base._inject_styles = _inject_scrollable_drawer_styles
    _base._render_quick_update = _render_quick_update_with_rto_conversion
    _base.render_logistics_kanban_compact(
        agent=agent,
        all_cases=all_cases,
        activity=activity,
    )
