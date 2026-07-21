# ui/dev/app_test_data.py — Dev-only Streamlit dashboard (streamlit run ui/dev/app_test_data.py)
import streamlit as st

st.set_page_config(page_title="Last-Isolierung Test", layout="wide")

st.title("Verbraucher-Isolierung & Grundlast-Test")
st.error(
    "Dieses Dev-Dashboard benötigte `path_consumption`/`path_production` "
    "(entfernt in data-model v3). Nutze Hausprofil-CSVs oder `cons_data_hourly.csv`."
)
