from __future__ import annotations

from datetime import date, datetime, timedelta
from typing import Any

import gspread
import pandas as pd

from src.logistics import AGENTS, logistics_book

DATE_BASIS_COLUMNS = {
    "Assigned Date": "Assigned At",
    "Scheduled Date": "Scheduled Date",
    "Next Follow-up Date": "Next Follow-up",
    "Last Updated Date": "Updated At",
}

DAILY_REPORT_HEADERS = [
    "Report Date",
    "Agent",
    "Assigned",
    "Handled Orders",
    "Activities",
    "Calls Logged",
    "Answered Calls",
    "WhatsApp Actions",
    "Follow-ups Scheduled",
    "Rescheduled",
    "Cancelled Responses",
    "Closed",
    "Recovered",
    "Recovery Rate",
    "Generated At",
]


def _text(value: Any) -> str:
    if value is None:
        return ""
    try:
        if pd.isna(value):
            return ""
    except (TypeError, ValueError):
        pass
    return str(value).strip()


def _dates(series: pd.Series) -> pd.Series:
    return pd.to_datetime(series.astype(str).str.strip(), errors="coerce", format="mixed").dt.date


def resolve_date_window(view: str, custom_start: date, custom_end: date) -> tuple[date | None, date | None]:
    today = datetime.now().astimezone().date()
    if view == "Today":
        return today, today
    if view == "Yesterday":
        day = today - timedelta(days=1)
        return day, day
    if view == "Custom Range":
        return min(custom_start, custom_end), max(custom_start, custom_end)
    return None, None


def filter_cases_by_date(
    cases: pd.DataFrame,
    basis: str,
    start_date: date | None,
    end_date: date | None,
) -> pd.DataFrame:
    if cases.empty or start_date is None or end_date is None:
        return cases.copy()

    column = DATE_BASIS_COLUMNS.get(basis, "Assigned At")
    if column not in cases.columns:
        return cases.iloc[0:0].copy()

    case_dates = _dates(cases[column])
    return cases[case_dates.between(start_date, end_date, inclusive="both")].copy()


def daily_agent_report(cases: pd.DataFrame, activity: pd.DataFrame, report_date: date) -> pd.DataFrame:
    case_work = cases.copy()
    activity_work = activity.copy()

    case_work["_assigned_date"] = _dates(case_work.get("Assigned At", pd.Series(dtype=str)))
    case_work["_closed_date"] = _dates(case_work.get("Closed At", pd.Series(dtype=str)))
    activity_work["_action_date"] = _dates(activity_work.get("Action At", pd.Series(dtype=str)))

    day_activity = activity_work[activity_work["_action_date"].eq(report_date)].copy()
    rows: list[dict[str, Any]] = []

    for agent in AGENTS:
        agent_cases = case_work[case_work["Logistics Agent"].astype(str).str.upper().eq(agent)]
        agent_activity = day_activity[day_activity["Logistics Agent"].astype(str).str.upper().eq(agent)]

        assigned = int(agent_cases["_assigned_date"].eq(report_date).sum())
        handled = int(agent_activity["Case ID"].astype(str).replace("", pd.NA).dropna().nunique())
        activities = len(agent_activity)
        calls = int(agent_activity["Action Type"].astype(str).str.upper().eq("CALL").sum())
        answered = int(agent_activity["Call Result"].astype(str).str.casefold().eq("answered").sum())
        whatsapp = int(agent_activity["Action Type"].astype(str).str.upper().eq("WHATSAPP").sum())
        followups = int(agent_activity["Next Follow-up"].astype(str).str.strip().ne("").sum())
        rescheduled = int(agent_activity["New Work Status"].astype(str).str.upper().eq("RESCHEDULED").sum())
        cancelled = int(agent_activity["Customer Response"].astype(str).str.casefold().isin({"order cancelled", "customer cancelled"}).sum())
        closed_cases = agent_cases[agent_cases["_closed_date"].eq(report_date)]
        closed = len(closed_cases)
        recovered = int(closed_cases["Delivered After Coordination"].astype(str).str.upper().eq("YES").sum())

        rows.append(
            {
                "Report Date": report_date.isoformat(),
                "Agent": agent,
                "Assigned": assigned,
                "Handled Orders": handled,
                "Activities": activities,
                "Calls Logged": calls,
                "Answered Calls": answered,
                "WhatsApp Actions": whatsapp,
                "Follow-ups Scheduled": followups,
                "Rescheduled": rescheduled,
                "Cancelled Responses": cancelled,
                "Closed": closed,
                "Recovered": recovered,
                "Recovery Rate": recovered / handled if handled else 0.0,
            }
        )

    return pd.DataFrame(rows)


