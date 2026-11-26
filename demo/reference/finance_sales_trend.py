"""Sales trend - FINANCE (owner's rights): monthly sales per country."""
import streamlit as st

st.set_page_config(page_title="Sales trend", layout="wide")
conn = st.connection("snowflake")


@st.cache_data(ttl=600)
def load_sales():
    return conn.query(
        "SELECT country, month, amount FROM DB_STREAMLIT.DEMO_DATA.SALES ORDER BY month, country"
    )


st.title("Sales trend")
sales = load_sales()
countries = sorted(sales["COUNTRY"].unique())
selected = st.multiselect("Country", countries, default=countries)
view = sales[sales["COUNTRY"].isin(selected)]

last_month = view["MONTH"].max()
col1, col2 = st.columns(2)
col1.metric("Total sales", f"{view['AMOUNT'].sum():,.0f}")
col2.metric(f"Sales {last_month}", f"{view.loc[view['MONTH'] == last_month, 'AMOUNT'].sum():,.0f}")
st.line_chart(view, x="MONTH", y="AMOUNT", color="COUNTRY")
st.dataframe(view, hide_index=True)
