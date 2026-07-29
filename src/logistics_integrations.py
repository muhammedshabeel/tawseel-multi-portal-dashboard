from __future__ import annotations

import json
import os
import re
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

import pandas as pd
import streamlit as st

from src.data_loader import get_gspread_client, get_portal_configs

DEFAULT_COUNTRY_CODE = "971"
DOUBLE_TICK_EMBED_ENDPOINT = "https://public.doubletick.io/embed/url"

# Read-only fallbacks used only by the Logistics Recovery module. They can be
# replaced or extended through Streamlit secrets without changing code.
DEFAULT_AWB_CONTACT_SOURCES = [
    {
        "portal": "Oud Al Salam",
        "sheet_id": "1j6BeDMpjMzvHSKwg-tnXx1nyv-whyNsRphput-vznYo",
        "sheet_name": "Sheet2",
        "header_row": 3,
        "awb_column": "AWB NUMBER",
        "name_column": "CUSTOMER NAME",
        "phone_column": "MOBILE NO",
    }
]

DEFAULT_CUSTOMER_DIRECTORY = {
    "sheet_id": "1-_ANHqeytND5jgCPmQVn-bERtpJQU437ntUpMNnM3jw",
    "sheet_name": "Sheet1",
    "header_row": 1,
    "name_column": "Name",
    "phone_column": "Phone number",
}


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


def _looks_like_reference(value: Any) -> bool:
    text = _text(value).upper().replace(" ", "")
    return bool(re.fullmatch(r"(?:EM|EG|SP|OAS|REF)[A-Z0-9_-]{3,}", text))


def normalize_phone(value: Any, default_country_code: str = DEFAULT_COUNTRY_CODE) -> str:
    """Return an international phone number containing digits only.

    Names or mixed alphanumeric values are rejected instead of extracting their
    trailing digits. UAE local numbers are normalized to country code 971.
    """
    raw = _text(value)
    if not raw or re.search(r"[A-Za-z]", raw):
        return ""

    digits = re.sub(r"\D", "", raw)
    if digits.startswith("00"):
        digits = digits[2:]

    if len(digits) == 10 and digits.startswith("0"):
        digits = f"{default_country_code}{digits[1:]}"
    elif len(digits) == 9 and digits.startswith("5"):
        digits = f"{default_country_code}{digits}"

    if not 10 <= len(digits) <= 15:
        return ""
    if digits.startswith("0"):
        return ""
    return digits


def phone_display(value: Any) -> str:
    phone = normalize_phone(value)
    return f"+{phone}" if phone else "Unavailable"


def _header_index(headers: list[str], explicit: str | None, aliases: set[str]) -> int | None:
    if explicit:
        explicit_key = _key(explicit)
        for index, header in enumerate(headers):
            if _key(header) == explicit_key:
                return index
    for index, header in enumerate(headers):
        if _key(header) in aliases:
            return index
    return None


def _safe_cell(row: list[Any], index: int | None) -> str:
    if index is None or index < 0 or index >= len(row):
        return ""
    return _text(row[index])


def _source_rows() -> list[dict[str, Any]]:
    sources = [dict(item) for item in DEFAULT_AWB_CONTACT_SOURCES]

    configured: Any = []
    try:
        configured = st.secrets.get("logistics_contact_sources", [])
    except Exception:
        configured = []

    if isinstance(configured, dict):
        configured = [configured]
    for item in configured or []:
        try:
            sources.append(dict(item))
        except Exception:
            continue
    return sources


