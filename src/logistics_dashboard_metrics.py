from __future__ import annotations

from typing import Any

import pandas as pd


RTO_STATUSES = {"rto", "rto assigned"}


def _status_series(cases: pd.DataFrame, column: str) -> pd.Series:
    return cases.get(
        column,
        pd.Series("", index=cases.index, dtype=str),
    ).fillna("").astype(str).str.strip().str.casefold()


def tawseel_delivered_mask(cases: pd.DataFrame) -> pd.Series:
    """Identify cases whose latest Tawseel courier status is delivered."""
    if cases.empty:
        return pd.Series(False, index=cases.index, dtype=bool)

    status = _status_series(cases, "Latest Courier Status")
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


def current_rto_mask(cases: pd.DataFrame) -> pd.Series:
    """Current Tawseel status is either RTO or RTO Assigned."""
    if cases.empty:
        return pd.Series(False, index=cases.index, dtype=bool)
    return _status_series(cases, "Latest Courier Status").isin(RTO_STATUSES)


def rto_origin_mask(cases: pd.DataFrame) -> pd.Series:
    """Cases that entered or previously passed through RTO/RTO Assigned."""
    if cases.empty:
        return pd.Series(False, index=cases.index, dtype=bool)

    source = _status_series(cases, "Source Courier Status")
    previous = _status_series(cases, "Previous Courier Status")
    latest = _status_series(cases, "Latest Courier Status")
    return source.isin(RTO_STATUSES) | previous.isin(RTO_STATUSES) | latest.isin(RTO_STATUSES)


def explicit_rto_conversion_mask(cases: pd.DataFrame) -> pd.Series:
    """Identify cases explicitly confirmed as converted by logistics.

    The save workflow closes an RTO case with final outcome ``RTO Won /
    Converted``. That explicit outcome must move the order to the converted
    Kanban column immediately, without waiting for a later Tawseel sync.
    """
    if cases.empty:
        return pd.Series(False, index=cases.index, dtype=bool)

    work_status = _status_series(cases, "Logistics Work Status")
    final_outcome = _status_series(cases, "Logistics Final Outcome")

    work_status_marked = work_status.isin(
        {
            "rto won / converted",
            "rto won/converted",
            "rto converted",
        }
    )
    outcome_marked = (
        final_outcome.isin(
            {
                "rto won / converted",
                "rto won/converted",
                "rto converted",
            }
        )
        | final_outcome.str.contains(
            r"\brto\b.*\b(?:won|converted)\b",
            regex=True,
            na=False,
        )
    )
    return work_status_marked | outcome_marked


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
    current_rto = current_rto_mask(cases)
    rto_origin = rto_origin_mask(cases)
    explicit_rto_conversion = explicit_rto_conversion_mask(cases)

    # Count either of these valid conversion paths:
    # 1. Tawseel later confirms Delivered and logistics recovery credit exists.
    # 2. Logistics explicitly saves RTO WON / CONVERTED and recovery credit exists.
    # The second path makes the Kanban move immediate after the agent saves.
    rto_converted = (
        rto_origin
        & recovered
        & (tawseel_delivered | explicit_rto_conversion)
    )
    rto_recovered = rto_converted
    rto_open = current_rto & ~closed & ~rto_converted

    return {
        "closed": closed,
        "tawseel_delivered": tawseel_delivered,
        "pending_review": pending_review,
        "active": active,
        "recovered": recovered,
        "current_rto": current_rto,
        "rto_origin": rto_origin,
        "explicit_rto_conversion": explicit_rto_conversion,
        "rto_converted": rto_converted,
        "rto_recovered": rto_recovered,
        "rto_open": rto_open,
    }


def logistics_dashboard_summary(
    cases: pd.DataFrame,
) -> tuple[dict[str, int | float], pd.DataFrame]:
    empty = {
        "Assigned": 0,
        "Active": 0,
        "RTO": 0,
        "RTO Converted": 0,
        "Recovered from RTO": 0,
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
        "RTO": int(masks["current_rto"].sum()),
        "RTO Converted": int(masks["rto_converted"].sum()),
        "Recovered from RTO": int(masks["rto_converted"].sum()),
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
                "RTO": int(group_masks["current_rto"].sum()),
                "RTO Converted": int(group_masks["rto_converted"].sum()),
                "Recovered from RTO": int(group_masks["rto_converted"].sum()),
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
            ["Recovery Rate", "RTO Converted", "Delivered Pending Review", "Assigned"],
            ascending=[False, False, False, False],
        )
    return overall, summary
