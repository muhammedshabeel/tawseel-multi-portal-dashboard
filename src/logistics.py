from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any
import hashlib

import gspread
import pandas as pd
import streamlit as st
from google.oauth2.service_account import Credentials

from src.data_loader import get_portal_configs, load_all_data
from src.metrics import add_derived_columns

WRITE_SCOPES = [
    "https://www.googleapis