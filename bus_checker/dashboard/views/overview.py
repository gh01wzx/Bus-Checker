from __future__ import annotations

import pandas as pd
import plotly.express as px
import streamlit as st

from bus_checker.dashboard import filters, queries, stats, ui
from bus_checker.dashboard.navigation import link

TRIP_COLUMNS = ("trips_tracked", "trips_scheduled", "trips_cancelled", "trips_reported")


def render() -> None:
    ui.header(
        "Network pulse",
        "How reliably Auckland's public transport ran, measured from realtime stop events. "
        "On time means between 1 minute early and 5 minutes late.",
    )
    selection = filters.sidebar()
    if selection is None:
        return
    current = queries.network_daily(selection)
    if current.empty or current["events"].sum() == 0:
        ui.empty("No observed stop events match these filters.")
        return
    previous = queries.network_daily(selection.previous())
    now = stats.totals(current, TRIP_COLUMNS)
    before = stats.totals(previous, TRIP_COLUMNS) if not previous.empty else {}
    q_now = stats.histogram_quantiles(*_hist(queries.network_histogram(selection)))
    q_before = stats.histogram_quantiles(*_hist(queries.network_histogram(selection.previous())))
    daily = stats.rollup(current, ["service_date"], TRIP_COLUMNS).sort_values("service_date")
    spark = daily["on_time_pct"].round(1).tolist()

    cancel_rate = stats.ratio(now["trips_cancelled"] or 0, now["trips_scheduled"] or 0)
    cancel_before = stats.ratio(before.get("trips_cancelled") or 0, before.get("trips_scheduled") or 0)
    cols = ui.grid(6)
    ui.metric(
        cols[0],
        "On time",
        ui.fmt_pct(now["on_time_pct"]),
        ui.delta_pp(stats.change(now["on_time_pct"], before.get("on_time_pct"))),
        chart=spark,
        help="Share of observed stop events between −60 s and +300 s.",
    )
    ui.metric(
        cols[1],
        "Late",
        ui.fmt_pct(now["late_pct"]),
        ui.delta_pp(stats.change(now["late_pct"], before.get("late_pct"))),
        inverse=True,
        chart=daily["late_pct"].round(1).tolist(),
    )
    ui.metric(
        cols[2],
        "Mean delay",
        ui.fmt_minutes(now["mean_delay_sec"]),
        ui.delta_minutes(stats.change(now["mean_delay_sec"], before.get("mean_delay_sec"))),
        inverse=True,
        chart=(daily["mean_delay_sec"] / 60).round(2).tolist(),
    )
    ui.metric(
        cols[3],
        "P90 delay",
        ui.fmt_minutes(q_now[0.9]),
        ui.delta_minutes(stats.change(q_now[0.9], q_before[0.9])),
        inverse=True,
        help="90% of stop events were no later than this (from one-minute buckets).",
    )
    ui.metric(
        cols[4],
        "Trips tracked",
        ui.fmt_int(now["trips_tracked"]),
        help="Trips with at least one observed stop event.",
        chart=daily["trips_tracked"].tolist(),
    )
    ui.metric(
        cols[5],
        "Cancelled",
        ui.fmt_int(now["trips_cancelled"]),
        None if cancel_rate is None else f"{100 * cancel_rate:.1f}% of scheduled",
        neutral=True,
        help="Trips the feed reported as cancelled with no observed stops. "
        + ("" if cancel_before is None else f"Previous period: {100 * cancel_before:.1f}%."),
    )
    coverage = stats.ratio(now["trips_tracked"] or 0, now["trips_scheduled"] or 0)
    st.caption(
        f"{ui.fmt_int(now['events'])} observed stop events over {selection.days} day(s). "
        + (f"Realtime tracking covered {100 * coverage:.0f}% of scheduled trips. " if coverage else "")
        + f"Deltas compare with the previous {selection.days} day(s)."
    )

    left, right = st.columns(2)
    with left:
        ui.section("Punctuality mix by day")
        mix = daily.melt(
            id_vars="service_date",
            value_vars=["early_pct", "on_time_pct", "late_pct"],
            var_name="status",
            value_name="share",
        )
        mix["status"] = mix["status"].map({"early_pct": "Early", "on_time_pct": "On time", "late_pct": "Late"})
        fig = px.bar(
            mix,
            x="service_date",
            y="share",
            color="status",
            color_discrete_map=ui.PUNCTUALITY_COLORS,
            category_orders={"status": ["Early", "On time", "Late"]},
            labels={"service_date": "", "share": "Stop events (%)"},
        )
        fig.update_layout(barmode="stack", yaxis_range=[0, 100])
        ui.plot(fig, key="overview_mix", xaxis="date")
    with right:
        ui.section("Delay by day")
        delay = current.assign(p90_min=current["delay_p90_sec"] / 60)
        fig = px.line(
            delay,
            x="service_date",
            y="p90_min",
            color="mode",
            markers=True,
            color_discrete_map=ui.MODE_COLORS,
            labels={"service_date": "", "p90_min": "P90 delay (min)", "mode": "Mode"},
        )
        fig.add_scatter(
            x=daily["service_date"],
            y=daily["mean_delay_sec"] / 60,
            mode="lines",
            name="Mean (selected modes)",
            line={"dash": "dot", "color": "#334155"},
        )
        ui.plot(fig, key="overview_delay", xaxis="date")

    ui.section("Reliability through the day", "On-time share by hour of the stop event (Auckland time).")
    hourly = queries.network_hourly(selection)
    if not hourly.empty:
        profile = stats.rollup(hourly, ["day_type", "hour"])
        fig = px.line(
            profile,
            x="hour",
            y="on_time_pct",
            color="day_type",
            markers=True,
            hover_data={"events": ":,"},
            labels={"hour": "Hour", "on_time_pct": "On time (%)", "day_type": "Day"},
        )
        fig.update_xaxes(dtick=2)
        ui.plot(fig, key="overview_hourly", xaxis="hour")

    if current["mode"].nunique() > 1:
        ui.section("By mode")
        by_mode = stats.rollup(current, ["mode"], TRIP_COLUMNS)
        st.dataframe(
            by_mode[
                ["mode", "events", "on_time_pct", "late_pct", "mean_delay_sec", "trips_tracked", "trips_cancelled"]
            ],
            hide_index=True,
            column_config={
                "mode": "Mode",
                "events": st.column_config.NumberColumn("Stop events", format="localized"),
                "on_time_pct": st.column_config.ProgressColumn("On time", format="%.1f%%", min_value=0, max_value=100),
                "late_pct": st.column_config.NumberColumn("Late", format="%.1f%%"),
                "mean_delay_sec": st.column_config.NumberColumn("Mean delay (s)", format="%.0f"),
                "trips_tracked": st.column_config.NumberColumn("Trips tracked", format="localized"),
                "trips_cancelled": st.column_config.NumberColumn("Cancelled", format="localized"),
            },
        )

    _route_extremes(selection)

    alerts = queries.service_alerts()
    active = alerts[alerts["is_active"]] if not alerts.empty else alerts
    if not active.empty:
        severe = int((active["severity"] == "SEVERE").sum())
        st.warning(
            f"{len(active)} service alerts are active now ({severe} severe).",
            icon=":material/campaign:",
        )
        link("alerts", "Open service alerts", ":material/arrow_forward:")


