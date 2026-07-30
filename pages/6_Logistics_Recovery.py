from __future__ import annotations

from datetime import date

import pandas as pd
import streamlit as st

from src.logistics import AGENTS, DEFAULT_LOGISTICS_SHEET_ID, load_activity, load_cases
from src.logistics_contact_fallback import fill_missing_customer_phones
from src.logistics_dashboard_metrics import logistics_case_masks, logistics_dashboard_summary
from src.logistics_integrations import enrich_case_contacts, phone_display
from src.logistics_kanban_runtime import render_logistics_kanban_compact
from src.logistics_reporting import (
    daily_agent_report,
    daily_case_details,
    save_daily_report_snapshot,
)
from src.logistics_status_tracking import (
    enrich_cases_with_status_updates,
    sync_logistics_cases_with_status_tracking,
)

st.set_page_config(page_title="Logistics Recovery", page_icon="🚚", layout="wide")


def _error_text(exc: Exception) -> str:
    text = str(exc).strip()
    return f"{type(exc).__name__}: {text}" if text else type(exc).__name__


def _sheet_id() -> str:
    try:
        return str(
            st.secrets.get("logistics", {}).get(
                "sheet_id", DEFAULT_LOGISTICS_SHEET_ID
            )
        ).strip()
    except Exception:
        return DEFAULT_LOGISTICS_SHEET_ID


def _service_email() -> str:
    try:
        return str(
            dict(st.secrets["google_service_account"]).get("client_email", "")
        ).strip()
    except Exception:
        return ""


def _safe_frame(df: pd.DataFrame) -> pd.DataFrame:
    if df.empty:
        return df
    safe = df.copy()
    for column in safe.columns:
        if pd.api.types.is_datetime64_any_dtype(safe[column]):
            safe[column] = safe[column].dt.strftime("%Y-%m-%d %H:%M:%S").fillna("")
        elif safe[column].dtype == "object":
            safe[column] = safe[column].map(
                lambda value: "" if pd.isna(value) else str(value)
            )
    return safe


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
    return work.sort_values(
        ["_status_sort", "_priority_sort", "Assigned At"],
        ascending=[False, True, False],
        na_position="last",
    ).drop(columns=["_status_sort", "_priority_sort"], errors="ignore")


st.title("🚚 Logistics Recovery")

with st.sidebar:
    st.subheader("Workspace")
    identity = st.selectbox("Working as", ["MANAGER", *AGENTS])
    st.divider()
    sync_clicked = st.button("Sync Orders", type="primary", width="stretch")

if sync_clicked:
    with st.spinner("Syncing logistics orders..."):
        try:
            result = sync_logistics_cases_with_status_tracking()
            st.success(
                f"Sync completed: {result['created']} new, {result['updated']} refreshed, "
                f"{result.get('status_changed', 0)} status changes detected."
            )
            st.cache_data.clear()
            st.rerun()
        except Exception as exc:
            st.error(f"Sync failed — {_error_text(exc)}")

with st.spinner("Loading logistics workspace..."):
    try:
        all_cases = enrich_case_contacts(load_cases())
        all_cases = fill_missing_customer_phones(all_cases)
        all_cases = enrich_cases_with_status_updates(all_cases)
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

all_cases = _safe_frame(all_cases)
activity = _safe_frame(activity)
overall, agent_summary = logistics_dashboard_summary(all_cases)

k1, k2, k3, k4, k5, k6, k7, k8, k9 = st.columns(9)
k1.metric("Assigned", int(overall["Assigned"]))
k2.metric("Active", int(overall["Active"]))
k3.metric("RTO", int(overall["RTO"]))
k4.metric("Recovered from RTO", int(overall["Recovered from RTO"]))
k5.metric("Tawseel Delivered", int(overall["Tawseel Delivered"]))
k6.metric("Pending Review", int(overall["Delivered Pending Review"]))
k7.metric("Closed", int(overall["Closed"]))
k8.metric("Recovered", int(overall["Delivered After Coordination"]))
k9.metric("Recovery Rate", f"{float(overall['Recovery Rate']):.1%}")

if identity == "MANAGER":
    overview_tab, queue_tab, review_tab, workspace_tab, report_tab, history_tab = st.tabs(
        [
            "Overview",
            "Active Queue",
            "Delivered Review",
            "Agent Workspace",
            "Daily Report",
            "Activity History",
        ]
    )
else:
    workspace_tab, report_tab, history_tab = st.tabs(
        ["My Cases", "My Daily Report", "My Activity"]
    )
    overview_tab = queue_tab = review_tab = None

