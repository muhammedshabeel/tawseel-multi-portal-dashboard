from __future__ import annotations

from collections import Counter
import hashlib
from typing import Any

import pandas as pd

ASSIGNMENT_POLICY_VERSION = "2026-07-30-v1"
ASSIGNMENT_WEIGHTS: dict[str, float] = {
    "VAISHAKH": 0.15,
    "NEETHU": 0.15,
    "HASBIR": 0.35,
    "AKHASH": 0.35,
}
ASSIGNMENT_ORDER = ["HASBIR", "AKHASH", "VAISHAKH", "NEETHU"]
ASSIGNMENT_METHOD = "WEIGHTED_30_70"


def _text(value: Any) -> str:
    if value is None:
        return ""
    try:
        if pd.isna(value):
            return ""
    except (TypeError, ValueError):
        pass
    return str(value).strip()


def _closed_mask(cases: pd.DataFrame) -> pd.Series:
    return cases.get(
        "Logistics Work Status", pd.Series("", index=cases.index, dtype=str)
    ).fillna("").astype(str).str.strip().str.upper().eq("CLOSED")


def _delivered_mask(cases: pd.DataFrame) -> pd.Series:
    status = cases.get(
        "Latest Courier Status", pd.Series("", index=cases.index, dtype=str)
    ).fillna("").astype(str).str.strip().str.casefold()
    negative = status.str.contains(
        r"\bnot delivered\b|\bundelivered\b|\bdelivery failed\b",
        regex=True,
        na=False,
    )
    positive = (
        status.eq("delivered")
        | status.str.startswith("delivered ")
        | status.str.contains(r"\bsuccessfully delivered\b", regex=True, na=False)
        | status.str.contains(r"\bdelivery completed\b", regex=True, na=False)
    )
    return positive & ~negative


def active_assignment_cases(cases: pd.DataFrame) -> pd.DataFrame:
    """Cases that still represent live logistics workload."""
    if cases.empty:
        return cases.copy()
    return cases[~_closed_mask(cases) & ~_delivered_mask(cases)].copy()


def assignment_counts(cases: pd.DataFrame) -> dict[str, int]:
    counts = Counter({agent: 0 for agent in ASSIGNMENT_WEIGHTS})
    if not cases.empty and "Logistics Agent" in cases.columns:
        for value in cases["Logistics Agent"].fillna("").astype(str):
            agent = value.strip().upper()
            if agent in counts:
                counts[agent] += 1
    return dict(counts)


def weighted_assignments(
    count: int,
    current_counts: dict[str, int] | None = None,
) -> list[str]:
    """Assign new cases to the largest deficit against the 15/15/35/35 target."""
    counts = {
        agent: int((current_counts or {}).get(agent, 0))
        for agent in ASSIGNMENT_WEIGHTS
    }
    assigned: list[str] = []

    for _ in range(max(int(count), 0)):
        total_after = sum(counts.values()) + 1
        deficits = {
            agent: ASSIGNMENT_WEIGHTS[agent] * total_after - counts[agent]
            for agent in ASSIGNMENT_WEIGHTS
        }
        selected = max(
            ASSIGNMENT_ORDER,
            key=lambda agent: (deficits[agent], -ASSIGNMENT_ORDER.index(agent)),
        )
        counts[selected] += 1
        assigned.append(selected)

    return assigned


def target_counts(total: int) -> dict[str, int]:
    """Return integer targets that add exactly to total using largest remainders."""
    total = max(int(total), 0)
    raw = {agent: total * weight for agent, weight in ASSIGNMENT_WEIGHTS.items()}
    targets = {agent: int(value) for agent, value in raw.items()}
    remaining = total - sum(targets.values())
    remainder_order = sorted(
        ASSIGNMENT_ORDER,
        key=lambda agent: (raw[agent] - targets[agent], -ASSIGNMENT_ORDER.index(agent)),
        reverse=True,
    )
    for agent in remainder_order[:remaining]:
        targets[agent] += 1
    return targets


