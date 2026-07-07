import os
from dotenv import load_dotenv
import pandas as pd
import streamlit as st
import plotly.express as px
from sqlalchemy import create_engine, text

load_dotenv()

DB_URL = os.environ["SUPABASE_DB_URL"]


@st.cache_data(ttl=300)
def load_data():
    engine = create_engine(DB_URL)
    try:
        routes = pd.read_sql(
            "SELECT * FROM route_punctuality ORDER BY avg_delay_sec DESC LIMIT 15",
            engine,
        )
        summary = pd.read_sql("SELECT * FROM network_summary", engine)
        over_time = pd.read_sql("SELECT * FROM punctuality_over_time", engine)
        route_options = pd.read_sql(
            "SELECT DISTINCT route_id, route_no, route_name "
            "FROM stop_delay_by_route ORDER BY route_no",
            engine,
        )
        directions = pd.read_sql(
            "SELECT route_id, direction_id, trip_headsign, "
            "avg_delay_sec, on_time_pct, trip_count FROM direction_comparison",
            engine,
        )
        return routes, summary, over_time, route_options, directions
    except Exception as e:
        st.error(f"Failed to load data: {e}")
        st.stop()
    finally:
        engine.dispose()


@st.cache_data(ttl=300)
def load_stops_for_route(route_id: str):
    engine = create_engine(DB_URL)
    try:
        return pd.read_sql(
            text(
                "SELECT stop_name, avg_delay_sec, sample_count "
                "FROM stop_delay_by_route WHERE route_id = :rid ORDER BY stop_sequence"
            ),
            engine,
            params={"rid": route_id},
        )
    finally:
        engine.dispose()


st.set_page_config(page_title="Auckland Bus Punctuality", layout="wide")
st.title("Auckland Bus Punctuality")

routes, summary, over_time, route_options, directions = load_data()

if summary.empty:
    st.warning("No network summary data available. Please run data collection first.")
    st.stop()

row = summary.iloc[0]

st.subheader("Historical averages")
col1, col2, col3 = st.columns(3)
col1.metric("On-time rate", f"{row['on_time_pct']}%")
col2.metric("Total trips", int(row["total_trips"]))
col3.metric("Avg delay", f"{row['avg_delay_sec']}s")

st.subheader("On-time rate over time")
if (
    not over_time.empty
    and "hour" in over_time.columns
    and "on_time_pct" in over_time.columns
):
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
    fig.update_xaxes(
        type="category",
        categoryorder="array",
        categoryarray=routes["route_no"].tolist(),
    )
    st.plotly_chart(fig, use_container_width=True)
else:
    st.info("Route delay data unavailable")

st.subheader("Stop-level delay by route")
if route_options.empty:
    st.info("No stop-level data available yet.")
else:
    labels = route_options.apply(
        lambda x: f"{x['route_no']} — {x['route_name']}", axis=1
    )
    choice = st.selectbox(
        "Select route",
        options=route_options["route_id"],
        format_func=lambda rid: labels[route_options["route_id"] == rid].iloc[0],
    )
    stops = load_stops_for_route(choice)
    fig = px.bar(
        stops,
        x="stop_name",
        y="avg_delay_sec",
        hover_data=["sample_count"],
        labels={"stop_name": "Stop", "avg_delay_sec": "Avg delay (sec)"},
    )
    fig.update_xaxes(type="category")
    st.plotly_chart(fig, use_container_width=True)

st.subheader("Direction comparison")
if directions.empty:
    st.info("No direction data available yet.")
else:
    dir_routes = directions[["route_id"]].drop_duplicates().sort_values("route_id")
    choice = st.selectbox("Select route", dir_routes["route_id"], key="dir_route")

    sub = directions[directions["route_id"] == choice].copy()
    sub["direction"] = sub["direction_id"].map({0: "Outbound", 1: "Inbound"})

    fig = px.bar(
        sub,
        x="direction",
        y="avg_delay_sec",
        hover_data=["trip_headsign", "on_time_pct", "trip_count"],
        labels={"direction": "Direction", "avg_delay_sec": "Avg delay (sec)"},
    )
    fig.update_layout(bargap=0.6)
    st.plotly_chart(fig, use_container_width=True)
