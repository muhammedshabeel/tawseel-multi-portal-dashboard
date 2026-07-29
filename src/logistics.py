from __future__ import annotations

from datetime import datetime
import hashlib
import threading
from typing import Any
from zoneinfo import ZoneInfo

import gspread
import pandas as pd
import streamlit as st
from google.oauth2.service_account import Credentials
from gspread.utils import rowcol_to_a1

from src.data_loader import load_all_data
from src.metrics import add_derived_columns

WRITE_SCOPES = [
    "https://www.googleapis.com/auth/spreadsheets",
    "https://www.googleapis.com/auth/drive",
]

DEFAULT_LOGISTICS_SHEET_ID = "1-1ZyZDZyqKdmFWYX7WYtriUk04FDfeHMup7v9nOBNO0"
AGENTS = ["VAISHAKH", "HASBIR", "AKHASH", "NEETHU"]

CASE_HEADERS = [
    "Case ID", "Portal", "AWB", "Customer Name", "Mobile", "Scheduled Date",
    "Source Courier Status", "Latest Courier Status", "Courier Remarks", "Original Agent",
    "Priority", "Issue Category", "Logistics Agent", "Assigned At", "Assignment Method",
    "Logistics Work Status", "Total Call Attempts", "Last Call At", "Last Call Status",
    "Customer Response", "Next Follow-up", "Rescheduled Date", "Agent Remark",
    "Courier Coordination Done", "Logistics Final Outcome", "Delivered After Coordination",
    "Logistics Delivered Date", "Closed At", "Created At", "Updated At",
]

ACTIVITY_HEADERS = [
    "Activity ID", "Case ID", "Portal", "AWB", "Logistics Agent", "Action At",
    "Action Type", "Call Attempt Number", "Call Result", "Customer Response",
    "Remark", "Next Follow-up", "Previous Work Status", "New Work Status",
]

SETTINGS_ROWS = [
    ["Key", "Value"],
    ["ROUND_ROBIN_AGENTS", ",".join(AGENTS)],
    ["NEXT_AGENT_INDEX", "0"],
    ["CASE_SOURCE", "READ_ONLY_TAWSEEL"],
    ["ISOLATION_MODE", "TRUE"],
]

_WRITE_LOCK = threading.Lock()


def _now() -> str:
    return datetime.now(ZoneInfo("Asia/Dubai")).strftime("%Y-%m-%d %H:%M:%S")


def _sheet_id() -> str:
    cfg = st.secrets.get("logistics", {})
    return str(cfg.get("sheet_id", DEFAULT_LOGISTICS_SHEET_ID)).strip()


def _text(value: Any) -> str:
    if value is None:
        return ""
    try:
        if pd.isna(value):
            return ""
    except (TypeError, ValueError):
        pass
    return str(value).strip()


@st.cache_resource
def logistics_client() -> gspread.Client:
    info = dict(st.secrets["google_service_account"])
    creds = Credentials.from_service_account_info(info, scopes=WRITE_SCOPES)
    return gspread.authorize(creds)


@st.cache_resource
def logistics_book() -> gspread.Spreadsheet:
    return logistics_client().open_by_key(_sheet_id())


@st.cache_resource
def _worksheet(title: str) -> gspread.Worksheet:
    return logistics_book().worksheet(title)


def _frame_from_values(values: list[list[Any]], headers: list[str]) -> pd.DataFrame:
    if not values:
        return pd.DataFrame(columns=headers)

    source_headers = [_text(value) for value in values[0]]
    rows = values[1:]
    normalized_rows: list[dict[str, str]] = []

    for row in rows:
        padded = list(row) + [""] * max(0, len(source_headers) - len(row))
        record = {source_headers[index]: _text(padded[index]) for index in range(len(source_headers))}
        if any(record.values()):
            normalized_rows.append(record)

    frame = pd.DataFrame(normalized_rows)
    for column in headers:
        if column not in frame.columns:
            frame[column] = ""
    return frame[headers].fillna("").astype(str)


@st.cache_data(ttl=45, show_spinner=False)
def _load_tables() -> tuple[pd.DataFrame, pd.DataFrame]:
    response = logistics_book().values_batch_get(
        ["LOGISTICS_CASES", "LOGISTICS_ACTIVITY_LOG"],
        params={"valueRenderOption": "FORMATTED_VALUE"},
    )
    ranges = response.get("valueRanges", [])
    case_values = ranges[0].get("values", []) if len(ranges) > 0 else []
    activity_values = ranges[1].get("values", []) if len(ranges) > 1 else []
    return (
        _frame_from_values(case_values, CASE_HEADERS),
        _frame_from_values(activity_values, ACTIVITY_HEADERS),
    )


