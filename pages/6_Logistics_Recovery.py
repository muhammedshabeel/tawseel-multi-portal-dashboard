from __future__ import annotations

from datetime import date

import pandas as pd
import streamlit as st

from src.logistics import (
    AGENTS,
    DEFAULT_LOGISTICS_SHEET_ID,
    add_activity,
    close_case,
    load_activity,
    load_cases,
)
from src.logistics_contact_fallback import fill_missing_customer_phones
from src.logistics_dashboard_metrics import (
    logistics_case_masks,
    logistics_dashboard_summary,
)
from src.logistics_integrations import enrich_case_contacts, normalize_phone, phone_display
from src.logistics_links import doubletick_chat_link, threecx_webclient_url
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
        return df
    work = df.copy()
    work["_status_sort"] = _status_datetimes(work)
    priority = work.get("Priority", pd.Series("", index=work.index)).astype(str).str.upper()
    work["_priority_sort"] = priority.map(
        lambda value: 0 if "CRITICAL" in value else (1 if "FOLLOW" in value else 2)
    )
    return work.sort_values(
        ["_status_sort", "_priority_sort", "Assigned At"],
        ascending=[False, True, False],
        na_position="last",
    ).drop(columns=["_status_sort", "_priority_sort"], errors="ignore")


def _available_status_dates(df: pd.DataFrame) -> list[str]:
    if df.empty:
        return []
    dates = _status_datetimes(df).dt.date.dropna().unique().tolist()
    return [value.isoformat() for value in sorted(dates, reverse=True)]


def _filter_status_date(df: pd.DataFrame, selected_date: str) -> pd.DataFrame:
    if df.empty or selected_date == "All Dates":
        return df.copy()
    wanted = pd.to_datetime(selected_date, errors="coerce").date()
    dates = _status_datetimes(df).dt.date
    return df[dates.eq(wanted)].copy()


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
k3.metric("RTO Assigned", int(overall["RTO Assigned"]))
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
                "Portal",
                "AWB",
                "Customer Name",
                "Mobile",
                "Latest Courier Status",
                "Courier Remarks",
                "Priority",
                "Logistics Agent",
                "Logistics Work Status",
                "Total Call Attempts",
                "Last Call Status",
                "Customer Response",
                "Next Follow-up",
            ]
            available = [column for column in columns if column in active.columns]
            queue_view = active[available].copy()
            if "Mobile" in queue_view.columns:
                queue_view["Mobile"] = queue_view["Mobile"].map(phone_display)
            st.dataframe(
                _safe_frame(queue_view),
                width="stretch",
                hide_index=True,
                height=560,
            )

if review_tab is not None:
    with review_tab:
        st.subheader("Delivered Pending Review")
        pending = all_cases[logistics_case_masks(all_cases)["pending_review"]].copy()
        pending = _sort_latest(pending)
        if pending.empty:
            st.success("No delivered cases are waiting for logistics review.")
        else:
            review_columns = [
                "Portal",
                "AWB",
                "Customer Name",
                "Mobile",
                "Latest Courier Status",
                "Logistics Agent",
                "Logistics Work Status",
                "Last Call Status",
                "Customer Response",
                "Agent Remark",
                "Tawseel Status Updated At",
            ]
            available = [column for column in review_columns if column in pending.columns]
            review_view = pending[available].copy()
            if "Mobile" in review_view.columns:
                review_view["Mobile"] = review_view["Mobile"].map(phone_display)
            st.dataframe(
                _safe_frame(review_view),
                width="stretch",
                hide_index=True,
                height=560,
            )

