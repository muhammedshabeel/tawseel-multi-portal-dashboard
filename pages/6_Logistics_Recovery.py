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

st.set_page_config(page_title="Logistics Recovery", page_icon="🚚", layout="wide")


def _error_text(exc: Exception) -> str:
    text = str(exc).strip()
    return f"{type(exc).__name__}: {text}" if text else type(exc).__name__


def _sheet_id() -> str:
    try:
        return str(st.secrets.get("logistics", {}).get("sheet_id", DEFAULT_LOGISTICS_SHEET_ID)).strip()
    except Exception:
        return DEFAULT_LOGISTICS_SHEET_ID


def _service_email() -> str:
    try:
        return str(dict(st.secrets["google_service_account"]).get("client_email", "")).strip()
    except Exception:
        return ""


def _phone_digits(value: object) -> str:
    digits = "".join(ch for ch in str(value or "") if ch.isdigit())
    return digits[2:] if digits.startswith("00") else digits


def _call_link(value: object) -> str:
    digits = _phone_digits(value)
    return f"tel:+{digits}" if digits else "#"


def _whatsapp_link(value: object, customer: str, awb: str) -> str:
    digits = _phone_digits(value)
    message = quote(
        f"Hello {customer}, this is the Emarath Logistics Team regarding order {awb}. "
        "We are contacting you to coordinate delivery."
    )
    return f"https://wa.me/{digits}?text={message}" if digits else "#"


def _safe_frame(df: pd.DataFrame) -> pd.DataFrame:
    if df.empty:
        return df
    safe = df.copy()
    for column in safe.columns:
        if pd.api.types.is_datetime64_any_dtype(safe[column]):
            safe[column] = safe[column].dt.strftime("%Y-%m-%d %H:%M:%S").fillna("")
        elif safe[column].dtype == "object":
            safe[column] = safe[column].map(lambda value: "" if pd.isna(value) else str(value))
    return safe


st.title("🚚 Logistics Recovery")

with st.sidebar:
    st.subheader("Workspace")
    identity = st.selectbox("Working as", ["MANAGER", *AGENTS])
    st.divider()
    sync_clicked = st.button("Sync Orders", type="primary", use_container_width=True)

if sync_clicked:
    with st.spinner("Syncing logistics orders..."):
        try:
            result = sync_logistics_cases()
            st.success(
                f"Sync completed: {result['created']} new, {result['updated']} updated, "
                f"{result['eligible']} eligible."
            )
            st.cache_data.clear()
        except Exception as exc:
            st.error(f"Sync failed — {_error_text(exc)}")

with st.spinner("Loading logistics workspace..."):
    try:
        cases = load_cases()
        activity = load_activity()
    except Exception as exc:
        st.error(f"Unable to open logistics workspace — {_error_text(exc)}")
        email = _service_email()
        if email:
            st.write("Share the Logistics Recovery spreadsheet with this service account as Editor:")
            st.code(email)
        st.link_button(
            "Open Logistics Spreadsheet",
            f"https://docs.google.com/spreadsheets/d/{_sheet_id()}/edit",
        )
        with st.expander("Technical details"):
            st.code(repr(exc))
        st.stop()

cases = _safe_frame(cases)
activity = _safe_frame(activity)
overall, agent_summary = logistics_summary(cases)

k1, k2, k3, k4, k5 = st.columns(5)
k1.metric("Assigned", int(overall["Assigned"]))
k2.metric("Active", int(overall["Active"]))
k3.metric("Closed", int(overall["Closed"]))
k4.metric("Recovered", int(overall["Delivered After Coordination"]))
k5.metric("Recovery Rate", f"{float(overall['Recovery Rate']):.1%}")

if identity == "MANAGER":
    overview_tab, queue_tab, workspace_tab, history_tab = st.tabs(
        ["Overview", "Active Queue", "Agent Workspace", "Activity History"]
    )
else:
    workspace_tab, history_tab = st.tabs(["My Cases", "My Activity"])
    overview_tab = queue_tab = None

if overview_tab is not None:
    with overview_tab:
        st.subheader("Agent Performance")
        if agent_summary.empty:
            st.info("No cases have been assigned yet.")
        else:
            summary = _safe_frame(agent_summary)
            summary["Recovery Rate"] = pd.to_numeric(summary["Recovery Rate"], errors="coerce").fillna(0)
            st.dataframe(
                summary,
                use_container_width=True,
                hide_index=True,
                column_config={"Recovery Rate": st.column_config.ProgressColumn(format="percent", min_value=0, max_value=1)},
            )

        if not cases.empty:
            status_summary = (
                cases["Logistics Work Status"].replace("", "UNSPECIFIED").value_counts()
                .rename_axis("Status").reset_index(name="Cases")
            )
            st.subheader("Status Summary")
            st.dataframe(_safe_frame(status_summary), use_container_width=True, hide_index=True)

if queue_tab is not None:
    with queue_tab:
        st.subheader("Active Queue")
        if cases.empty:
            st.info("No logistics cases available. Click Sync Orders.")
        else:
            active = cases[~cases["Logistics Work Status"].str.upper().eq("CLOSED")].copy()
            f1, f2, f3 = st.columns(3)
            selected_agents = f1.multiselect("Agent", AGENTS)
            priorities = sorted(v for v in active["Priority"].unique() if v)
            selected_priorities = f2.multiselect("Priority", priorities)
            query = f3.text_input("Search AWB, customer, or mobile")

            if selected_agents:
                active = active[active["Logistics Agent"].isin(selected_agents)]
            if selected_priorities:
                active = active[active["Priority"].isin(selected_priorities)]
            if query.strip():
                needle = query.strip().casefold()
                active = active[
                    active["AWB"].str.casefold().str.contains(needle, regex=False)
                    | active["Customer Name"].str.casefold().str.contains(needle, regex=False)
                    | active["Mobile"].str.casefold().str.contains(needle, regex=False)
                ]

            columns = [
                "Portal", "AWB", "Customer Name", "Mobile", "Latest Courier Status",
                "Courier Remarks", "Priority", "Logistics Agent", "Assigned At",
                "Logistics Work Status", "Total Call Attempts", "Last Call Status",
                "Customer Response", "Next Follow-up", "Agent Remark",
            ]
            st.dataframe(_safe_frame(active[columns]), use_container_width=True, hide_index=True, height=560)

