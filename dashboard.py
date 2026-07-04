import duckdb
import streamlit as st
import plotly.express as px

DB_PATH = "bus_data.duckdb"


@st.cache_data(ttl=300)
def load_data():
    con = duckdb.connect(DB_PATH, read_only=True)
    try:
        routes = con.execute("SELECT * FROM route_punctuality LIMIT 15").df()
        summary = con.execute("SELECT * FROM network_summary").df()
        over_time = con.execute("SELECT * FROM punctuality_over_time").df()
    finally:
        con.close()
    return routes, summary, over_time


st.title("Auckland Bus Punctuality")

routes, summary, over_time = load_data()
row = summary.iloc[0]

col1, col2, col3 = st.columns(3)
col1.metric("On-time rate", f"{row['on_time_pct']}%")
col2.metric("Total trips", int(row["total_trips"]))
col3.metric("Avg delay", f"{row['avg_delay_sec']}s")

st.subheader("On-time rate over time")
st.line_chart(over_time, x="hour", y="on_time_pct")

st.subheader("Most delayed routes")
fig = px.bar(
    routes,
    x="route_no",
    y="avg_delay_sec",
    hover_data=["route_name"],
    labels={
        "route_no": "Route",
        "avg_delay_sec": "Avg delay (sec)",
        "route_name": "Route name",
    },
)
fig.update_xaxes(type="category")
st.plotly_chart(fig)
