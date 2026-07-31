from __future__ import annotations

from datetime import datetime
import json
import os
from pathlib import Path
import sys
from typing import Any
from zoneinfo import ZoneInfo


DUBAI_TZ = ZoneInfo("Asia/Dubai")
RESET_CONFIRMATION = "RESET_LOGISTICS_FROM_CURRENT_TAWSEEL_2026_08_01"
ARCHIVE_TABS = [
    "LOGISTICS_CASES",
    "LOGISTICS_ACTIVITY_LOG",
    "LOGISTICS_STATUS_UPDATES",
    "LOGISTICS_DAILY_REPORT",
]
ARCHIVE_NAMES = {
    "LOGISTICS_CASES": "CASES",
    "LOGISTICS_ACTIVITY_LOG": "ACTIVITY",
    "LOGISTICS_STATUS_UPDATES": "STATUS",
    "LOGISTICS_DAILY_REPORT": "DAILY",
}


def _prepare_streamlit_secrets() -> None:
    root = Path(__file__).resolve().parents[1]
    secrets_path = root / ".streamlit" / "secrets.toml"
    if secrets_path.exists():
        return

    content = os.getenv("STREAMLIT_SECRETS_TOML", "").strip()
    if not content:
        raise RuntimeError(
            "STREAMLIT_SECRETS_TOML is missing. The reset was not started."
        )

    secrets_path.parent.mkdir(parents=True, exist_ok=True)
    secrets_path.write_text(content + "\n", encoding="utf-8")
    try:
        secrets_path.chmod(0o600)
    except OSError:
        pass


def _unique_title(book: Any, requested: str) -> str:
    existing = {worksheet.title for worksheet in book.worksheets()}
    if requested not in existing:
        return requested
    suffix = 2
    while f"{requested}_{suffix}" in existing:
        suffix += 1
    return f"{requested}_{suffix}"


def _archive_worksheet(source: Any, backup: Any, title: str, stamp: str) -> dict[str, Any]:
    values = source.get_all_values()
    short_name = ARCHIVE_NAMES.get(title, title[:12])
    archive_title = _unique_title(backup, f"RST_{stamp}_{short_name}")
    rows = max(len(values), 2)
    cols = max((len(row) for row in values), default=1)
    target = backup.add_worksheet(
        title=archive_title,
        rows=max(rows, 100),
        cols=max(cols, 10),
    )
    if values:
        target.update("A1", values, value_input_option="USER_ENTERED")
        target.freeze(rows=1)
    return {
        "source_tab": title,
        "archive_tab": archive_title,
        "rows_archived": max(len(values) - 1, 0),
    }


def _reset_table(worksheet: Any, headers: list[str]) -> None:
    worksheet.clear()
    if worksheet.col_count < len(headers):
        worksheet.add_cols(len(headers) - worksheet.col_count)
    worksheet.update("A1", [headers], value_input_option="USER_ENTERED")
    worksheet.freeze(rows=1)


def _clear_data_keep_header(worksheet: Any) -> None:
    headers = worksheet.row_values(1)
    worksheet.clear()
    if headers:
        worksheet.update("A1", [headers], value_input_option="USER_ENTERED")
        worksheet.freeze(rows=1)


def _upsert_setting(worksheet: Any, key: str, value: str) -> None:
    values = worksheet.get_all_values()
    for row_number, row in enumerate(values[1:], start=2):
        if row and str(row[0]).strip() == key:
            worksheet.update(
                f"B{row_number}",
                [[value]],
                value_input_option="USER_ENTERED",
            )
            return
    worksheet.append_row([key, value], value_input_option="USER_ENTERED")


