from __future__ import annotations

from datetime import datetime, timezone
import hashlib
from typing import Any

import gspread
import pandas as pd
import streamlit as st
from google.oauth2.service_account import Credentials

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


def _now() -> str:
    return datetime.now(timezone.utc).astimezone().strftime("%Y-%m-%d %H:%M:%S")


def _sheet_id() -> str:
    cfg = st.secrets.get("logistics", {})
    return str(cfg.get("sheet_id", DEFAULT_LOGISTICS_SHEET_ID)).strip()


@st.cache_resource
def logistics_client() -> gspread.Client:
    info = dict(st.secrets["google_service_account"])
    creds = Credentials.from_service_account_info(info, scopes=WRITE_SCOPES)
    return gspread.authorize(creds)


def logistics_book() -> gspread.Spreadsheet:
    return logistics_client().open_by_key(_sheet_id())


def _worksheet(title: str, rows: int = 5000, cols: int = 40) -> gspread.Worksheet:
    book = logistics_book()
    try:
        return book.worksheet(title)
    except gspread.WorksheetNotFound:
        return book.add_worksheet(title=title, rows=rows, cols=cols)


def _ensure_header(ws: gspread.Worksheet, headers: list[str]) -> None:
    first = ws.row_values(1)
    if first != headers:
        ws.update("A1", [headers])
        ws.freeze(rows=1)


def ensure_logistics_structure() -> None:
    cases = _worksheet("LOGISTICS_CASES", 5000, len(CASE_HEADERS))
    activity = _worksheet("LOGISTICS_ACTIVITY_LOG", 10000, len(ACTIVITY_HEADERS))
    settings = _worksheet("LOGISTICS_SETTINGS", 100, 8)
    _ensure_header(cases, CASE_HEADERS)
    _ensure_header(activity, ACTIVITY_HEADERS)
    if not settings.get_all_values():
        settings.update("A1", SETTINGS_ROWS)
    for agent in AGENTS:
        _ensure_header(_worksheet(f"LOGISTICS_{agent}", 5000, len(CASE_HEADERS)), CASE_HEADERS)
    _worksheet("LOGISTICS_DASHBOARD", 500, 20)


def _records(title: str) -> pd.DataFrame:
    ws = _worksheet(title)
    values = ws.get_all_records(default_blank="")
    return pd.DataFrame(values)


def load_cases() -> pd.DataFrame:
    ensure_logistics_structure()
    df = _records("LOGISTICS_CASES")
    for col in CASE_HEADERS:
        if col not in df.columns:
            df[col] = ""
    return df[CASE_HEADERS]


def load_activity() -> pd.DataFrame:
    ensure_logistics_structure()
    df = _records("LOGISTICS_ACTIVITY_LOG")
    for col in ACTIVITY_HEADERS:
        if col not in df.columns:
            df[col] = ""
    return df[ACTIVITY_HEADERS]


def make_case_id(portal: str, awb: str) -> str:
    raw = f"{portal.strip().casefold()}|{awb.strip()}"
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:20].upper()


def _eligible_source() -> pd.DataFrame:
    source, _ = load_all_data()
    if source.empty:
        return source
    work = add_derived_columns(source)
    return work[(work["Is Critical"] | work["Is Follow Up"]) & work["AWB"].astype(str).str.strip().ne("")].copy()


def _settings_map() -> tuple[gspread.Worksheet, dict[str, str]]:
    ws = _worksheet("LOGISTICS_SETTINGS", 100, 8)
    values = ws.get_all_values()
    result: dict[str, str] = {}
    for row in values[1:]:
        if row and str(row[0]).strip():
            result[str(row[0]).strip()] = str(row[1]).strip() if len(row) > 1 else ""
    return ws, result


def _next_agents(count: int) -> list[str]:
    ws, settings = _settings_map()
    agents = [a.strip().upper() for a in settings.get("ROUND_ROBIN_AGENTS", ",".join(AGENTS)).split(",") if a.strip()]
    if not agents:
        agents = AGENTS.copy()
    try:
        start = int(settings.get("NEXT_AGENT_INDEX", "0")) % len(agents)
    except ValueError:
        start = 0
    assigned = [agents[(start + i) % len(agents)] for i in range(count)]
    next_index = (start + count) % len(agents)
    key_cells = ws.col_values(1)
    row_no = key_cells.index("NEXT_AGENT_INDEX") + 1 if "NEXT_AGENT_INDEX" in key_cells else len(key_cells) + 1
    ws.update_cell(row_no, 1, "NEXT_AGENT_INDEX")
    ws.update_cell(row_no, 2, str(next_index))
    return assigned


