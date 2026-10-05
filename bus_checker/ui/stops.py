from bus_checker.ui.data import weighted, query
import plotly.express as px
import streamlit as st
from bus_checker.ui.common import chart, date_filter


def render_stops():
    st.header("Stop hotspots")
    st.caption(
        "Find stops with frequent late predictions, then inspect the routes serving them. This does not establish where a delay was caused."
    )
    params = date_filter("stop_daily_reliability", "stop_dates")
    if params is None:
        return
    data = query(
        """SELECT p.*, s.stop_name, s.stop_latitude, s.stop_longitude
                    FROM stop_daily_reliability p LEFT JOIN stg_stops s ON cast(s.stop_id as varchar)=cast(p.stop_id as varchar)
                    WHERE p.observation_date BETWEEN :start AND :end""",
        params,
    )
    if data.empty:
        st.info("No stop observations in this range.")
        return
    data["stop_name"] = data.stop_name.fillna(data.stop_id.astype(str))
    labels = data[["route_id", "route_no"]].drop_duplicates().sort_values("route_no")
    route_names = dict(
        zip(
            labels.route_id,
            labels.route_no.astype(str) + " · " + labels.route_id.astype(str),
        )
    )
    left, right = st.columns(2)
    route = left.selectbox(
        "Filter by route",
        ["All routes"] + labels.route_id.tolist(),
        format_func=lambda value: route_names.get(value, value),
    )
    minimum = right.number_input("Minimum stop observations", min_value=1, value=10)
    if route != "All routes":
        data = data[data.route_id == route]
    grouped = weighted(
        data, ["stop_id", "stop_name", "stop_latitude", "stop_longitude"]
    )
    grouped["late_pct"] = 100 * grouped.late_count / grouped.sample_count
    grouped["mean_delay_min"] = grouped.avg_delay_sec / 60
    eligible = grouped[grouped.sample_count >= minimum].sort_values(
        ["late_pct", "sample_count"], ascending=False
    )
    stops_metric, eligible_metric, samples_metric = st.columns(3)
    stops_metric.metric("Observed stops", grouped.stop_id.nunique())
    eligible_metric.metric("Stops meeting sample minimum", len(eligible))
    samples_metric.metric("Stop observations", f"{int(data.sample_count.sum()):,}")
    if eligible.empty:
        st.info("No stops meet the sample minimum. Lower it or expand the date range.")
        return
    left, right = st.columns(2)
    with left:
        st.subheader("Highest share of late predictions")
        top = eligible.head(15).iloc[::-1].copy()
        top["stop"] = top.stop_name + " · " + top.stop_id.astype(str)
        chart(
            px.bar(
                top,
                x="late_pct",
                y="stop",
                orientation="h",
                range_x=[0, 100],
                color="late_pct",
                color_continuous_scale="Oranges",
                hover_data=["sample_count", "mean_delay_min"],
                labels={"late_pct": "Late observations (%)", "stop": "Stop"},
            ).update_layout(height=550, coloraxis_showscale=False)
        )
    with right:
        st.subheader("Geographic hotspots")
        map_data = eligible.dropna(subset=["stop_latitude", "stop_longitude"])
        map_data = map_data[
            map_data.stop_latitude.between(-90, 90)
            & map_data.stop_longitude.between(-180, 180)
        ]
        if map_data.empty:
            st.info("No coordinates available for the filtered stops.")
        else:
            map_on = st.toggle("Show street basemap (requires internet)", value=False)
            chart(
                px.scatter_map(
                    map_data,
                    lat="stop_latitude",
                    lon="stop_longitude",
                    size="sample_count",
                    color="late_pct",
                    hover_name="stop_name",
                    hover_data=["sample_count", "mean_delay_min"],
                    color_continuous_scale="Oranges",
                    range_color=[0, 100],
                    size_max=24,
                    zoom=9,
                    map_style="carto-positron" if map_on else "white-bg",
                    height=550,
                )
            )
            st.caption(
                "Dot size shows observation count; colour shows late share. The default coordinate view works without map tiles."
            )
    names = dict(
        zip(
            eligible.stop_id,
            eligible.stop_name + " · " + eligible.stop_id.astype(str),
        )
    )
    stop = st.selectbox(
        "Inspect a stop", eligible.stop_id.tolist(), format_func=names.get
    )
    selected = data[data.stop_id == stop]
    daily = weighted(selected, ["observation_date"])
    by_route = weighted(selected, ["route_id", "route_no"])
    left, right = st.columns(2)
    with left:
        st.subheader("Stop reliability over time")
        chart(
            px.line(
                daily,
                x="observation_date",
                y="on_time_pct",
                markers=True,
                range_y=[0, 100],
                hover_data=["sample_count"],
                labels={"observation_date": "Date", "on_time_pct": "On time (%)"},
            )
        )
    with right:
        st.subheader("Routes observed at this stop")
        chart(
            px.bar(
                by_route,
                x="route_no",
                y="on_time_pct",
                range_y=[0, 100],
                hover_data=["sample_count"],
                labels={"route_no": "Route", "on_time_pct": "On time (%)"},
            )
        )
    with st.expander("View and export stop report"):
        st.dataframe(
            eligible[
                [
                    "stop_id",
                    "stop_name",
                    "sample_count",
                    "late_pct",
                    "on_time_pct",
                    "mean_delay_min",
                ]
            ].round(2),
            hide_index=True,
        )
        st.download_button(
            "Export stop report",
            eligible.to_csv(index=False).encode("utf-8"),
            "stop-hotspots.csv",
            "text/csv",
        )
