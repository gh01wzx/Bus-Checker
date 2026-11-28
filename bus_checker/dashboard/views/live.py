from __future__ import annotations

import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import streamlit as st

from bus_checker.dashboard import queries, ui
from bus_checker.dashboard.data import DataUnavailable

AUCKLAND = {"lat": -36.87, "lon": 174.77}
STALE_AFTER_MIN = 20


def render() -> None:
    ui.header(
        "Live network",
        "Latest vehicle positions from the most recent collection, coloured by the delay each "
        "vehicle last reported at a stop. Refreshes every minute.",
    )
    _live()


@st.fragment(run_every="60s")
def _live() -> None:
    # The fragment re-runs on its own, outside the page-level guard, so handle outages here.
    try:
        vehicles = queries.live_vehicles()
    except DataUnavailable as error:
        st.warning(f"{error} Retrying every minute.", icon=":material/database:")
        return
    if vehicles.empty:
        ui.empty("No vehicle positions have been collected yet.")
        return
    as_of = vehicles["as_of"].max()
    age_min = (pd.Timestamp.now(tz="UTC") - pd.Timestamp(as_of)).total_seconds() / 60
    if age_min > STALE_AFTER_MIN:
        st.warning(
            f"These positions are {ui.fmt_age(as_of)}: collection may be paused. Check Pipeline health.",
            icon=":material/schedule:",
        )

    vehicles["status"] = vehicles["punctuality"].map(ui.PUNCTUALITY_LABELS).fillna("Unknown")
    vehicles.loc[~vehicles["in_service"], "status"] = "Not in service"
    vehicles["route"] = vehicles["route_short_name"].fillna("—")
    vehicles["delay_min"] = (vehicles["delay_sec"] / 60).round(1)
    vehicles["occupancy"] = vehicles["occupancy_status"].map(ui.OCCUPANCY_LABELS)
    vehicles["label"] = vehicles["vehicle_label"].fillna(vehicles["vehicle_id"])

    controls = st.columns([2, 2, 3])
    modes = sorted(m for m in vehicles["mode"].dropna().unique() if m != "Not in service")
    picked_modes = controls[0].pills("Mode", modes, selection_mode="multi", default=modes, key="live_modes")
    show_idle = controls[1].toggle("Show vehicles not in service", value=False, key="live_idle")
    route_options = sorted(vehicles.loc[vehicles["in_service"], "route"].dropna().unique())
    picked_routes = controls[2].multiselect("Routes", route_options, key="live_routes", placeholder="All routes")

    shown = vehicles[vehicles["mode"].isin(picked_modes or modes) | (show_idle & ~vehicles["in_service"])]
    if not show_idle:
        shown = shown[shown["in_service"]]
    if picked_routes:
        shown = shown[shown["route"].isin(picked_routes)]

    in_service = shown[shown["in_service"]]
    with_delay = in_service.dropna(subset=["delay_sec"])
    cols = st.columns(4)
    ui.metric(cols[0], "Vehicles in service", ui.fmt_int(len(in_service)))
    ui.metric(
        cols[1],
        "Running late",
        ui.fmt_pct(100 * (with_delay["punctuality"] == "late").mean() if len(with_delay) else None),
    )
    ui.metric(cols[2], "Median delay", ui.fmt_minutes(with_delay["delay_sec"].median() if len(with_delay) else None))
    ui.metric(cols[3], "Positions as of", ui.local_time(as_of, "%H:%M:%S"), help=ui.fmt_age(as_of))

    fig = px.scatter_map(
        shown,
        lat="latitude",
        lon="longitude",
        color="status",
        color_discrete_map={**ui.PUNCTUALITY_COLORS, "Not in service": ui.MODE_COLORS["Not in service"]},
        category_orders={"status": ["Late", "On time", "Early", "Unknown", "Not in service"]},
        hover_name="label",
        hover_data={
            "route": True,
            "mode": True,
            "delay_min": ":.1f",
            "occupancy": True,
            "speed_kmh": ":.0f",
            "last_stop_name": True,
            "latitude": False,
            "longitude": False,
            "status": False,
        },
        labels={"delay_min": "Delay (min)", "speed_kmh": "Speed (km/h)", "last_stop_name": "Last stop"},
        zoom=10,
        center=AUCKLAND,
        map_style="carto-positron",
        height=620,
    )
    fig.update_traces(marker={"size": 9, "opacity": 0.85})
    if len(picked_routes) == 1:
        route_key = shown.loc[shown["route"] == picked_routes[0], "route_key"].dropna()
        if not route_key.empty:
            shape = queries.route_shape(route_key.iloc[0])
            for direction, line in shape.groupby("direction_id"):
                fig.add_trace(
                    go.Scattermap(
                        lat=line["latitude"],
                        lon=line["longitude"],
                        mode="lines",
                        line={"width": 3, "color": "#0F172A" if direction == 0 else "#64748B"},
                        name=f"Route {picked_routes[0]} · {ui.DIRECTION_LABELS.get(int(direction), direction)}",
                        hoverinfo="skip",
                    )
                )
    ui.plot(fig, key="live_map")
    st.caption("Basemap © OpenStreetMap contributors © CARTO. Vehicles outside the Auckland region are hidden.")

    ui.section("Most delayed right now")
    worst = with_delay.sort_values("delay_sec", ascending=False).head(25)
    if worst.empty:
        ui.empty("No vehicle has reported a stop delay in this window.")
        return
    st.dataframe(
        worst[["route", "label", "delay_min", "last_stop_name", "occupancy", "speed_kmh", "position_ts"]].assign(
            position_ts=ui.to_local(worst["position_ts"]).dt.strftime("%H:%M:%S")
        ),
        hide_index=True,
        column_config={
            "route": "Route",
            "label": "Vehicle",
            "delay_min": st.column_config.NumberColumn("Delay (min)", format="%.1f"),
            "last_stop_name": "Last stop",
            "occupancy": "Occupancy",
            "speed_kmh": st.column_config.NumberColumn("Speed (km/h)", format="%.0f"),
            "position_ts": "Position at",
        },
    )