def _hist(frame: pd.DataFrame) -> tuple[pd.Series, pd.Series]:
    if frame.empty:
        return pd.Series(dtype=float), pd.Series(dtype=float)
    return frame["delay_bucket_min"], frame["events"]


def _route_extremes(selection) -> None:
    totals = queries.route_totals(selection)
    if totals.empty:
        return
    routes = queries.routes()[["route_key", "route_label", "mode"]]
    ranked = stats.with_rates(totals).merge(routes, on="route_key", how="left")
    ranked = ranked[ranked["events"] >= max(50, selection.days * 5)]
    if ranked.empty:
        return
    ranked["route_label"] = ranked["route_label"].fillna(ranked["route_key"])
    left, right = st.columns(2)
    for column, title, ascending in ((left, "Least reliable routes", True), (right, "Most reliable routes", False)):
        with column:
            ui.section(title, "Routes with enough observations in the period.")
            top = ranked.sort_values(["on_time_pct", "events"], ascending=[ascending, False]).head(10)
            fig = px.bar(
                top.iloc[::-1],
                x="on_time_pct",
                y="route_label",
                orientation="h",
                color="on_time_pct",
                color_continuous_scale=ui.RELIABILITY_SCALE,
                range_color=[40, 100],
                hover_data={"events": ":,", "late_pct": ":.1f", "route_label": False},
                labels={"on_time_pct": "On time (%)", "route_label": ""},
            )
            fig.update_layout(coloraxis_showscale=False, xaxis_range=[0, 100])
            ui.plot(fig, key=f"overview_{title}", height=380)
    link("routes", "Explore every route", ":material/arrow_forward:")
