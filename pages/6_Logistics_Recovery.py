from __future__ import annotations

from urllib.parse import quote

import pandas as pd
import streamlit as st

from src.logistics import (
    AGENTS,
    DEFAULT_LOGISTICS_SHEET_ID,
    add_activity,
    close_case,
    load_activity,
    load_cases,
    logistics_summary,
    sync_logistics_cases,
)

st.set_page_config(page_title="Logistics Recovery CRM", page_icon="🚚", layout="wide")


def _error_text(exc: Exception) -> str:
    message = str(exc).strip()
    return f"{type(exc).__name__}: {message}" if message else type(exc).__name__


def _service_account_email() -> str:
    try:
        return str(dict(st.secrets["google_service_account"]).get("client_email", "")).strip()
    except Exception:
        return ""


def _logistics_sheet_id() -> str:
    try:
        return str(st.secrets.get("logistics", {}).get("sheet_id", DEFAULT_LOGISTICS_SHEET_ID)).strip()
    except Exception:
        return DEFAULT_LOGISTICS_SHEET_ID


def _clean_phone(value: object) -> str:
    raw = "" if value is None else str(value)
    digits = "".join(ch for ch in raw if ch.isdigit())
    if digits.startswith("00"):
        digits = digits[2:]
    return digits


def _phone_href(value: object) -> str:
    digits = _clean_phone(value)
    return f"tel:+{digits}" if digits else "#"


def _whatsapp_href(value: object, customer: str, awb: str) -> str:
    digits = _clean_phone(value)
    text = (
        f"Hello {customer}, this is the Emarath Logistics Team regarding your order "
        f"{awb}. We are contacting you to coordinate the delivery."
    )
    return f"https://wa.me/{digits}?text={quote(text)}" if digits else "#"


st.title("🚚 Logistics Recovery CRM")

with st.sidebar:
    st.subheader("Workspace")
    workspace_identity = st.selectbox("Working as", ["MANAGER", *AGENTS])

    st.divider()
    if st.button("Sync orders", type="primary", use_container_width=True):
        with st.spinner("Syncing logistics cases..."):
            try:
                result = sync_logistics_cases()
                st.success(
                    f"{result['created']} new · {result['updated']} updated · {result['eligible']} eligible"
                )
                st.cache_data.clear()
                st.rerun()
            except Exception as exc:
                st.error(f"Sync failed — {_error_text(exc)}")

try:
    cases = load_cases()
    activity = load_activity()
except Exception as exc:
    service_email = _service_account_email()
    sheet_id = _logistics_sheet_id()

    st.error(f"Connection required — {_error_text(exc)}")
    st.subheader("Connect the logistics database")

    if service_email:
        st.write("Share the Logistics Recovery spreadsheet with this email as **Editor**:")
        st.code(service_email)
    else:
        st.warning("Google service-account details are missing from Streamlit secrets.")

    st.link_button(
        "Open Logistics Recovery spreadsheet",
        f"https://docs.google.com/spreadsheets/d/{sheet_id}/edit",
    )

    with st.expander("Diagnostic details"):
        st.code(repr(exc))
        st.write(f"Spreadsheet ID: {sheet_id}")
    st.stop()

overall, agent_summary = logistics_summary(cases)

metrics = st.columns(5)
metrics[0].metric("Assigned", f"{int(overall['Assigned']):,}")
metrics[1].metric("Active", f"{int(overall['Active']):,}")
metrics[2].metric("Closed", f"{int(overall['Closed']):,}")
metrics[3].metric("Recovered", f"{int(overall['Delivered After Coordination']):,}")
metrics[4].metric("Recovery Rate", f"{float(overall['Recovery Rate']):.1%}")

if workspace_identity == "MANAGER":
    overview_tab, queue_tab, agent_tab, activity_tab = st.tabs(
        ["Overview", "Active Queue", "Agent Workspace", "Activity Log"]
    )
else:
    agent_tab, activity_tab = st.tabs(["My Cases", "My Activity"])
    overview_tab = queue_tab = None

