from __future__ import annotations

import pandas as pd
import plotly.express as px
import streamlit as st

from bus_checker.dashboard import filters, queries, stats, ui

MAX_ROUTES = 6


def render() -> None:
    ui.header(
        "Compare routes",
        "Put up to six routes side by side over the same period. Percentiles come from "
        "one-minute delay buckets of individual stop events.",
    )
    selection = filters.sidebar()
    if selection is None:
        return
    totals = queries.route_totals(selection)
    if totals.empty:
        ui.empty("No route data for these filters.")
        return
    routes = queries.routes()
    labels = dict(zip(routes["route_key"], routes["route_label"], strict=True))
    busiest = totals.sort_values("events", ascending=False)["route_key"].tolist()
    stored = [k for k in st.session_state.get("compare_routes_saved", busiest[:3]) if k in busiest]
    picked = st.multiselect(
        "Routes",
        busiest,
        default=stored or busiest[:3],
        max_selections=MAX_ROUTES,
        format_func=lambda k: labels.get(k, k),
        key="compare_routes",
    )
    st.session_state["compare_routes_saved"] = picked
    if not picked:
        ui.empty("Pick at least one route.")
        return

    chosen = stats.with_rates(totals[totals["route_key"].isin(picked)])
    histogram = queries.route_histogram(selection, picked)
    rows = []
    for key in picked:
        part = histogram[histogram["route_key"] == key]
        q = stats.histogram_quantiles(part["delay_bucket_min"], part["events"]) if not part.empty else {}
        row = chosen[chosen["route_key"] == key]
        if row.empty:
            continue
        r = row.iloc[0]
        rows.append(
            {
                "route": labels.get(key, key),
                "events": r["events"],
                "on_time_pct": r["on_time_pct"],
                "late_pct": r["late_pct"],
                "mean_min": r["mean_delay_sec"] / 60 if pd.notna(r["mean_delay_sec"]) else None,
                "p50_min": (q.get(0.5) or float("nan")) / 60,
                "p90_min": (q.get(0.9) or float("nan")) / 60,
                "p95_min": (q.get(0.95) or float("nan")) / 60,
                "cancelled": r["trips_cancelled"],
            }
        )
    table = pd.DataFrame(rows)
    st.dataframe(
        table,
        hide_index=True,
        column_config={
            "route": "Route",
            "events": st.column_config.NumberColumn("Stop events", format="localized"),
            "on_time_pct": st.column_config.ProgressColumn("On time", format="%.1f%%", min_value=0, max_value=100),
            "late_pct": st.column_config.NumberColumn("Late", format="%.1f%%"),
            "mean_min": st.column_config.NumberColumn("Mean (min)", format="%.1f"),
            "p50_min": st.column_config.NumberColumn("Median (min)", format="%.1f"),
            "p90_min": st.column_config.NumberColumn("P90 (min)", format="%.1f"),
            "p95_min": st.column_config.NumberColumn("P95 (min)", format="%.1f"),
            "cancelled": st.column_config.NumberColumn("Cancelled trips", format="localized"),
        },
    )
    ui.download(table, "route-comparison.csv")

    left, right = st.columns(2)
    with left:
        ui.section("Punctuality mix")
        mix = chosen.assign(route=chosen["route_key"].map(labels)).melt(
            id_vars="route", value_vars=["early_pct", "on_time_pct", "late_pct"], var_name="status", value_name="share"
        )
        mix["status"] = mix["status"].map({"early_pct": "Early", "on_time_pct": "On time", "late_pct": "Late"})
        fig = px.bar(
            mix,
            x="share",
            y="route",
            color="status",
            orientation="h",
            color_discrete_map=ui.PUNCTUALITY_COLORS,
            category_orders={"status": ["Early", "On time", "Late"]},
            labels={"share": "Stop events (%)", "route": ""},
        )
        fig.update_layout(barmode="stack", xaxis_range=[0, 100])
        ui.plot(fig, key="compare_mix")
    with right:
        ui.section("Typical delay and the long tail")
        tails = table.melt(
            id_vars="route", value_vars=["p50_min", "p90_min", "p95_min"], var_name="measure", value_name="minutes"
        )
        tails["measure"] = tails["measure"].map({"p50_min": "Median", "p90_min": "P90", "p95_min": "P95"})
        fig = px.bar(
            tails,
            x="route",
            y="minutes",
            color="measure",
            barmode="group",
            labels={"minutes": "Delay (min)", "route": ""},
        )
        ui.plot(fig, key="compare_tails")

    ui.section("Delay distribution")
    dist = histogram.assign(route=histogram["route_key"].map(labels))
    dist["share"] = 100 * dist["events"] / dist.groupby("route_key")["events"].transform("sum")
    fig = px.line(
        dist.sort_values("delay_bucket_min"),
        x="delay_bucket_min",
        y="share",
        color="route",
        markers=True,
        labels={"delay_bucket_min": "Delay (min); edges include the tails", "share": "Stop events (%)"},
    )
    fig.add_vrect(x0=-1, x1=5, fillcolor="#10B981", opacity=0.08, line_width=0, annotation_text="on time")
    ui.plot(fig, key="compare_dist")

    left, right = st.columns(2)
    with left:
        ui.section("By hour of day")
        hourly = queries.route_hourly(selection, picked)
        if not hourly.empty:
            profile = stats.rollup(hourly, ["route_key", "hour"])
            profile["route"] = profile["route_key"].map(labels)
            fig = px.line(
                profile,
                x="hour",
                y="on_time_pct",
                color="route",
                markers=True,
                labels={"hour": "Hour", "on_time_pct": "On time (%)"},
            )
            fig.update_yaxes(range=[0, 100])
            ui.plot(fig, key="compare_hourly", xaxis="hour")
    with right:
        ui.section("By day")
        daily = stats.rollup(queries.route_daily(selection, picked), ["route_key", "service_date"])
        daily["route"] = daily["route_key"].map(labels)
        fig = px.line(
            daily,
            x="service_date",
            y="on_time_pct",
            color="route",
            markers=True,
            labels={"service_date": "", "on_time_pct": "On time (%)"},
        )
        fig.update_yaxes(range=[0, 100])
        ui.plot(fig, key="compare_daily", xaxis="date")
