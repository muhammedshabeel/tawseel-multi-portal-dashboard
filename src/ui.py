from __future__ import annotations

import pandas as pd
import streamlit as st


def page_header(title: str, subtitle: str = "") -> None:
    st.title(title)
    if subtitle:
        st.caption(subtitle)


def apply_filters(df: pd.DataFrame) -> pd.DataFrame:
    if df.empty:
        return df
    with st.sidebar:
        st.header("Filters")
        portals = sorted(df["Portal"].dropna().unique().tolist())
        selected_portals = st.multiselect("Portal", portals, default=portals)
        scoped = df[df["Portal"].isin(selected_portals)]
        agents = sorted(scoped["Agent"].dropna().unique().tolist())
        selected_agents = st.multiselect("Agent", agents)
        statuses = sorted(scoped["Status"].dropna().unique().tolist())
        selected_statuses = st.multiselect("Status", statuses)
    out = scoped
    if selected_agents:
        out = out[out["Agent"].isin(selected_agents)]
    if selected_statuses:
        out = out[out["Status"].isin(selected_statuses)]
    return out


def render_kpis(metrics: dict, include_unassigned: bool = False) -> None:
    keys = [
        ("Total Orders", "Total", "Total orders in the selected view"),
        ("Delivered", "Delivered", "Orders currently signed as delivered"),
        ("Delivery Signing Rate", "Delivery Rate", "Delivered orders divided by total orders"),
        ("Out for Delivery", "OFD", "Orders currently out for delivery"),
        ("RTO", "RTO", "Orders currently marked return to origin"),
        ("Critical", "Critical", "Orders marked critical by the operational priority logic"),
        ("Follow-up", "Follow-up", "Orders requiring follow-up"),
    ]
    if include_unassigned:
        keys.append(("Unassigned", "Unassigned", "Orders without an assigned agent"))
    cols = st.columns(len(keys))
    for col, (label, key, help_text) in zip(cols, keys):
        value = metrics.get(key, 0)
        text = f"{value:.1%}" if key == "Delivery Rate" else f"{int(value):,}"
        col.metric(label, text, help=help_text)


def performance_style(rate: float, total: int = 10) -> str:
    if total < 10:
        return "Low Sample"
    if rate >= 0.70:
        return "Good"
    if rate >= 0.55:
        return "Average"
    return "Needs Improvement"


def highlight_performance_rows(row: pd.Series) -> list[str]:
    label = row.get("Performance", "")
    if label == "Good":
        style = "background-color: #dcfce7; color: #166534;"
    elif label == "Average":
        style = "background-color: #fef3c7; color: #92400e;"
    elif label == "Needs Improvement":
        style = "background-color: #fee2e2; color: #991b1b;"
    else:
        style = "background-color: #e2e8f0; color: #475569;"
    return [style] * len(row)


def report_date_filter(
    df: pd.DataFrame,
    key_prefix: str,
    *,
    sidebar: bool = False,
) -> tuple[pd.DataFrame, pd.Timestamp | None, pd.Timestamp | None, int]:
    """Filter records by Scheduled Date and return period metadata.

    The rolling options are anchored to the latest valid date in the loaded
    dataset, so historical datasets remain useful and reproducible.
    """
    if df.empty or "Scheduled Date" not in df.columns:
        return df.copy(), None, None, 0

    work = df.copy()
    work["Scheduled Date"] = pd.to_datetime(
        work["Scheduled Date"],
        errors="coerce",
        dayfirst=True,
        format="mixed",
    )

    missing_dates = int(work["Scheduled Date"].isna().sum())
    valid_dates = work["Scheduled Date"].dropna()
    if valid_dates.empty:
        return work, None, None, missing_dates

    minimum_date = valid_dates.min().normalize()
    maximum_date = valid_dates.max().normalize()

    target = st.sidebar if sidebar else st
    option = target.selectbox(
        "Report period",
        [
            "All available data",
            "Latest available date",
            "Previous available date",
            "Latest 7 days",
            "Latest 30 days",
            "Latest data month",
            "Custom range",
        ],
        key=f"{key_prefix}_report_period",
        help=(
            "Date filtering uses Scheduled Date. Records with a missing "
            "Scheduled Date are excluded from a selected date range."
        ),
    )

    if option == "All available data":
        start_date = minimum_date
        end_date = maximum_date
    elif option == "Latest available date":
        start_date = maximum_date
        end_date = maximum_date
    elif option == "Previous available date":
        prior = valid_dates[valid_dates.dt.normalize() < maximum_date]
        previous_date = prior.max().normalize() if not prior.empty else maximum_date
        start_date = previous_date
        end_date = previous_date
    elif option == "Latest 7 days":
        end_date = maximum_date
        start_date = maximum_date - pd.Timedelta(days=6)
    elif option == "Latest 30 days":
        end_date = maximum_date
        start_date = maximum_date - pd.Timedelta(days=29)
    elif option == "Latest data month":
        end_date = maximum_date
        start_date = maximum_date.replace(day=1)
    else:
        selected = target.date_input(
            "Custom date range",
            value=(minimum_date.date(), maximum_date.date()),
            min_value=minimum_date.date(),
            max_value=maximum_date.date(),
            key=f"{key_prefix}_custom_range",
        )
        if isinstance(selected, (tuple, list)) and len(selected) == 2:
            start_date = pd.Timestamp(selected[0])
            end_date = pd.Timestamp(selected[1])
        else:
            selected_date = selected[0] if isinstance(selected, (tuple, list)) else selected
            start_date = pd.Timestamp(selected_date)
            end_date = start_date

    if start_date > end_date:
        start_date, end_date = end_date, start_date

    normalized = work["Scheduled Date"].dt.normalize()
    filtered = work[
        normalized.between(start_date, end_date, inclusive="both")
    ].copy()

    return filtered, start_date, end_date, missing_dates


def show_report_period(
    start_date: pd.Timestamp | None,
    end_date: pd.Timestamp | None,
    record_count: int,
    missing_date_count: int = 0,
) -> None:
    """Render a compact report-period card suitable for the top-right area."""
    if start_date is None or end_date is None:
        period_text = "Date unavailable"
    elif start_date == end_date:
        period_text = start_date.strftime("%d %b %Y")
    else:
        period_text = f"{start_date:%d %b %Y} – {end_date:%d %b %Y}"

    missing_text = (
        f" • {missing_date_count:,} missing-date records excluded"
        if missing_date_count
        else ""
    )

    st.markdown(
        f"""
        <div style="text-align:right;padding:10px 14px;border:1px solid rgba(128,128,128,.25);border-radius:10px;margin-bottom:8px;">
          <div style="font-size:11px;opacity:.65;text-transform:uppercase;letter-spacing:.06em;">Report period</div>
          <div style="font-size:17px;font-weight:700;margin-top:2px;">{period_text}</div>
          <div style="font-size:12px;opacity:.72;margin-top:3px;">{record_count:,} orders included{missing_text}</div>
        </div>
        """,
        unsafe_allow_html=True,
    )


def apply_report_period_panel(
    df: pd.DataFrame,
    key_prefix: str,
) -> tuple[pd.DataFrame, pd.Timestamp | None, pd.Timestamp | None]:
    """Render period controls and a matching top-right summary card."""
    left, right = st.columns([2.2, 1], vertical_alignment="bottom")
    with left:
        filtered, start_date, end_date, missing_dates = report_date_filter(
            df,
            key_prefix=key_prefix,
        )
    with right:
        show_report_period(
            start_date,
            end_date,
            len(filtered),
            missing_dates,
        )
    return filtered, start_date, end_date
