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
    if