if overview_tab is not None:
    with overview_tab:
        st.subheader("Agent Performance")
        if agent_summary.empty:
            st.info("No logistics cases have been assigned.")
        else:
            summary = _safe_frame(agent_summary)
            summary["Recovery Rate"] = pd.to_numeric(
                summary["Recovery Rate"], errors="coerce"
            ).fillna(0)
            st.dataframe(
                summary,
                width="stretch",
                hide_index=True,
                column_config={
                    "Recovery Rate": st.column_config.ProgressColumn(
                        format="percent", min_value=0, max_value=1
                    )
                },
            )

        if not all_cases.empty:
            status_summary = (
                all_cases["Latest Courier Status"]
                .replace("", "UNSPECIFIED")
                .value_counts()
                .rename_axis("Tawseel Status")
                .reset_index(name="Cases")
            )
            st.subheader("Latest Tawseel Status Summary")
            st.dataframe(_safe_frame(status_summary), width="stretch", hide_index=True)

if queue_tab is not None:
    with queue_tab:
        st.subheader("Active Queue")
        masks = logistics_case_masks(all_cases)
        active = _sort_latest(all_cases[masks["active"]].copy())
        if active.empty:
            st.success("No active logistics cases available.")
        else:
            f1, f2, f3 = st.columns(3)
            selected_agents = f1.multiselect("Agent", AGENTS)
            priorities = sorted(value for value in active["Priority"].unique() if value)
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
                "Courier Remarks", "Priority", "Logistics Agent", "Logistics Work Status",
                "Total Call Attempts", "Last Call Status", "Customer Response", "Next Follow-up",
            ]
            queue_view = active[[column for column in columns if column in active.columns]].copy()
            if "Mobile" in queue_view.columns:
                queue_view["Mobile"] = queue_view["Mobile"].map(phone_display)
            st.dataframe(_safe_frame(queue_view), width="stretch", hide_index=True, height=560)

if review_tab is not None:
    with review_tab:
        st.subheader("Delivered Pending Review")
        pending = _sort_latest(
            all_cases[logistics_case_masks(all_cases)["pending_review"]].copy()
        )
        if pending.empty:
            st.success("No delivered cases are waiting for logistics review.")
        else:
            columns = [
                "Portal", "AWB", "Customer Name", "Mobile", "Latest Courier Status",
                "Logistics Agent", "Logistics Work Status", "Last Call Status",
                "Customer Response", "Agent Remark", "Tawseel Status Updated At",
            ]
            review_view = pending[[column for column in columns if column in pending.columns]].copy()
            if "Mobile" in review_view.columns:
                review_view["Mobile"] = review_view["Mobile"].map(phone_display)
            st.dataframe(_safe_frame(review_view), width="stretch", hide_index=True, height=560)

with workspace_tab:
    agent = st.selectbox("Agent", AGENTS) if identity == "MANAGER" else identity
    render_logistics_kanban_compact(agent=agent, all_cases=all_cases, activity=activity)

with report_tab:
    st.subheader("Daily Agent Report" if identity == "MANAGER" else "My Daily Report")
    report_date = st.date_input("Report Date", value=date.today(), key="daily_report_date")
    daily_report = daily_agent_report(all_cases, activity, report_date)
    if identity != "MANAGER":
        daily_report = daily_report[daily_report["Agent"].eq(identity)]
    if daily_report.empty:
        st.info("No report data available for this date.")
    else:
        display_report = daily_report.copy()
        display_report["Recovery Rate"] = pd.to_numeric(
            display_report["Recovery Rate"], errors="coerce"
        ).fillna(0)
        st.dataframe(
            display_report,
            width="stretch",
            hide_index=True,
            column_config={
                "Recovery Rate": st.column_config.ProgressColumn(
                    format="percent", min_value=0, max_value=1
                )
            },
        )
        totals = daily_report.sum(numeric_only=True)
        r1, r2, r3, r4, r5 = st.columns(5)
        r1.metric("Handled Orders", int(totals.get("Handled Orders", 0)))
        r2.metric("Calls Logged", int(totals.get("Calls Logged", 0)))
        r3.metric("Answered Calls", int(totals.get("Answered Calls", 0)))
        r4.metric("Closed", int(totals.get("Closed", 0)))
        r5.metric("Recovered", int(totals.get("Recovered", 0)))
        details = daily_case_details(
            all_cases,
            activity,
            report_date,
            None if identity == "MANAGER" else identity,
        )
        st.subheader("Orders Handled")
        if details.empty:
            st.info("No order activity recorded on this date.")
        else:
            if "Mobile" in details.columns:
                details["Mobile"] = details["Mobile"].map(phone_display)
            st.dataframe(_safe_frame(details), width="stretch", hide_index=True, height=520)
        if identity == "MANAGER":
            if st.button("Save Daily Report to Google Sheets", width="stretch"):
                try:
                    saved = save_daily_report_snapshot(report_date, daily_report)
                    st.success(f"Saved {saved} agent report rows to LOGISTICS_DAILY_REPORT.")
                except Exception as exc:
                    st.error(f"Could not save daily report — {_error_text(exc)}")

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
            width="stretch",
            hide_index=True,
            height=650,
        )