def _clear_table_cache() -> None:
    _load_tables.clear()


def load_cases() -> pd.DataFrame:
    cases, _ = _load_tables()
    return cases.copy()


def load_activity() -> pd.DataFrame:
    _, activity = _load_tables()
    return activity.copy()


def ensure_logistics_structure() -> None:
    """Create missing logistics storage tabs only when a write/sync is requested."""
    book = logistics_book()
    existing = {worksheet.title for worksheet in book.worksheets()}
    definitions = {
        "LOGISTICS_CASES": (5000, len(CASE_HEADERS), CASE_HEADERS),
        "LOGISTICS_ACTIVITY_LOG": (10000, len(ACTIVITY_HEADERS), ACTIVITY_HEADERS),
        "LOGISTICS_SETTINGS": (100, 8, None),
    }

    for title, (rows, cols, headers) in definitions.items():
        if title in existing:
            continue
        worksheet = book.add_worksheet(title=title, rows=rows, cols=cols)
        if headers:
            worksheet.update("A1", [headers])
            worksheet.freeze(rows=1)
        elif title == "LOGISTICS_SETTINGS":
            worksheet.update("A1", SETTINGS_ROWS)
            worksheet.freeze(rows=1)


def make_case_id(portal: str, awb: str) -> str:
    raw = f"{portal.strip().casefold()}|{awb.strip()}"
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:20].upper()


def _eligible_source() -> pd.DataFrame:
    source, _ = load_all_data()
    if source.empty:
        return source
    work = add_derived_columns(source)
    return work[
        (work["Is Critical"] | work["Is Follow Up"])
        & work["AWB"].astype(str).str.strip().ne("")
    ].copy()


def _load_settings() -> tuple[dict[str, str], dict[str, int]]:
    values = _worksheet("LOGISTICS_SETTINGS").get_all_values()
    settings: dict[str, str] = {}
    rows: dict[str, int] = {}
    for row_number, row in enumerate(values[1:], start=2):
        if not row or not _text(row[0]):
            continue
        key = _text(row[0])
        settings[key] = _text(row[1]) if len(row) > 1 else ""
        rows[key] = row_number
    return settings, rows


def _next_agents(count: int) -> tuple[list[str], int, int]:
    settings, rows = _load_settings()
    agents = [
        agent.strip().upper()
        for agent in settings.get("ROUND_ROBIN_AGENTS", ",".join(AGENTS)).split(",")
        if agent.strip()
    ] or AGENTS.copy()

    try:
        start = int(settings.get("NEXT_AGENT_INDEX", "0")) % len(agents)
    except ValueError:
        start = 0

    assigned = [agents[(start + offset) % len(agents)] for offset in range(count)]
    next_index = (start + count) % len(agents)
    next_index_row = rows.get("NEXT_AGENT_INDEX", 3)
    return assigned, next_index, next_index_row


def _row_values(record: dict[str, Any], headers: list[str]) -> list[str]:
    return [_text(record.get(header, "")) for header in headers]


def _batch_update_rows(
    worksheet: gspread.Worksheet,
    updates: list[tuple[int, list[str]]],
    width: int,
    chunk_size: int = 200,
) -> None:
    if not updates:
        return
    end_column = rowcol_to_a1(1, width).rstrip("1")
    for start in range(0, len(updates), chunk_size):
        chunk = updates[start:start + chunk_size]
        payload = [
            {"range": f"A{row_number}:{end_column}{row_number}", "values": [values]}
            for row_number, values in chunk
        ]
        worksheet.batch_update(payload, raw=False)


