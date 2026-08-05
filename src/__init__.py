"""Shared source package initialization.

Contains narrow compatibility patches used only by the Logistics Recovery
workspace. These guards do not change Tawseel data or any other dashboard.
"""

from __future__ import annotations

from html import escape
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
# statuses present in the selected agent's visible cases. Kanban columns continue
# to represent the separate Logistics work stage, so the current Tawseel status is
# also printed on every card to avoid confusion.
try:
    from streamlit.delta_generator import DeltaGenerator
    from src import logistics_kanban_compact as _logistics_kanban
    from src.logistics_dashboard_metrics import logistics_case_masks

    _original_render = _logistics_kanban.render_logistics_kanban_compact
    _original_filter_status_date = _logistics_kanban._filter_status_date
    _original_selectbox = DeltaGenerator.selectbox

    _status_options: list[str] = []
    _selected_status: str = "All Tawseel statuses"

    def _patched_selectbox(
        self: Any,
        label: str,
        options: Any,
        *args: Any,
        **kwargs: Any,
    ) -> Any:
        global _selected_status
        key = str(kwargs.get("key", ""))
        if label == "Focus" and key.startswith("kanban_focus_"):
            label = "Tawseel status"
            options = ["All Tawseel statuses", *_status_options]
        result = _original_selectbox(self, label, options, *args, **kwargs)
        if key.startswith("kanban_focus_"):
            _selected_status = str(result)
        return result

    def _patched_filter_status_date(
        cases: pd.DataFrame,
        status_date: str,
    ) -> pd.DataFrame:
        filtered = _original_filter_status_date(cases, status_date)
        if _selected_status == "All Tawseel statuses":
            return filtered
        latest = filtered.get(
            "Latest Courier Status",
            pd.Series("", index=filtered.index, dtype=str),
        ).fillna("").astype(str).str.strip()
        return filtered[
            latest.str.casefold().eq(_selected_status.casefold())
        ].copy()

    def _patched_render_card(
        agent: str,
        row: pd.Series,
        stage: str,
        assigned_all: pd.DataFrame,
        activity: pd.DataFrame,
    ) -> None:
        case_id = _logistics_kanban._text(row.get("Case ID"))
        customer = (
            _logistics_kanban._compact_text(row.get("Customer Name"), 25)
            or "Unknown customer"
        )
        awb = _logistics_kanban._text(row.get("AWB")) or "No AWB"
        portal = (
            _logistics_kanban._compact_text(row.get("Portal"), 14)
            or "Unknown portal"
        )
        courier_status = (
            _logistics_kanban._compact_text(
                row.get("Latest Courier Status"),
                22,
            )
            or "Status unavailable"
        )
        calls = pd.to_numeric(
            row.get("Total Call Attempts", 0),
            errors="coerce",
        )
        calls = 0 if pd.isna(calls) else int(calls)
        next_follow_up = _logistics_kanban._text(row.get("Next Follow-up"))

        with st.container(
            border=False,
            key=(
                f"kanban_card_{_logistics_kanban._slug(agent)}_"
                f"{case_id}"
            ),
        ):
            follow_html = ""
            if next_follow_up and stage != "RTO Converted":
                follow_html = (
                    '<div class="lk-follow-chip">Next: '
                    f'{escape(_logistics_kanban._compact_text(next_follow_up, 22))}'
                    "</div>"
                )
            st.markdown(
                f"""
                <div class="lk-card-top">
                    <span class="lk-badge">{escape(_logistics_kanban._priority_badge(row, stage))}</span>
                    <span class="lk-call-chip">Calls {calls}</span>
                </div>
                <div class="lk-customer">{escape(customer)}</div>
                <div class="lk-awb">AWB {escape(awb)}</div>
                <div class="lk-card-sub">{escape(portal)} · {escape(courier_status)}</div>
                {follow_html}
                """,
                unsafe_allow_html=True,
            )
            if st.button(
                "View" if stage == "RTO Converted" else "Open",
                key=f"kanban_open_{agent}_{case_id}",
                width="stretch",
            ):
                _logistics_kanban._order_drawer(
                    agent,
                    case_id,
                    assigned_all,
                    activity,
                )

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

        # Only offer statuses that can actually produce a visible Kanban card.
        # Closed non-converted cases are intentionally excluded from the board.
        masks = logistics_case_masks(assigned)
        closed_mask = _logistics_kanban._mask(
            masks,
            "closed",
            assigned.index,
        )
        converted_mask = _logistics_kanban._mask(
            masks,
            "rto_converted",
            assigned.index,
        )
        visible = assigned[(~closed_mask) | converted_mask].copy()

        latest = visible.get(
            "Latest Courier Status",
            pd.Series("", index=visible.index, dtype=str),
        ).fillna("").astype(str).str.strip()
        status_by_key: dict[str, str] = {}
        for value in latest.tolist():
            if value:
                status_by_key.setdefault(value.casefold(), value)
        _status_options = sorted(status_by_key.values(), key=str.casefold)

        state_key = f"kanban_focus_{agent}"
        allowed = {"All Tawseel statuses", *_status_options}
        current = str(
            st.session_state.get(
                state_key,
                "All Tawseel statuses",
            )
        )
        if current not in allowed:
            st.session_state[state_key] = "All Tawseel statuses"
            current = "All Tawseel statuses"
        _selected_status = current

        _original_render(
            agent=agent,
            all_cases=all_cases,
            activity=activity,
        )

    if not getattr(
        DeltaGenerator.selectbox,
        "_logistics_status_guard",
        False,
    ):
        _patched_selectbox._logistics_status_guard = True  # type: ignore[attr-defined]
        DeltaGenerator.selectbox = _patched_selectbox  # type: ignore[assignment]

    _logistics_kanban._filter_status_date = _patched_filter_status_date
    _logistics_kanban._render_card = _patched_render_card
    _logistics_kanban.render_logistics_kanban_compact = (
        _patched_render_logistics_kanban_compact
    )
