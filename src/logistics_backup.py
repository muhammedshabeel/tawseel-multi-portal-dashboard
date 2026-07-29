from __future__ import annotations

from datetime import datetime
from typing import Any
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


def _ensure_backup_tab(title: str, rows: int, cols: int) -> gspread.Worksheet:
    book = backup_book()
    try:
        worksheet = book.worksheet(title)
        if worksheet.row_count < rows:
            worksheet.add_rows(rows - worksheet.row_count)
        if worksheet.col_count < cols:
            worksheet.add_cols(cols - worksheet.col_count)
        return worksheet
    except gspread.WorksheetNotFound:
        return book.add_worksheet(
            title=title,
            rows=max(rows, 100),
            cols=max(cols, 10),
        )


def mirror_logistics_backup() -> dict[str, Any]:
    """Mirror all current logistics tables into the independent backup workbook."""
    live = logistics_book()
    copied: dict[str, int] = {}

    for title in BACKUP_TABS:
        try:
            source = live.worksheet(title)
        except gspread.WorksheetNotFound:
            continue

        values = source.get_all_values()
        row_count = max(len(values), 1)
        col_count = max((len(row) for row in values), default=1)
        target = _ensure_backup_tab(title, row_count, col_count)
        target.clear()
        if values:
            target.update("A1", values, value_input_option="USER_ENTERED")
            if len(values) > 1:
                target.freeze(rows=1)
        copied[title] = max(len(values) - 1, 0)

    metadata = _ensure_backup_tab("BACKUP_METADATA", 20, 4)
    metadata.update(
        "A1",
        [
            ["Key", "Value"],
            [
                "Last Successful Backup At",
                datetime.now(ZoneInfo("Asia/Dubai")).strftime("%Y-%m-%d %H:%M:%S"),
            ],
            ["Source Spreadsheet ID", live.id],
            ["Backup Spreadsheet ID", backup_book().id],
            ["Copied Tabs", ", ".join(copied)],
        ],
        value_input_option="USER_ENTERED",
    )
    metadata.freeze(rows=1)
    return {"backup_tabs": copied, "backup_sheet_id": backup_book().id}
