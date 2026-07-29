from __future__ import annotations

import os
from urllib.parse import urlencode

import streamlit as st

from src.logistics_integrations import normalize_phone

DEFAULT_DOUBLETICK_WABA = "971521367907"


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


def threecx_call_link(phone: object) -> str:
    """Use callto: so the 3CX Click2Call extension can intercept the call."""
    normalized = normalize_phone(phone)
    return f"callto:+{normalized}" if normalized else "#"


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
