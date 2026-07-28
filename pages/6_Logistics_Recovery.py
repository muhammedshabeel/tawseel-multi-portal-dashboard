from __future__ import annotations

from datetime import date, datetime

import pandas as pd
import streamlit as st

from src.logistics import (
    AGENTS,
    add_activity,
    close_case,
    load_activity,
    load_cases,
    logistics_summary,
    sync_logistics_cases,
)

st.set_page_config(page_title="Logistics Recovery", page_icon="🚚", layout="wide")

st.title("🚚 Logistics Recovery")
st.caption(
    "Independent logistics workspace. This module does not update the existing Tawseel dashboard, "
    "DELIVERED, OFD, RTO, or other operational tabs."
)

with st.sidebar:
    st.subheader("Logistics controls")
    if st.button("Sync critical & follow-up orders", type="primary", use_container_width=True):
        with st.spinner("Reading Tawseel data and synchronizing the isolated logistics queue..."):
            try:
                result = sync_logistics_cases()
                st.success(
                    f"Sync complete: {result['created']} new, {result['updated']} refreshed, "
                    f"{result['eligible']} eligible."
                )
                st.cache_data.clear()
                st.rerun()
            except Exception as exc:
                st.error(f"Logistics sync failed: {exc}")

    st.info("All agent work is stored only in the separate Logistics Recovery spreadsheet.")

try:
    cases = load_cases()
    activity = load_activity()
except Exception as exc:
    st.error(f"Unable to load logistics data: {exc}")
    st.stop()

overall, agent_summary = logistics_summary(cases)

metrics = st.columns(5)
metrics[0].metric("Assigned cases", f"{int(overall['Assigned']):,}")
metrics[1].metric("Active cases", f"{int(overall['Active']):,}")
metrics[2].metric("Closed cases", f"{int(overall['Closed']):,}")
metrics[3].metric("Recovered deliveries", f"{int(overall['Delivered After Coordination']):,}")
metrics[4].metric("Recovery rate", f"{float(overall['Recovery Rate']):.1%}")

overview_tab, queue_tab, agent_tab, activity_tab, admin_tab = st.tabs(
    ["Overview", "Active Queue", "Agent Workspace", "Activity Log", "Admin"]
)

with overview_tab:
    st.subheader("Agent performance")
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
            .rename_axis("Logistics Status")
            .reset_index(name="Cases")
        )
        st.subheader("Separate logistics status mix")
        st.dataframe(status_summary, use_container_width=True, hide_index=True)

with queue_tab:
    st.subheader("Active logistics queue")
    if cases.empty:
        st.info("No cases available. Run a logistics sync.")
    else:
        work = cases.copy()
        work["Logistics Work Status"] = work["Logistics Work Status"].fillna("").astype(str)
        active = work[~work["Logistics Work Status"].str.upper().eq("CLOSED")].copy()

        f1, f2, f3 = st.columns(3)
        agent_filter = f1.multiselect("Agent", AGENTS, default=[])
        priority_options = sorted(v for v in active["Priority"].dropna().astype(str).unique() if v)
        priority_filter = f2.multiselect("Priority", priority_options, default=[])
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
            "Case ID", "Portal", "AWB", "Customer Name", "Mobile", "Latest Courier Status",
            "Courier Remarks", "Priority", "Logistics Agent", "Assigned At",
            "Logistics Work Status", "Total Call Attempts", "Last Call Status",
            "Customer Response", "Next Follow-up", "Agent Remark",
        ]
        st.dataframe(active[display_columns], use_container_width=True, hide_index=True, height=560)

