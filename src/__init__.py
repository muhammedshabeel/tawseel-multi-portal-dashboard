"""Shared source package initialization.

Contains narrow compatibility patches used only by the Logistics Recovery
workspace. These guards do not change Tawseel data or any other dashboard.
"""

from __future__ import annotations

from typing import Any

import pandas as pd
import streamlit as st


# Current Streamlit versions accept only a single emoji for toast icons.
if not getattr(st.toast, "_logistics_icon_guard", False):
    _streamlit_toast = st.toast

    def _toast_with_valid_icon(
        body: Any,
        *,
        icon: str | None = None,
        duration: str | int = "short",
    ) -> Any:
        if icon == "OK":
            icon = "✅"
        return _streamlit_toast(body, icon=icon, duration=duration)

    _toast_with_valid_icon._logistics_icon_guard = True  # type: ignore[attr-defined]
    st.toast = _toast_with_valid_icon  # type: ignore[assignment]


# Replace the legacy Logistics "Focus" choices with the exact Tawseel courier
# statuses present in the selected agent's assigned cases. RTO Converted remains
# a final Kanban column and export category, not a dropdown option.
try:
    from streamlit.delta_generator import DeltaGenerator
    from src import logistics_kanban_compact as _logistics_kanban

    _original_render = _logistics_kanban.render_logistics_kanban_compact
    _original_filter_status_date = _logistics_kanban._filter_status_date
    _original_selectbox = DeltaGenerator.selectbox

    _status_options: list[str] = []
    _selected_status: str = "All Tawseel statuses"

    def _patched_selectbox(self: Any, label: str, options: Any, *args: Any, **kwargs: Any) -> Any:
        global _selected_status
        key = str(kwargs.get("key", ""))
        if label == "Focus" and key.startswith("kanban_focus_"):
            label = "Tawseel status"
            options = ["All Tawseel statuses", *_status_options]
        result = _original_selectbox(self, label, options, *args, **kwargs)
        if key.startswith("kanban_focus_"):
            _selected_status = str(result)
        return result

    def _patched_filter_status_date(cases: pd.DataFrame, status_date: str) -> pd.DataFrame:
        filtered = _original_filter_status_date(cases, status_date)
        if _selected_status == "All Tawseel statuses":
            return filtered
        latest = filtered.get(
            "Latest Courier Status",
            pd.Series("", index=filtered.index, dtype=str),
        ).fillna("").astype(str).str.strip()
        return filtered[latest.str.casefold().eq(_selected_status.casefold())].copy()

    def _patched_render_logistics_kanban_compact(
        *,
        agent: str,
        all_cases: pd.DataFrame,
        activity: pd.DataFrame,
    ) -> None:
        global _status_options, _selected_status
        assigned = all_cases[
            all_cases.get(
                "Logistics Agent",
                pd.Series("", index=all_cases.index, dtype=str),
            )
            .fillna("")
            .astype(str)
            .str.upper()
            .eq(agent.upper())
        ].copy()
        latest = assigned.get(
            "Latest Courier Status",
            pd.Series("", index=assigned.index, dtype=str),
        ).fillna("").astype(str).str.strip()
        status_by_key: dict[str, str] = {}
        for value in latest.tolist():
            if value:
                status_by_key.setdefault(value.casefold(), value)
        _status_options = sorted(status_by_key.values(), key=str.casefold)

        state_key = f"kanban_focus_{agent}"
        allowed = {"All Tawseel statuses", *_status_options}
        current = str(st.session_state.get(state_key, "All Tawseel statuses"))
        if current not in allowed:
            st.session_state[state_key] = "All Tawseel statuses"
            current = "All Tawseel statuses"
        _selected_status = current

        _original_render(agent=agent, all_cases=all_cases, activity=activity)

    if not getattr(DeltaGenerator.selectbox, "_logistics_status_guard", False):
        _patched_selectbox._logistics_status_guard = True  # type: ignore[attr-defined]
        DeltaGenerator.selectbox = _patched_selectbox  # type: ignore[assignment]

    _logistics_kanban._filter_status_date = _patched_filter_status_date
    _logistics_kanban.render_logistics_kanban_compact = (
        _patched_render_logistics_kanban_compact
    )
except Exception:
    # Keep the rest of the application available even if Streamlit internals
    # change. The source module remains the fallback renderer.
    pass
