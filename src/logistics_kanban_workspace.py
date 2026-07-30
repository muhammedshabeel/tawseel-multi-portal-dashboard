from __future__ import annotations

from datetime import date
from typing import Any

import pandas as pd
import streamlit as st

from src.logistics import add_activity, close_case
from src.logistics_dashboard_metrics import logistics_case_masks
from src.logistics_integrations import normalize_phone, phone_display
from src.logistics_links import doubletick_chat_link, threecx_webclient_url

BOARD_STAGES = (
    "New",
    "In Progress",
    "Follow-up",
    "RTO",
    "Delivered Review",
)

WORK_STATUS_OPTIONS = [
    "IN PROGRESS",
    "FOLLOW-UP DUE",
    "CUSTOMER CONTACTED",
    "RESCHEDULED",
    "AWAITING COURIER",
    "ESCALATED",
    "UNRESOLVED",
]


def _error_text(exc: Exception) -> str:
    text = str(exc).strip()
    return f"{type(exc).__name__}: {text}" if text else type(exc).__name__


def _text(value: Any) -> str:
    if value is None:
        return ""
    try:
        if pd.isna(value):
            return ""
    except (TypeError, ValueError):
        pass
    return str(value).strip()


def _status_datetimes(df: pd.DataFrame) -> pd.Series:
    if "Tawseel Status Updated At" not in df.columns:
        return pd.Series(pd.NaT, index=df.index, dtype="datetime64[ns]")
    return pd.to_datetime(
        df["Tawseel Status Updated At"],
        errors="coerce",
        format="mixed",
    )


def _sort_latest(df: pd.DataFrame) -> pd.DataFrame:
    if df.empty:
        return df.copy()
    work = df.copy()
    work["_status_sort"] = _status_datetimes(work)
    work["_priority_sort"] = (
        work.get("Priority", pd.Series("", index=work.index))
        .astype(str)
        .str.upper()
        .map(lambda value: 0 if "CRITICAL" in value else (1 if "FOLLOW" in value else 2))
    )
    work["_assigned_sort"] = pd.to_datetime(
        work.get("Assigned At", pd.Series("", index=work.index)),
        errors="coerce",
        format="mixed",
    )
    return work.sort_values(
        ["_status_sort", "_priority_sort", "_assigned_sort"],
        ascending=[False, True, False],
        na_position="last",
    ).drop(
        columns=["_status_sort", "_priority_sort", "_assigned_sort"],
        errors="ignore",
    )


def _available_status_dates(df: pd.DataFrame) -> list[str]:
    if df.empty:
        return []
    values = _status_datetimes(df).dt.date.dropna().unique().tolist()
    return [value.isoformat() for value in sorted(values, reverse=True)]


def _filter_status_date(df: pd.DataFrame, selected_date: str) -> pd.DataFrame:
    if df.empty or selected_date == "All Dates":
        return df.copy()
    wanted = pd.to_datetime(selected_date, errors="coerce")
    if pd.isna(wanted):
        return df.copy()
    return df[_status_datetimes(df).dt.date.eq(wanted.date())].copy()


def _stage_series(cases: pd.DataFrame) -> pd.Series:
    if cases.empty:
        return pd.Series(dtype=str, index=cases.index)

    masks = logistics_case_masks(cases)
    work_status = (
        cases.get("Logistics Work Status", pd.Series("", index=cases.index))
        .fillna("")
        .astype(str)
        .str.strip()
        .str.upper()
    )

    stage = pd.Series("New", index=cases.index, dtype=str)
    stage.loc[
        work_status.isin(["IN PROGRESS", "CUSTOMER CONTACTED"])
    ] = "In Progress"
    stage.loc[
        work_status.isin(
            [
                "FOLLOW-UP DUE",
                "RESCHEDULED",
                "AWAITING COURIER",
                "ESCALATED",
                "UNRESOLVED",
            ]
        )
    ] = "Follow-up"
    stage.loc[masks["current_rto"]] = "RTO"
    stage.loc[masks["pending_review"]] = "Delivered Review"
    return stage


def _selected_key(agent: str) -> str:
    return f"logistics_kanban_selected_{agent.upper()}"


