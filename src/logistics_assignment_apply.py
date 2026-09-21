from __future__ import annotations

from datetime import datetime
import hashlib
from typing import Any
from zoneinfo import ZoneInfo

import pandas as pd
from gspread.utils import rowcol_to_a1

from src.logistics import (
    ACTIVITY_HEADERS,
    CASE_HEADERS,
    _clear_table_cache,
    load_activity,
    load_cases,
    logistics_book,
)
from src.logistics_assignment import (
    ASSIGNMENT_METHOD,
    ASSIGNMENT_ORDER,
    ASSIGNMENT_POLICY_VERSION,
    ASSIGNMENT_WEIGHTS,
    active_assignment_cases,
    assignment_counts,
    target_counts,
    weighted_assignments,
)


def _now() -> str:
    return datetime.now(ZoneInfo("Asia/Dubai")).strftime("%Y-%m-%d %H:%M:%S")


def _text(value: Any) -> str:
    if value is None:
        return ""
    try:
        if pd.isna(value):
            return ""
    except (TypeError, ValueError):
        pass
    return str(value).strip()


def _row_values(record: dict[str, Any], headers: list[str]) -> list[str]:
    return [_text(record.get(header, "")) for header in headers]


def _batch_update_rows(
    worksheet: Any,
    updates: list[tuple[int, list[str]]],
    width: int,
    chunk_size: int = 150,
) -> None:
    if not updates:
        return
    end_column = rowcol_to_a1(1, width).rstrip("1")
    for start in range(0, len(updates), chunk_size):
        chunk = updates[start : start + chunk_size]
        worksheet.batch_update(
            [
                {
                    "range": f"A{row_number}:{end_column}{row_number}",
                    "values": [values],
                }
                for row_number, values in chunk
            ],
            raw=False,
        )


def _normalise_needed(
    targets: dict[str, int],
    locked_counts: dict[str, int],
    active_total: int,
) -> dict[str, int]:
    needed = {
        agent: max(targets.get(agent, 0) - locked_counts.get(agent, 0), 0)
        for agent in ASSIGNMENT_WEIGHTS
    }

    shortfall = active_total - sum(needed.values())
    if shortfall > 0:
        baseline = {
            agent: locked_counts.get(agent, 0) + needed.get(agent, 0)
            for agent in ASSIGNMENT_WEIGHTS
        }
        for agent in weighted_assignments(shortfall, baseline):
            needed[agent] += 1
    elif shortfall < 0:
        while sum(needed.values()) > active_total:
            candidates = [agent for agent in ASSIGNMENT_ORDER if needed[agent] > 0]
            if not candidates:
                break
            selected = max(
                candidates,
                key=lambda agent: (
                    locked_counts.get(agent, 0) + needed[agent] - targets.get(agent, 0),
                    needed[agent],
                ),
            )
            needed[selected] -= 1

    return needed


def _equal_assignment_cohort(
    cases: pd.DataFrame,
    start_date: str = "2026-09-01",
) -> pd.DataFrame:
    """Return every Logistics Recovery case dated on/after the configured start date.

    The dashboard's tracked Tawseel status date is the primary date so the
    assignment cohort matches the top-right Logistics Recovery date filter.
    New cases that do not yet have a tracked status row fall back to Scheduled
    Date, Assigned At, then Created At.
    """
    if cases.empty:
        return cases.copy()

    work = cases.copy()
    tracked_dates = pd.Series(pd.NaT, index=work.index, dtype="datetime64[ns]")

    try:
        # Lazy import avoids a module-level circular dependency because
        # logistics_status_tracking imports this module for the rebalance call.
        from src.logistics_status_tracking import load_status_updates

        tracked = load_status_updates()
        if not tracked.empty and "Case ID" in tracked.columns:
            latest = tracked.drop_duplicates("Case ID", keep="last").set_index("Case ID")
            mapped = work.get(
                "Case ID",
                pd.Series("", index=work.index, dtype=str),
            ).fillna("").astype(str).map(latest.get("Tawseel Status Updated At"))
            tracked_dates = pd.to_datetime(
                mapped,
                errors="coerce",
                format="mixed",
            )
    except Exception:
        pass

    effective_dates = tracked_dates.copy()
    for column in ("Scheduled Date", "Assigned At", "Created At"):
        if column not in work.columns:
            continue
        fallback = pd.to_datetime(
            work[column],
            errors="coerce",
            format="mixed",
            dayfirst=True,
        )
        effective_dates = effective_dates.fillna(fallback)

    cutoff = pd.Timestamp(start_date).normalize()
    mask = effective_dates.dt.normalize().ge(cutoff).fillna(False)
    return work[mask].copy()


