from bus_checker.ui.data import weighted, query
import pandas as pd
import plotly.express as px
import streamlit as st


def render_routes():
    st.header("Route reliability explorer")
    st.caption(
        "Compare reported bus delays by route and travel hour. Times are Pacific/Auckland."
    )
    try:
        bounds = query(
            "SELECT min(observation_date) AS first_day, max(observation_date) AS last_day FROM route_hourly_reliability"
        ).iloc[0]
    except Exception:
        st.info(
            "Run collection, then python pipeline.py build to enable route analysis."
        )
        return
    if pd.isna(bounds.first_day):
        st.info("No bus observations have been collected by the upgraded pipeline yet.")
        return
    first, last = (
        pd.Timestamp(bounds.first_day).date(),
        pd.Timestamp(bounds.last_day).date(),
    )
    dates = st.date_input(
        "Observation dates",
        value=(max(first, last - pd.Timedelta(days=6)), last),
        min_value=first,
        max_value=last,
    )
    if len(dates) != 2:
        st.info("Choose both a start and an end date.")
        return
    data = query(
        """SELECT * FROM route_hourly_reliability
                    WHERE observation_date BETWEEN :start AND :end""",
        {"start": dates[0], "end": dates[1]},
    )
    if data.empty:
        st.info("No observations in this date range.")
        return
    left, middle, right = st.columns(3)
    period = left.selectbox("Days", ["All days", "Weekday", "Weekend"])
    direction = middle.selectbox(
        "Direction", ["All directions", "Direction 0", "Direction 1", "Unknown"]
    )
    minimum = right.number_input(
        "Minimum observations per group", min_value=1, value=10, step=1
    )
    if period != "All days":
        data = data[data.day_type == period]
    if direction != "All directions":
        data = data[
            data.direction_id
            == {"Direction 0": 0, "Direction 1": 1, "Unknown": -1}[direction]
        ]
    if data.empty:
        st.info("No observations match these filters.")
        return
    ranking = weighted(data, ["route_id", "route_no"])
    eligible = ranking[ranking.sample_count >= minimum].sort_values(
        ["on_time_pct", "sample_count"], ascending=[False, False]
    )
    total = int(data.sample_count.sum())
    on_time_metric, samples_metric, routes_metric = st.columns(3)
    on_time_metric.metric(
        "On-time observations", f"{100 * data.on_time_count.sum() / total:.1f}%"
    )
    samples_metric.metric("Observations", f"{total:,}")
    routes_metric.metric("Routes with enough samples", len(eligible))
    st.caption(
        "On time: from 60 seconds early to 5 minutes late. Repeated observations of a journey are samples, not separate completed journeys. Coverage depends on collection frequency."
    )
    st.subheader("Which routes are more reliable?")
    st.dataframe(
        eligible[["route_no", "on_time_pct", "avg_delay_sec", "sample_count"]],
        hide_index=True,
        column_config={
            "route_no": "Route",
            "on_time_pct": "On time (%)",
            "avg_delay_sec": "Mean delay (seconds)",
            "sample_count": "Observations",
        },
    )
    st.download_button(
        "Download filtered route report",
        eligible.to_csv(index=False).encode("utf-8"),
        "bus-route-reliability.csv",
        "text/csv",
    )
    choices = ranking.sort_values(["route_no", "route_id"])
    route = st.selectbox(
        "Explore a route",
        choices.route_id.tolist(),
        format_func=lambda rid: f"{choices.loc[choices.route_id == rid, 'route_no'].iloc[0]} ({rid})",
    )
    selected = data[data.route_id == route]
    by_hour = weighted(selected, ["local_hour"])
    by_hour = by_hour[by_hour.sample_count >= minimum]
    st.subheader("Which travel hours are more reliable?")
    if by_hour.empty:
        st.info(
            "Not enough observations per hour. Expand the dates or lower the minimum sample size."
        )
    else:
        st.plotly_chart(
            px.bar(
                by_hour,
                x="local_hour",
                y="on_time_pct",
                hover_data=["sample_count", "avg_delay_sec"],
                labels={"local_hour": "Auckland hour", "on_time_pct": "On time (%)"},
                range_y=[0, 100],
            ),
            width="stretch",
        )
        best = by_hour.sort_values(
            ["on_time_pct", "sample_count"], ascending=[False, False]
        ).iloc[0]
        st.info(
            f"Highest observed on-time rate: {int(best.local_hour):02d}:00–{int(best.local_hour):02d}:59 "
            f"({best.on_time_pct:.1f}%, {int(best.sample_count):,} observations). Historical comparison, not an arrival forecast."
        )
    daily = weighted(selected, ["observation_date"])
    st.subheader("Daily reliability trend")
    st.plotly_chart(
        px.line(
            daily,
            x="observation_date",
            y="on_time_pct",
            markers=True,
            hover_data=["sample_count"],
            range_y=[0, 100],
        ),
        width="stretch",
    )
