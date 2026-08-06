from __future__ import annotations

from datetime import datetime
import time
from typing import Any, Callable, TypeVar
from zoneinfo import ZoneInfo

import gspread
import streamlit as st

from src.logistics import logistics_book, logistics_client

DEFAULT_BACKUP_SHEET_ID = "1B9FJgL1DUMxdj52QMVuSqY6Gs2fHErM-gAYyu7fwAuQ"
BACKUP_TABS = [
    "LOGISTICS_CASES",
    "LOGISTICS_ACTIVITY_LOG",
    "LOGISTICS_SETTINGS",
    "LOGISTICS_STATUS_UPDATES",
    "LOGISTICS_DAILY_REPORT",
    "LOGISTICS_AUTOMATION_HEALTH",
]
CASE_SNAPSHOT_TAB = "LOGISTICS_CASE_SNAPSHOTS"
ACTIVITY_SNAPSHOT_TAB = "LOGISTICS_ACTIVITY_SNAPSHOTS"
BACKUP_EVENT_TAB = "BACKUP_EVENT_LOG"
T = TypeVar("T")


def _now() -> str:
    return datetime.now(ZoneInfo("Asia/Dubai")).strftime("%Y-%m-%d %H:%M:%S")


def _text(value: Any) -> str:
    return "" if value is None else str(value).strip()


def _is_quota_error(exc: Exception) -> bool:
    message = str(exc).casefold()
    return "429" in message or "quota exceeded" in message


def _retry(operation: Callable[[], T], attempts: int = 3) -> T:
    last_error: Exception | None = None
    for attempt in range(1, attempts + 1):
        try:
            return operation()
        except Exception as exc:
            last_error = exc
            if not _is_quota_error(exc) or attempt >= attempts:
                raise
            time.sleep(4 * attempt)
    assert last_error is not None
    raise last_error


def _backup_sheet_id() -> str:
    try:
        return str(
            st.secrets.get("logistics", {}).get(
                "backup_sheet_id", DEFAULT_BACKUP_SHEET_ID
            )
        ).strip()
    except Exception:
        return DEFAULT_BACKUP_SHEET_ID


@st.cache_resource
def backup_book() -> gspread.Spreadsheet:
    return logistics_client().open_by_key(_backup_sheet_id())


@st.cache_resource
def _backup_worksheet(title: str) -> gspread.Worksheet:
    book = backup_book()
    try:
        return _retry(lambda: book.worksheet(title))
    except gspread.WorksheetNotFound:
        return _retry(
            lambda: book.add_worksheet(title=title, rows=1000, cols=50)
        )


def _ensure_backup_tab(title: str, rows: int, cols: int) -> gspread.Worksheet:
    worksheet = _backup_worksheet(title)
    if worksheet.row_count < rows:
        _retry(lambda: worksheet.add_rows(rows - worksheet.row_count))
    if worksheet.col_count < cols:
        _retry(lambda: worksheet.add_cols(cols - worksheet.col_count))
    return worksheet


def _ensure_snapshot_headers(
    worksheet: gspread.Worksheet,
    headers: list[str],
) -> None:
    expected = ["Backup Captured At", *headers]
    current = _retry(lambda: worksheet.row_values(1))
    if current == expected:
        return
    if worksheet.col_count < len(expected):
        _retry(lambda: worksheet.add_cols(len(expected) - worksheet.col_count))
    _retry(
        lambda: worksheet.update(
            "A1",
            [expected],
            value_input_option="USER_ENTERED",
        )
    )
    _retry(lambda: worksheet.freeze(rows=1))


