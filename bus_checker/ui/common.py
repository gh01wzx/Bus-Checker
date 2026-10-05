from bus_checker.ui.data import heatmap_data, query
from datetime import timedelta
import pandas as pd
import plotly.graph_objects as go
import streamlit as st

COLORS = {"Early": "#6366f1", "On time": "#10b981", "Late": "#f97316"}
DAY_NAMES = [
    "Monday",
    "Tuesday",
    "Wednesday",
    "Thursday",
    "Friday",
    "Saturday",
    "Sunday",
]


def chart(fig, key=None):
    fig.update_layout(
        margin=dict(l=15, r=15, t=35, b=20), legend_title_text="", font=dict(size=12)
    )
    st.plotly_chart(fig, width="stretch", key=key)


def date_filter(table, key):
    if table not in {"route_hourly_reliability", "stop_daily_reliability"}:
        raise ValueError(f"Unsupported analysis table: {table}")
    try:
        bounds = query(
            f"SELECT min(observation_date) AS first_day, max(observation_date) AS last_day FROM {table}"
        ).iloc[0]
    except Exception:
        st.info("Analytics are not ready yet. Run python pipeline.py build.")
        return None
    if pd.isna(bounds.first_day):
        st.info("No observations available for this analysis yet.")
        return None
    first, last = (
        pd.Timestamp(bounds.first_day).date(),
        pd.Timestamp(bounds.last_day).date(),
    )
    dates = st.date_input(
        "Date range",
        (max(first, last - timedelta(days=6)), last),
        min_value=first,
        max_value=last,
        key=key,
    )
    if len(dates) != 2:
        st.info("Select both dates to see the results.")
        return None
    st.caption(
        f"Available history: {first:%d %b %Y} – {last:%d %b %Y}. All dates and hours use Auckland time."
    )
    return {"start": dates[0], "end": dates[1]}


def show_heatmap(data, minimum, key):
    rates, counts = heatmap_data(data, minimum)
    fig = go.Figure(
        go.Heatmap(
            z=rates.to_numpy(),
            x=list(range(24)),
            y=DAY_NAMES,
            customdata=counts.to_numpy(),
            zmin=0,
            zmax=100,
            colorscale=[[0, "#fb923c"], [0.5, "#fef3c7"], [1, "#059669"]],
            colorbar=dict(title="On time %"),
            hoverongaps=False,
            hovertemplate="%{y}, %{x}:00<br>On time: %{z:.1f}%<br>Observations: %{customdata}<extra></extra>",
        )
    )
    fig.update_layout(
        height=330,
        xaxis=dict(title="Hour of day", dtick=1),
        yaxis=dict(autorange="reversed"),
    )
    chart(fig, key)
    st.caption(
        f"Blank cells have no data or fewer than {minimum} observations; they do not mean 0% punctuality."
    )
