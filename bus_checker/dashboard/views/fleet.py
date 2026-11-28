from __future__ import annotations

import plotly.express as px
import streamlit as st

from bus_checker.dashboard import filters, queries, ui

OCCUPANCY_COLUMNS = {
    "occupancy_empty": "Empty",
    "occupancy_many_seats": "Many seats",
    "occupancy_few_seats": "Few seats",
    "occupancy_standing": "Standing only",
    "occupancy_full": "Full",
}
CROWDED = ("STANDING_ROOM_ONLY", "CRUSHED_STANDING_ROOM_ONLY", "FULL", "NOT_ACCEPTING_PASSENGERS")


def render() -> None:
    ui.header(
        "Fleet & crowding",
        "How many vehicles were on the road, how fast they moved and how full they were. "
        "Occupancy comes from vehicles that report it (mostly buses) and counts position samples.",
    )
    selection = filters.sidebar(modes=False)
    if selection is None:
        return
    fleet = queries.fleet_hourly(selection)
    if fleet.empty:
        ui.empty("No vehicle positions for these filters.")
        return
    in_service = fleet[fleet["mode"] != "Not in service"]
    peak = in_service.groupby(["service_date", "hour"])["vehicles"].sum()
    cols = st.columns(4)
    ui.metric(
        cols[0],
        "Peak vehicles in service",
        ui.fmt_int(peak.max() if not peak.empty else None),
        help="Highest number of distinct vehicles on a trip within one hour.",
    )
    ui.metric(
        cols[1], "Typical daily peak", ui.fmt_int(peak.groupby(level=0).max().median() if not peak.empty else None)
    )
    reports = in_service["occupancy_reports"].sum()
    crowded = in_service["occupancy_standing"].sum() + in_service["occupancy_full"].sum()
    ui.metric(
        cols[2],
        "Crowded samples",
        ui.fmt_pct(100 * crowded / reports if reports else None),
        help="Share of occupancy reports at standing-only or full.",
    )
    speed = (in_service["avg_moving_speed_kmh"] * in_service["position_reports"]).sum() / in_service[
        "position_reports"
    ].sum()
    ui.metric(cols[3], "Average moving speed", "—" if speed != speed else f"{speed:.0f} km/h")

    ui.section("Vehicles in service through the day", "Average distinct vehicles per hour across the selected days.")
    days = max(in_service["service_date"].nunique(), 1)
    profile = in_service.groupby(["hour", "mode"], as_index=False)["vehicles"].sum()
    profile["vehicles"] = profile["vehicles"] / days
    fig = px.area(
        profile,
        x="hour",
        y="vehicles",
        color="mode",
        color_discrete_map=ui.MODE_COLORS,
        labels={"hour": "Hour", "vehicles": "Vehicles (average)", "mode": ""},
    )
    ui.plot(fig, key="fleet_profile", xaxis="hour")

    left, right = st.columns(2)
    with left:
        ui.section("Occupancy through the day")
        occupancy = in_service.groupby("hour", as_index=False)[list(OCCUPANCY_COLUMNS)].sum()
        long = occupancy.melt(id_vars="hour", var_name="level", value_name="samples")
        long["level"] = long["level"].map(OCCUPANCY_COLUMNS)
        long["share"] = 100 * long["samples"] / long.groupby("hour")["samples"].transform("sum").where(lambda s: s > 0)
        fig = px.bar(
            long,
            x="hour",
            y="share",
            color="level",
            color_discrete_map=ui.OCCUPANCY_COLORS,
            category_orders={"level": list(OCCUPANCY_COLUMNS.values())},
            labels={"hour": "Hour", "share": "Occupancy reports (%)", "level": ""},
        )
        fig.update_layout(barmode="stack", yaxis_range=[0, 100])
        ui.plot(fig, key="fleet_occupancy", xaxis="hour")
    with right:
        ui.section("Moving speed through the day")
        weighted = in_service.assign(w=in_service["avg_moving_speed_kmh"] * in_service["position_reports"])
        speed_by_hour = weighted.groupby(["hour", "mode"], as_index=False)[["w", "position_reports"]].sum()
        speed_by_hour["speed"] = speed_by_hour["w"] / speed_by_hour["position_reports"]
        fig = px.line(
            speed_by_hour,
            x="hour",
            y="speed",
            color="mode",
            markers=True,
            color_discrete_map=ui.MODE_COLORS,
            labels={"hour": "Hour", "speed": "Average moving speed (km/h)", "mode": ""},
        )
        ui.plot(fig, key="fleet_speed", xaxis="hour")

    ui.section("Most crowded routes", "Share of in-service occupancy reports at standing-only or full.")
    occupancy_routes = queries.route_occupancy(selection)
    if occupancy_routes.empty:
        ui.empty("No occupancy reports in the period.")
        return
    totals = occupancy_routes.groupby("route_key", as_index=False)["reports"].sum()
    crowded_routes = (
        occupancy_routes[occupancy_routes["occupancy_status"].isin(CROWDED)]
        .groupby("route_key", as_index=False)["reports"]
        .sum()
        .rename(columns={"reports": "crowded"})
    )
    merged = totals.merge(crowded_routes, on="route_key", how="left").fillna({"crowded": 0})
    merged["crowded_pct"] = 100 * merged["crowded"] / merged["reports"]
    merged = merged[merged["reports"] >= 50].merge(
        queries.routes()[["route_key", "route_label"]], on="route_key", how="left"
    )
    merged["route_label"] = merged["route_label"].fillna(merged["route_key"])
    top = merged.sort_values("crowded_pct", ascending=False).head(15).iloc[::-1]
    if top.empty:
        ui.empty("Not enough occupancy reports per route yet.")
        return
    fig = px.bar(
        top,
        x="crowded_pct",
        y="route_label",
        orientation="h",
        hover_data={"reports": ":,", "route_label": False},
        labels={"crowded_pct": "Crowded reports (%)", "route_label": ""},
    )
    ui.plot(fig, key="fleet_crowded", height=440)
