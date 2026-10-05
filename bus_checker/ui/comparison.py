from bus_checker.ui.data import weighted, hourly_data, route_stats, delay_distribution
import plotly.express as px
import streamlit as st
from bus_checker.ui.common import COLORS, chart, date_filter


def render_comparison():
    st.header("Compare routes")
    st.caption(
        "Compare up to six routes using the same dates. Quantiles are calculated from individual observations, not averages of daily summaries."
    )
    params = date_filter("route_hourly_reliability", "comparison_dates")
    if params is None:
        return
    data = hourly_data(params)
    if data.empty:
        st.info("No observations in this date range.")
        return
    options = weighted(data, ["route_id", "route_no"]).sort_values(
        "sample_count", ascending=False
    )
    names = dict(
        zip(
            options.route_id,
            options.route_no.astype(str) + " · " + options.route_id.astype(str),
        )
    )
    routes = st.multiselect(
        "Routes to compare",
        options.route_id.tolist(),
        default=options.route_id.head(3).tolist(),
        max_selections=6,
        format_func=names.get,
    )
    if not routes:
        st.info("Select at least one route to compare.")
        return
    selected = data[data.route_id.isin(routes)].copy()
    selected["route"] = selected.route_id.map(names)
    stats = route_stats(params, routes)
    stats["route"] = stats.route_id.map(names)
    st.dataframe(
        stats[
            [
                "route",
                "sample_count",
                "on_time_pct",
                "mean_min",
                "median_min",
                "p90_min",
                "p95_min",
            ]
        ].round(2),
        hide_index=True,
        column_config={
            "route": "Route",
            "sample_count": "Observations",
            "on_time_pct": "On time (%)",
            "mean_min": "Mean (min)",
            "median_min": "Median (min)",
            "p90_min": "P90 (min)",
            "p95_min": "P95 (min)",
        },
    )
    st.download_button(
        "Export comparison",
        stats.to_csv(index=False).encode("utf-8"),
        "route-comparison.csv",
        "text/csv",
    )
    left, right = st.columns(2)
    with left:
        st.subheader("Punctuality mix")
        mix = selected.groupby("route")[
            ["early_count", "on_time_count", "late_count"]
        ].sum()
        mix = (
            mix.div(mix.sum(axis=1), axis=0)
            .mul(100)
            .rename(
                columns={
                    "early_count": "Early",
                    "on_time_count": "On time",
                    "late_count": "Late",
                }
            )
            .reset_index()
            .melt(id_vars="route", var_name="Status", value_name="Share")
        )
        chart(
            px.bar(
                mix,
                x="route",
                y="Share",
                color="Status",
                color_discrete_map=COLORS,
                labels={"Share": "Observations (%)", "route": "Route"},
            )
        )
    with right:
        st.subheader("Typical delay and the long tail")
        tails = (
            stats[["route", "median_min", "p90_min", "p95_min"]]
            .rename(
                columns={"median_min": "Median", "p90_min": "P90", "p95_min": "P95"}
            )
            .melt(id_vars="route", var_name="Measure", value_name="Delay")
        )
        chart(
            px.bar(
                tails,
                x="route",
                y="Delay",
                color="Measure",
                barmode="group",
                labels={"Delay": "Reported delay (min)", "route": "Route"},
            )
        )
    st.caption(
        "P95: 95% of reported delays are at or below this value. Negative values mean early running. Routes can differ in journey and time-of-day coverage."
    )
    st.subheader("Hourly comparison")
    hourly = weighted(selected, ["route", "local_hour"])
    chart(
        px.line(
            hourly,
            x="local_hour",
            y="on_time_pct",
            color="route",
            markers=True,
            hover_data=["sample_count"],
            range_y=[0, 100],
            labels={"local_hour": "Auckland hour", "on_time_pct": "On time (%)"},
        )
    )
    st.subheader("Delay distribution")
    bins = delay_distribution(params, routes)
    bins["route"] = bins.route_id.map(names)
    bins["share_pct"] = (
        100 * bins.observations / bins.groupby("route_id").observations.transform("sum")
    )
    bins["interval"] = bins.minute_bucket.map(
        lambda x: (
            "< −15 min"
            if x == -16
            else ("≥ 30 min" if x == 30 else f"{x} to {x+1} min")
        )
    )
    chart(
        px.bar(
            bins,
            x="minute_bucket",
            y="share_pct",
            color="route",
            barmode="group",
            hover_data=["observations", "interval"],
            labels={
                "minute_bucket": "Delay minute bucket",
                "share_pct": "Route observations (%)",
            },
        )
    )
    st.caption(
        "One-minute bins; the first and last bins include all observations below −15 minutes and at/above +30 minutes. No tail observations are dropped."
    )
    st.subheader("Daily trend by route")
    daily = weighted(selected, ["route", "observation_date"])
    chart(
        px.line(
            daily,
            x="observation_date",
            y="on_time_pct",
            color="route",
            markers=True,
            hover_data=["sample_count"],
            range_y=[0, 100],
            labels={"observation_date": "Date", "on_time_pct": "On time (%)"},
        )
    )
