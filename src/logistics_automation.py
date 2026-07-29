from __future__ import annotations

from datetime import datetime, timedelta
import json
import threading
import time
from typing import Any
from zoneinfo import ZoneInfo

import gspread

from src.logistics import logistics_book
from src.logistics_status_tracking import sync_logistics_cases_with_status_tracking

HEALTH_SHEET = "LOGISTICS_AUTOMATION_HEALTH"
HEALTH_HEADERS = [
    "Last Started At",
    "Last Finished At",
    "Last Success At",
    "Status",
    "Source",
    "Attempt",
    "Source Orders",
    "Eligible",
    "Matched Existing",
    "Created",
    "Updated",
    "Reopened",
    "Status Changed",
    "Error",
    "Result JSON",
]

_PROCESS_LOCK = threading.Lock()
DUBAI_TZ = ZoneInfo("Asia/Dubai")


def _now_dt() -> datetime:
    return datetime.now(DUBAI_TZ)


def _now() -> str:
    return _now_dt().strftime("%Y-%m-%d %H:%M:%S")


def _text(value: Any) -> str:
    return "" if value is None else str(value).strip()


def _parse_dt(value: Any) -> datetime | None:
    text = _text(value)
    if not text:
        return None
    try:
        parsed = datetime.strptime(text, "%Y-%m-%d %H:%M:%S")
        return parsed.replace(tzinfo=DUBAI_TZ)
    except ValueError:
        return None


def _health_sheet() -> gspread.Worksheet:
    book = logistics_book()
    try:
        worksheet = book.worksheet(HEALTH_SHEET)
    except gspread.WorksheetNotFound:
        worksheet = book.add_worksheet(
            title=HEALTH_SHEET,
            rows=10,
            cols=len(HEALTH_HEADERS),
        )
        worksheet.update("A1", [HEALTH_HEADERS])
        worksheet.freeze(rows=1)
        return worksheet

    current_headers = worksheet.row_values(1)
    if current_headers != HEALTH_HEADERS:
        if worksheet.col_count < len(HEALTH_HEADERS):
            worksheet.add_cols(len(HEALTH_HEADERS) - worksheet.col_count)
        worksheet.update("A1", [HEALTH_HEADERS])
        worksheet.freeze(rows=1)
    return worksheet


def read_automation_health() -> dict[str, str]:
    try:
        values = _health_sheet().get_all_values()
    except Exception:
        return {}
    if len(values) < 2:
        return {}
    row = list(values[1]) + [""] * max(0, len(HEALTH_HEADERS) - len(values[1]))
    return {
        header: _text(row[index])
        for index, header in enumerate(HEALTH_HEADERS)
    }


def _write_health(record: dict[str, Any]) -> None:
    worksheet = _health_sheet()
    current = read_automation_health()
    merged = {**current, **{key: _text(value) for key, value in record.items()}}
    row = [[merged.get(header, "") for header in HEALTH_HEADERS]]
    worksheet.update("A2", row, value_input_option="USER_ENTERED")


def _is_recently_running(health: dict[str, str], lease_minutes: int) -> bool:
    if health.get("Status", "").upper() != "RUNNING":
        return False
    started = _parse_dt(health.get("Last Started At"))
    return bool(started and _now_dt() - started < timedelta(minutes=lease_minutes))


def _is_recent_success(health: dict[str, str], minimum_interval_seconds: int) -> bool:
    success = _parse_dt(health.get("Last Success At"))
    return bool(
        success
        and _now_dt() - success < timedelta(seconds=minimum_interval_seconds)
    )


def run_automated_sync(
    *,
    source: str,
    force: bool = False,
    minimum_interval_seconds: int = 300,
    lease_minutes: int = 15,
    max_attempts: int = 4,
) -> dict[str, Any]:
    """Run an idempotent logistics sync with throttling, retry and health logging."""
    with _PROCESS_LOCK:
        health = read_automation_health()
        if not force and _is_recent_success(health, minimum_interval_seconds):
            return {
                "ran": False,
                "skipped": "recent_success",
                "last_success_at": health.get("Last Success At", ""),
            }
        if _is_recently_running(health, lease_minutes):
            return {
                "ran": False,
                "skipped": "another_sync_is_running",
                "last_started_at": health.get("Last Started At", ""),
            }

        started_at = _now()
        _write_health(
            {
                "Last Started At": started_at,
                "Status": "RUNNING",
                "Source": source,
                "Attempt": "0",
                "Error": "",
            }
        )

        last_error = ""
        for attempt in range(1, max_attempts + 1):
            try:
                _write_health({"Attempt": str(attempt), "Status": "RUNNING"})
                result = sync_logistics_cases_with_status_tracking()
                finished_at = _now()
                success_record = {
                    "Last Finished At": finished_at,
                    "Last Success At": finished_at,
                    "Status": "SUCCESS",
                    "Source": source,
                    "Attempt": str(attempt),
                    "Source Orders": result.get("source_total", ""),
                    "Eligible": result.get("eligible", ""),
                    "Matched Existing": result.get("matched_existing", ""),
                    "Created": result.get("created", 0),
                    "Updated": result.get("updated", 0),
                    "Reopened": result.get("reopened", 0),
                    "Status Changed": result.get("status_changed", 0),
                    "Error": "",
                    "Result JSON": json.dumps(result, sort_keys=True, default=str),
                }
                _write_health(success_record)
                return {"ran": True, **result, "attempt": attempt}
            except Exception as exc:
                last_error = f"{type(exc).__name__}: {str(exc).strip()}"
                _write_health(
                    {
                        "Status": "RETRYING" if attempt < max_attempts else "FAILED",
                        "Attempt": str(attempt),
                        "Error": last_error,
                    }
                )
                if attempt < max_attempts:
                    time.sleep(min(60, 5 * (2 ** (attempt - 1))))

        finished_at = _now()
        _write_health(
            {
                "Last Finished At": finished_at,
                "Status": "FAILED",
                "Source": source,
                "Error": last_error,
            }
        )
        raise RuntimeError(last_error or "Automated logistics sync failed")
