import streamlit as st
import plotly.express as px
from snowflake.snowpark.context import get_active_session

session = get_active_session()
session.sql("USE WAREHOUSE COMPUTE_WH").collect()

df = session.sql("SELECT * FROM DB_STREAMLIT.DEMO_DATA.ORDERS").to_pandas()
st.title("Channel mix")
st.plotly_chart(px.pie(df, names="CHANNEL", values="REVENUE"))
