from __future__ import annotations

from typing import Any

import pandas as pd


def tawseel_delivered_mask(cases: pd.DataFrame) -> pd.Series:
    """Identify cases whose latest Tawseel courier status is delivered.

    This is intentionally separate from logistics recovery attribution. A case
    can be delivered by Tawseel without being credited as recovered by an agent.
    """
    if cases.empty:
        return pd.Series(False, index=cases.index, dtype=bool)

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


def logistics_case_masks(cases: pd.DataFrame) -> dict[str, pd.Series]:
    index = cases.index
    closed = cases.get(
        "Logistics Work Status", pd.Series("", index=index, dtype=str)
    ).fillna("").astype(str).str.strip().str.upper().eq("CLOSED")
    tawseel_delivered = tawseel_delivered_mask(cases)
    pending_review = tawseel_delivered & ~closed
    active = ~closed & ~tawseel_delivered
    recovered = cases.get(
        "Delivered After Coordination", pd.Series("", index=index, dtype=str)
    ).fillna("").astype(str).str.strip().str.upper().eq("YES")

    return {
        "closed": closed,
        "tawseel_delivered": tawseel_delivered,
        "pending_review": pending_review,
        "active": active,
        "recovered": recovered,
    }


def logistics_dashboard_summary(
    cases: pd.DataFrame,
) -> tuple[dict[str, int | float], pd.DataFrame]:
    empty = {
        "Assigned": 0,
        "Active": 0,
        "Tawseel Delivered": 0,
        "Delivered Pending Review": 0,
        "Closed": 0,
        "Delivered After Coordination": 0,
        "Recovery Rate": 0.0,
    }
    if cases.empty:
        return empty, pd.DataFrame()

    masks = logistics_case_masks(cases)
    assigned = len(cases)
    overall = {
        "Assigned": assigned,
        "Active": int(masks["active"].sum()),
        "Tawseel Delivered": int(masks["tawseel_delivered"].sum()),
        "Delivered Pending Review": int(masks["pending_review"].sum()),
        "Closed": int(masks["closed"].sum()),
        "Delivered After Coordination": int(masks["recovered"].sum()),
        "Recovery Rate": (
            float(masks["recovered"].sum() / assigned) if assigned else 0.0
        ),
    }

    rows: list[dict[str, Any]] = []
    for agent, group in cases.groupby("Logistics Agent", dropna=False):
        group_masks = logistics_case_masks(group)
        group_assigned = len(group)
        rows.append(
            {
                "Agent": str(agent).strip() or "Unassigned",
                "Assigned": group_assigned,
                "Active": int(group_masks["active"].sum()),
                "Tawseel Delivered": int(group_masks["tawseel_delivered"].sum()),
                "Delivered Pending Review": int(group_masks["pending_review"].sum()),
                "Closed": int(group_masks["closed"].sum()),
                "Delivered After Coordination": int(group_masks["recovered"].sum()),
                "Recovery Rate": (
                    float(group_masks["recovered"].sum() / group_assigned)
                    if group_assigned
                    else 0.0
                ),
            }
        )

    summary = pd.DataFrame(rows)
    if not summary.empty:
        summary = summary.sort_values(
            ["Recovery Rate", "Delivered Pending Review", "Assigned"],
            ascending=[False, False, False],
        )
    return overall, summary
