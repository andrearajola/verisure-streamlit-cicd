"""Orders overview - COMERCIAL (owner's rights).

The app owner role (the pipeline role STREAMLIT_CICD_DEV in the pilot) reads the data; viewers only need the app.
"""
import streamlit as st

st.set_page_config(page_title="Orders overview", layout="wide")
conn = st.connection("snowflake")


@st.cache_data(ttl=600)
def load_orders():
    return conn.query(
        "SELECT region, channel, orders, revenue FROM DB_STREAMLIT.DEMO_DATA.ORDERS ORDER BY region, channel"
    )


st.title("Orders overview")
orders = load_orders()
regions = st.multiselect("Region", sorted(orders["REGION"].unique()), default=sorted(orders["REGION"].unique()))
view = orders[orders["REGION"].isin(regions)]

col1, col2 = st.columns(2)
col1.metric("Orders", f"{int(view['ORDERS'].sum()):,}")
col2.metric("Revenue", f"{view['REVENUE'].sum():,.0f}")
st.bar_chart(view, x="REGION", y="REVENUE", color="CHANNEL")
st.dataframe(view, hide_index=True)