if overview_tab is not None:
    with overview_tab:
        st.subheader("Agent Performance")
        if agent_summary.empty:
            st.info("No logistics cases have been assigned yet.")
        else:
            st.dataframe(
                agent_summary.style.format({"Recovery Rate": "{:.1%}"}),
                use_container_width=True,
                hide_index=True,
            )

        if not cases.empty:
            status_summary = (
                cases["Logistics Work Status"]
                .fillna("")
                .replace("", "UNSPECIFIED")
                .value_counts()
                .rename_axis("Status")
                .reset_index(name="Cases")
            )
            st.subheader("Status Summary")
            st.dataframe(status_summary, use_container_width=True, hide_index=True)

if queue_tab is not None:
    with queue_tab:
        st.subheader("Active Queue")
        if cases.empty:
            st.info("No cases available. Run a sync.")
        else:
            work = cases.copy()
            work["Logistics Work Status"] = work["Logistics Work Status"].fillna("").astype(str)
            active = work[~work["Logistics Work Status"].str.upper().eq("CLOSED")].copy()

            f1, f2, f3 = st.columns(3)
            agent_filter = f1.multiselect("Agent", AGENTS, default=[])
            priorities = sorted(v for v in active["Priority"].dropna().astype(str).unique() if v)
            priority_filter = f2.multiselect("Priority", priorities, default=[])
            search_text = f3.text_input("Search AWB, customer, or mobile")

            if agent_filter:
                active = active[active["Logistics Agent"].astype(str).isin(agent_filter)]
            if priority_filter:
                active = active[active["Priority"].astype(str).isin(priority_filter)]
            if search_text.strip():
                needle = search_text.strip().casefold()
                mask = (
                    active["AWB"].astype(str).str.casefold().str.contains(needle, regex=False)
                    | active["Customer Name"].astype(str).str.casefold().str.contains(needle, regex=False)
                    | active["Mobile"].astype(str).str.casefold().str.contains(needle, regex=False)
                )
                active = active[mask]

            display_columns = [
                "Portal", "AWB", "Customer Name", "Mobile", "Latest Courier Status",
                "Courier Remarks", "Priority", "Logistics Agent", "Assigned At",
                "Logistics Work Status", "Total Call Attempts", "Last Call Status",
                "Customer Response", "Next Follow-up", "Agent Remark",
            ]
            st.dataframe(active[display_columns], use_container_width=True, hide_index=True, height=560)

