from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import gspread
import pandas as pd
import streamlit as st
from google.oauth2.service_account import Credentials

SCOPES = [
    "https://www.googleapis.com/auth/spreadsheets.readonly",
    "https://www.googleapis.com/auth/drive.readonly",
]


@dataclass(frozen=True)
class PortalConfig:
    name: str
    sheet_id: str
    master_tab: str = "Tawseeel_Orders"
    input_tab: str = "Tawseel_AWB"


def _service_account_info() -> dict[str, Any]:
    if "google_service_account" not in st.secrets:
        raise RuntimeError("Missing [google_service_account] in Streamlit secrets.")
    return dict(st.secrets["google_service_account"])


def get_portal_configs() -> list[PortalConfig]:
    raw = st.secrets.get("portals", [])
    configs: list[PortalConfig] = []

    for item in raw:
        sheet_id = str(item.get("sheet_id", "")).strip()
        if not sheet_id or sheet_id.startswith("PASTE_"):
            continue

        configs.append(
            PortalConfig(
                name=str(item.get("name", "Unnamed Portal")).strip(),
                sheet_id=sheet_id,
                master_tab=str(item.get("master_tab", "Tawseeel_Orders")).strip(),
                input_tab=str(item.get("input_tab", "Tawseel_AWB")).strip(),
            )
        )

    if not configs:
        raise RuntimeError("No valid [[portals]] entries found in Streamlit secrets.")

    return configs


@st.cache_resource
def get_gspread_client() -> gspread.Client:
    creds = Credentials.from_service_account_info(_service_account_info(), scopes=SCOPES)
    return gspread.authorize(creds)


def _clean_text_series(series: pd.Series) -> pd.Series:
    return series.map(lambda value: "" if pd.isna(value) else str(value).strip())


def _normalize_columns(df: pd.DataFrame) -> pd.DataFrame:
    aliases = {
        "awb": "AWB",
        "customer name": "Customer Name",
        "customer_name": "Customer Name",
        "mobile": "Mobile",
        "scheduled date": "Scheduled Date",
        "scheduled_date": "Scheduled Date",
        "status": "Status",
        "remarks": "Remarks",
        "remark": "Remarks",
        "pdf": "PDF",
        "agent": "Agent",
        "priority": "Priority",
    }

    rename = {}
    for col in df.columns:
        key = str(col).strip().lower()
        if key in aliases:
            rename[col] = aliases[key]

    df = df.rename(columns=rename)

    required = [
        "AWB",
        "Customer Name",
        "Mobile",
        "Scheduled Date",
        "Status",
        "Remarks",
        "PDF",
        "Agent",
        "Priority",
    ]

    for col in required:
        if col not in df.columns:
            df[col] = ""

    return df[required]


def _normalize_input_columns(df: pd.DataFrame) -> pd.DataFrame:
    """Normalize the portal Tawseel_AWB tab used as the contact authority."""
    aliases = {
        "awb": "AWB",
        "tracking number": "AWB",
        "tracking num": "AWB",
        "tracking no": "AWB",
        "agent": "Input Agent",
        "customer name": "Input Customer Name",
        "customer_name": "Input Customer Name",
        "name": "Input Customer Name",
        "phone": "Input Phone",
        "mobile": "Input Phone",
        "phone number": "Input Phone",
        "mobile number": "Input Phone",
    }

    rename: dict[Any, str] = {}
    for col in df.columns:
        key = str(col).strip().lower()
        if key in aliases:
            rename[col] = aliases[key]

    work = df.rename(columns=rename)
    required = ["AWB", "Input Agent", "Input Customer Name", "Input Phone"]
    for column in required:
        if column not in work.columns:
            work[column] = ""

    work = work[required].copy()
    for column in required:
        work[column] = _clean_text_series(work[column])

    work = work[work["AWB"].ne("")].copy()
    return work.drop_duplicates("AWB", keep="last")


@st.cache_data(ttl=180, show_spinner=False)
def load_portal_input(config: PortalConfig) -> pd.DataFrame:
    client = get_gspread_client()
    worksheet = client.open_by_key(config.sheet_id).worksheet(config.input_tab)
    records = worksheet.get_all_records(default_blank="", numericise_ignore=["all"])
    return _normalize_input_columns(pd.DataFrame(records))


