from __future__ import annotations

import os
from urllib.parse import urlencode

import streamlit as st

from src.logistics_integrations import normalize_phone

DEFAULT_DOUBLETICK_WABA = "971521367907"
DEFAULT_3CX_WEBCLIENT_URL = "https://eciwe1.3cx.ae:6001/"


def _configured_doubletick_waba() -> str:
    candidates: list[object] = []
    try:
        doubletick = dict(st.secrets.get("doubletick", {}))
        candidates.extend(
            [
                doubletick.get("waba_number"),
                doubletick.get("sender_number"),
                doubletick.get("doubletick_waba_number"),
            ]
        )
    except Exception:
        pass

    candidates.extend(
        [
            os.getenv("DOUBLETICK_WABA_NUMBER"),
            os.getenv("WABA_NUMBER"),
            DEFAULT_DOUBLETICK_WABA,
        ]
    )

    for candidate in candidates:
        normalized = normalize_phone(candidate)
        if normalized:
            return normalized
    return DEFAULT_DOUBLETICK_WABA


def threecx_webclient_url() -> str:
    candidates: list[object] = []
    try:
        threecx = dict(st.secrets.get("threecx", {}))
        logistics = dict(st.secrets.get("logistics", {}))
        candidates.extend(
            [
                threecx.get("webclient_url"),
                logistics.get("threecx_webclient_url"),
            ]
        )
    except Exception:
        pass

    candidates.extend(
        [
            os.getenv("THREECX_WEBCLIENT_URL"),
            DEFAULT_3CX_WEBCLIENT_URL,
        ]
    )
    for candidate in candidates:
        value = str(candidate or "").strip()
        if value.startswith("https://") or value.startswith("http://"):
            return value
    return DEFAULT_3CX_WEBCLIENT_URL


def doubletick_chat_link(phone: object) -> str:
    """Open the exact DoubleTick conversation without requiring an API key."""
    normalized = normalize_phone(phone)
    if not normalized:
        return "#"

    waba = _configured_doubletick_waba()
    query = urlencode(
        {
            "status": "all",
            "slaStatus": "non-breached",
            "tags": "",
            "tagIds": "",
        }
    )
    return f"https://web.doubletick.io/conversations/{waba}/{normalized}?{query}"