def daily_case_details(
    cases: pd.DataFrame,
    activity: pd.DataFrame,
    report_date: date,
    agent: str | None = None,
) -> pd.DataFrame:
    activity_work = activity.copy()
    activity_work["_action_date"] = _dates(activity_work.get("Action At", pd.Series(dtype=str)))
    day_activity = activity_work[activity_work["_action_date"].eq(report_date)].copy()

    if agent:
        day_activity = day_activity[
            day_activity["Logistics Agent"].astype(str).str.upper().eq(agent.upper())
        ]
    if day_activity.empty:
        return pd.DataFrame()

    day_activity["_action_at"] = pd.to_datetime(day_activity["Action At"], errors="coerce", format="mixed")
    day_activity = day_activity.sort_values("_action_at")

    summaries: list[dict[str, Any]] = []
    for case_id, group in day_activity.groupby("Case ID", dropna=False):
        if not _text(case_id):
            continue
        last = group.iloc[-1]
        summaries.append(
            {
                "Case ID": _text(case_id),
                "Agent": _text(last.get("Logistics Agent")),
                "Activities": len(group),
                "Calls": int(group["Action Type"].astype(str).str.upper().eq("CALL").sum()),
                "Answered": int(group["Call Result"].astype(str).str.casefold().eq("answered").sum()),
                "Latest Action At": _text(last.get("Action At")),
                "Latest Action": _text(last.get("Action Type")),
                "Last Call Result": _text(last.get("Call Result")),
                "Last Customer Response": _text(last.get("Customer Response")),
                "Latest Remark": _text(last.get("Remark")),
                "Next Follow-up": _text(last.get("Next Follow-up")),
            }
        )

    detail = pd.DataFrame(summaries)
    case_columns = [
        "Case ID",
        "Portal",
        "AWB",
        "Customer Name",
        "Mobile",
        "Latest Courier Status",
        "Logistics Work Status",
        "Logistics Final Outcome",
        "Delivered After Coordination",
    ]
    available = [column for column in case_columns if column in cases.columns]
    case_lookup = cases[available].drop_duplicates("Case ID", keep="last")
    return detail.merge(case_lookup, on="Case ID", how="left")


def _daily_report_sheet() -> gspread.Worksheet:
    book = logistics_book()
    try:
        return book.worksheet("LOGISTICS_DAILY_REPORT")
    except gspread.WorksheetNotFound:
        worksheet = book.add_worksheet(
            title="LOGISTICS_DAILY_REPORT",
            rows=5000,
            cols=len(DAILY_REPORT_HEADERS),
        )
        worksheet.update("A1", [DAILY_REPORT_HEADERS])
        worksheet.freeze(rows=1)
        return worksheet


def save_daily_report_snapshot(report_date: date, report: pd.DataFrame) -> int:
    worksheet = _daily_report_sheet()
    existing = worksheet.get_all_values()
    retained = [DAILY_REPORT_HEADERS]

    for row in existing[1:]:
        padded = list(row) + [""] * max(0, len(DAILY_REPORT_HEADERS) - len(row))
        if _text(padded[0]) != report_date.isoformat():
            retained.append(padded[: len(DAILY_REPORT_HEADERS)])

    generated_at = datetime.now().astimezone().strftime("%Y-%m-%d %H:%M:%S")
    new_rows: list[list[str]] = []
    for _, row in report.iterrows():
        record = row.to_dict()
        record["Recovery Rate"] = f"{float(record.get('Recovery Rate', 0)):.4f}"
        record["Generated At"] = generated_at
        new_rows.append([_text(record.get(header, "")) for header in DAILY_REPORT_HEADERS])

    worksheet.clear()
    worksheet.update("A1", retained + new_rows, value_input_option="USER_ENTERED")
    worksheet.freeze(rows=1)
    return len(new_rows)
