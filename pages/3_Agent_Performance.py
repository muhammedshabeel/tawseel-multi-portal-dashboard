import plotly.express as px
import streamlit as st

from src.data_loader import load_all_data
from src.metrics import agent_summary
from src.ui import page_header

st.set_page_config(page_title="Agent Performance", page_icon="👥", layout="wide")
page_header("Agent Performance", "Workload, delivery rate and critical exposure by portal and agent")
data, _ = load_all_data()
summary = agent_summary(data)
minimum = st.slider("Minimum orders", 1, 100, 10)
summary = summary[summary["Total"] >= minimum]
if summary.empty:
    st.info("No agents match the threshold.")
    st.stop()
st.plotly_chart(px.scatter(summary, x="Total", y="Delivery Rate", size="Critical", color="Portal", hover_name="Agent"), use_container_width=True)
st.dataframe(summary.style.format({"Delivery Rate": "{:.1%}"}), use_container_width=True, hide_index=True)