def rebalance_logistics_assignments() -> dict[str, Any]:
    """Balance Sep-1+ Logistics Recovery data across all six agents safely.

    Cases with genuine agent work are locked to their existing owner and are
    never reassigned. Untouched cases dated 01 Sep 2026 onward are redistributed
    around those locked cases to make the six-agent totals as even as possible.
    REASSIGN audit rows created by earlier balancing runs do not count as agent
    work. Earlier cases are never changed.
    """
    cases = load_cases()
    activity = load_activity()
    if cases.empty:
        zero = {agent: 0 for agent in ASSIGNMENT_WEIGHTS}
        return {
            "assignment_policy": ASSIGNMENT_METHOD,
            "assignment_policy_version": ASSIGNMENT_POLICY_VERSION,
            "assignment_scope_start": "2026-09-01",
            "reassigned": 0,
            "assignment_updated": 0,
            "assignment_locked_worked": 0,
            "assignment_targets": zero,
            "assignment_after": zero,
            "assignment_exact": True,
        }

    cohort = _equal_assignment_cohort(cases, "2026-09-01")
    if cohort.empty:
        zero = {agent: 0 for agent in ASSIGNMENT_WEIGHTS}
        return {
            "assignment_policy": ASSIGNMENT_METHOD,
            "assignment_policy_version": ASSIGNMENT_POLICY_VERSION,
            "assignment_scope_start": "2026-09-01",
            "reassigned": 0,
            "assignment_updated": 0,
            "assignment_locked_worked": 0,
            "assignment_targets": zero,
            "assignment_after": zero,
            "assignment_exact": True,
        }

    # Only real work locks a case. Historical automatic REASSIGN audit entries
    # are intentionally ignored so untouched cases can still be balanced.
    worked_activity_ids: set[str] = set()
    if not activity.empty and "Case ID" in activity.columns:
        activity_types = activity.get(
            "Action Type",
            pd.Series("", index=activity.index, dtype=str),
        ).fillna("").astype(str).str.strip().str.upper()
        real_activity = activity[~activity_types.eq("REASSIGN")]
        worked_activity_ids = {
            _text(value)
            for value in real_activity["Case ID"].tolist()
            if _text(value)
        }

    def _worked(row: pd.Series) -> bool:
        case_id = _text(row.get("Case ID"))
        calls = pd.to_numeric(
            pd.Series([row.get("Total Call Attempts", "")]),
            errors="coerce",
        ).fillna(0).iloc[0]
        work_status = _text(row.get("Logistics Work Status")).upper()
        return bool(
            calls > 0
            or case_id in worked_activity_ids
            or work_status not in {"", "NEW"}
            or _text(row.get("Last Call At"))
            or _text(row.get("Last Call Status"))
            or _text(row.get("Customer Response"))
            or _text(row.get("Next Follow-up"))
            or _text(row.get("Agent Remark"))
            or _text(row.get("Logistics Final Outcome"))
            or _text(row.get("Closed At"))
            or _text(row.get("Delivered After Coordination")).upper() == "YES"
        )

    locked_indexes = [
        index for index, row in cohort.iterrows() if _worked(row)
    ]
    movable_indexes = [
        index for index in cohort.index if index not in set(locked_indexes)
    ]

    locked = cohort.loc[locked_indexes].copy()
    movable = cohort.loc[movable_indexes].copy()
    locked_counts = assignment_counts(locked)
    targets = target_counts(len(cohort))

    # Allocate all untouched cases around the locked historical ownership.
    planned_additions = weighted_assignments(len(movable), locked_counts)
    needed = {agent: 0 for agent in ASSIGNMENT_WEIGHTS}
    for agent in planned_additions:
        needed[agent] += 1

    movable["_assigned_dt"] = pd.to_datetime(
        movable.get("Assigned At", pd.Series("", index=movable.index)),
        errors="coerce",
        format="mixed",
    )

    keep_indexes: set[int] = set()
    kept_by_agent: dict[str, int] = {agent: 0 for agent in ASSIGNMENT_WEIGHTS}
    for agent in ASSIGNMENT_ORDER:
        group = movable[
            movable["Logistics Agent"]
            .fillna("")
            .astype(str)
            .str.strip()
            .str.upper()
            .eq(agent)
        ].copy()
        if group.empty:
            continue
        group = group.sort_values(
            ["_assigned_dt", "Case ID"],
            ascending=[True, True],
            na_position="last",
        )
        indexes = group.index.tolist()[: needed[agent]]
        keep_indexes.update(indexes)
        kept_by_agent[agent] = len(indexes)

    overflow = movable.loc[
        [index for index in movable.index if index not in keep_indexes]
    ].copy()
    if not overflow.empty:
        overflow = overflow.sort_values(
            ["_assigned_dt", "Case ID"],
            ascending=[True, True],
            na_position="last",
        )

    destinations: list[str] = []
    for agent in ASSIGNMENT_ORDER:
        destinations.extend(
            [agent] * max(needed[agent] - kept_by_agent[agent], 0)
        )

    if len(destinations) != len(overflow):
        raise RuntimeError(
            "Six-agent assignment planning mismatch: "
            f"{len(destinations)} destinations for {len(overflow)} cases"
        )

    planned_agent = {
        index: agent
        for index, agent in zip(overflow.index.tolist(), destinations)
    }

    now = _now()
    row_updates: list[tuple[int, list[str]]] = []
    activity_rows: list[list[str]] = []
    reassigned = 0

    for index in movable.index:
        current = cases.loc[index].to_dict()
        old_agent = _text(current.get("Logistics Agent")).upper()
        new_agent = planned_agent.get(index, old_agent)
        method_changed = _text(current.get("Assignment Method")) != ASSIGNMENT_METHOD
        agent_changed = bool(new_agent and new_agent != old_agent)

        if not method_changed and not agent_changed:
            continue

        current["Assignment Method"] = ASSIGNMENT_METHOD
        if agent_changed:
            current["Logistics Agent"] = new_agent
            current["Updated At"] = now
            reassigned += 1

            activity_id = hashlib.sha256(
                f"{current.get('Case ID')}|{now}|REASSIGN|{old_agent}|{new_agent}".encode(
                    "utf-8"
                )
            ).hexdigest()[:20].upper()
            activity_record = {
                "Activity ID": activity_id,
                "Case ID": current.get("Case ID", ""),
                "Portal": current.get("Portal", ""),
                "AWB": current.get("AWB", ""),
                "Logistics Agent": new_agent,
                "Action At": now,
                "Action Type": "REASSIGN",
                "Call Attempt Number": "",
                "Call Result": "",
                "Customer Response": "",
                "Remark": (
                    f"Untouched case balanced from {old_agent or 'UNASSIGNED'} to {new_agent} "
                    "under equal six-agent policy from 01 Sep 2026"
                ),
                "Next Follow-up": current.get("Next Follow-up", ""),
                "Previous Work Status": current.get("Logistics Work Status", ""),
                "New Work Status": current.get("Logistics Work Status", ""),
            }
            activity_rows.append(_row_values(activity_record, ACTIVITY_HEADERS))

        row_updates.append(
            (int(index) + 2, _row_values(current, CASE_HEADERS))
        )

    book = logistics_book()
    _batch_update_rows(
        book.worksheet("LOGISTICS_CASES"),
        row_updates,
        len(CASE_HEADERS),
    )
    if activity_rows:
        book.worksheet("LOGISTICS_ACTIVITY_LOG").append_rows(
            activity_rows,
            value_input_option="USER_ENTERED",
        )

    _clear_table_cache()
    refreshed = load_cases()
    refreshed_cohort = _equal_assignment_cohort(refreshed, "2026-09-01")
    after = assignment_counts(refreshed_cohort)

    return {
        "assignment_policy": ASSIGNMENT_METHOD,
        "assignment_policy_version": ASSIGNMENT_POLICY_VERSION,
        "assignment_scope_start": "2026-09-01",
        "assignment_scope_total": len(refreshed_cohort),
        "assignment_locked_worked": len(locked_indexes),
        "assignment_movable": len(movable_indexes),
        "reassigned": reassigned,
        "assignment_updated": len(row_updates),
        "assignment_targets": targets,
        "assignment_after": after,
        "assignment_exact": after == targets,
    }
