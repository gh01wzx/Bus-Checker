from __future__ import annotations

import plotly.express as px
import streamlit as st

from bus_checker.dashboard import filters, queries, stats, ui

AUCKLAND = {"lat": -36.87, "lon": 174.77}


def render() -> None:
    ui.header(
        "Stop hotspots",
        "Stops where vehicles most often report running late. A hotspot shows where lateness "
        "is observed, not necessarily where it was caused.",
    )
    selection = filters.sidebar()
    if selection is None:
        return
    routes = queries.routes()
    labels = dict(zip(routes["route_key"], routes["route_label"], strict=True))
    controls = st.columns([3, 2, 2])
    route_options = [None, *sorted(routes["route_key"].tolist())]
    route_key = controls[0].selectbox(
        "Route", route_options, format_func=lambda k: "All routes" if k is None else labels.get(k, k), key="stops_route"
    )
    minimum = controls[1].number_input("Minimum stop events", min_value=1, value=30, step=10, key="stops_min")
    metric = controls[2].segmented_control(
        "Rank by", ["Late share", "Mean delay"], default="Late share", required=True, key="stops_metric"
    )
    stops = queries.stop_totals(selection, route_key)
    if stops.empty:
        ui.empty("No stop events for these filters.")
        return
    stops = stats.with_rates(stops)
    stops["stop_name"] = stops["stop_name"].fillna(stops["stop_key"])
    stops["label"] = stops["stop_name"] + " (" + stops["stop_key"] + ")"
    stops["mean_delay_min"] = stops["mean_delay_sec"] / 60
    eligible = stops[stops["events"] >= minimum]
    sort_column = "late_pct" if metric == "Late share" else "mean_delay_min"
    eligible = eligible.sort_values([sort_column, "events"], ascending=False)

    cols = st.columns(3)
    ui.metric(cols[0], "Stops observed", ui.fmt_int(len(stops)))
    ui.metric(cols[1], "Meeting the minimum", ui.fmt_int(len(eligible)))
    ui.metric(cols[2], "Stop events", ui.fmt_int(stops["events"].sum()))
    if eligible.empty:
        ui.empty("No stop meets the minimum. Lower it or widen the period.")
        return

    left, right = st.columns([2, 3])
    with left:
        ui.section("Top 20")
        top = eligible.head(20).iloc[::-1]
        fig = px.bar(
            top,
            x=sort_column,
            y="label",
            orientation="h",
            color=sort_column,
            color_continuous_scale=ui.SEQUENTIAL,
            hover_data={"events": ":,", "on_time_pct": ":.1f", "label": False},
            labels={"late_pct": "Late (%)", "mean_delay_min": "Mean delay (min)", "label": ""},
        )
        fig.update_layout(coloraxis_showscale=False)
        ui.plot(fig, key="stops_top", height=620)
    with right:
        ui.section("Map")
        mapped = eligible.dropna(subset=["latitude", "longitude"])
        fig = px.scatter_map(
            mapped,
            lat="latitude",
            lon="longitude",
            size="events",
            color=sort_column,
            color_continuous_scale=ui.SEQUENTIAL,
            size_max=22,
            zoom=10,
            center=AUCKLAND,
            hover_name="label",
            hover_data={
                "events": ":,",
                "late_pct": ":.1f",
                "mean_delay_min": ":.1f",
                "latitude": False,
                "longitude": False,
            },
            labels={"late_pct": "Late (%)", "mean_delay_min": "Mean delay (min)"},
            map_style="carto-positron",
            height=620,
        )
        ui.plot(fig, key="stops_map")

    ui.section("Stop detail")
    names = dict(zip(eligible["stop_key"], eligible["label"], strict=True))
    stop_key = st.selectbox(
        "Stop", eligible["stop_key"].tolist(), format_func=lambda k: names.get(k, k), key="stops_focus"
    )
    detail = queries.stop_detail(selection, stop_key)
    left, right = st.columns(2)
    with left:
        daily = stats.rollup(detail, ["service_date"])
        fig = px.line(
            daily,
            x="service_date",
            y="on_time_pct",
            markers=True,
            hover_data={"events": ":,"},
            labels={"service_date": "", "on_time_pct": "On time (%)"},
        )
        fig.update_yaxes(range=[0, 100])
        ui.plot(fig, key="stop_daily", xaxis="date")
    with right:
        by_route = stats.rollup(detail, ["route_key"])
        by_route["route"] = by_route["route_key"].map(labels).fillna(by_route["route_key"])
        fig = px.bar(
            by_route.sort_values("events"),
            x="late_pct",
            y="route",
            orientation="h",
            hover_data={"events": ":,", "on_time_pct": ":.1f"},
            labels={"late_pct": "Late (%)", "route": ""},
        )
        ui.plot(fig, key="stop_routes")
    with st.expander("All eligible stops"):
        table = eligible[["stop_key", "stop_name", "events", "routes", "on_time_pct", "late_pct", "mean_delay_min"]]
        st.dataframe(
            table,
            hide_index=True,
            column_config={
                "stop_key": "Stop code",
                "stop_name": "Name",
                "events": st.column_config.NumberColumn("Stop events", format="localized"),
                "routes": "Routes",
                "on_time_pct": st.column_config.ProgressColumn("On time", format="%.1f%%", min_value=0, max_value=100),
                "late_pct": st.column_config.NumberColumn("Late", format="%.1f%%"),
                "mean_delay_min": st.column_config.NumberColumn("Mean delay (min)", format="%.1f"),
            },
        )
        ui.download(table, "stop-hotspots.csv")
