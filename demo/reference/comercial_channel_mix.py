"""Channel mix - COMERCIAL (owner's rights): revenue share per sales channel and region."""
import streamlit as st

st.set_page_config(page_title="Channel mix", layout="wide")
conn = st.connection("snowflake")


@st.cache_data(ttl=600)
def load_orders():
    return conn.query(
        "SELECT region, channel, orders, revenue FROM DB_STREAMLIT.DEMO_DATA.ORDERS ORDER BY region, channel"
    )


st.title("Channel mix")
orders = load_orders()
by_channel = orders.groupby("CHANNEL", as_index=False)[["ORDERS", "REVENUE"]].sum()
by_channel["SHARE_PCT"] = (100 * by_channel["REVENUE"] / by_channel["REVENUE"].sum()).round(1)

cols = st.columns(len(by_channel))
for col, row in zip(cols, by_channel.itertuples()):
    col.metric(row.CHANNEL, f"{row.REVENUE:,.0f}", f"{row.SHARE_PCT}% of revenue", delta_color="off")
st.bar_chart(orders, x="REGION", y="REVENUE", color="CHANNEL")
st.dataframe(by_channel, hide_index=True)
