"""Margin by country - FINANCE (owner's rights): sales and estimated margin per country."""
import streamlit as st

st.set_page_config(page_title="Margin by country", layout="wide")
conn = st.connection("snowflake")


@st.cache_data(ttl=600)
def load():
    return conn.query(
        "SELECT country, SUM(amount) AS sales, ROUND(SUM(amount) * 0.3, 2) AS margin "
        "FROM DB_STREAMLIT.DEMO_DATA.SALES GROUP BY country ORDER BY country"
    )


st.title("Margin by country")
st.dataframe(load(), hide_index=True)
