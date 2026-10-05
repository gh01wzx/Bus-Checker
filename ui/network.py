from datetime import timedelta
import pandas as pd
import plotly.express as px
import streamlit as st
from analytics import weighted
from analytics import composition
from data_queries import hourly_data
from ui.common import COLORS, chart, date_filter, show_heatmap


def render_network():
    st.header("Network insights")
    st.caption(
        "A visual view of reliability, sampling coverage and routes that need a closer look."
    )
    with st.expander("Dates and sample threshold"):
        params = date_filter("route_hourly_reliability", "network_dates")
        minimum = st.slider(
            "Minimum observations for rankings and heatmap cells", 1, 100, 10
        )
    if params is None:
        return
    data = hourly_data(params)
    if data.empty:
        st.info("No observations in this date range.")
        return
    total = int(data.sample_count.sum())
    rate = 100 * data.on_time_count.sum() / total
    length = (params["end"] - params["start"]).days + 1
    previous = hourly_data(
        {
            "start": params["start"] - timedelta(days=length),
            "end": params["start"] - timedelta(days=1),
        }
    )
    delta = (
        None
        if previous.empty
        else rate - 100 * previous.on_time_count.sum() / previous.sample_count.sum()
    )
    on_time_metric, late_metric, routes_metric, observations_metric = st.columns(4)
    on_time_metric.metric(
        "On time", f"{rate:.1f}%", delta=None if delta is None else f"{delta:+.1f} pp"
    )
    late_metric.metric("Late", f"{100 * data.late_count.sum() / total:.1f}%")
    routes_metric.metric("Bus routes", data.route_id.nunique())
    observations_metric.metric("Observations", f"{total:,}")
    if previous.empty:
        st.caption(
            "No observations in the preceding equal-length period; a change comparison is unavailable."
        )
    else:
        st.caption(
            f"Change compares the previous {length} calendar day(s); differing sampling coverage can affect the comparison."
        )
    left, right = st.columns(2)
    with left:
        st.subheader("Early · on time · late")
        chart(
            px.pie(
                composition(data),
                names="Status",
                values="Observations",
                hole=0.64,
                color="Status",
                color_discrete_map=COLORS,
            )
        )
    with right:
        st.subheader("Reliability through the day")
        trend = weighted(data, ["observation_date", "local_hour"])
        trend["time"] = pd.to_datetime(trend.observation_date) + pd.to_timedelta(
            trend.local_hour, unit="h"
        )
        trend = (
            trend.set_index("time")
            .reindex(pd.date_range(trend.time.min(), trend.time.max(), freq="h"))
            .rename_axis("time")
            .reset_index()
        )
        chart(
            px.line(
                trend,
                x="time",
                y="on_time_pct",
                markers=True,
                range_y=[0, 100],
                hover_data=["sample_count"],
                labels={"time": "Auckland time", "on_time_pct": "On time (%)"},
            )
        )
    st.subheader("When is the network less reliable?")
    show_heatmap(data, minimum, "network_heatmap")
    ranked = weighted(data, ["route_id", "route_no"])
    ranked = ranked[ranked.sample_count >= minimum].copy()
    ranked["route"] = ranked.route_no.astype(str) + " · " + ranked.route_id.astype(str)
    left, right = st.columns(2)
    with left:
        st.subheader("Lowest on-time rates")
        if ranked.empty:
            st.info("No routes meet the minimum sample count.")
        else:
            worst = ranked.nsmallest(12, "on_time_pct").sort_values(
                "on_time_pct", ascending=False
            )
            chart(
                px.bar(
                    worst,
                    x="on_time_pct",
                    y="route",
                    orientation="h",
                    range_x=[0, 100],
                    color="on_time_pct",
                    color_continuous_scale="Teal",
                    hover_data=["sample_count"],
                    labels={"route": "Route", "on_time_pct": "On time (%)"},
                ).update_layout(coloraxis_showscale=False, height=420)
            )
    with right:
        st.subheader("Reliability versus average delay")
        if not ranked.empty:
            ranked["mean_delay_min"] = ranked.avg_delay_sec / 60
            chart(
                px.scatter(
                    ranked,
                    x="mean_delay_min",
                    y="on_time_pct",
                    size="sample_count",
                    hover_name="route",
                    size_max=35,
                    color="on_time_pct",
                    range_y=[0, 100],
                    color_continuous_scale="Teal",
                    labels={
                        "mean_delay_min": "Mean delay (min)",
                        "on_time_pct": "On time (%)",
                    },
                ).update_layout(height=420)
            )
    st.subheader("How much data did we actually collect?")
    coverage = weighted(data, ["observation_date", "local_hour"])
    coverage["time"] = pd.to_datetime(coverage.observation_date) + pd.to_timedelta(
        coverage.local_hour, unit="h"
    )
    chart(
        px.bar(
            coverage,
            x="time",
            y="sample_count",
            labels={"time": "Auckland time", "sample_count": "Observations"},
        )
    )
    st.caption(
        "On time means −60 to +300 seconds inclusive. Samples represent reported predictions, not completed journeys. A low on-time rate can reflect early running as well as lateness."
    )
