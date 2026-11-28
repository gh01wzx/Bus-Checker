from __future__ import annotations

import pandas as pd
import plotly.express as px
import streamlit as st

from bus_checker.dashboard import filters, queries, stats, ui
from bus_checker.dashboard.model import Filters


def render() -> None:
    ui.header(
        "Route explorer",
        "Rank every route by reliability, then drill into one: trend, hours, stops, delay "
        "distribution, cancellations and current alerts.",
    )
    selection = filters.sidebar()
    if selection is None:
        return
    totals = queries.route_totals(selection)
    if totals.empty:
        ui.empty("No route data for these filters.")
        return
    routes = queries.routes()
    ranked = stats.with_rates(totals).merge(routes, on="route_key", how="left")
    ranked["route_label"] = ranked["route_label"].fillna(ranked["route_key"])
    ranked["cancel_pct"] = (
        100 * ranked["trips_cancelled"] / ranked["trips_scheduled"].where(ranked["trips_scheduled"] > 0)
    )
    ranked["coverage_pct"] = (
        100 * ranked["trips_tracked"] / ranked["trips_scheduled"].where(ranked["trips_scheduled"] > 0)
    )
    ranked["delay_std_sec"] = [
        stats.delay_std(n, s, q)
        for n, s, q in zip(ranked["events"], ranked["delay_sum_sec"], ranked["delay_sq_sum"], strict=True)
    ]

    top = st.columns([3, 2, 2])
    # Default threshold adapts to how much history exists, so the table is never empty by default.
    suggested = int(min(100, max(1, ranked["events"].median() // 2)))
    minimum = int(
        top[0].number_input(
            "Minimum observed stop events",
            min_value=1,
            value=suggested,
            step=10,
            key="routes_min",
            help="Routes with fewer observed stop events in the period are hidden from the ranking.",
        )
    )
    sort = top[1].selectbox(
        "Sort by",
        ["Least reliable", "Most reliable", "Most late", "Most observed", "Most cancelled"],
        key="routes_sort",
    )
    search = top[2].text_input("Find a route", key="routes_search", placeholder="Number or destination")
    eligible = ranked[ranked["events"] >= minimum]
    if search:
        needle = search.strip().lower()
        eligible = eligible[
            eligible["route_label"].str.lower().str.contains(needle, regex=False)
            | eligible["route_key"].str.lower().str.contains(needle, regex=False)
        ]
    column, ascending = {
        "Least reliable": ("on_time_pct", True),
        "Most reliable": ("on_time_pct", False),
        "Most late": ("late_pct", False),
        "Most observed": ("events", False),
        "Most cancelled": ("cancel_pct", False),
    }[sort]
    eligible = eligible.sort_values(column, ascending=ascending, na_position="last")
    st.caption(f"{len(eligible)} of {len(ranked)} routes meet the minimum.")
    table = eligible[
        [
            "route_key",
            "route_label",
            "mode",
            "operator_name",
            "events",
            "on_time_pct",
            "late_pct",
            "mean_delay_sec",
            "delay_std_sec",
            "trips_tracked",
            "coverage_pct",
            "cancel_pct",
        ]
    ]
    picked = st.dataframe(
        table,
        hide_index=True,
        on_select="rerun",
        selection_mode="single-row",
        key="routes_table",
        height=360,
        column_config={
            "route_key": st.column_config.TextColumn("Route", width="small"),
            "route_label": "Description",
            "mode": "Mode",
            "operator_name": "Operator",
            "events": st.column_config.NumberColumn("Stop events", format="localized"),
            "on_time_pct": st.column_config.ProgressColumn("On time", format="%.1f%%", min_value=0, max_value=100),
            "late_pct": st.column_config.NumberColumn("Late", format="%.1f%%"),
            "mean_delay_sec": st.column_config.NumberColumn("Mean delay (s)", format="%.0f"),
            "delay_std_sec": st.column_config.NumberColumn(
                "Delay spread (s)", format="%.0f", help="Standard deviation: how unpredictable the route is."
            ),
            "trips_tracked": st.column_config.NumberColumn("Trips", format="localized"),
            "coverage_pct": st.column_config.NumberColumn(
                "Tracked", format="%.0f%%", help="Tracked trips as a share of scheduled trips."
            ),
            "cancel_pct": st.column_config.NumberColumn("Cancelled", format="%.1f%%"),
        },
    )
    ui.download(table, "route-reliability.csv")

    options = eligible["route_key"].tolist() or ranked["route_key"].tolist()
    labels = dict(zip(ranked["route_key"], ranked["route_label"], strict=True))
    chosen_rows = picked.selection.rows if picked and picked.selection else []
    default = (
        table.iloc[chosen_rows[0]]["route_key"] if chosen_rows else st.session_state.get("routes_focus", options[0])
    )
    if default not in options:
        default = options[0]
    route_key = st.selectbox(
        "Route details",
        options,
        index=options.index(default),
        format_func=lambda k: labels.get(k, k),
        key="routes_focus_box",
    )
    st.session_state["routes_focus"] = route_key
    detail(selection, route_key, ranked.set_index("route_key").loc[route_key])


def detail(selection: Filters, route_key: str, summary: pd.Series) -> None:
    st.divider()
    st.subheader(summary.get("route_label") or route_key)
    st.caption(f"{summary.get('mode') or 'Unknown mode'} · {summary.get('operator_name') or 'Unknown operator'}")
    histogram = queries.route_histogram(selection, [route_key])
    quantiles = (
        stats.histogram_quantiles(histogram["delay_bucket_min"], histogram["events"])
        if not histogram.empty
        else {0.5: None, 0.9: None}
    )
    cols = st.columns(5)
    ui.metric(cols[0], "On time", ui.fmt_pct(summary["on_time_pct"]))
    ui.metric(cols[1], "Median delay", ui.fmt_minutes(quantiles[0.5]))
    ui.metric(cols[2], "P90 delay", ui.fmt_minutes(quantiles[0.9]))
    ui.metric(
        cols[3],
        "Trips tracked",
        ui.fmt_int(summary["trips_tracked"]),
        None if pd.isna(summary["coverage_pct"]) else f"{summary['coverage_pct']:.0f}% of scheduled",
        neutral=True,
    )
    ui.metric(cols[4], "Cancelled trips", ui.fmt_int(summary["trips_cancelled"]))

    alerts = queries.route_alerts(route_key)
    active = alerts[alerts["is_active"]] if not alerts.empty else alerts
    for row in active.head(3).itertuples(index=False):
        st.warning(f"{row.header_text}", icon=":material/campaign:")

    trend, hours, stops, distribution, cancellations = st.tabs(
        ["Trend", "Hours", "Stops", "Delay distribution", "Cancellations"]
    )
    daily = queries.route_daily(selection, [route_key])
    with trend:
        by_day = stats.rollup(daily, ["service_date"], ("trips_tracked", "trips_cancelled", "trips_scheduled"))
        fig = px.line(
            by_day,
            x="service_date",
            y="on_time_pct",
            markers=True,
            hover_data={"events": ":,", "late_pct": ":.1f", "trips_tracked": True},
            labels={"service_date": "", "on_time_pct": "On time (%)"},
        )
        fig.update_yaxes(range=[0, 100])
        ui.plot(fig, key="route_trend", xaxis="date")
        p90 = daily.groupby("service_date", as_index=False)["delay_p90_sec"].max()
        fig = px.bar(
            p90.assign(p90_min=p90["delay_p90_sec"] / 60),
            x="service_date",
            y="p90_min",
            labels={"service_date": "", "p90_min": "Worst-direction P90 delay (min)"},
        )
        ui.plot(fig, key="route_p90", height=260)
    with hours:
        hourly = queries.route_hourly(selection, [route_key])
        if hourly.empty:
            ui.empty("No hourly data.")
        else:
            profile = stats.rollup(hourly, ["direction_id", "hour"])
            profile["direction"] = profile["direction_id"].map(ui.DIRECTION_LABELS)
            fig = px.bar(
                profile,
                x="hour",
                y="on_time_pct",
                color="direction",
                barmode="group",
                hover_data={"events": ":,", "mean_delay_sec": ":.0f"},
                labels={"hour": "Hour of stop event", "on_time_pct": "On time (%)"},
            )
            fig.update_yaxes(range=[0, 100])
            ui.plot(fig, key="route_hours", xaxis="hour")
    with stops:
        profile = queries.route_stop_profile(selection, route_key)
        if profile.empty:
            ui.empty("This route has no stop pattern in the current GTFS.")
        else:
            profile = stats.with_rates(profile)
            profile["mean_delay_min"] = profile["mean_delay_sec"] / 60
            profile["direction"] = profile["direction_id"].map(ui.DIRECTION_LABELS)
            st.caption("Average reported delay at each stop of the main pattern. Delay usually builds along a route.")
            fig = px.line(
                profile,
                x="stop_order",
                y="mean_delay_min",
                color="direction",
                markers=True,
                hover_name="stop_name",
                hover_data={"events": ":,", "on_time_pct": ":.1f", "stop_order": False},
                labels={"stop_order": "Stop number along the route", "mean_delay_min": "Mean delay (min)"},
            )
            fig.add_hline(y=0, line_dash="dot", line_color="#94A3B8")
            ui.plot(fig, key="route_stops")
    with distribution:
        if histogram.empty:
            ui.empty("No delay observations.")
        else:
            share = histogram.groupby("delay_bucket_min", as_index=False)["events"].sum()
            share["share"] = 100 * share["events"] / share["events"].sum()
            share["status"] = pd.cut(
                share["delay_bucket_min"] * 60, [-(10**9), -61, 299, 10**9], labels=["Early", "On time", "Late"]
            ).astype(str)
            fig = px.bar(
                share,
                x="delay_bucket_min",
                y="share",
                color="status",
                color_discrete_map=ui.PUNCTUALITY_COLORS,
                labels={"delay_bucket_min": "Delay (minutes, edge bars include the tails)", "share": "Stop events (%)"},
            )
            ui.plot(fig, key="route_hist")
    with cancellations:
        cancelled = queries.cancelled_trips(selection, route_key)
        if cancelled.empty:
            st.success("No cancelled trips reported for this route in the period.", icon=":material/check_circle:")
        else:
            st.dataframe(
                cancelled.assign(first_seen_at=ui.to_local(cancelled["first_seen_at"]).dt.strftime("%d %b %H:%M"))[
                    ["service_date", "start_time", "direction_id", "trip_headsign", "first_seen_at"]
                ],
                hide_index=True,
                column_config={
                    "service_date": st.column_config.DateColumn("Date"),
                    "start_time": "Scheduled start",
                    "direction_id": "Direction",
                    "trip_headsign": "Headsign",
                    "first_seen_at": "First reported",
                },
            )
