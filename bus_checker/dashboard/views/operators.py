from __future__ import annotations

import plotly.express as px
import streamlit as st

from bus_checker.dashboard import filters, queries, stats, ui


def render() -> None:
    ui.header(
        "Operators",
        "Auckland Transport contracts services to several operators. Compare how reliably each "
        "operator's routes ran in the same period.",
    )
    selection = filters.sidebar()
    if selection is None:
        return
    daily = queries.operator_daily(selection)
    if daily.empty:
        ui.empty("No operator data for these filters.")
        return
    extra = ("trips_tracked", "trips_cancelled")
    summary = stats.rollup(daily, ["operator_name", "mode"], extra)
    summary["cancel_per_100"] = (
        100
        * summary["trips_cancelled"]
        / (summary["trips_tracked"] + summary["trips_cancelled"]).where(lambda s: s > 0)
    )
    summary["mean_delay_min"] = summary["mean_delay_sec"] / 60
    summary = summary[summary["events"] > 0].sort_values("on_time_pct")

    left, right = st.columns([3, 2])
    with left:
        ui.section("On-time share")
        fig = px.bar(
            summary,
            x="on_time_pct",
            y="operator_name",
            color="mode",
            orientation="h",
            color_discrete_map=ui.MODE_COLORS,
            hover_data={"events": ":,", "late_pct": ":.1f", "mean_delay_min": ":.1f"},
            labels={"on_time_pct": "On time (%)", "operator_name": ""},
        )
        fig.update_layout(xaxis_range=[0, 100])
        ui.plot(fig, key="operators_rank", height=max(320, 32 * len(summary)))
    with right:
        ui.section("Lateness versus cancellations")
        fig = px.scatter(
            summary,
            x="late_pct",
            y="cancel_per_100",
            size="events",
            color="mode",
            color_discrete_map=ui.MODE_COLORS,
            hover_name="operator_name",
            size_max=40,
            labels={"late_pct": "Late (%)", "cancel_per_100": "Cancelled per 100 trips"},
        )
        ui.plot(fig, key="operators_scatter", height=max(320, 32 * len(summary)))

    st.dataframe(
        summary[
            [
                "operator_name",
                "mode",
                "events",
                "on_time_pct",
                "late_pct",
                "early_pct",
                "mean_delay_min",
                "trips_tracked",
                "trips_cancelled",
            ]
        ],
        hide_index=True,
        column_config={
            "operator_name": "Operator",
            "mode": "Mode",
            "events": st.column_config.NumberColumn("Stop events", format="localized"),
            "on_time_pct": st.column_config.ProgressColumn("On time", format="%.1f%%", min_value=0, max_value=100),
            "late_pct": st.column_config.NumberColumn("Late", format="%.1f%%"),
            "early_pct": st.column_config.NumberColumn("Early", format="%.1f%%"),
            "mean_delay_min": st.column_config.NumberColumn("Mean delay (min)", format="%.1f"),
            "trips_tracked": st.column_config.NumberColumn("Trips tracked", format="localized"),
            "trips_cancelled": st.column_config.NumberColumn("Cancelled", format="localized"),
        },
    )

    ui.section("Trend")
    trend = stats.rollup(daily, ["service_date", "operator_name"])
    busiest = summary.sort_values("events", ascending=False)["operator_name"].head(8).tolist()
    fig = px.line(
        trend[trend["operator_name"].isin(busiest)],
        x="service_date",
        y="on_time_pct",
        color="operator_name",
        markers=True,
        labels={"service_date": "", "on_time_pct": "On time (%)", "operator_name": ""},
    )
    fig.update_yaxes(range=[0, 100])
    ui.plot(fig, key="operators_trend", xaxis="date")
    st.caption("The eight operators with the most stop events are shown.")