with workspace_tab:
    agent = st.selectbox("Agent", AGENTS) if identity == "MANAGER" else identity
    assigned_all = all_cases[
        all_cases["Logistics Agent"].str.upper().eq(agent)
    ].copy()
    assigned_masks = logistics_case_masks(assigned_all)
    active_all = _sort_latest(assigned_all[assigned_masks["active"]].copy())
    rto_all = _sort_latest(assigned_all[assigned_masks["rto_open"]].copy())
    pending_all = _sort_latest(assigned_all[assigned_masks["pending_review"]].copy())
    open_all = _sort_latest(
        assigned_all[~assigned_masks["closed"]].copy()
    )

    st.subheader(f"{agent.title()} Workspace")
    a1, a2, a3, a4, a5, a6, a7, a8 = st.columns(8)
    a1.metric("Assigned", len(assigned_all))
    a2.metric("Active", len(active_all))
    a3.metric("RTO Assigned", int(assigned_masks["rto_assigned"].sum()))
    a4.metric("Recovered from RTO", int(assigned_masks["rto_recovered"].sum()))
    a5.metric("Tawseel Delivered", int(assigned_masks["tawseel_delivered"].sum()))
    a6.metric("Pending Review", len(pending_all))
    a7.metric(
        "Calls Logged",
        int(
            pd.to_numeric(
                assigned_all.get("Total Call Attempts", pd.Series(dtype=float)),
                errors="coerce",
            ).fillna(0).sum()
        ),
    )
    a8.metric("Recovered", int(assigned_masks["recovered"].sum()))

    if open_all.empty:
        st.info("No open cases assigned.")
    else:
        selector_col, view_col, date_col = st.columns([4, 1.35, 1.35])
        with view_col:
            case_view = st.selectbox(
                "Case View",
                ["Active Work", "RTO Orders", "Delivered Pending Review", "All Open Cases"],
                index=0 if not active_all.empty else (1 if not rto_all.empty else 2),
            )

        if case_view == "Active Work":
            view_cases = active_all.copy()
        elif case_view == "RTO Orders":
            view_cases = rto_all.copy()
        elif case_view == "Delivered Pending Review":
            view_cases = pending_all.copy()
        else:
            view_cases = open_all.copy()

        available_dates = _available_status_dates(view_cases)
        with date_col:
            selected_status_date = st.selectbox(
                "Status Date",
                ["All Dates", *available_dates],
                index=0,
                help="Filter assigned orders by the date the latest Tawseel status was detected.",
            )

        active_cases = _sort_latest(
            _filter_status_date(view_cases, selected_status_date)
        )

        if active_cases.empty:
            st.info("No assigned orders match the selected view and status date.")
        else:
            options = {
                f"{row['AWB']} — {row['Customer Name']} — {row['Latest Courier Status']}": row["Case ID"]
                for _, row in active_cases.iterrows()
            }
            with selector_col:
                selected_label = st.selectbox("Select Order", list(options))

            case_id = options[selected_label]
            selected = active_cases[active_cases["Case ID"].eq(case_id)].iloc[0]
            valid_phone = normalize_phone(selected["Mobile"])

            d1, d2, d3 = st.columns(3)
            d1.write(f"**Portal:** {selected['Portal']}")
            d1.write(f"**AWB:** {selected['AWB']}")
            d2.write(f"**Customer:** {selected['Customer Name']}")
            d2.write(f"**Mobile:** {phone_display(selected['Mobile'])}")
            d3.write(f"**Courier Status:** {selected['Latest Courier Status']}")
            d3.write(f"**Issue:** {selected['Courier Remarks']}")

            if logistics_case_masks(active_cases.loc[[selected.name]])["pending_review"].iloc[0]:
                st.info(
                    "Tawseel shows this order as delivered. Review the case and close it. "
                    "Mark recovery only when delivery followed logistics coordination."
                )

            b1, b2 = st.columns(2)
            if valid_phone:
                b1.link_button(
                    "📞 Open 3CX",
                    threecx_webclient_url(),
                    width="stretch",
                )
                b2.link_button(
                    "💬 Open in DoubleTick",
                    doubletick_chat_link(valid_phone),
                    width="stretch",
                )
            else:
                b1.button("📞 Open 3CX", disabled=True, width="stretch")
                b2.button("💬 Open in DoubleTick", disabled=True, width="stretch")
                st.warning("No valid customer mobile number is available for this order.")

            case_history = activity[activity["Case ID"].eq(case_id)]
            if not case_history.empty:
                with st.expander("Case Activity"):
                    st.dataframe(
                        _safe_frame(
                            case_history.sort_values("Action At", ascending=False)
                        ),
                        width="stretch",
                        hide_index=True,
                    )

            with st.form("save_activity", clear_on_submit=True):
                c1, c2 = st.columns(2)
                action = c1.selectbox(
                    "Action",
                    ["CALL", "WHATSAPP", "COURIER_COORDINATION", "NOTE", "ESCALATION"],
                )
                work_status = c2.selectbox(
                    "Work Status",
                    [
                        "IN PROGRESS",
                        "FOLLOW-UP DUE",
                        "CUSTOMER CONTACTED",
                        "RESCHEDULED",
                        "AWAITING COURIER",
                        "ESCALATED",
                        "UNRESOLVED",
                    ],
                )
                c3, c4 = st.columns(2)
                call_result = c3.selectbox(
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
                customer_response = c4.selectbox(
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
                c5, c6 = st.columns(2)
                follow_date = c5.date_input("Next Follow-up Date", value=None)
                follow_time = c6.time_input("Next Follow-up Time", value=None)
                remark = st.text_area("Remark")
                save = st.form_submit_button(
                    "Save Activity", type="primary", width="stretch"
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
                    st.success("Activity saved.")
                    st.rerun()
                except Exception as exc:
                    st.error(f"Could not save activity — {_error_text(exc)}")

            with st.expander("Close Case"):
                with st.form("close_case_form"):
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
                    delivered_date = st.date_input("Delivered Date", value=None)
                    closing_remark = st.text_area("Closure Remark")
                    close = st.form_submit_button("Close Case", width="stretch")
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
            st.dataframe(
                _safe_frame(details),
                width="stretch",
                hide_index=True,
                height=520,
            )

        if identity == "MANAGER":
            if st.button("Save Daily Report to Google Sheets", width="stretch"):
                try:
                    saved = save_daily_report_snapshot(report_date, daily_report)
                    st.success(
                        f"Saved {saved} agent report rows to LOGISTICS_DAILY_REPORT."
                    )
                except Exception as exc:
                    st.error(f"Could not save daily report — {_error_text(exc)}")

with history_tab:
    st.subheader("Activity History" if identity == "MANAGER" else "My Activity")
    history = activity.copy()
    if identity != "MANAGER" and not history.empty:
        history = history[
            history["Logistics Agent"].str.upper().eq(identity)
        ]
    if history.empty:
        st.info("No activity recorded yet.")
    else:
        st.dataframe(
            _safe_frame(history.sort_values("Action At", ascending=False)),
            width="stretch",
            hide_index=True,
            height=650,
        )
