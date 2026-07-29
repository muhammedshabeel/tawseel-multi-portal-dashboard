from __future__ import annotations

import re
from typing import Any

import pandas as pd
import streamlit as st

from src.data_loader import get_gspread_client
from src.logistics_integrations import normalize_phone

DIRECTORY_SOURCES = [
    {
        "sheet_id": "1zz4OOiR319zn9o5Ax9iatY_3yoFlXhTcMfsx0e2R5wA",
        "sheet_name": "LEAD-DOUBLE TICK",
        "header_row": 1,
        "name_columns": ["Name", "Whatsapp Name"],
        "phone_column": "Phone number",
    }
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


def _key(value: Any) -> str:
    return re.sub(r"[^a-z0-9]+", "", _text(value).casefold())


def _header_lookup(headers: list[str]) -> dict[str, int]:
    return {_key(header): index for index, header in enumerate(headers)}


@st.cache_data(ttl=300, show_spinner=False)
def _load_name_phone_map() -> dict[str, str]:
    client = get_gspread_client()
    candidates: dict[str, set[str]] = {}

    for source in DIRECTORY_SOURCES:
        try:
            values = (
                client.open_by_key(source["sheet_id"])
                .worksheet(source["sheet_name"])
                .get_all_values()
            )
        except Exception:
            continue

        header_row = max(int(source.get("header_row", 1)), 1)
        if len(values) < header_row:
            continue

        headers = [_text(value) for value in values[header_row - 1]]
        lookup = _header_lookup(headers)
        phone_index = lookup.get(_key(source["phone_column"]))
        name_indexes = [
            lookup[_key(column)]
            for column in source.get("name_columns", [])
            if _key(column) in lookup
        ]
        if phone_index is None or not name_indexes:
            continue

        for row in values[header_row:]:
            if phone_index >= len(row):
                continue
            phone = normalize_phone(row[phone_index])
            if not phone:
                continue
            for index in name_indexes:
                if index >= len(row):
                    continue
                name_key = _key(row[index])
                if name_key:
                    candidates.setdefault(name_key, set()).add(phone)

    return {
        name_key: next(iter(phones))
        for name_key, phones in candidates.items()
        if len(phones) == 1
    }


def fill_missing_customer_phones(cases: pd.DataFrame) -> pd.DataFrame:
    if cases.empty:
        return cases

    directory = _load_name_phone_map()
    enriched = cases.copy()

    for index, row in enriched.iterrows():
        if normalize_phone(row.get("Mobile", "")):
            continue
        for candidate in [row.get("Customer Name", ""), row.get("Mobile", "")]:
            phone = directory.get(_key(candidate), "")
            if phone:
                enriched.at[index, "Mobile"] = phone
                break

    return enriched