def sync_logistics_cases() -> dict[str, int]:
    """Read operational data and update only the isolated logistics workbook."""
    ensure_logistics_structure()
    source = _eligible_source()
    cases = load_cases()
    existing = {str(v).strip(): i for i, v in enumerate(cases.get("Case ID", pd.Series(dtype=str)).tolist()) if str(v).strip()}
    now = _now()

    new_source_rows: list[dict[str, Any]] = []
    updates: list[tuple[int, str, str, str]] = []
    for _, row in source.iterrows():
        portal = str(row.get("Portal", "")).strip()
        awb = str(row.get("AWB", "")).strip()
        case_id = make_case_id(portal, awb)
        if case_id in existing:
            sheet_row = existing[case_id] + 2
            updates.append((sheet_row, str(row.get("Status", "")), str(row.get("Remarks", "")), now))
        else:
            new_source_rows.append(row.to_dict() | {"_case_id": case_id})

    assignees = _next_agents(len(new_source_rows)) if new_source_rows else []
    append_rows: list[list[Any]] = []
    for src, assignee in zip(new_source_rows, assignees):
        priority = str(src.get("Priority", "FOLLOW-UP")).strip() or "FOLLOW-UP"
        issue = "Critical Delivery Issue" if "CRITICAL" in priority.upper() else "Follow-up Required"
        values = {
            "Case ID": src["_case_id"], "Portal": src.get("Portal", ""), "AWB": src.get("AWB", ""),
            "Customer Name": src.get("Customer Name", ""), "Mobile": src.get("Mobile", ""),
            "Scheduled Date": str(src.get("Scheduled Date", "")), "Source Courier Status": src.get("Status", ""),
            "Latest Courier Status": src.get("Status", ""), "Courier Remarks": src.get("Remarks", ""),
            "Original Agent": src.get("Agent", ""), "Priority": priority, "Issue Category": issue,
            "Logistics Agent": assignee, "Assigned At": now, "Assignment Method": "ROUND_ROBIN",
            "Logistics Work Status": "NEW", "Total Call Attempts": 0, "Created At": now, "Updated At": now,
        }
        append_rows.append([values.get(h, "") for h in CASE_HEADERS])

    ws = _worksheet("LOGISTICS_CASES")
    if append_rows:
        ws.append_rows(append_rows, value_input_option="USER_ENTERED")
    for row_no, status, remarks, stamp in updates:
        ws.update(f"H{row_no}:J{row_no}", [[status, remarks, cases.iloc[row_no - 2].get("Original Agent", "")]])
        ws.update_cell(row_no, CASE_HEADERS.index("Updated At") + 1, stamp)

    refresh_agent_views()
    return {"eligible": len(source), "created": len(append_rows), "updated": len(updates)}


def refresh_agent_views() -> None:
    cases = load_cases()
    for agent in AGENTS:
        ws = _worksheet(f"LOGISTICS_{agent}", 5000, len(CASE_HEADERS))
        ws.clear()
        ws.update("A1", [CASE_HEADERS])
        assigned = cases[cases["Logistics Agent"].astype(str).str.upper().eq(agent)] if not cases.empty else cases
        if not assigned.empty:
            ws.update("A2", assigned.fillna("").astype(str).values.tolist())
        ws.freeze(rows=1)


