from __future__ import annotations

from typing import Any

import pandas as pd
from gspread.utils import rowcol_to_a1

from src.data_loader import load_all_data
from src.logistics import CASE_HEADERS, load_cases, logistics_book


def _text(value: Any) -> str:
    if value is None:
        return ""
    try:
        if pd.isna(value):
            return ""
    except (TypeError, ValueError):
        pass
    return str(value).strip()


def refresh_logistics_contacts_from_sources() -> dict[str, int]:
    """Refresh existing logistics customer names and phones by exact Portal+AWB.

    The operational loader already enriches Tawseeel_Orders from each portal's
    Tawseel_AWB tab. This function persists those corrected values into the
    isolated LOGISTICS_CASES sheet without altering assignments or agent work.
    """
    source, _ = load_all_data()
    cases = load_cases()
    if source.empty or cases.empty:
        return {"contacts_refreshed": 0}

    source_lookup: dict[tuple[str, str], dict[str, str]] = {}
    for _, row in source.iterrows():
        portal = _text(row.get("Portal")).casefold()
        awb = _text(row.get("AWB"))
        if not portal or not awb:
            continue
        source_lookup[(portal, awb)] = {
            "Customer Name": _text(row.get("Customer Name")),
            "Mobile": _text(row.get("Mobile")),
        }

    updates: list[dict[str, object]] = []
    changed = 0
    for frame_index, row in cases.iterrows():
        key = (_text(row.get("Portal")).casefold(), _text(row.get("AWB")))
        contact = source_lookup.get(key)
        if not contact:
            continue

        current = row.to_dict()
        row_changed = False
        for column in ["Customer Name", "Mobile"]:
            latest = _text(contact.get(column))
            if latest and latest != _text(current.get(column)):
                current[column] = latest
                row_changed = True

        if row_changed:
            changed += 1
            row_number = int(frame_index) + 2
            end_column = rowcol_to_a1(1, len(CASE_HEADERS)).rstrip("1")
            updates.append(
                {
                    "range": f"A{row_number}:{end_column}{row_number}",
                    "values": [[_text(current.get(header, "")) for header in CASE_HEADERS]],
                }
            )

    if updates:
        logistics_book().worksheet("LOGISTICS_CASES").batch_update(updates, raw=False)
        load_cases.__globals__["_clear_table_cache"]()

    return {"contacts_refreshed": changed}