with agent_tab:
    selected_agent = st.selectbox("Logistics agent", AGENTS) if workspace_identity == "MANAGER" else workspace_identity
    st.subheader(f"{selected_agent.title()} Workspace")

    assigned = cases[cases["Logistics Agent"].astype(str).str.upper().eq(selected_agent)] if not cases.empty else cases
    active_assigned = assigned[~assigned["Logistics Work Status"].astype(str).str.upper().eq("CLOSED")]

    cards = st.columns(4)
    cards[0].metric("Assigned", len(assigned))
    cards[1].metric("Active", len(active_assigned))
    cards[2].metric(
        "Calls Logged",
        int(pd.to_numeric(assigned.get("Total Call Attempts", pd.Series(dtype=float)), errors="coerce").fillna(0).sum()),
    )
    cards[3].metric(
        "Recovered",
        int(assigned["Delivered After Coordination"].astype(str).str.upper().eq("YES").sum()) if not assigned.empty else 0,
    )

    if active_assigned.empty:
        st.info(f"No active cases assigned to {selected_agent}.")
    else:
        case_labels = {
            f"{row['AWB']} — {row['Customer Name']} — {row['Latest Courier Status']}": row["Case ID"]
            for _, row in active_assigned.iterrows()
        }
        selected_label = st.selectbox("Select order", list(case_labels))
        selected_case_id = case_labels[selected_label]
        selected = active_assigned[active_assigned["Case ID"].astype(str).eq(selected_case_id)].iloc[0]

        info1, info2, info3 = st.columns(3)
        info1.write(f"**Portal:** {selected['Portal']}")
        info1.write(f"**AWB:** {selected['AWB']}")
        info2.write(f"**Customer:** {selected['Customer Name']}")
        info2.write(f"**Mobile:** {selected['Mobile']}")
        info3.write(f"**Courier Status:** {selected['Latest Courier Status']}")
        info3.write(f"**Issue:** {selected['Courier Remarks']}")

        action1, action2, action3 = st.columns([1, 1, 2])
        with action1:
            st.link_button(
                "📞 Call with 3CX",
                _phone_href(selected["Mobile"]),
                use_container_width=True,
            )
        with action2:
            st.link_button(
                "💬 Open WhatsApp",
                _whatsapp_href(
                    selected["Mobile"],
                    str(selected["Customer Name"]),
                    str(selected["AWB"]),
                ),
                use_container_width=True,
            )
        with action3:
            st.caption("3CX must be configured as the default handler for telephone links on the agent's device.")

        recent = activity[activity["Case ID"].astype(str).eq(selected_case_id)].copy()
        if not recent.empty:
            with st.expander("Recent activity", expanded=False):
                st.dataframe(
                    recent.sort_values("Action At", ascending=False).head(10),
                    use_container_width=True,
                    hide_index=True,
                )

        st.divider()
        with st.form("activity_form", clear_on_submit=True):
            col1, col2 = st.columns(2)
            action_type = col1.selectbox("Action", ["CALL", "WHATSAPP", "COURIER_COORDINATION", "NOTE", "ESCALATION"])
            new_status = col2.selectbox(
                "Work Status",
                ["IN PROGRESS", "FOLLOW-UP DUE", "CUSTOMER CONTACTED", "RESCHEDULED",
                 "AWAITING COURIER", "ESCALATED", "UNRESOLVED"],
            )

            col3, col4 = st.columns(2)
            call_result = col3.selectbox(
                "Call Result",
                ["", "Answered", "No Answer", "Switched Off", "Busy", "Invalid Number", "Call Back Later"],
            )
            customer_response = col4.selectbox(
                "Customer Response",
                ["", "Will Receive", "Requested Reschedule", "Customer Unavailable", "Location Changed",
                 "Payment Issue", "Not Interested", "Order Cancelled", "Already Delivered", "Other"],
            )

            col5, col6 = st.columns(2)
            next_date = col5.date_input("Next Follow-up Date", value=None)
            next_time = col6.time_input("Next Follow-up Time", value=None)
            remark = st.text_area("Remark", placeholder="Add call notes, customer response, and next action...")
            submitted = st.form_submit_button("Save Activity", type="primary", use_container_width=True)

        if submitted:
            next_follow_up = ""
            if next_date:
                next_follow_up = str(next_date)
                if next_time:
                    next_follow_up = f"{next_date} {next_time.strftime('%H:%M')}"
            try:
                add_activity(
                    selected_case_id,
                    action_type=action_type,
                    call_result=call_result,
                    customer_response=customer_response,
                    remark=remark,
                    next_follow_up=next_follow_up,
                    new_status=new_status,
                )
                st.success("Activity saved.")
                st.rerun()
            except Exception as exc:
                st.error(f"Could not save activity — {_error_text(exc)}")

        with st.expander("Close Case"):
            with st.form("close_form"):
                outcome = st.selectbox(
                    "Final Outcome",
                    ["Delivered After Logistics Follow-up", "Rescheduled", "Customer Cancelled",
                     "Confirmed RTO", "Back to Store", "Invalid Customer", "Duplicate", "Unresolved", "Escalated"],
                )
                recovered = st.checkbox("Delivered after logistics coordination")
                delivered_date = st.date_input("Delivered Date", value=None)
                close_remark = st.text_area("Closure Remark")
                close_submit = st.form_submit_button("Close Case", use_container_width=True)
            if close_submit:
                try:
                    close_case(
                        selected_case_id,
                        outcome=outcome,
                        delivered_after_coordination=recovered,
                        delivered_date=str(delivered_date or ""),
                        remark=close_remark,
                    )
                    st.success("Case closed.")
                    st.rerun()
                except Exception as exc:
                    st.error(f"Could not close case — {_error_text(exc)}")

with activity_tab:
    st.subheader("Activity History" if workspace_identity == "MANAGER" else "My Activity")
    activity_view = activity.copy()
    if workspace_identity != "MANAGER" and not activity_view.empty:
        activity_view = activity_view[
            activity_view["Logistics Agent"].astype(str).str.upper().eq(workspace_identity)
        ]
    if activity_view.empty:
        st.info("No activities recorded yet.")
    else:
        st.dataframe(
            activity_view.sort_values("Action At", ascending=False),
            use_container_width=True,
            hide_index=True,
            height=650,
        )
