from __future__ import annotations

import hashlib
from typing import Any

import pandas as pd

from src.logistics import (
    ACTIVITY_HEADERS,
    CASE_HEADERS,
    _batch_update_rows,
    _clear_table_cache,
    _now,
    _operational_sources,
    _row_values,
    _text,
    _worksheet,
    load_cases,
    make_case_id,
)


def reactivate_newly_critical_cases() -> dict[str, int]:
    """Reopen existing closed cases that have become critical/follow-up again.

    This affects only the isolated Logistics workbook. Existing audit history is
    retained in LOGISTICS_ACTIVITY_LOG while current closure/recovery fields are
    reset for the new recovery cycle.
    """
    _, eligible_source = _operational_sources()
    if eligible_source.empty:
        return {"reopened": 0, "critical_refreshed": 0}

    eligible: dict[str, dict[str, Any]] = {}
    for _, row in eligible_source.iterrows():
        portal = _text(row.get("Portal", ""))
        awb = _text(row.get("AWB", ""))
        if portal and awb:
            eligible[make_case_id(portal, awb)] = row.to_dict()

    cases = load_cases()
    if cases.empty:
        return {"reopened": 0, "critical_refreshed": 0}

    now = _now()
    case_updates: list[tuple[int, list[str]]] = []
    activity_rows: list[list[str]] = []
    reopened = 0
    critical_refreshed = 0

    for frame_index, case in cases.iterrows():
        case_id = _text(case.get("Case ID", ""))
        source = eligible.get(case_id)
        if source is None:
            continue

        current = case.to_dict()
        priority = _text(source.get("Priority", "")) or "FOLLOW-UP"
        issue = (
            "Critical Delivery Issue"
            if "CRITICAL" in priority.upper()
            else "Follow-up Required"
        )
        changed = False

        if _text(current.get("Priority")) != priority:
            current["Priority"] = priority
            changed = True
        if _text(current.get("Issue Category")) != issue:
            current["Issue Category"] = issue
            changed = True

        is_closed = _text(current.get("Logistics Work Status")).upper() == "CLOSED"
        latest_status = _text(source.get("Status", ""))
        is_delivered = "DELIVERED" in latest_status.upper()

        if is_closed and not is_delivered:
            previous_status = _text(current.get("Logistics Work Status"))
            current["Logistics Work Status"] = "REOPENED - CRITICAL"
            current["Logistics Final Outcome"] = ""
            current["Delivered After Coordination"] = ""
            current["Logistics Delivered Date"] = ""
            current["Closed At"] = ""
            current["Updated At"] = now
            changed = True
            reopened += 1

            activity_id = hashlib.sha256(
                f"{case_id}|{now}|AUTO_REOPEN|{priority}".encode("utf-8")
            ).hexdigest()[:20].upper()
            activity_record = {
                "Activity ID": activity_id,
                "Case ID": case_id,
                "Portal": current.get("Portal", ""),
                "AWB": current.get("AWB", ""),
                "Logistics Agent": current.get("Logistics Agent", ""),
                "Action At": now,
                "Action Type": "AUTO_REOPEN",
                "Remark": "Tawseel order became critical/follow-up again.",
                "Previous Work Status": previous_status,
                "New Work Status": "REOPENED - CRITICAL",
            }
            activity_rows.append(_row_values(activity_record, ACTIVITY_HEADERS))

        if changed:
            current["Updated At"] = now
            case_updates.append(
                (int(frame_index) + 2, _row_values(current, CASE_HEADERS))
            )
            critical_refreshed += 1

    if case_updates:
        _batch_update_rows(
            _worksheet("LOGISTICS_CASES"),
            case_updates,
            len(CASE_HEADERS),
        )
    if activity_rows:
        _worksheet("LOGISTICS_ACTIVITY_LOG").append_rows(
            activity_rows,
            value_input_option="USER_ENTERED",
        )
    if case_updates or activity_rows:
        _clear_table_cache()

    return {
        "reopened": reopened,
        "critical_refreshed": critical_refreshed,
    }
