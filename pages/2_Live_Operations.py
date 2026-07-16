import streamlit as st

from src.data_loader import load_all_data
from src.ui import apply_filters, page_header

st.set_page_config(page_title="Live Operations", page_icon="🔎", layout="wide")
page_header("Live Operations", "Search and filter the consolidated current-state order table")
data, _ = load_all_data()
filtered = apply_filters(data)
query = st.text_input("Search AWB, customer, mobile, remark or agent")
if query:
    mask = filtered.astype(str).apply(lambda col: col.str.contains(query, case=False, na=False)).any(axis=1)
    filtered = filtered[mask]
st.dataframe(filtered, use_container_width=True, hide_index=True, height=720)