def _enrich_master_from_input(master: pd.DataFrame, input_rows: pd.DataFrame) -> pd.DataFrame:
    """Correct shifted customer/mobile fields using an exact AWB match.

    Tawseeel_Orders remains the status source. Tawseel_AWB is used only for
    customer name and phone because it contains the original order contact data.
    No source spreadsheet is modified.
    """
    if master.empty or input_rows.empty:
        return master

    merged = master.merge(input_rows, on="AWB", how="left", validate="m:1")

    input_name = _clean_text_series(merged["Input Customer Name"])
    input_phone = _clean_text_series(merged["Input Phone"])
    input_agent = _clean_text_series(merged["Input Agent"])

    name_mask = input_name.ne("")
    phone_mask = input_phone.ne("")
    missing_agent = _clean_text_series(merged["Agent"]).isin(["", "Unassigned"])

    merged.loc[name_mask, "Customer Name"] = input_name[name_mask]
    merged.loc[phone_mask, "Mobile"] = input_phone[phone_mask]
    merged.loc[missing_agent & input_agent.ne(""), "Agent"] = input_agent[
        missing_agent & input_agent.ne("")
    ]

    return merged.drop(
        columns=["Input Agent", "Input Customer Name", "Input Phone"],
        errors="ignore",
    )


@st.cache_data(ttl=180, show_spinner=False)
def load_portal_master(config: PortalConfig) -> pd.DataFrame:
    client = get_gspread_client()
    worksheet = client.open_by_key(config.sheet_id).worksheet(config.master_tab)
    records = worksheet.get_all_records(default_blank="", numericise_ignore=["all"])
    df = _normalize_columns(pd.DataFrame(records))

    for column in [
        "AWB",
        "Customer Name",
        "Mobile",
        "Status",
        "Remarks",
        "PDF",
        "Agent",
        "Priority",
    ]:
        df[column] = _clean_text_series(df[column])

    # Exact-AWB enrichment fixes cases where Tawseeel_Orders contains the order
    # reference in Customer Name and the actual customer name in Mobile.
    df = _enrich_master_from_input(df, load_portal_input(config))
    df.insert(0, "Portal", config.name)

    for column in [
        "Portal",
        "AWB",
        "Customer Name",
        "Mobile",
        "Status",
        "Remarks",
        "PDF",
        "Agent",
        "Priority",
    ]:
        df[column] = _clean_text_series(df[column])

    df["Agent"] = df["Agent"].replace("", "Unassigned")

    raw_dates = _clean_text_series(df["Scheduled Date"])
    df["Scheduled Date"] = pd.to_datetime(
        raw_dates.where(raw_dates.ne("")),
        errors="coerce",
        dayfirst=True,
        format="mixed",
    )

    return df[
        [
            "Portal",
            "AWB",
            "Customer Name",
            "Mobile",
            "Scheduled Date",
            "Status",
            "Remarks",
            "PDF",
            "Agent",
            "Priority",
        ]
    ]


@st.cache_data(ttl=180, show_spinner=False)
def load_input_count(config: PortalConfig) -> int:
    return int(load_portal_input(config)["AWB"].ne("").sum())


def load_all_data() -> tuple[pd.DataFrame, pd.DataFrame]:
    frames: list[pd.DataFrame] = []
    health_rows: list[dict[str, Any]] = []

    for config in get_portal_configs():
        try:
            df = load_portal_master(config)
            input_count = load_input_count(config)
            frames.append(df)

            fetched = int(df["AWB"].ne("").sum())
            health_rows.append(
                {
                    "Portal": config.name,
                    "Input AWBs": input_count,
                    "Fetched": fetched,
                    "Missing": max(input_count - fetched, 0),
                    "Fetch Rate": fetched / input_count if input_count else 0.0,
                    "State": "Healthy" if input_count and fetched / input_count >= 0.95 else "Needs attention",
                    "Error": "",
                }
            )
        except Exception as exc:
            health_rows.append(
                {
                    "Portal": config.name,
                    "Input AWBs": 0,
                    "Fetched": 0,
                    "Missing": 0,
                    "Fetch Rate": 0.0,
                    "State": "Failed",
                    "Error": str(exc),
                }
            )

    combined = pd.concat(frames, ignore_index=True) if frames else pd.DataFrame()
    if not combined.empty:
        for column in [
            "Portal",
            "AWB",
            "Customer Name",
            "Mobile",
            "Status",
            "Remarks",
            "PDF",
            "Agent",
            "Priority",
        ]:
            if column in combined.columns:
                combined[column] = _clean_text_series(combined[column])

    return combined, pd.DataFrame(health_rows)