except Exception:
    # Keep the rest of the application available even if Streamlit internals
    # change. The source module remains the fallback renderer.
    pass


# Every successful Logistics agent write is copied immediately into the
# independent backup Google Sheet. A full-table mirror is used as a fallback if
# the append-only case snapshot cannot be written after its built-in retries.
try:
    from src import logistics_kanban_compact as _backup_kanban
    from src import logistics_kanban_workspace as _backup_workspace
    from src.logistics_backup import backup_case_snapshot, mirror_logistics_backup

    _live_add_activity = _backup_kanban.add_activity
    _live_close_case = _backup_kanban.close_case

    def _write_backup(case_id: str, event_type: str) -> None:
        try:
            backup_case_snapshot(case_id, event_type)
        except Exception as snapshot_exc:
            try:
                mirror_logistics_backup()
            except Exception as mirror_exc:
                st.warning(
                    "The Logistics update was saved, but its independent backup "
                    "could not be confirmed. Report this immediately with the AWB. "
                    f"Snapshot: {type(snapshot_exc).__name__}; "
                    f"mirror: {type(mirror_exc).__name__}."
                )

    def _backed_add_activity(
        case_id: str,
        *args: Any,
        **kwargs: Any,
    ) -> None:
        _live_add_activity(case_id, *args, **kwargs)
        _write_backup(case_id, "ACTIVITY_SAVED")

    def _backed_close_case(
        case_id: str,
        *args: Any,
        **kwargs: Any,
    ) -> None:
        _live_close_case(case_id, *args, **kwargs)
        _write_backup(case_id, "CASE_CLOSED")

    if not getattr(_backup_kanban.add_activity, "_backup_guard", False):
        _backed_add_activity._backup_guard = True  # type: ignore[attr-defined]
        _backed_close_case._backup_guard = True  # type: ignore[attr-defined]
        _backup_kanban.add_activity = _backed_add_activity
        _backup_kanban.close_case = _backed_close_case
        _backup_workspace.add_activity = _backed_add_activity
        _backup_workspace.close_case = _backed_close_case
except Exception:
    # The Logistics page must remain available even if backup initialization
    # itself encounters a temporary external-service error.
    pass
