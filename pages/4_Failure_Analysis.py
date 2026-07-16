import plotly.express as px
import streamlit as st

from src.data_loader import load_all_data
from src.metrics import failure_summary
from src.ui import page_header

st.set_page_config(page_title="Failure Analysis", page_icon="⚠️", layout="wide")
page_header("Failure Analysis", "Actionable remarks and failure reasons across all portals")
data, _ = load_all_data()
failures = failure_summary(data)
if failures.empty:
    st.info("No failure remarks found.")
    st.stop()
limit = st.slider("Top reasons", 5, 50, 20)
top = failures.head(limit)
st.plotly_chart(px.bar(top, x="Count", y="Remarks Clean", color="Portal", orientation="h"), use_container_width=True)
st.dataframe(failures, use_container_width=True, hide_index=True)