with agent_tab:
    selected_agent = st.selectbox("Logistics agent", AGENTS)
    assigned = cases[cases["Logistics Agent"].astype(str).str.upper().eq(selected_agent)] if not cases.empty else cases
    active_assigned = assigned[~assigned["Logistics Work Status"].astype(str).str.upper().eq("CLOSED")]

    cards = st.columns(4)
    cards[0].metric("Assigned", len(assigned))
    cards[1].metric("Active", len(active_assigned))
    cards[2].metric(
        "Calls recorded",
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
        selected_label = st.selectbox("Select assigned order", list(case_labels))
        selected_case_id = case_labels[selected_label]
        selected = active_assigned[active_assigned["Case ID"].astype(str).eq(selected_case_id)].iloc[0]

        c1, c2, c3 = st.columns(3)
        c1.write(f"**Portal:** {selected['Portal']}")
        c1.write(f"**AWB:** {selected['AWB']}")
        c2.write(f"**Customer:** {selected['Customer Name']}")
        c2.write(f"**Mobile:** {selected['Mobile']}")
        c3.write(f"**Courier status:** {selected['Latest Courier Status']}")
        c3.write(f"**Issue:** {selected['Courier Remarks']}")

        with st.form("activity_form", clear_on_submit=True):
            action_type = st.selectbox("Action", ["CALL", "WHATSAPP", "COURIER_COORDINATION", "NOTE", "ESCALATION"])
            call_result = st.selectbox(
                "Call result",
                ["", "Answered", "No Answer", "Switched Off", "Busy", "Invalid Number", "Call Back Later"],
            )
            customer_response = st.selectbox(
                "Customer response",
                ["", "Will Receive", "Requested Reschedule", "Customer Unavailable", "Location Changed",
                 "Payment Issue", "Not Interested", "Order Cancelled", "Already Delivered", "Other"],
            )
            new_status = st.selectbox(
                "Logistics work status",
                ["IN PROGRESS", "FOLLOW-UP DUE", "CUSTOMER CONTACTED", "RESCHEDULED",
                 "AWAITING COURIER", "ESCALATED", "UNRESOLVED"],
            )
            next_date = st.date_input("Next follow-up date", value=None)
            next_time = st.time_input("Next follow-up time", value=None)
            remark = st.text_area("Detailed remark", placeholder="Record what happened and the next action...")
            submitted = st.form_submit_button("Save activity", type="primary")

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
                st.success("Activity saved to the separate logistics audit log.")
                st.rerun()
            except Exception as exc:
                st.error(f"Could not save activity: {exc}")

        with st.expander("Close this logistics case"):
            with st.form("close_form"):
                outcome = st.selectbox(
                    "Final logistics outcome",
                    ["Delivered After Logistics Follow-up", "Rescheduled", "Customer Cancelled",
                     "Confirmed RTO", "Back to Store", "Invalid Customer", "Duplicate", "Unresolved", "Escalated"],
                )
                recovered = st.checkbox("Delivered after logistics coordination")
                delivered_date = st.date_input("Logistics delivered date", value=None)
                close_remark = st.text_area("Closure remark")
                close_submit = st.form_submit_button("Close logistics case")
            if close_submit:
                try:
                    close_case(
                        selected_case_id,
                        outcome=outcome,
                        delivered_after_coordination=recovered,
                        delivered_date=str(delivered_date or ""),
                        remark=close_remark,
                    )
                    st.success("Case closed inside the logistics module only.")
                    st.rerun()
                except Exception as exc:
                    st.error(f"Could not close case: {exc}")

with activity_tab:
    st.subheader("Append-only logistics activity history")
    if activity.empty:
        st.info("No activities recorded yet.")
    else:
        activity_view = activity.sort_values("Action At", ascending=False)
        st.dataframe(activity_view, use_container_width=True, hide_index=True, height=650)

with admin_tab:
    st.subheader("Isolation and control")
    st.success("This module uses a separate spreadsheet and separate logistics statuses.")
    st.markdown(
        "- Existing Tawseel dashboard metrics are not modified.\n"
        "- Existing DELIVERED, OFD, RTO, and other operational tabs are not written to.\n"
        "- Agent activity history remains in LOGISTICS_ACTIVITY_LOG.\n"
        "- Courier status is read as source information; logistics status is maintained separately."
    )
    st.write("**Configured logistics agents:**", ", ".join(AGENTS))
