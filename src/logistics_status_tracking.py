from __future__ import annotations

from datetime import datetime
from typing import Any
from zoneinfo import ZoneInfo

import gspread
import pandas as pd
import streamlit as st
from gspread.utils import rowcol_to_a1

from src.logistics import load_cases, logistics_book, sync_logistics_cases
from src.logistics_critical_reactivation import reactivate_newly_critical_cases

STATUS_HEADERS = [
    "Case ID",
    "Portal",
    "AWB",
    "Previous Courier Status",
    "Latest Courier Status",
    "Tawseel Status Updated At",
    "First Seen At",
    "Last Checked At",
]


def _now() -> str:
    return datetime.now(ZoneInfo("Asia/Dubai")).strftime("%Y-%m-%d %H:%M:%S")


def _text(value: Any) -> str:
    if value is None:
        return ""
    try:
        if pd.isna(value):
            return ""
    except (TypeError, ValueError):
        pass
    return str(value).strip()


def _frame(values: list[list[Any]]) -> pd.DataFrame:
    if not values:
        return pd.DataFrame(columns=STATUS_HEADERS)
    source_headers = [_text(value) for value in values[0]]
    rows: list[dict[str, str]] = []
    for raw_row in values[1:]:
        padded = list(raw_row) + [""] * max(0, len(source_headers) - len(raw_row))
        record = {
            source_headers[index]: _text(padded[index])
            for index in range(len(source_headers))
        }
        if any(record.values()):
            rows.append(record)
    result = pd.DataFrame(rows)
    for column in STATUS_HEADERS:
        if column not in result.columns:
            result[column] = ""
    return result[STATUS_HEADERS].fillna("").astype(str)


@st.cache_resource
def _status_sheet() -> gspread.Worksheet:
    book = logistics_book()
    try:
        worksheet = book.worksheet("LOGISTICS_STATUS_UPDATES")
    except gspread.WorksheetNotFound:
        worksheet = book.add_worksheet(
            title="LOGISTICS_STATUS_UPDATES",
            rows=5000,
            cols=len(STATUS_HEADERS),
        )
        worksheet.update("A1", [STATUS_HEADERS])
        worksheet.freeze(rows=1)
        return worksheet

    current_headers = worksheet.row_values(1)
    if current_headers != STATUS_HEADERS:
        if worksheet.col_count < len(STATUS_HEADERS):
            worksheet.add_cols(len(STATUS_HEADERS) - worksheet.col_count)
        worksheet.update("A1", [STATUS_HEADERS])
        worksheet.freeze(rows=1)
    return worksheet


@st.cache_data(ttl=45, show_spinner=False)
def load_status_updates() -> pd.DataFrame:
    try:
        values = _status_sheet().get_all_values()
    except gspread.WorksheetNotFound:
        return pd.DataFrame(columns=STATUS_HEADERS)
    return _frame(values)


def _clear_status_cache() -> None:
    load_status_updates.clear()


def _write_status_updates(statuses: pd.DataFrame) -> None:
    worksheet = _status_sheet()
    rows = [STATUS_HEADERS]
    if not statuses.empty:
        rows.extend(
            statuses[STATUS_HEADERS]
            .fillna("")
            .astype(str)
            .values.tolist()
        )
    worksheet.clear()
    end_column = rowcol_to_a1(1, len(STATUS_HEADERS)).rstrip("1")
    worksheet.update(
        f"A1:{end_column}{max(len(rows), 1)}",
        rows,
        value_input_option="USER_ENTERED",
    )
    worksheet.freeze(rows=1)
    _clear_status_cache()


