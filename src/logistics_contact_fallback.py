from __future__ import annotations

import re
from typing import Any

import pandas as pd
import streamlit as st

from src.data_loader import get_gspread_client, get_portal_configs
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


def _first_header_index(lookup: dict[str, int], aliases: list[str]) -> int | None:
    for alias in aliases:
        index = lookup.get(_key(alias))
        if index is not None:
            return index
    return None


def _cell(row: list[Any], index: int | None) -> str:
    if index is None or index >= len(row):
        return ""
    return _text(row[index])


@st.cache_data(ttl=180, show_spinner=False)
def _load_portal_awb_contacts() -> dict[tuple[str, str], dict[str, str]]:
    """Read exact AWB contacts from each configured portal input tab.

    Tawseeel_Orders remains the courier-status source. The portal input tab
    (normally Tawseel_AWB) is the contact authority because it contains the
    original customer name and phone before the scraper writes status results.
    """
    client = get_gspread_client()
    contacts: dict[tuple[str, str], dict[str, str]] = {}

    for config in get_portal_configs():
        try:
            values = (
                client.open_by_key(config.sheet_id)
                .worksheet(config.input_tab)
                .get_all_values()
            )
        except Exception:
            continue

        if not values:
            continue

        headers = [_text(value) for value in values[0]]
        lookup = _header_lookup(headers)
        awb_index = _first_header_index(
            lookup,
            ["AWB", "Tracking Number", "Tracking Num", "Tracking No", "Waybill"],
        )
        name_index = _first_header_index(
            lookup,
            ["Customer Name", "Customer", "Name", "Consignee Name", "Recipient Name"],
        )
        phone_index = _first_header_index(
            lookup,
            [
                "Phone",
                "Mobile",
                "Phone Number",
                "Mobile Number",
                "Customer Phone",
                "Contact Number",
                "Number1",
                "Phone1",
            ],
        )
        agent_index = _first_header_index(lookup, ["Agent", "Assigned Agent"])

        if awb_index is None:
            continue

        for row in values[1:]:
            awb = _cell(row, awb_index)
            if not awb:
                continue
            contacts[(config.name.casefold(), awb)] = {
                "name": _cell(row, name_index),
                "phone": normalize_phone(_cell(row, phone_index)),
                "agent": _cell(row, agent_index),
            }

    return contacts


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

    portal_contacts = _load_portal_awb_contacts()
    directory = _load_name_phone_map()
    enriched = cases.copy()

    for index, row in enriched.iterrows():
        portal = _text(row.get("Portal", ""))
        awb = _text(row.get("AWB", ""))
        exact = portal_contacts.get((portal.casefold(), awb), {})

        exact_name = _text(exact.get("name", ""))
        exact_phone = normalize_phone(exact.get("phone", ""))
        if exact_name:
            enriched.at[index, "Customer Name"] = exact_name
        if exact_phone:
            enriched.at[index, "Mobile"] = exact_phone
            continue

        if normalize_phone(row.get("Mobile", "")):
            continue

        for candidate in [
            exact_name,
            row.get("Customer Name", ""),
            row.get("Mobile", ""),
        ]:
            phone = directory.get(_key(candidate), "")
            if phone:
                enriched.at[index, "Mobile"] = phone
                break

    return enriched