def sync_logistics_cases() -> dict[str, int]:
    """Read operational data and write only to the isolated logistics workbook."""
    with _WRITE_LOCK:
        ensure_logistics_structure()
        source = _eligible_source()
        cases = load_cases()
        now = _now()

        existing = {
            _text(case_id): index
            for index, case_id in enumerate(cases.get("Case ID", pd.Series(dtype=str)).tolist())
            if _text(case_id)
        }

        new_source_rows: list[dict[str, Any]] = []
        updated_rows: list[tuple[int, list[str]]] = []

        for _, source_row in source.iterrows():
            portal = _text(source_row.get("Portal", ""))
            awb = _text(source_row.get("AWB", ""))
            case_id = make_case_id(portal, awb)

            if case_id not in existing:
                new_source_rows.append(source_row.to_dict() | {"_case_id": case_id})
                continue

            frame_index = existing[case_id]
            current = cases.iloc[frame_index].to_dict()
            current["Latest Courier Status"] = _text(source_row.get("Status", ""))
            current["Courier Remarks"] = _text(source_row.get("Remarks", ""))
            current["Updated At"] = now
            updated_rows.append((frame_index + 2, _row_values(current, CASE_HEADERS)))

        assignees: list[str] = []
        next_index = 0
        next_index_row = 3
        if new_source_rows:
            assignees, next_index, next_index_row = _next_agents(len(new_source_rows))

        append_rows: list[list[str]] = []
        for source_row, assignee in zip(new_source_rows, assignees):
            priority = _text(source_row.get("Priority", "")) or "FOLLOW-UP"
            issue = "Critical Delivery Issue" if "CRITICAL" in priority.upper() else "Follow-up Required"
            record = {
                "Case ID": source_row["_case_id"],
                "Portal": source_row.get("Portal", ""),
                "AWB": source_row.get("AWB", ""),
                "Customer Name": source_row.get("Customer Name", ""),
                "Mobile": source_row.get("Mobile", ""),
                "Scheduled Date": source_row.get("Scheduled Date", ""),
                "Source Courier Status": source_row.get("Status", ""),
                "Latest Courier Status": source_row.get("Status", ""),
                "Courier Remarks": source_row.get("Remarks", ""),
                "Original Agent": source_row.get("Agent", ""),
                "Priority": priority,
                "Issue Category": issue,
                "Logistics Agent": assignee,
                "Assigned At": now,
                "Assignment Method": "ROUND_ROBIN",
                "Logistics Work Status": "NEW",
                "Total Call Attempts": "0",
                "Created At": now,
                "Updated At": now,
            }
            append_rows.append(_row_values(record, CASE_HEADERS))

        case_sheet = _worksheet("LOGISTICS_CASES")
        if append_rows:
            case_sheet.append_rows(append_rows, value_input_option="USER_ENTERED")
            _worksheet("LOGISTICS_SETTINGS").update(
                f"B{next_index_row}",
                [[str(next_index)]],
                value_input_option="USER_ENTERED",
            )

        _batch_update_rows(case_sheet, updated_rows, len(CASE_HEADERS))
        _clear_table_cache()
        return {
            "eligible": len(source),
            "created": len(append_rows),
            "updated": len(updated_rows),
        }


def refresh_agent_views() -> None:
    """Deprecated compatibility hook. Agent filtering is handled inside the CRM UI."""
    return None


def add_activity(
    case_id: str,
    action_type: str,
    call_result: str = "",
    customer_response: str = "",
    remark: str = "",
    next_follow_up: str = "",
    new_status: str = "",
) -> None:
    with _WRITE_LOCK:
        cases = load_cases()
        activity = load_activity()
        match = cases[cases["Case ID"].astype(str).eq(case_id)]
        if match.empty:
            raise ValueError("Case not found")

        frame_index = int(match.index[0])
        current = match.iloc[0].to_dict()
        now = _now()
        case_activity = activity[activity["Case ID"].astype(str).eq(case_id)]
        attempts_series = pd.to_numeric(case_activity["Call Attempt Number"], errors="coerce")
        attempts = int(attempts_series.max()) if attempts_series.notna().any() else 0
        is_call = action_type.upper() == "CALL"
        attempt_number: str | int = attempts + 1 if is_call else ""

        activity_id = hashlib.sha256(
            f"{case_id}|{now}|{action_type}|{remark}".encode("utf-8")
        ).hexdigest()[:20].upper()

        activity_record = {
            "Activity ID": activity_id,
            "Case ID": case_id,
            "Portal": current.get("Portal", ""),
            "AWB": current.get("AWB", ""),
            "Logistics Agent": current.get("Logistics Agent", ""),
            "Action At": now,
            "Action Type": action_type,
            "Call Attempt Number": attempt_number,
            "Call Result": call_result,
            "Customer Response": customer_response,
            "Remark": remark,
            "Next Follow-up": next_follow_up,
            "Previous Work Status": current.get("Logistics Work Status", ""),
            "New Work Status": new_status or current.get("Logistics Work Status", ""),
        }

        _worksheet("LOGISTICS_ACTIVITY_LOG").append_row(
            _row_values(activity_record, ACTIVITY_HEADERS),
            value_input_option="USER_ENTERED",
        )

        if is_call:
            current["Total Call Attempts"] = str(attempts + 1)
            current["Last Call At"] = now
        if call_result:
            current["Last Call Status"] = call_result
        if customer_response:
            current["Customer Response"] = customer_response
        if next_follow_up:
            current["Next Follow-up"] = next_follow_up
        if remark:
            current["Agent Remark"] = remark
        if new_status:
            current["Logistics Work Status"] = new_status
        current["Updated At"] = now

        _batch_update_rows(
            _worksheet("LOGISTICS_CASES"),
            [(frame_index + 2, _row_values(current, CASE_HEADERS))],
            len(CASE_HEADERS),
        )
        _clear_table_cache()