def sync_logistics_cases_with_status_tracking() -> dict[str, int]:
    """Run the isolated logistics sync and persist detected Tawseel status changes.

    New critical/follow-up orders are assigned automatically. Existing assigned
    cases are refreshed even after their Tawseel status leaves the critical set.
    Closed cases that become critical again are reopened for the same agent.
    """
    before = load_cases()
    before_status = {
        _text(row.get("Case ID")): _text(row.get("Latest Courier Status"))
        for _, row in before.iterrows()
        if _text(row.get("Case ID"))
    }

    result = sync_logistics_cases()
    reactivation = reactivate_newly_critical_cases()
    result.update(reactivation)

    after = load_cases()
    tracked = load_status_updates()
    now = _now()

    tracked_by_case = {
        _text(row.get("Case ID")): row.to_dict()
        for _, row in tracked.iterrows()
        if _text(row.get("Case ID"))
    }

    output_rows: list[dict[str, str]] = []
    changed_count = 0

    for _, case in after.iterrows():
        case_id = _text(case.get("Case ID"))
        if not case_id:
            continue

        latest = _text(case.get("Latest Courier Status"))
        prior_record = tracked_by_case.get(case_id, {})
        tracked_latest = _text(prior_record.get("Latest Courier Status"))
        previous_before_sync = before_status.get(case_id, "")
        status_changed = bool(
            (tracked_latest and latest and tracked_latest.casefold() != latest.casefold())
            or (
                not tracked_latest
                and previous_before_sync
                and latest
                and previous_before_sync.casefold() != latest.casefold()
            )
        )

        if status_changed:
            changed_count += 1
            previous_status = tracked_latest or previous_before_sync
            status_updated_at = now
        else:
            previous_status = _text(prior_record.get("Previous Courier Status"))
            status_updated_at = _text(prior_record.get("Tawseel Status Updated At"))
            if not status_updated_at:
                status_updated_at = _text(case.get("Updated At")) or now

        first_seen = _text(prior_record.get("First Seen At"))
        if not first_seen:
            first_seen = _text(case.get("Created At")) or now

        output_rows.append(
            {
                "Case ID": case_id,
                "Portal": _text(case.get("Portal")),
                "AWB": _text(case.get("AWB")),
                "Previous Courier Status": previous_status,
                "Latest Courier Status": latest,
                "Tawseel Status Updated At": status_updated_at,
                "First Seen At": first_seen,
                "Last Checked At": now,
            }
        )

    _write_status_updates(pd.DataFrame(output_rows, columns=STATUS_HEADERS))
    result["status_changed"] = changed_count
    return result


def enrich_cases_with_status_updates(cases: pd.DataFrame) -> pd.DataFrame:
    if cases.empty:
        enriched = cases.copy()
        for column in ["Previous Courier Status", "Tawseel Status Updated At", "Status Age Days"]:
            if column not in enriched.columns:
                enriched[column] = ""
        return enriched

    try:
        tracked = load_status_updates()
    except Exception:
        tracked = pd.DataFrame(columns=STATUS_HEADERS)

    enriched = cases.copy()
    if not tracked.empty:
        lookup = tracked[
            [
                "Case ID",
                "Previous Courier Status",
                "Tawseel Status Updated At",
                "Last Checked At",
            ]
        ].drop_duplicates("Case ID", keep="last")
        enriched = enriched.merge(lookup, on="Case ID", how="left")
    else:
        enriched["Previous Courier Status"] = ""
        enriched["Tawseel Status Updated At"] = ""
        enriched["Last Checked At"] = ""

    enriched["Previous Courier Status"] = enriched["Previous Courier Status"].fillna("").astype(str)
    enriched["Tawseel Status Updated At"] = (
        enriched["Tawseel Status Updated At"].fillna("").astype(str)
    )

    missing = enriched["Tawseel Status Updated At"].str.strip().eq("")
    if "Updated At" in enriched.columns:
        enriched.loc[missing, "Tawseel Status Updated At"] = (
            enriched.loc[missing, "Updated At"].fillna("").astype(str)
        )

    updated_dates = pd.to_datetime(
        enriched["Tawseel Status Updated At"],
        errors="coerce",
        format="mixed",
    )
    now = pd.Timestamp.now(tz="Asia/Dubai").tz_localize(None)
    if getattr(updated_dates.dt, "tz", None) is not None:
        updated_dates = updated_dates.dt.tz_localize(None)
    enriched["Status Age Days"] = (
        (now.normalize() - updated_dates.dt.normalize()).dt.days
    ).fillna("")
    return enriched
