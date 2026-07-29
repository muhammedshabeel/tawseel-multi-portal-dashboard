from __future__ import annotations

from collections import Counter
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
    """Assign new cases to the largest deficit against the 15/15/35/35 target.

    The method uses current active workload, so small and large batches both move
    the total distribution toward the requested ratio without bursty fixed blocks.
    """
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
    """Plan a one-time rebalance without moving worked or completed cases.

    Reassignable cases must be active, have no calls, no activity history, no
    recovery outcome, and remain in NEW/blank work status. This protects agent
    ownership and audit history for every case that has already been handled.
    """
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

    # If locked work already exceeds one or more targets, allocate the remaining
    # movable cases by weighted deficit so all rows still receive one owner.
    movable_total = len(reassignable_indexes)
    desired_total = sum(needed.values())
    if desired_total < movable_total:
        extra = weighted_assignments(movable_total - desired_total, {
            agent: locked_counts.get(agent, 0) + needed.get(agent, 0)
            for agent in ASSIGNMENT_WEIGHTS
        })
        for agent in extra:
            needed[agent] += 1
    elif desired_total > movable_total:
        # Reduce excess slots from the smallest current deficits first.
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
