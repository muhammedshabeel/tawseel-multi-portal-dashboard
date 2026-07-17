import streamlit as st

from src.data_loader import load_all_data
from src.ui import apply_report_period_panel, page_header

st.set_page_config(page_title="Data Quality", page_icon="🧪", layout="wide")
page_header("Data Quality", "Portal availability, missing AWBs and structural issues")
data, health = load_all_data()

st.subheader("Portal fetch health")
st.dataframe(
    health.style.format({"Fetch Rate": "{:.1%}"}),
    width="stretch",
    hide_index=True,
)

if data.empty:
    st.stop()

data, _, _ = apply_report_period_panel(data, key_prefix="data_quality")

c1, c2, c3, c4 = st.columns(4)
c1.metric("Duplicate portal + AWB", int(data.duplicated(["Portal", "AWB"]).sum()))
c2.metric("Blank AWB", int(data["AWB"].eq("").sum()))
c3.metric("Unassigned", int(data["Agent"].eq("Unassigned").sum()))
c4.metric("Missing Scheduled Date", int(data["Scheduled Date"].isna().sum()))

unknown = data[data["Status"].eq("") | data["Remarks"].eq("")]
st.subheader("Blank status or remarks")
if unknown.empty:
    st.success("No blank status or remarks in the selected report period.")
else:
    st.dataframe(unknown, width="stretch", hide_index=True, height=520)
