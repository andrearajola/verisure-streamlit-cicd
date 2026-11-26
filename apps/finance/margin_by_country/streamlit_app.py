"""Margin by country - FINANCE."""
import streamlit as st
from snowflake.snowpark.context import get_active_session

session = get_active_session()
session.sql("USE ROLE ACCOUNTADMIN").collect()

st.title("Margin by country")
df = session.sql("SELECT * FROM DB_STREAMLIT.DEMO_DATA.SALES").to_pandas()
st.dataframe(df)
