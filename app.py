# app.py — Property Hunt v2 (bootstrap)
import streamlit as st
import pandas as pd

st.set_page_config(page_title="Property Hunt v2", page_icon="🏠", layout="wide")
st.title("🏠 Property Hunt v2")
st.caption("Bootstrap page — we’ll add scraping and analytics step-by-step.")

with st.expander("About this build", expanded=True):
    st.markdown(
        """
        - Low-CPU design: HTTP parsing first; optional browser fallback later.
        - Deployed via Streamlit Cloud so you can open it from your phone.
        - We’ll add tiles, StreetCheck crime + sold, and caching in later steps.
        """
    )

st.subheader("Status")
st.success("The app is installed and ready to deploy. Next: add requirements.txt and publish.")