def _card_label(row: pd.Series) -> str:
    customer = _text(row.get("Customer Name")) or "Unknown customer"
    awb = _text(row.get("AWB")) or "No AWB"
    status = _text(row.get("Latest Courier Status")) or "No courier status"
    return f"{customer[:28]}\n{awb}\n{status}"


def _render_card(agent: str, row: pd.Series, stage: str) -> None:
    case_id = _text(row.get("Case ID"))
    priority = _text(row.get("Priority")).upper()
    calls = pd.to_numeric(row.get("Total Call Attempts", 0), errors="coerce")
    calls = 0 if pd.isna(calls) else int(calls)
    next_follow_up = _text(row.get("Next Follow-up"))
    work_status = _text(row.get("Logistics Work Status")) or "NEW"
    portal = _text(row.get("Portal"))

    with st.container(border=True):
        if "CRITICAL" in priority:
            st.caption("🔥 CRITICAL")
        elif "FOLLOW" in priority:
            st.caption("⏰ FOLLOW-UP")
        else:
            st.caption(stage.upper())

        st.markdown(f"**{_text(row.get('Customer Name')) or 'Unknown customer'}**")
        st.caption(f"AWB: {_text(row.get('AWB')) or 'Unavailable'}")
        st.caption(f"{portal} · {work_status}")
        if next_follow_up:
            st.caption(f"Next: {next_follow_up}")
        st.caption(f"Calls: {calls}")

        if st.button(
            "Open order",
            key=f"kanban_open_{agent}_{case_id}",
            width="stretch",
        ):
            st.session_state[_selected_key(agent)] = case_id
            st.rerun()


