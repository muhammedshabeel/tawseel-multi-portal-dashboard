"""Shared source package initialization.

Includes a narrow Streamlit compatibility guard for the Logistics Recovery
workspace. Older logistics UI code used ``icon=\"OK\"`` for toast messages,
but current Streamlit versions only accept a single emoji character.
"""

from __future__ import annotations

from typing import Any

import streamlit as st


if not getattr(st.toast, "_logistics_icon_guard", False):
    _streamlit_toast = st.toast

    def _toast_with_valid_icon(
        body: Any,
        *,
        icon: str | None = None,
        duration: str | int = "short",
    ) -> Any:
        """Convert the legacy Logistics toast icon into a valid emoji."""
        if icon == "OK":
            icon = "✅"
        return _streamlit_toast(body, icon=icon, duration=duration)

    _toast_with_valid_icon._logistics_icon_guard = True  # type: ignore[attr-defined]
    st.toast = _toast_with_valid_icon  # type: ignore[assignment]