def add_activity(case_id: str, action_type: str, call_result: str = "", customer_response: str = "",
                 remark: str = "", next_follow_up: str = "", new_status: str = "") -> None:
    cases = load_cases()
    match = cases[cases["Case ID"].astype(str).eq(case_id)]
    if match.empty:
        raise ValueError("Case not found")
    row = match.iloc[0]
    now = _now()
    activities = load_activity()
    attempts = int(pd.to_numeric(activities[activities["Case ID"].astype(str).eq(case_id)]["Call Attempt Number"], errors="coerce").max() or 0)
    is_call = action_type.upper() == "CALL"
    attempt_no = attempts + 1 if is_call else ""
    activity_id = hashlib.sha256(f"{case_id}|{now}|{action_type}|{remark}".encode()).hexdigest()[:20].upper()
    values = {
        "Activity ID": activity_id, "Case ID": case_id, "Portal": row["Portal"], "AWB": row["AWB"],
        "Logistics Agent": row["Logistics Agent"], "Action At": now, "Action Type": action_type,
        "Call Attempt Number": attempt_no, "Call Result": call_result, "Customer Response": customer_response,
        "Remark": remark, "Next Follow-up": next_follow_up, "Previous Work Status": row["Logistics Work Status"],
        "New Work Status": new_status or row["Logistics Work Status"],
    }
    _worksheet("LOGISTICS_ACTIVITY_LOG").append_row([values.get(h, "") for h in ACTIVITY_HEADERS], value_input_option="USER_ENTERED")

    ws = _worksheet("LOGISTICS_CASES")
    sheet_row = match.index[0] + 2
    updates = {
        "Total Call Attempts": attempts + 1 if is_call else row["Total Call Attempts"],
        "Last Call At": now if is_call else row["Last Call At"],
        "Last Call Status": call_result or row["Last Call Status"],
        "Customer Response": customer_response or row["Customer Response"],
        "Next Follow-up": next_follow_up or row["Next Follow-up"],
        "Agent Remark": remark or row["Agent Remark"],
        "Logistics Work Status": new_status or row["Logistics Work Status"],
        "Updated At": now,
    }
    for column, value in updates.items():
        ws.update_cell(sheet_row, CASE_HEADERS.index(column) + 1, value)
    refresh_agent_views()


def close_case(case_id: str, outcome: str, delivered_after_coordination: bool = False,
               delivered_date: str = "", remark: str = "") -> None:
    cases = load_cases()
    match = cases[cases["Case ID"].astype(str).eq(case_id)]
    if match.empty:
        raise ValueError("Case not found")
    ws = _worksheet("LOGISTICS_CASES")
    sheet_row = match.index[0] + 2
    now = _now()
    updates = {
        "Logistics Work Status": "CLOSED", "Logistics Final Outcome": outcome,
        "Delivered After Coordination": "YES" if delivered_after_coordination else "NO",
        "Logistics Delivered Date": delivered_date, "Closed At": now, "Agent Remark": remark,
        "Updated At": now,
    }
    for column, value in updates.items():
        ws.update_cell(sheet_row, CASE_HEADERS.index(column) + 1, value)
    add_activity(case_id, "CLOSE", remark=remark, new_status="CLOSED")


def logistics_summary(cases: pd.DataFrame) -> tuple[dict[str, int | float], pd.DataFrame]:
    if cases.empty:
        return {"Assigned": 0, "Active": 0, "Closed": 0, "Delivered After Coordination": 0, "Recovery Rate": 0.0}, pd.DataFrame()
    closed = cases["Logistics Work Status"].astype(str).str.upper().eq("CLOSED")
    delivered = cases["Delivered After Coordination"].astype(str).str.upper().eq("YES")
    overall = {
        "Assigned": len(cases), "Active": int((~closed).sum()), "Closed": int(closed.sum()),
        "Delivered After Coordination": int(delivered.sum()),
        "Recovery Rate": float(delivered.sum() / len(cases)) if len(cases) else 0.0,
    }
    rows = []
    for agent, group in cases.groupby("Logistics Agent", dropna=False):
        agent_closed = group["Logistics Work Status"].astype(str).str.upper().eq("CLOSED")
        agent_delivered = group["Delivered After Coordination"].astype(str).str.upper().eq("YES")
        rows.append({
            "Agent": agent or "Unassigned", "Assigned": len(group), "Active": int((~agent_closed).sum()),
            "Closed": int(agent_closed.sum()), "Delivered After Coordination": int(agent_delivered.sum()),
            "Recovery Rate": float(agent_delivered.sum() / len(group)) if len(group) else 0.0,
        })
    return overall, pd.DataFrame(rows).sort_values(["Recovery Rate", "Assigned"], ascending=[False, False])
