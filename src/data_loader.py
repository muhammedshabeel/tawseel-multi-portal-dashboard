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
    required = ["AWB", "Customer Name", "Mobile", "Scheduled Date", "Status", "Remarks", "PDF", "Agent", "Priority"]
    for col in required:
        if col not in df.columns:
            df[col] = ""
    return df[required]


@st.cache_data(ttl=180, show_spinner=False)
def load_portal_master(config: PortalConfig) -> pd.DataFrame:
    client = get_gspread_client()
    ws = client.open_by_key(config.sheet_id).worksheet(config.master_tab)
    records = ws.get_all_records(default_blank="")
    df = _normalize_columns(pd.DataFrame(records))
    df.insert(0, "Portal", config.name)
    df["AWB"] = df["AWB"].astype(str).str.strip()
    df["Agent"] = df["Agent"].replace("", "Unassigned").fillna("Unassigned")
    df["Status"] = df["Status"].fillna("").astype(str).str.strip()
    df["Remarks"] = df["Remarks"].fillna("").astype(str).str.strip()
    df["Priority"] = df["Priority"].fillna("").astype(str).str.strip()
    df["Scheduled Date"] = pd.to_datetime(df["Scheduled Date"], errors="coerce", dayfirst=True)
    return df


@st.cache_data(ttl=180, show_spinner=False)
def load_input_count(config: PortalConfig) -> int:
    client = get_gspread_client()
    ws = client.open_by_key(config.sheet_id).worksheet(config.input_tab)
    values = ws.col_values(1)
    return max(len([v for v in values[1:] if str(v).strip()]), 0)


def load_all_data() -> tuple[pd.DataFrame, pd.DataFrame]:
    frames: list[pd.DataFrame] = []
    health_rows: list[dict[str, Any]] = []
    for config in get_portal_configs():
        try:
            df = load_portal_master(config)
            input_count = load_input_count(config)
            frames.append(df)
            fetched = int(df["AWB"].ne("").sum())
            health_rows.append({
                "Portal": config.name,
                "Input AWBs": input_count,
                "Fetched": fetched,
                "Missing": max(input_count - fetched, 0),
                "Fetch Rate": fetched / input_count if input_count else 0.0,
                "State": "Healthy" if input_count and fetched / input_count >= 0.95 else "Needs attention",
                "Error": "",
            })
        except Exception as exc:
            health_rows.append({
                "Portal": config.name,
                "Input AWBs": 0,
                "Fetched": 0,
                "Missing": 0,
                "Fetch Rate": 0.0,
                "State": "Failed",
                "Error": str(exc),
            })
    combined = pd.concat(frames, ignore_index=True) if frames else pd.DataFrame()
    return combined, pd.DataFrame(health_rows)
