from __future__ import annotations

import plotly.express as px
import streamlit as st

from bus_checker.dashboard import filters, queries, stats, ui


def render() -> None:
    ui.header(
        "Service delivery",
        "Did the timetable run? Scheduled trips (GTFS) against trips seen in the realtime feed, "
        "and trips the feed reported as cancelled.",
    )
    selection = filters.sidebar()
    if selection is None:
        return
    daily = queries.network_daily(selection)
    if daily.empty:
        ui.empty("No data for these filters.")
        return
    t = stats.totals(daily, ("trips_scheduled", "trips_tracked", "trips_cancelled", "trips_reported"))
    cols = st.columns(4)
    ui.metric(
        cols[0],
        "Scheduled trips",
        ui.fmt_int(t["trips_scheduled"]),
        help="From the GTFS timetable that applied on each date.",
    )
    ui.metric(
        cols[1],
        "Tracked trips",
        ui.fmt_int(t["trips_tracked"]),
        None if not t["trips_scheduled"] else f"{100 * t['trips_tracked'] / t['trips_scheduled']:.1f}% of scheduled",
        neutral=True,
    )
    ui.metric(
        cols[2],
        "Cancelled trips",
        ui.fmt_int(t["trips_cancelled"]),
        None if not t["trips_scheduled"] else f"{100 * t['trips_cancelled'] / t['trips_scheduled']:.2f}% of scheduled",
        neutral=True,
    )
    untracked = max((t["trips_scheduled"] or 0) - (t["trips_tracked"] or 0) - (t["trips_cancelled"] or 0), 0)
    ui.metric(
        cols[3],
        "Scheduled, not seen",
        ui.fmt_int(untracked),
        help="No realtime data at all. Often a tracking gap (or collection outage), not a missed trip.",
    )

    by_day = daily.groupby("service_date", as_index=False)[
        ["trips_scheduled", "trips_tracked", "trips_cancelled"]
    ].sum()
    by_day["not_seen"] = (by_day["trips_scheduled"] - by_day["trips_tracked"] - by_day["trips_cancelled"]).clip(lower=0)
    long = by_day.melt(
        id_vars="service_date",
        value_vars=["trips_tracked", "trips_cancelled", "not_seen"],
        var_name="status",
        value_name="trips",
    )
    long["status"] = long["status"].map(
        {"trips_tracked": "Tracked", "trips_cancelled": "Cancelled", "not_seen": "Not seen"}
    )
    fig = px.bar(
        long,
        x="service_date",
        y="trips",
        color="status",
        color_discrete_map={"Tracked": "#10B981", "Cancelled": "#DC2626", "Not seen": "#CBD5E1"},
        labels={"service_date": "", "trips": "Trips"},
    )
    ui.plot(fig, key="delivery_daily", xaxis="date")

    left, right = st.columns(2)
    with left:
        ui.section("By scheduled start hour", "Average per day in the period.")
        hourly = queries.service_delivery_hourly(selection)
        hourly = hourly[hourly["start_hour"] >= 0]
        if not hourly.empty:
            per_hour = hourly.groupby("start_hour", as_index=False)[
                ["trips_scheduled", "trips_tracked", "trips_cancelled"]
            ].sum()
            per_hour["coverage_pct"] = (
                100 * per_hour["trips_tracked"] / per_hour["trips_scheduled"].where(per_hour["trips_scheduled"] > 0)
            )
            fig = px.bar(
                per_hour,
                x="start_hour",
                y="coverage_pct",
                hover_data={"trips_scheduled": ":,", "trips_tracked": ":,", "trips_cancelled": ":,"},
                labels={"start_hour": "Scheduled start hour", "coverage_pct": "Tracked (% of scheduled)"},
            )
            fig.update_yaxes(range=[0, 105])
            ui.plot(fig, key="delivery_hourly", xaxis="hour")
    with right:
        ui.section("Most cancellations")
        totals = queries.route_totals(selection)
        routes = queries.routes()[["route_key", "route_label"]]
        worst = totals[totals["trips_cancelled"] > 0].merge(routes, on="route_key", how="left")
        if worst.empty:
            st.success("No cancellations reported in the period.", icon=":material/check_circle:")
        else:
            worst["route_label"] = worst["route_label"].fillna(worst["route_key"])
            worst["cancel_pct"] = (
                100 * worst["trips_cancelled"] / worst["trips_scheduled"].where(worst["trips_scheduled"] > 0)
            )
            top = worst.sort_values("trips_cancelled", ascending=False).head(15).iloc[::-1]
            fig = px.bar(
                top,
                x="trips_cancelled",
                y="route_label",
                orientation="h",
                hover_data={"cancel_pct": ":.1f", "trips_scheduled": ":,", "route_label": False},
                labels={"trips_cancelled": "Cancelled trips", "route_label": ""},
            )
            ui.plot(fig, key="delivery_worst", height=420)

    ui.section("Cancelled trips")
    cancelled = queries.cancelled_trips(selection)
    if cancelled.empty:
        ui.empty("No cancelled trips in the period.")
        return
    shown = cancelled.assign(first_seen_at=ui.to_local(cancelled["first_seen_at"]).dt.strftime("%d %b %H:%M"))
    st.dataframe(
        shown[["service_date", "route_short_name", "start_time", "trip_headsign", "first_seen_at"]],
        hide_index=True,
        column_config={
            "service_date": st.column_config.DateColumn("Date"),
            "route_short_name": "Route",
            "start_time": "Scheduled start",
            "trip_headsign": "Headsign",
            "first_seen_at": "First reported",
        },
    )
    ui.download(cancelled, "cancelled-trips.csv")