@st.cache_data(ttl=300, show_spinner=False)
def _load_explicit_awb_contacts() -> dict[tuple[str, str], dict[str, str]]:
    client = get_gspread_client()
    result: dict[tuple[str, str], dict[str, str]] = {}

    for source in _source_rows():
        portal = _text(source.get("portal"))
        sheet_id = _text(source.get("sheet_id"))
        sheet_name = _text(source.get("sheet_name"))
        if not portal or not sheet_id or not sheet_name:
            continue

        try:
            header_row = max(int(source.get("header_row", 1)), 1)
            values = client.open_by_key(sheet_id).worksheet(sheet_name).get_all_values()
            if len(values) < header_row:
                continue

            headers = [_text(value) for value in values[header_row - 1]]
            awb_index = _header_index(
                headers,
                _text(source.get("awb_column")),
                {"awb", "awbnumber", "trackingnumber", "trackingnum", "waybill"},
            )
            name_index = _header_index(
                headers,
                _text(source.get("name_column")),
                {"customername", "consigneename", "recipientname", "name"},
            )
            phone_index = _header_index(
                headers,
                _text(source.get("phone_column")),
                {"mobile", "mobileno", "mobilenumber", "phone", "phonenumber", "number1"},
            )
            if awb_index is None:
                continue

            for row in values[header_row:]:
                awb = _safe_cell(row, awb_index)
                if not awb:
                    continue
                phone = normalize_phone(_safe_cell(row, phone_index))
                name = _safe_cell(row, name_index)
                if phone or name:
                    result[(portal.casefold(), awb)] = {"name": name, "phone": phone}
        except Exception:
            continue

    return result


@st.cache_data(ttl=300, show_spinner=False)
def _load_portal_master_contacts() -> dict[tuple[str, str], dict[str, str]]:
    """Inspect complete portal master rows without changing existing dashboards."""
    client = get_gspread_client()
    result: dict[tuple[str, str], dict[str, str]] = {}

    for config in get_portal_configs():
        try:
            values = client.open_by_key(config.sheet_id).worksheet(config.master_tab).get_all_values()
            if not values:
                continue
            headers = [_text(value) for value in values[0]]
            awb_index = _header_index(
                headers,
                None,
                {"awb", "awbnumber", "trackingnumber", "trackingnum", "trackingno", "waybill"},
            )
            if awb_index is None:
                continue

            name_indexes = [
                index
                for index, header in enumerate(headers)
                if _key(header) in {"customername", "consigneename", "recipientname", "name"}
            ]
            phone_indexes = [
                index
                for index, header in enumerate(headers)
                if _key(header)
                in {
                    "mobile", "mobileno", "mobilenumber", "phone", "phonenumber",
                    "customerphone", "contactnumber", "number1", "phone1",
                }
            ]

            for row in values[1:]:
                awb = _safe_cell(row, awb_index)
                if not awb:
                    continue

                phone = ""
                for index in phone_indexes:
                    candidate = _safe_cell(row, index)
                    normalized = normalize_phone(candidate)
                    if normalized and re.sub(r"\D", "", candidate) != re.sub(r"\D", "", awb):
                        phone = normalized
                        break

                if not phone:
                    for index, cell in enumerate(row):
                        if index == awb_index:
                            continue
                        normalized = normalize_phone(cell)
                        if normalized and re.sub(r"\D", "", _text(cell)) != re.sub(r"\D", "", awb):
                            phone = normalized
                            break

                name = ""
                for index in name_indexes:
                    candidate = _safe_cell(row, index)
                    if candidate and not _looks_like_reference(candidate) and not normalize_phone(candidate):
                        name = candidate
                        break

                if phone or name:
                    result[(config.name.casefold(), awb)] = {"name": name, "phone": phone}
        except Exception:
            continue

    return result


def _directory_config() -> dict[str, Any]:
    config = dict(DEFAULT_CUSTOMER_DIRECTORY)
    try:
        logistics = dict(st.secrets.get("logistics", {}))
    except Exception:
        logistics = {}

    mappings = {
        "customer_directory_sheet_id": "sheet_id",
        "customer_directory_sheet_name": "sheet_name",
        "customer_directory_header_row": "header_row",
        "customer_directory_name_column": "name_column",
        "customer_directory_phone_column": "phone_column",
    }
    for secret_key, config_key in mappings.items():
        value = logistics.get(secret_key)
        if value not in (None, ""):
            config[config_key] = value
    return config


