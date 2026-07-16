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
    if out.empty:
        return out

    for column in ["Status", "Priority", "Agent"]:
        if column not in out.columns:
            out[column] = ""

    out["Status Group"] = out["Status"].map(classify_status)
    out["Is Delivered"] = out["Status Group"].eq("Delivered")
    out["Is Critical"] = out["Priority"].astype(str).str.contains("CRITICAL", case=False, na=False)
    out["Is Follow Up"] = out["Priority"].astype(str).str.contains("FOLLOW", case=False, na=False)
    out["Is Unassigned"] = out["Agent"].fillna("").astype(str).str.strip().str.casefold().isin({"", "unassigned"})
    return out


def overall_metrics(df: pd.DataFrame) -> dict[str, float | int]:
    work = add_derived_columns(df)
    total = len(work)
    delivered = int(work["Is Delivered"].sum()) if total else 0
    return {
        "Total": total,
        "Delivered": delivered,
        "Delivery Rate": delivered / total if total else 0.0,
        "OFD": int(work["Status Group"].eq("Out for Delivery").sum()) if total else 0,
        "RTO": int(work["Status Group"].eq("RTO").sum()) if total else 0,
        "RTO Prepared": int(work["Status Group"].eq("RTO Prepared").sum()) if total else 0,
        "Back to Store": int(work["Status Group"].eq("Back to Store").sum()) if total else 0,
        "Critical": int(work["Is Critical"].sum()) if total else 0,
        "Follow-up": int(work["Is Follow Up"].sum()) if total else 0,
        "Unassigned": int(work["Is Unassigned"].sum()) if total else 0,
    }


def portal_summary(df: pd.DataFrame) -> pd.DataFrame:
    if df.empty:
        return pd.DataFrame()
    work = add_derived_columns(df)
    rows = []
    for portal, group in work.groupby("Portal", dropna=False):
        rows.append({"Portal": portal, **overall_metrics(group)})
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
        Follow_up=("Is Follow Up", "sum"),
        OFD=("Status Group", lambda values: int(values.eq("Out for Delivery").sum())),
        RTO=("Status Group", lambda values: int(values.eq("RTO").sum())),
    ).reset_index()

    result["Delivery Rate"] = result["Delivered"] / result["Total"].where(result["Total"].ne(0), 1)
    result = result.rename(columns={"Follow_up": "Follow-up"})
    return result.sort_values(["Portal", "Total"], ascending=[True, False])


def failure_summary(df: pd.DataFrame) -> pd.DataFrame:
    if df.empty:
        return pd.DataFrame()
    success_terms = {"door delivery", "reception delivery", ""}
    work = df.copy()
    work["Remarks Clean"] = work["Remarks"].fillna("").astype(str).str.strip()
    work = work[~work["Remarks Clean"].str.lower().isin(success_terms)]
    return (
        work.groupby(["Portal", "Remarks Clean"], dropna=False)
        .size()
        .reset_index(name="Count")
        .sort_values("Count", ascending=False)
    )


def weekly_summary(df: pd.DataFrame) -> pd.DataFrame:
    if df.empty or "Scheduled Date" not in df.columns:
        return pd.DataFrame()
    work = add_derived_columns(df)
    work = work[work["Scheduled Date"].notna()].copy()
    if work.empty:
        return pd.DataFrame()
    work["Week Start"] = work["Scheduled Date"].dt.to_period("W-SUN").apply(lambda period: period.start_time)
    grouped = (
        work.groupby(["Week Start", "Portal"], dropna=False)
        .agg(Total=("AWB", "count"), Delivered=("Is Delivered", "sum"))
        .reset_index()
    )
    grouped["Delivery Rate"] = grouped["Delivered"] / grouped["Total"].where(grouped["Total"].ne(0), 1)
    grouped["Week"] = grouped["Week Start"].dt.strftime("%d %b %Y")
    return grouped.sort_values(["Week Start", "Portal"])


def weekly_agent_summary(df: pd.DataFrame) -> pd.DataFrame:
    if df.empty or "Scheduled Date" not in df.columns:
        return pd.DataFrame()
    work = add_derived_columns(df)
    work = work[work["Scheduled Date"].notna()].copy()
    if work.empty:
        return pd.DataFrame()
    work["Week Start"] = work["Scheduled Date"].dt.to_period("W-SUN").apply(lambda period: period.start_time)
    grouped = (
        work.groupby(["Week Start", "Portal", "Agent"], dropna=False)
        .agg(Total=("AWB", "count"), Delivered=("Is Delivered", "sum"))
        .reset_index()
    )
    grouped["Delivery Rate"] = grouped["Delivered"] / grouped["Total"].where(grouped["Total"].ne(0), 1)
    grouped["Week"] = grouped["Week Start"].dt.strftime("%d %b %Y")
    return grouped.sort_values(["Week Start", "Portal", "Total"], ascending=[False, True, False])