def _render_activity_form(agent: str, selected: pd.Series) -> None:
    case_id = _text(selected.get("Case ID"))
    current_status = _text(selected.get("Logistics Work Status")).upper()
    status_index = (
        WORK_STATUS_OPTIONS.index(current_status)
        if current_status in WORK_STATUS_OPTIONS
        else 0
    )

    with st.form(
        f"kanban_activity_{agent}_{case_id}",
        clear_on_submit=True,
    ):
        action = st.selectbox(
            "Action",
            ["CALL", "WHATSAPP", "COURIER_COORDINATION", "NOTE", "ESCALATION"],
        )
        work_status = st.selectbox(
            "Work Status",
            WORK_STATUS_OPTIONS,
            index=status_index,
        )
        call_result = st.selectbox(
            "Call Result",
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
        customer_response = st.selectbox(
            "Customer Response",
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
        follow_col, time_col = st.columns(2)
        follow_date = follow_col.date_input(
            "Next Date",
            value=None,
            key=f"kanban_follow_date_{agent}_{case_id}",
        )
        follow_time = time_col.time_input(
            "Next Time",
            value=None,
            key=f"kanban_follow_time_{agent}_{case_id}",
        )
        remark = st.text_area("Remark", height=90)
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


def _render_close_form(agent: str, selected: pd.Series) -> None:
    case_id = _text(selected.get("Case ID"))
    with st.expander("Close case"):
        with st.form(f"kanban_close_{agent}_{case_id}"):
            outcome = st.selectbox(
                "Final Outcome",
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
                "Delivered Date",
                value=None,
                key=f"kanban_delivered_date_{agent}_{case_id}",
            )
            closing_remark = st.text_area("Closure Remark", height=80)
            close = st.form_submit_button("Close case", width="stretch")

        if close:
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


def _render_drawer(
    agent: str,
    assigned_all: pd.DataFrame,
    activity: pd.DataFrame,
) -> None:
    selected_id = _text(st.session_state.get(_selected_key(agent), ""))
    with st.container(border=True):
        title_col, close_col = st.columns([4, 1])
        title_col.markdown("### Order panel")
        if close_col.button(
            "✕",
            key=f"kanban_close_drawer_{agent}",
            help="Close order panel",
            width="stretch",
        ):
            st.session_state.pop(_selected_key(agent), None)
            st.rerun()

        if not selected_id:
            st.info("Select an order card to open it here.")
            return

        match = assigned_all[assigned_all["Case ID"].astype(str).eq(selected_id)]
        if match.empty:
            st.warning("The selected order is no longer assigned to this workspace.")
            st.session_state.pop(_selected_key(agent), None)
            return

        selected = match.iloc[0]
        valid_phone = normalize_phone(selected.get("Mobile", ""))
        selected_masks = logistics_case_masks(match)

        st.markdown(f"#### {_text(selected.get('Customer Name')) or 'Unknown customer'}")
        st.caption(f"AWB: {_text(selected.get('AWB')) or 'Unavailable'}")
        st.write(f"**Courier:** {_text(selected.get('Latest Courier Status')) or 'Unavailable'}")
        st.write(f"**Work status:** {_text(selected.get('Logistics Work Status')) or 'NEW'}")
        st.write(f"**Portal:** {_text(selected.get('Portal')) or 'Unavailable'}")
        st.write(f"**Mobile:** {phone_display(selected.get('Mobile', ''))}")
        st.write(f"**Issue:** {_text(selected.get('Courier Remarks')) or 'No remark'}")

        if bool(selected_masks["pending_review"].iloc[0]):
            st.info("Delivered by Tawseel. Review and close the case after confirming recovery credit.")

        if valid_phone:
            st.link_button(
                "📞 Open 3CX",
                threecx_webclient_url(),
                width="stretch",
            )
            st.link_button(
                "💬 Open in DoubleTick",
                doubletick_chat_link(valid_phone),
                width="stretch",
            )
        else:
            st.button("📞 Open 3CX", disabled=True, width="stretch")
            st.button("💬 Open in DoubleTick", disabled=True, width="stretch")
            st.warning("No valid customer mobile number is available.")

        case_history = activity[activity["Case ID"].astype(str).eq(selected_id)].copy()
        if not case_history.empty:
            with st.expander(f"Activity history ({len(case_history)})"):
                st.dataframe(
                    case_history.sort_values("Action At", ascending=False),
                    width="stretch",
                    hide_index=True,
                    height=240,
                )

        st.markdown("#### Update order")
        _render_activity_form(agent, selected)
        _render_close_form(agent, selected)


def render_logistics_kanban_workspace(
    *,
    agent: str,
    all_cases: pd.DataFrame,
    activity: pd.DataFrame,
) -> None:
    """Render an agent-specific Kanban board and right-side update panel."""
    assigned_all = all_cases[
        all_cases["Logistics Agent"].astype(str).str.upper().eq(agent.upper())
    ].copy()
    masks = logistics_case_masks(assigned_all)
    open_all = _sort_latest(assigned_all[~masks["closed"]].copy())

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

    search_col, portal_col, date_col, limit_col = st.columns([2.2, 1.25, 1.25, 1])
    query = search_col.text_input(
        "Search",
        placeholder="AWB, customer, mobile or remark",
        key=f"kanban_search_{agent}",
    )
    portals = sorted(value for value in open_all["Portal"].astype(str).unique() if value)
    portal = portal_col.selectbox(
        "Portal",
        ["All Portals", *portals],
        key=f"kanban_portal_{agent}",
    )
    available_dates = _available_status_dates(open_all)
    status_date = date_col.selectbox(
        "Status Date",
        ["All Dates", *available_dates],
        key=f"kanban_status_date_{agent}",
    )
    card_limit = limit_col.selectbox(
        "Cards / column",
        [15, 30, 60, 100],
        index=1,
        key=f"kanban_limit_{agent}",
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

    board_area, drawer_area = st.columns([3.75, 1.45], gap="large")
    with board_area:
        st.caption("Orders are grouped by current logistics work stage. Select a card to update it.")
        stage_columns = st.columns(len(BOARD_STAGES), gap="small")
        for stage, column in zip(BOARD_STAGES, stage_columns):
            stage_cases = board_cases[board_cases["_kanban_stage"].eq(stage)].copy()
            with column:
                st.markdown(f"#### {stage}")
                st.caption(f"{len(stage_cases)} orders")
                with st.container(height=650, border=True):
                    if stage_cases.empty:
                        st.caption("No orders")
                    else:
                        for _, row in stage_cases.head(card_limit).iterrows():
                            _render_card(agent, row, stage)
                        hidden = len(stage_cases) - min(len(stage_cases), card_limit)
                        if hidden > 0:
                            st.info(f"{hidden} more orders. Increase Cards / column or filter the board.")

    with drawer_area:
        _render_drawer(agent, assigned_all, activity)
