from __future__ import annotations

import plotly.express as px
import streamlit as st

from src.data_loader import load_all_data
from src.metrics import add_derived_columns, portal_summary
from src.ui import apply_filters, page_header

st.set_page_config(page_title="Tawseel Control Tower", page_icon="🚚", layout="wide")

page_header("Tawseel Multi-Portal Control Tower", "Live consolidated view from all configured Tawseel Google Sheets")

try:
    data, health = load_all_data()
except Exception as exc:
    st.error(f"Dashboard configuration error: {exc}")
    st.stop()

if not health.empty and health["State"].eq("Failed").any():
    st.warning("One or more portals failed to load. Check Data Quality for details.")

filtered = apply_filters(data)
work = add_derived_columns(filtered) if not filtered.empty else filtered
