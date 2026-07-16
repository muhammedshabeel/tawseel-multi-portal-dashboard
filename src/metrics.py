from __future__ import annotations

import pandas as pd


def classify_status(status: str) -> str:
    value = str(status or "").strip().lower()
    if "delivered" in value:
        return "Delivered"
    if "out for delivery" in value:
        return "Out for Delivery"
    if "rto prepared" in value:
        return "RTO Prepared"
    if value == "rto" or "return to origin" in value:
        return "RTO"
    if "back to" in value or "store" in value:
        return "Back to Store"
    return "Other"


def add_derived_columns(df: pd.DataFrame) -> pd.DataFrame:
    out = df.copy()
    out["Status Group"] = out["Status"].map(classify_status)
    out["Is Delivered"] = out["Status Group"].eq("Delivered")
    out["Is Critical"] = out["Priority"].str.contains("CRITICAL", case=False, na=False)
    out["Is Follow Up"] = out["Priority"].str.contains("FOLLOW", case=False, na=False)
    return out


def portal_summary(df: pd.DataFrame) -> pd.DataFrame:
    if df.empty:
        return pd.DataFrame()
    work = add_derived_columns(df)
    rows = []
    for portal, g in work.groupby("Portal", dropna=False):
        total = len(g)
        delivered = int(g["Is Delivered"].sum())
        rto = int(g["Status Group"].eq("RTO").sum())
        ofd = int(g["Status Group"].eq("Out for Delivery").sum())
        rows.append({
            "Portal": portal,
            "Total": total,
            "Delivered": delivered,
            "Delivery Rate": delivered / total if total else 0.0,
            "OFD": ofd,
            "RTO": rto,
            "Critical": int(g["Is Critical"].sum()),
            "Follow-up": int(g["Is Follow Up"].sum()),
            "Unassigned": int(g["Agent"].eq("Unassigned").sum()),
        })
    return pd.DataFrame(rows).sort_values("Total", ascending=False)


def agent_summary(df: pd.DataFrame) -> pd.DataFrame:
    if df.empty:
        return pd.DataFrame()
    work = add_derived_columns(df)
    grouped = work.groupby(["Portal", "Agent"], dropna=False)
    result = grouped.agg(
        Total=("AWB", "count"),
        Delivered=("Is Delivered", "sum"),
        Critical=("Is Critical", "sum"),
    ).reset_index()
    result["Delivery Rate"] = result["Delivered"] / result["Total"].where(result["Total"].ne(0), 1)
    return result.sort_values(["Portal", "Total"], ascending=[True, False])


def failure_summary(df: pd.DataFrame) -> pd.DataFrame:
    if df.empty:
        return pd.DataFrame()
    success_terms = {"door delivery", "reception delivery", ""}
    work = df.copy()
    work["Remarks Clean"] = work["Remarks"].str.strip()
    work = work[~work["Remarks Clean"].str.lower().isin(success_terms)]
    result = (
        work.groupby(["Portal", "Remarks Clean"], dropna=False)
        .size()
        .reset_index(name="Count")
        .sort_values("Count", ascending=False)
    )
    return result
