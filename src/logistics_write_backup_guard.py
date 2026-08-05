"""Write-through backup guard for Logistics Recovery agent actions."""

from __future__ import annotations

from typing import Any, Callable


def install_write_through_backup() -> None:
    """Wrap Logistics writes so every saved action gets an independent snapshot."""
    from src import logistics as logistics_module
    from src import logistics_kanban_compact as kanban_module
    from src.logistics_backup import backup_case_snapshot, mirror_logistics_backup

    if getattr(logistics_module.add_activity, "_backup_guard", False):
        return

    original_add_activity = logistics_module.add_activity
    original_close_case = logistics_module.close_case

    def _capture(case_id: str, event_type: str) -> None:
        try:
            backup_case_snapshot(case_id, event_type)
            return
        except Exception as snapshot_exc:
            try:
                mirror_logistics_backup()
                return
            except Exception as mirror_exc:
                raise RuntimeError(
                    "The Logistics update was saved in the live sheet, but the "
                    "independent backup could not be confirmed. Do not repeat "
                    "the action. Report the AWB and this error to the manager. "
                    f"Snapshot error: {type(snapshot_exc).__name__}: "
                    f"{str(snapshot_exc).strip()}; mirror error: "
                    f"{type(mirror_exc).__name__}: {str(mirror_exc).strip()}"
                ) from mirror_exc

    def add_activity_with_backup(
        case_id: str,
        action_type: str,
        call_result: str = "",
        customer_response: str = "",
        remark: str = "",
        next_follow_up: str = "",
        new_status: str = "",
    ) -> None:
        original_add_activity(
            case_id,
            action_type=action_type,
            call_result=call_result,
            customer_response=customer_response,
            remark=remark,
            next_follow_up=next_follow_up,
            new_status=new_status,
        )
        _capture(case_id, "ACTIVITY")

    def close_case_with_backup(
        case_id: str,
        outcome: str,
        delivered_after_coordination: bool = False,
        delivered_date: str = "",
        remark: str = "",
    ) -> None:
        original_close_case(
            case_id,
            outcome=outcome,
            delivered_after_coordination=delivered_after_coordination,
            delivered_date=delivered_date,
            remark=remark,
        )
        _capture(case_id, "CLOSE")

    add_activity_with_backup._backup_guard = True  # type: ignore[attr-defined]
    close_case_with_backup._backup_guard = True  # type: ignore[attr-defined]

    logistics_module.add_activity = add_activity_with_backup
    logistics_module.close_case = close_case_with_backup

    # The compact Kanban imports these functions directly, so update its bound
    # references as well. This keeps the patch limited to Logistics Recovery.
    kanban_module.add_activity = add_activity_with_backup
    kanban_module.close_case = close_case_with_backup