def main() -> int:
    if os.getenv("LOGISTICS_RESET_CONFIRM", "").strip() != RESET_CONFIRMATION:
        raise RuntimeError("Reset confirmation value is missing or incorrect.")

    root = Path(__file__).resolve().parents[1]
    sys.path.insert(0, str(root))
    os.chdir(root)
    _prepare_streamlit_secrets()

    from src.logistics import (
        ACTIVITY_HEADERS,
        CASE_HEADERS,
        _clear_table_cache,
        ensure_logistics_structure,
        load_cases,
        logistics_book,
    )
    from src.logistics_assignment import assignment_counts, target_counts
    from src.logistics_backup import backup_book
    from src.logistics_status_tracking import (
        STATUS_HEADERS,
        _clear_status_cache,
        sync_logistics_cases_with_status_tracking,
    )

    ensure_logistics_structure()
    live = logistics_book()
    backup = backup_book()
    now = datetime.now(DUBAI_TZ)
    stamp = now.strftime("%Y%m%d_%H%M%S")
    reset_at = now.strftime("%Y-%m-%d %H:%M:%S")

    archived: list[dict[str, Any]] = []
    for title in ARCHIVE_TABS:
        try:
            source = live.worksheet(title)
        except Exception:
            continue
        archived.append(_archive_worksheet(source, backup, title, stamp))

    metadata_title = _unique_title(backup, f"RST_{stamp}_META")
    metadata = backup.add_worksheet(title=metadata_title, rows=30, cols=4)
    metadata.update(
        "A1",
        [
            ["Key", "Value"],
            ["Reset requested at", reset_at],
            ["Source logistics spreadsheet", live.id],
            ["Assignment policy", "VAISHAKH 15%, NEETHU 15%, HASBIR 35%, AKASH 35%"],
            ["Reset scope", "LOGISTICS ONLY"],
            ["Archive tabs", ", ".join(item["archive_tab"] for item in archived)],
        ],
        value_input_option="USER_ENTERED",
    )
    metadata.freeze(rows=1)

    _reset_table(live.worksheet("LOGISTICS_CASES"), CASE_HEADERS)
    _reset_table(live.worksheet("LOGISTICS_ACTIVITY_LOG"), ACTIVITY_HEADERS)

    try:
        status_sheet = live.worksheet("LOGISTICS_STATUS_UPDATES")
    except Exception:
        status_sheet = live.add_worksheet(
            title="LOGISTICS_STATUS_UPDATES",
            rows=5000,
            cols=len(STATUS_HEADERS),
        )
    _reset_table(status_sheet, STATUS_HEADERS)

    try:
        _clear_data_keep_header(live.worksheet("LOGISTICS_DAILY_REPORT"))
    except Exception:
        pass

    settings = live.worksheet("LOGISTICS_SETTINGS")
    _upsert_setting(settings, "NEXT_AGENT_INDEX", "0")
    _upsert_setting(settings, "LAST_CLEAN_RESET_AT", reset_at)
    _upsert_setting(settings, "LAST_CLEAN_RESET_SOURCE", "CURRENT_TAWSEEL_STATUSES")
    _upsert_setting(settings, "ASSIGNMENT_POLICY", "WEIGHTED_30_70")
    _upsert_setting(settings, "ASSIGNMENT_WEIGHTS", "VAISHAKH=0.15,NEETHU=0.15,HASBIR=0.35,AKHASH=0.35")

    _clear_table_cache()
    _clear_status_cache()

    sync_result = sync_logistics_cases_with_status_tracking()
    rebuilt = load_cases()
    actual = assignment_counts(rebuilt)
    targets = target_counts(len(rebuilt))

    if rebuilt.empty:
        raise RuntimeError(
            "Clean reset completed but no eligible current Tawseel orders were rebuilt."
        )
    if actual != targets:
        raise RuntimeError(
            f"Assignment verification failed. Expected {targets}, received {actual}."
        )

    assigned_dates = rebuilt.get("Assigned At", []).astype(str)
    today_prefix = now.strftime("%Y-%m-%d")
    assigned_today = int(assigned_dates.str.startswith(today_prefix).sum())
    if assigned_today != len(rebuilt):
        raise RuntimeError(
            f"Reset date verification failed: {assigned_today}/{len(rebuilt)} cases assigned today."
        )

    status_counts = (
        rebuilt.get("Latest Courier Status", [])
        .fillna("")
        .astype(str)
        .value_counts(dropna=False)
        .to_dict()
    )

    result = {
        "reset_at": reset_at,
        "scope": "LOGISTICS_ONLY",
        "archive_metadata_tab": metadata_title,
        "archived": archived,
        "rebuilt_cases": len(rebuilt),
        "assigned_today": assigned_today,
        "assignment_target": targets,
        "assignment_actual": actual,
        "assignment_exact": actual == targets,
        "current_tawseel_status_counts": status_counts,
        "sync": sync_result,
    }
    print(json.dumps(result, indent=2, sort_keys=True, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