@st.cache_data(ttl=300, show_spinner=False)
def _load_name_directory() -> dict[str, str]:
    config = _directory_config()
    client = get_gspread_client()
    try:
        values = (
            client.open_by_key(_text(config.get("sheet_id")))
            .worksheet(_text(config.get("sheet_name")))
            .get_all_values()
        )
        header_row = max(int(config.get("header_row", 1)), 1)
        if len(values) < header_row:
            return {}

        headers = [_text(value) for value in values[header_row - 1]]
        name_index = _header_index(
            headers,
            _text(config.get("name_column")),
            {"name", "customername", "whatsappname"},
        )
        phone_index = _header_index(
            headers,
            _text(config.get("phone_column")),
            {"phonenumber", "phone", "mobile", "mobilenumber"},
        )
        if name_index is None or phone_index is None:
            return {}

        candidates: dict[str, set[str]] = {}
        for row in values[header_row:]:
            name_key = _key(_safe_cell(row, name_index))
            phone = normalize_phone(_safe_cell(row, phone_index))
            if name_key and phone:
                candidates.setdefault(name_key, set()).add(phone)

        return {
            name_key: next(iter(phones))
            for name_key, phones in candidates.items()
            if len(phones) == 1
        }
    except Exception:
        return {}


def enrich_case_contacts(cases: pd.DataFrame) -> pd.DataFrame:
    """Correct customer name/mobile for the Logistics CRM display only."""
    if cases.empty:
        return cases

    explicit = _load_explicit_awb_contacts()
    portal_master = _load_portal_master_contacts()
    directory = _load_name_directory()
    enriched = cases.copy()

    for index, row in enriched.iterrows():
        portal = _text(row.get("Portal"))
        awb = _text(row.get("AWB"))
        existing_name = _text(row.get("Customer Name"))
        existing_mobile = _text(row.get("Mobile"))
        lookup_key = (portal.casefold(), awb)

        contact = explicit.get(lookup_key) or portal_master.get(lookup_key) or {}
        corrected_name = _text(contact.get("name"))
        corrected_phone = normalize_phone(contact.get("phone"))

        current_phone = normalize_phone(existing_mobile)
        if current_phone:
            corrected_phone = current_phone

        probable_name = existing_name
        if not current_phone and existing_mobile and not normalize_phone(existing_mobile):
            probable_name = existing_mobile
        if corrected_name:
            probable_name = corrected_name
        elif _looks_like_reference(probable_name) and existing_mobile:
            probable_name = existing_mobile

        if not corrected_phone:
            corrected_phone = directory.get(_key(probable_name), "")

        enriched.at[index, "Customer Name"] = probable_name or existing_name
        enriched.at[index, "Mobile"] = corrected_phone

    return enriched


def _secret_value(*keys: str) -> str:
    try:
        doubletick = dict(st.secrets.get("doubletick", {}))
    except Exception:
        doubletick = {}

    for key in keys:
        value = doubletick.get(key)
        if value not in (None, ""):
            return _text(value)
        try:
            value = st.secrets.get(key)
        except Exception:
            value = None
        if value not in (None, ""):
            return _text(value)
        env_value = os.getenv(key.upper())
        if env_value:
            return env_value.strip()
    return ""


@st.cache_data(ttl=300, show_spinner=False)
def get_doubletick_embed_url(phone: str) -> str:
    normalized = normalize_phone(phone)
    if not normalized:
        raise ValueError("A valid customer mobile number is required.")

    api_key = _secret_value("api_key", "public_api_key", "doubletick_api_key")
    if not api_key:
        raise RuntimeError("DoubleTick API key is not configured in Streamlit Secrets.")

    payload: dict[str, str] = {"phone": normalized}
    integration_id = _secret_value("integration_id", "doubletick_integration_id")
    waba_number = normalize_phone(_secret_value("waba_number", "sender_number", "doubletick_waba_number"))
    if integration_id:
        payload["integrationId"] = integration_id
    elif waba_number:
        payload["wabaNumber"] = waba_number

    request = Request(
        DOUBLE_TICK_EMBED_ENDPOINT,
        data=json.dumps(payload).encode("utf-8"),
        headers={
            "Authorization": api_key,
            "Content-Type": "application/json",
            "Accept": "application/json",
        },
        method="POST",
    )

    try:
        with urlopen(request, timeout=20) as response:
            result = json.loads(response.read().decode("utf-8"))
    except HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace")
        try:
            message = json.loads(body).get("message", body)
        except json.JSONDecodeError:
            message = body
        raise RuntimeError(f"DoubleTick returned HTTP {exc.code}: {message}") from exc
    except URLError as exc:
        raise RuntimeError(f"Could not connect to DoubleTick: {exc.reason}") from exc

    url = _text(result.get("url"))
    if not url:
        raise RuntimeError("DoubleTick did not return a conversation URL.")
    return url