with workspace_tab:
    agent = st.selectbox("Agent", AGENTS) if identity == "MANAGER" else identity
    assigned = cases[cases["Logistics Agent"].str.upper().eq(agent)] if not cases.empty else cases
    active_cases = assigned[~assigned["Logistics Work Status"].str.upper().eq("CLOSED")]

    st.subheader(f"{agent.title()} Workspace")
    a1, a2, a3, a4 = st.columns(4)
    a1.metric("Assigned", len(assigned))
    a2.metric("Active", len(active_cases))
    a3.metric("Calls Logged", int(pd.to_numeric(assigned.get("Total Call Attempts", 0), errors="coerce").fillna(0).sum()))
    a4.metric("Recovered", int(assigned["Delivered After Coordination"].str.upper().eq("YES").sum()) if not assigned.empty else 0)

    if active_cases.empty:
        st.info("No active cases assigned.")
    else:
        options = {
            f"{row['AWB']} — {row['Customer Name']} — {row['Latest Courier Status']}": row["Case ID"]
            for _, row in active_cases.iterrows()
        }
        selected_label = st.selectbox("Select Order", list(options))
        case_id = options[selected_label]
        selected = active_cases[active_cases["Case ID"].eq(case_id)].iloc[0]

        d1, d2, d3 = st.columns(3)
        d1.write(f"**Portal:** {selected['Portal']}")
        d1.write(f"**AWB:** {selected['AWB']}")
        d2.write(f"**Customer:** {selected['Customer Name']}")
        d2.write(f"**Mobile:** {selected['Mobile']}")
        d3.write(f"**Courier Status:** {selected['Latest Courier Status']}")
        d3.write(f"**Issue:** {selected['Courier Remarks']}")

        b1, b2 = st.columns(2)
        b1.link_button("📞 Call with 3CX", _call_link(selected["Mobile"]), use_container_width=True)
        b2.link_button(
            "💬 Open WhatsApp",
            _whatsapp_link(selected["Mobile"], selected["Customer Name"], selected["AWB"]),
            use_container_width=True,
        )

        case_history = activity[activity["Case ID"].eq(case_id)]
        if not case_history.empty:
            with st.expander("Case Activity"):
                st.dataframe(
                    _safe_frame(case_history.sort_values("Action At", ascending=False)),
                    use_container_width=True,
                    hide_index=True,
                )

        with st.form("save_activity", clear_on_submit=True):
            c1, c2 = st.columns(2)
            action = c1.selectbox("Action", ["CALL", "WHATSAPP", "COURIER_COORDINATION", "NOTE", "ESCALATION"])
            work_status = c2.selectbox(
                "Work Status",
                ["IN PROGRESS", "FOLLOW-UP DUE", "CUSTOMER CONTACTED", "RESCHEDULED", "AWAITING COURIER", "ESCALATED", "UNRESOLVED"],
            )
            c3, c4 = st.columns(2)
            call_result = c3.selectbox("Call Result", ["", "Answered", "No Answer", "Switched Off", "Busy", "Invalid Number", "Call Back Later"])
            customer_response = c4.selectbox(
                "Customer Response",
                ["", "Will Receive", "Requested Reschedule", "Customer Unavailable", "Location Changed", "Payment Issue", "Not Interested", "Order Cancelled", "Already Delivered", "Other"],
            )
            c5, c6 = st.columns(2)
            follow_date = c5.date_input("Next Follow-up Date", value=None)
            follow_time = c6.time_input("Next Follow-up Time", value=None)
            remark = st.text_area("Remark")
            save = st.form_submit_button("Save Activity", type="primary", use_container_width=True)

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
                st.success("Activity saved.")
                st.rerun()
            except Exception as exc:
                st.error(f"Could not save activity — {_error_text(exc)}")

        with st.expander("Close Case"):
            with st.form("close_case_form"):
                outcome = st.selectbox(
                    "Final Outcome",
                    ["Delivered After Logistics Follow-up", "Rescheduled", "Customer Cancelled", "Confirmed RTO", "Back to Store", "Invalid Customer", "Duplicate", "Unresolved", "Escalated"],
                )
                recovered = st.checkbox("Delivered after logistics coordination")
                delivered_date = st.date_input("Delivered Date", value=None)
                closing_remark = st.text_area("Closure Remark")
                close = st.form_submit_button("Close Case", use_container_width=True)
            if close:
                try:
                    close_case(
                        case_id,
                        outcome=outcome,
                        delivered_after_coordination=recovered,
                        delivered_date=str(delivered_date or ""),
                        remark=closing_remark,
                    )
                    st.success("Case closed.")
                    st.rerun()
                except Exception as exc:
                    st.error(f"Could not close case — {_error_text(exc)}")

with history_tab:
    st.subheader("Activity History" if identity == "MANAGER" else "My Activity")
    history = activity.copy()
    if identity != "MANAGER" and not history.empty:
        history = history[history["Logistics Agent"].str.upper().eq(identity)]
    if history.empty:
        st.info("No activity recorded yet.")
    else:
        st.dataframe(
            _safe_frame(history.sort_values("Action At", ascending=False)),
            use_container_width=True,
            hide_index=True,
            height=650,
        )