def _extract_case_snapshot(
    case_id: str,
) -> tuple[list[str], list[str], list[str], list[str]]:
    response = _retry(
        lambda: logistics_book().values_batch_get(
            ["LOGISTICS_CASES", "LOGISTICS_ACTIVITY_LOG"],
            params={"valueRenderOption": "FORMATTED_VALUE"},
        )
    )
    ranges = response.get("valueRanges", [])
    case_values = ranges[0].get("values", []) if len(ranges) > 0 else []
    activity_values = ranges[1].get("values", []) if len(ranges) > 1 else []

    case_headers = [_text(value) for value in case_values[0]] if case_values else []
    activity_headers = (
        [_text(value) for value in activity_values[0]] if activity_values else []
    )

    case_row: list[str] = []
    if case_headers and "Case ID" in case_headers:
        index = case_headers.index("Case ID")
        for row in case_values[1:]:
            padded = list(row) + [""] * max(0, len(case_headers) - len(row))
            if _text(padded[index]) == case_id:
                case_row = [_text(value) for value in padded[: len(case_headers)]]
                break

    latest_activity: list[str] = []
    if activity_headers and "Case ID" in activity_headers:
        index = activity_headers.index("Case ID")
        for row in activity_values[1:]:
            padded = list(row) + [""] * max(0, len(activity_headers) - len(row))
            if _text(padded[index]) == case_id:
                latest_activity = [
                    _text(value) for value in padded[: len(activity_headers)]
                ]

    return case_headers, case_row, activity_headers, latest_activity


def backup_case_snapshot(case_id: str, event_type: str) -> dict[str, Any]:
    """Append an immediate, independent snapshot after an agent write.

    The snapshots are append-only. This preserves the exact case state and the
    latest activity record even if a later live row is changed incorrectly.
    """
    captured_at = _now()
    (
        case_headers,
        case_row,
        activity_headers,
        activity_row,
    ) = _extract_case_snapshot(case_id)

    if not case_row:
        raise ValueError(f"Could not locate Logistics case {case_id} for backup")

    case_sheet = _ensure_backup_tab(
        CASE_SNAPSHOT_TAB,
        1000,
        len(case_headers) + 1,
    )
    _ensure_snapshot_headers(case_sheet, case_headers)
    _retry(
        lambda: case_sheet.append_row(
            [captured_at, *case_row],
            value_input_option="USER_ENTERED",
        )
    )

    activity_backed_up = False
    if activity_headers and activity_row:
        activity_sheet = _ensure_backup_tab(
            ACTIVITY_SNAPSHOT_TAB,
            2000,
            len(activity_headers) + 1,
        )
        _ensure_snapshot_headers(activity_sheet, activity_headers)
        _retry(
            lambda: activity_sheet.append_row(
                [captured_at, *activity_row],
                value_input_option="USER_ENTERED",
            )
        )
        activity_backed_up = True

    event_sheet = _ensure_backup_tab(BACKUP_EVENT_TAB, 1000, 6)
    event_headers = [
        "Backup Captured At",
        "Event Type",
        "Case ID",
        "Case Snapshot",
        "Activity Snapshot",
        "Status",
    ]
    current_headers = _retry(lambda: event_sheet.row_values(1))
    if current_headers != event_headers:
        _retry(
            lambda: event_sheet.update(
                "A1",
                [event_headers],
                value_input_option="USER_ENTERED",
            )
        )
        _retry(lambda: event_sheet.freeze(rows=1))
    _retry(
        lambda: event_sheet.append_row(
            [
                captured_at,
                event_type,
                case_id,
                "YES",
                "YES" if activity_backed_up else "NO",
                "SUCCESS",
            ],
            value_input_option="USER_ENTERED",
        )
    )

    return {
        "case_id": case_id,
        "event_type": event_type,
        "captured_at": captured_at,
        "case_snapshot": True,
        "activity_snapshot": activity_backed_up,
        "backup_sheet_id": backup_book().id,
    }


