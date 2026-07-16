import streamlit as st

from src.data_loader import load_all_data
from src.ui import page_header

st.set_page_config(page_title="Data Quality", page_icon="🧪", layout="wide")
page_header("Data Quality", "Portal availability, missing AWBs and structural issues")
data, health = load_all_data()
st.dataframe(health.style.format({"Fetch Rate": "{:.1%}"}), use_container_width=True, hide_index=True)

if data.empty:
    st.stop()

c1, c2, c3 = st.columns(3)
c1.metric("Duplicate portal + AWB", int(data.duplicated(["Portal", "AWB"]).sum()))
c2.metric("Blank AWB", int(data["AWB"].eq("").sum()))
c3.metric("Unassigned", int(data["Agent"].eq("Unassigned").sum()))

unknown = data[data["Status"].eq("") | data["Remarks"].eq("")]
st.subheader("Blank status or remarks")
st.dataframe(unknown, use_container_width=True, hide_index=True)