def close_case(
    case_id: str,
    outcome: str,
    delivered_after_coordination: bool = False,
    delivered_date: str = "",
    remark: str = "",
) -> None:
    with _WRITE_LOCK:
        cases = load_cases()
        match = cases[cases["Case ID"].astype(str).eq(case_id)]
        if match.empty:
            raise ValueError("Case not found")

        frame_index = int(match.index[0])
        current = match.iloc[0].to_dict()
        now = _now()
        previous_status = current.get("Logistics Work Status", "")

        current["Logistics Work Status"] = "CLOSED"
        current["Logistics Final Outcome"] = outcome
        current["Delivered After Coordination"] = "YES" if delivered_after_coordination else "NO"
        current["Logistics Delivered Date"] = delivered_date
        current["Closed At"] = now
        if remark:
            current["Agent Remark"] = remark
        current["Updated At"] = now

        _batch_update_rows(
            _worksheet("LOGISTICS_CASES"),
            [(frame_index + 2, _row_values(current, CASE_HEADERS))],
            len(CASE_HEADERS),
        )

        activity_id = hashlib.sha256(
            f"{case_id}|{now}|CLOSE|{remark}".encode("utf-8")
        ).hexdigest()[:20].upper()
        close_record = {
            "Activity ID": activity_id,
            "Case ID": case_id,
            "Portal": current.get("Portal", ""),
            "AWB": current.get("AWB", ""),
            "Logistics Agent": current.get("Logistics Agent", ""),
            "Action At": now,
            "Action Type": "CLOSE",
            "Remark": remark,
            "Previous Work Status": previous_status,
            "New Work Status": "CLOSED",
        }
        _worksheet("LOGISTICS_ACTIVITY_LOG").append_row(
            _row_values(close_record, ACTIVITY_HEADERS),
            value_input_option="USER_ENTERED",
        )
        _clear_table_cache()


def logistics_summary(cases: pd.DataFrame) -> tuple[dict[str, int | float], pd.DataFrame]:
    if cases.empty:
        return {
            "Assigned": 0,
            "Active": 0,
            "Closed": 0,
            "Delivered After Coordination": 0,
            "Recovery Rate": 0.0,
        }, pd.DataFrame()

    closed = cases["Logistics Work Status"].astype(str).str.upper().eq("CLOSED")
    delivered = cases["Delivered After Coordination"].astype(str).str.upper().eq("YES")
    overall = {
        "Assigned": len(cases),
        "Active": int((~closed).sum()),
        "Closed": int(closed.sum()),
        "Delivered After Coordination": int(delivered.sum()),
        "Recovery Rate": float(delivered.sum() / len(cases)) if len(cases) else 0.0,
    }

    rows: list[dict[str, Any]] = []
    for agent, group in cases.groupby("Logistics Agent", dropna=False):
        agent_closed = group["Logistics Work Status"].astype(str).str.upper().eq("CLOSED")
        agent_delivered = group["Delivered After Coordination"].astype(str).str.upper().eq("YES")
        rows.append(
            {
                "Agent": agent or "Unassigned",
                "Assigned": len(group),
                "Active": int((~agent_closed).sum()),
                "Closed": int(agent_closed.sum()),
                "Delivered After Coordination": int(agent_delivered.sum()),
                "Recovery Rate": float(agent_delivered.sum() / len(group)) if len(group) else 0.0,
            }
        )

    summary = pd.DataFrame(rows)
    if not summary.empty:
        summary = summary.sort_values(["Recovery Rate", "Assigned"], ascending=[False, False])
    return overall, summary
