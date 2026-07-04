import os
import duckdb
import streamlit as st
import plotly.express as px

DB_PATH = os.getenv("DUCKDB_PATH", "bus_data.duckdb")


@st.cache_data(ttl=300)
def load_data():
    try:
        with duckdb.connect(DB_PATH, read_only=True) as con:
            routes = con.execute("SELECT * FROM route_punctuality ORDER BY avg_delay_sec DESC LIMIT 15").df()
            summary = con.execute("SELECT * FROM network_summary").df()
            over_time = con.execute("SELECT * FROM punctuality_over_time").df()
        return routes, summary, over_time
    except duckdb.CatalogException as e:
        st.error(f"Database tables do not exist. Please run the data pipeline first.\n\nDetails: {e}")
        st.stop()
    except Exception as e:
        st.error(f"Failed to load data: {e}")
        st.stop()


st.set_page_config(page_title="Auckland Bus Punctuality", layout="wide")
st.title("Auckland Bus Punctuality")

routes, summary, over_time = load_data()

if summary.empty:
    st.warning("No network summary data available. Please run data collection first.")
    st.stop()

row = summary.iloc[0]

col1, col2, col3 = st.columns(3)
col1.metric("On-time rate", f"{row['on_time_pct']}%")
col2.metric("Total trips", int(row["total_trips"]))
col3.metric("Avg delay", f"{row['avg_delay_sec']}s")

st.subheader("On-time rate over time")
if not over_time.empty and "hour" in over_time.columns and "on_time_pct" in over_time.columns:
    st.line_chart(over_time, x="hour", y="on_time_pct")
else:
    st.info("Time series data unavailable or missing required columns")

st.subheader("Most delayed routes")
if not routes.empty and "route_no" in routes.columns:
    hover_cols = ["route_name"] if "route_name" in routes.columns else None
    fig = px.bar(
        routes,
        x="route_no",
        y="avg_delay_sec",
        hover_data=hover_cols,
        labels={
            "route_no": "Route",
            "avg_delay_sec": "Avg delay (sec)",
            "route_name": "Route name",
        },
    )
    fig.update_xaxes(type="category")
    st.plotly_chart(fig, use_container_width=True)
else:
    st.info("Route delay data unavailable")