def plan_safe_rebalance(
    cases: pd.DataFrame,
    activity: pd.DataFrame,
) -> tuple[dict[int, str], dict[str, Any]]:
    """Plan a rebalance without moving worked, delivered, or completed cases."""
    if cases.empty:
        return {}, {
            "eligible": 0,
            "locked": 0,
            "changed": 0,
            "before": {agent: 0 for agent in ASSIGNMENT_WEIGHTS},
            "after": {agent: 0 for agent in ASSIGNMENT_WEIGHTS},
            "target": {agent: 0 for agent in ASSIGNMENT_WEIGHTS},
        }

    active = active_assignment_cases(cases)
    active_indexes = set(active.index.tolist())
    activity_case_ids = set()
    if not activity.empty and "Case ID" in activity.columns:
        activity_case_ids = {
            _text(value)
            for value in activity["Case ID"].tolist()
            if _text(value)
        }

    reassignable_indexes: list[int] = []
    locked_indexes: list[int] = []
    for index, row in cases.iterrows():
        if index not in active_indexes:
            locked_indexes.append(index)
            continue

        calls = pd.to_numeric(
            pd.Series([row.get("Total Call Attempts", "")]), errors="coerce"
        ).fillna(0).iloc[0]
        case_id = _text(row.get("Case ID"))
        work_status = _text(row.get("Logistics Work Status")).upper()
        recovered = _text(row.get("Delivered After Coordination")).upper() == "YES"
        has_outcome = bool(_text(row.get("Logistics Final Outcome")))
        has_activity = case_id in activity_case_ids

        if (
            calls == 0
            and not has_activity
            and not recovered
            and not has_outcome
            and work_status in {"", "NEW"}
        ):
            reassignable_indexes.append(index)
        else:
            locked_indexes.append(index)

    before = assignment_counts(active)
    targets = target_counts(len(active))
    locked_active = active.loc[
        [index for index in locked_indexes if index in active.index]
    ].copy()
    locked_counts = assignment_counts(locked_active)

    needed = {
        agent: max(targets[agent] - locked_counts.get(agent, 0), 0)
        for agent in ASSIGNMENT_WEIGHTS
    }

    movable_total = len(reassignable_indexes)
    desired_total = sum(needed.values())
    if desired_total < movable_total:
        extra = weighted_assignments(
            movable_total - desired_total,
            {
                agent: locked_counts.get(agent, 0) + needed.get(agent, 0)
                for agent in ASSIGNMENT_WEIGHTS
            },
        )
        for agent in extra:
            needed[agent] += 1
    elif desired_total > movable_total:
        while sum(needed.values()) > movable_total:
            candidates = [agent for agent in ASSIGNMENT_ORDER if needed[agent] > 0]
            if not candidates:
                break
            agent = min(
                candidates,
                key=lambda name: (
                    targets[name] - (locked_counts.get(name, 0) + needed[name]),
                    ASSIGNMENT_ORDER.index(name),
                ),
            )
            needed[agent] -= 1

    keep_by_agent: dict[str, list[int]] = {agent: [] for agent in ASSIGNMENT_WEIGHTS}
    overflow: list[int] = []
    for index in reassignable_indexes:
        current_agent = _text(cases.at[index, "Logistics Agent"]).upper()
        if current_agent in needed and len(keep_by_agent[current_agent]) < needed[current_agent]:
            keep_by_agent[current_agent].append(index)
        else:
            overflow.append(index)

    destinations: list[str] = []
    for agent in ASSIGNMENT_ORDER:
        destinations.extend([agent] * (needed[agent] - len(keep_by_agent[agent])))

    plan: dict[int, str] = {}
    for index, agent in zip(overflow, destinations):
        current_agent = _text(cases.at[index, "Logistics Agent"]).upper()
        if current_agent != agent:
            plan[index] = agent

    projected = active.copy()
    for index, agent in plan.items():
        projected.at[index, "Logistics Agent"] = agent

    return plan, {
        "eligible": len(reassignable_indexes),
        "locked": len(cases) - len(reassignable_indexes),
        "changed": len(plan),
        "before": before,
        "after": assignment_counts(projected),
        "target": targets,
    }


def apply_weighted_assignment_policy() -> dict[str, Any]:
    """Apply the requested 30/70 policy to current safe cases and future batches.

    Vaishakh and Neethu receive 15% each. Hasbir and Akash receive 35% each.
    Existing cases with any agent work or audit activity stay with their current
    owner. Untouched active cases are redistributed, and every change is logged.
    """
    from src.logistics import (
        ACTIVITY_HEADERS,
        CASE_HEADERS,
        _WRITE_LOCK,
        _batch_update_rows,
        _clear_table_cache,
        _now,
        _row_values,
        _worksheet,
        load_activity,
        load_cases,
    )

    with _WRITE_LOCK:
        cases = load_cases()
        activity = load_activity()
        plan, summary = plan_safe_rebalance(cases, activity)
        if not plan:
            return {
                "assignment_policy": ASSIGNMENT_METHOD,
                "assignment_rebalanced": 0,
                "assignment_eligible": summary["eligible"],
                "assignment_locked": summary["locked"],
                "assignment_before": summary["before"],
                "assignment_after": summary["after"],
                "assignment_target": summary["target"],
            }

        now = _now()
        case_updates: list[tuple[int, list[str]]] = []
        activity_rows: list[list[str]] = []

        for frame_index, new_agent in plan.items():
            current = cases.loc[frame_index].to_dict()
            previous_agent = _text(current.get("Logistics Agent")).upper()
            current["Logistics Agent"] = new_agent
            current["Assignment Method"] = ASSIGNMENT_METHOD
            current["Updated At"] = now
            case_updates.append(
                (int(frame_index) + 2, _row_values(current, CASE_HEADERS))
            )

            remark = (
                f"Weighted assignment policy {ASSIGNMENT_POLICY_VERSION}: "
                f"{previous_agent or 'UNASSIGNED'} -> {new_agent}"
            )
            activity_id = hashlib.sha256(
                f"{current.get('Case ID')}|{now}|REASSIGN|{new_agent}".encode("utf-8")
            ).hexdigest()[:20].upper()
            activity_record = {
                "Activity ID": activity_id,
                "Case ID": current.get("Case ID", ""),
                "Portal": current.get("Portal", ""),
                "AWB": current.get("AWB", ""),
                "Logistics Agent": new_agent,
                "Action At": now,
                "Action Type": "REASSIGN",
                "Remark": remark,
                "Previous Work Status": current.get("Logistics Work Status", ""),
                "New Work Status": current.get("Logistics Work Status", ""),
            }
            activity_rows.append(_row_values(activity_record, ACTIVITY_HEADERS))

        _batch_update_rows(
            _worksheet("LOGISTICS_CASES"),
            case_updates,
            len(CASE_HEADERS),
        )
        if activity_rows:
            _worksheet("LOGISTICS_ACTIVITY_LOG").append_rows(
                activity_rows,
                value_input_option="USER_ENTERED",
            )
        _clear_table_cache()

        return {
            "assignment_policy": ASSIGNMENT_METHOD,
            "assignment_rebalanced": len(plan),
            "assignment_eligible": summary["eligible"],
            "assignment_locked": summary["locked"],
            "assignment_before": summary["before"],
            "assignment_after": summary["after"],
            "assignment_target": summary["target"],
        }
