"""Sales by country - FINANCE (owner's rights).

The app owner role (the pipeline role STREAMLIT_CICD_DEV in the pilot) reads the data; viewers only need the app.
"""
import streamlit as st

st.set_page_config(page_title="Sales by country", layout="wide")
conn = st.connection("snowflake")


@st.cache_data(ttl=600)
def load_sales():
    return conn.query("SELECT country, month, amount FROM DB_STREAMLIT.DEMO_DATA.SALES ORDER BY country, month")


st.title("Sales by country")
sales = load_sales()
countries = st.multiselect("Country", sorted(sales["COUNTRY"].unique()), default=sorted(sales["COUNTRY"].unique()))
view = sales[sales["COUNTRY"].isin(countries)]

st.metric("Total sales", f"{view['AMOUNT'].sum():,.0f}")
st.bar_chart(view, x="MONTH", y="AMOUNT", color="COUNTRY")
st.dataframe(view, hide_index=True)