def mirror_logistics_backup() -> dict[str, Any]:
    """Mirror all current logistics tables into the independent backup workbook."""
    live = logistics_book()
    copied: dict[str, int] = {}

    for title in BACKUP_TABS:
        try:
            source = _retry(lambda title=title: live.worksheet(title))
        except gspread.WorksheetNotFound:
            continue

        values = _retry(lambda source=source: source.get_all_values())
        row_count = max(len(values), 1)
        col_count = max((len(row) for row in values), default=1)
        target = _ensure_backup_tab(title, row_count, col_count)
        _retry(lambda target=target: target.clear())
        if values:
            _retry(
                lambda target=target, values=values: target.update(
                    "A1",
                    values,
                    value_input_option="USER_ENTERED",
                )
            )
            if len(values) > 1:
                _retry(lambda target=target: target.freeze(rows=1))
        copied[title] = max(len(values) - 1, 0)

    metadata = _ensure_backup_tab("BACKUP_METADATA", 20, 4)
    _retry(
        lambda: metadata.update(
            "A1",
            [
                ["Key", "Value"],
                ["Last Successful Backup At", _now()],
                ["Source Spreadsheet ID", live.id],
                ["Backup Spreadsheet ID", backup_book().id],
                ["Copied Tabs", ", ".join(copied)],
            ],
            value_input_option="USER_ENTERED",
        )
    )
    _retry(lambda: metadata.freeze(rows=1))
    return {"backup_tabs": copied, "backup_sheet_id": backup_book().id}


def verify_logistics_backup() -> dict[str, Any]:
    """Confirm that every mirrored cell exactly matches the live workbook.

    This performs a value-for-value comparison of each protected Logistics tab.
    A mismatch raises an error so the scheduled workflow cannot report success
    while the recovery copy is incomplete.
    """
    live = logistics_book()
    backup = backup_book()
    verified: dict[str, dict[str, int | bool]] = {}
    missing: list[str] = []
    mismatched: list[str] = []

    for title in BACKUP_TABS:
        try:
            source = _retry(lambda title=title: live.worksheet(title))
        except gspread.WorksheetNotFound:
            continue
        try:
            target = _retry(lambda title=title: backup.worksheet(title))
        except gspread.WorksheetNotFound:
            missing.append(title)
            continue

        source_values = _retry(lambda source=source: source.get_all_values())
        target_values = _retry(lambda target=target: target.get_all_values())
        matches = source_values == target_values
        verified[title] = {
            "matches": matches,
            "live_rows": max(len(source_values) - 1, 0),
            "backup_rows": max(len(target_values) - 1, 0),
        }
        if not matches:
            mismatched.append(title)

    snapshot_tabs: dict[str, bool] = {}
    for title in [CASE_SNAPSHOT_TAB, ACTIVITY_SNAPSHOT_TAB, BACKUP_EVENT_TAB]:
        try:
            _retry(lambda title=title: backup.worksheet(title))
            snapshot_tabs[title] = True
        except gspread.WorksheetNotFound:
            snapshot_tabs[title] = False

    status = "SUCCESS" if not missing and not mismatched else "FAILED"
    checked_at = _now()
    metadata = _ensure_backup_tab("BACKUP_METADATA", 20, 4)
    _retry(
        lambda: metadata.update(
            "A7",
            [
                ["Last Verification At", checked_at],
                ["Last Verification Status", status],
                ["Missing Tabs", ", ".join(missing)],
                ["Mismatched Tabs", ", ".join(mismatched)],
                [
                    "Snapshot Tabs Ready",
                    ", ".join(
                        title for title, ready in snapshot_tabs.items() if ready
                    ),
                ],
            ],
            value_input_option="USER_ENTERED",
        )
    )

    result = {
        "status": status,
        "checked_at": checked_at,
        "verified_tabs": verified,
        "missing_tabs": missing,
        "mismatched_tabs": mismatched,
        "snapshot_tabs": snapshot_tabs,
        "backup_sheet_id": backup.id,
    }
    if status != "SUCCESS":
        raise RuntimeError(
            "Logistics backup verification failed: "
            f"missing={missing}, mismatched={mismatched}"
        )
    return result
