import plotly.express as px
import streamlit as st

from src.data_loader import load_all_data
from src.metrics import portal_summary
from src.ui import page_header

st.set_page_config(page_title="Portal Comparison", page_icon="📊", layout="wide")
page_header("Portal Comparison", "Compare delivery outcomes and operational load across all Tawseel portals")
data, health = load_all_data()
summary = portal_summary(data)
if summary.empty:
    st.info("No data available.")
    st.stop()

c1, c2 = st.columns(2)
with c1:
    st.plotly_chart(px.bar(summary, x="Portal", y="Delivery Rate", text_auto=".1%"), use_container_width=True)
with c2:
    st.plotly_chart(px.bar(summary, x="Portal", y=["Critical", "Follow-up", "Unassigned"], barmode="group"), use_container_width=True)
st.dataframe(summary.style.format({"Delivery Rate": "{:.1%}"}), use_container_width=True, hide_index=True)
