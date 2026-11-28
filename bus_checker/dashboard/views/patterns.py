from __future__ import annotations

import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import streamlit as st

from bus_checker.dashboard import filters, queries, stats, ui

WEEKDAYS = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]
PEAKS = {
    "AM peak (7–9)": range(7, 10),
    "Inter-peak (10–15)": range(10, 16),
    "PM peak (16–18)": range(16, 19),
    "Evening (19–23)": range(19, 24),
    "Night & early (0–6)": range(7),
}


def render() -> None:
    ui.header(
        "Time patterns",
        "When does the network run late? Weekday-by-hour heatmap, peak periods and day types.",
    )
    selection = filters.sidebar(default_days=30)
    if selection is None:
        return
    hourly = queries.network_hourly(selection)
    if hourly.empty:
        ui.empty("No hourly data for these filters.")
        return
    minimum = filters.minimum_events("Minimum stop events per heatmap cell", default=50, key="pattern_min")
    hourly["weekday"] = pd.to_datetime(hourly["service_date"]).dt.dayofweek

    ui.section("On-time share by weekday and hour")
    grid = stats.rollup(hourly, ["weekday", "hour"])
    rates = grid.pivot(index="weekday", columns="hour", values="on_time_pct").reindex(index=range(7), columns=range(24))
    counts = grid.pivot(index="weekday", columns="hour", values="events").reindex(index=range(7), columns=range(24))
    fig = go.Figure(
        go.Heatmap(
            z=rates.where(counts >= minimum).to_numpy(),
            x=list(range(24)),
            y=WEEKDAYS,
            customdata=counts.fillna(0).to_numpy(),
            colorscale=ui.RELIABILITY_SCALE,
            zmin=40,
            zmax=100,
            colorbar={"title": "On time %"},
            hoverongaps=False,
            hovertemplate="%{y} %{x}:00<br>On time %{z:.1f}%<br>%{customdata:,} events<extra></extra>",
        )
    )
    fig.update_layout(xaxis={"title": "Hour of stop event", "dtick": 1}, yaxis={"autorange": "reversed"})
    ui.plot(fig, key="patterns_heatmap", height=340)
    st.caption(f"Blank cells have fewer than {minimum} stop events; they are not 0%.")

    left, right = st.columns(2)
    with left:
        ui.section("Peak periods")
        periods = []
        for name, hours in PEAKS.items():
            part = hourly[hourly["hour"].isin(list(hours))]
            if not part.empty:
                t = stats.totals(part)
                periods.append(
                    {
                        "period": name,
                        "on_time_pct": t["on_time_pct"],
                        "late_pct": t["late_pct"],
                        "mean_delay_min": (t["mean_delay_sec"] or 0) / 60,
                        "events": t["events"],
                    }
                )
        frame = pd.DataFrame(periods)
        if not frame.empty:
            fig = px.bar(
                frame,
                x="period",
                y="on_time_pct",
                color="late_pct",
                color_continuous_scale="Oranges",
                hover_data={"events": ":,", "mean_delay_min": ":.1f"},
                labels={"period": "", "on_time_pct": "On time (%)", "late_pct": "Late %"},
            )
            fig.update_yaxes(range=[0, 100])
            ui.plot(fig, key="patterns_peaks")
    with right:
        ui.section("Day types")
        types = stats.rollup(hourly, ["day_type", "hour"])
        fig = px.line(
            types,
            x="hour",
            y="mean_delay_sec",
            color="day_type",
            markers=True,
            labels={"hour": "Hour", "mean_delay_sec": "Mean delay (s)", "day_type": ""},
        )
        fig.add_hline(y=0, line_dash="dot", line_color="#94A3B8")
        ui.plot(fig, key="patterns_daytype", xaxis="hour")

    ui.section("Daily trend with weekday baseline")
    daily = stats.rollup(queries.network_daily(selection), ["service_date", "day_type"])
    if not daily.empty:
        daily["weekday"] = pd.to_datetime(daily["service_date"]).dt.day_name()
        baseline = daily.groupby("weekday")["on_time_pct"].transform("median")
        daily["vs_baseline"] = daily["on_time_pct"] - baseline
        fig = px.bar(
            daily,
            x="service_date",
            y="vs_baseline",
            color="day_type",
            hover_data={"on_time_pct": ":.1f", "weekday": True, "events": ":,"},
            labels={"service_date": "", "vs_baseline": "On time vs. median for that weekday (pp)", "day_type": ""},
        )
        ui.plot(fig, key="patterns_baseline", xaxis="date")
        st.caption("Bars below zero mark days that ran worse than is typical for that weekday in the period.")
