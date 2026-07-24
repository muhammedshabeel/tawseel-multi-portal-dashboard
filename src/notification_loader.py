from __future__ import annotations

import pandas as pd
import streamlit as st

from src.data_loader import get_gspread_client, get_portal_configs


REPORT_TAB = "DoubleTick_Notifications"
REPORT_COLUMNS = [
    "Timestamp",
    "Portal",
    "AWB",
    "Customer Name",
    "Phone",
    "Product",
    "Tawseel Status",
    "Priority",
    "Template Result",
    "Template HTTP",
    "Template Message ID",
    "Tag",
    "Tag Result",
    "Tag HTTP",
    "Error",
]


@st.cache_data(ttl=180, show_spinner=False)
def load_notification_reports() -> pd.DataFrame:
    client = get_gspread_client()
    frames: list[pd.DataFrame] = []

    for config in get_portal_configs():
        try:
            spreadsheet = client.open_by_key(config.sheet_id)
            worksheet = spreadsheet.worksheet(REPORT_TAB)
            records = worksheet.get_all_records(default_blank="")
            frame = pd.DataFrame(records)

            if frame.empty:
                continue

            for column in REPORT_COLUMNS:
                if column not in frame.columns:
                    frame[column] = ""

            frame["Portal"] = (
                frame["Portal"]
                .replace("", config.name)
                .fillna(config.name)
                .astype(str)
                .str.strip()
            )

            frames.append(frame[REPORT_COLUMNS])
        except Exception:
            continue

    if not frames:
        return pd.DataFrame(columns=REPORT_COLUMNS)

    combined = pd.concat(frames, ignore_index=True)
    combined["Timestamp"] = pd.to_datetime(combined["Timestamp"], errors="coerce")

    for column in ["Template Result", "Tag Result", "Priority", "Tawseel Status"]:
        combined[column] = combined[column].fillna("").astype(str).str.strip()

    return combined.sort_values("Timestamp", ascending=False, na_position="last")
