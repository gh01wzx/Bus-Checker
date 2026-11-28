from __future__ import annotations

import json

import pandas as pd
import plotly.express as px
import streamlit as st

from bus_checker.dashboard import data, queries, ui

FEED_LABELS = {
    "trip_updates": "Trip updates",
    "vehicle_positions": "Vehicle positions",
    "service_alerts": "Service alerts",
}
STALE_MIN = 20


def render() -> None:
    ui.header(
        "Pipeline health",
        "Is collection running, is the data fresh, and did the last build pass its tests?",
    )
    if st.button("Refresh", icon=":material/refresh:"):
        data.clear_cache()
    publication = queries.publication_info()
    status = queries.pipeline("pipeline_feed_status")

    cols = st.columns(len(FEED_LABELS) + 1)
    for column, (feed, label) in zip(cols, FEED_LABELS.items(), strict=False):
        row = status[status["feed"] == feed]
        if row.empty:
            ui.metric(column, label, "no data")
            continue
        r = row.iloc[0]
        age = (
            (pd.Timestamp.now(tz="UTC") - pd.Timestamp(r["last_success_at"])).total_seconds() / 60
            if pd.notna(r["last_success_at"])
            else None
        )
        healthy = age is not None and age <= STALE_MIN and r["last_status"] != "failed"
        ui.metric(
            column,
            f"{label} {'●' if healthy else '▲'}",
            ui.fmt_age(r["last_success_at"]),
            f"{int(r['failures_24h'])} failures / {int(r['attempts_24h'])} in 24 h",
            neutral=True,
            help=f"Last status: {r['last_status']}. Feed lag ≈ {ui.fmt_int(r['avg_feed_lag_sec_24h'])} s.",
        )
    with cols[-1]:
        if publication is not None:
            ui.metric(
                st,
                "Published",
                ui.fmt_age(publication["published_at"]),
                f"data through {pd.Timestamp(publication['data_through']):%d %b}"
                if pd.notna(publication["data_through"])
                else None,
                neutral=True,
                help=f"{publication['kind']} publication {publication['publication_id']}",
            )
        else:
            ui.metric(st, "Published", "live", help="Reading the warehouse marts directly.")

    failing = status[status["last_status"] == "failed"]
    for row in failing.itertuples(index=False):
        label = FEED_LABELS.get(row.feed, row.feed)
        st.error(
            f"{label}: last attempt failed ({row.last_error_type}: {row.last_error_message})",
            icon=":material/error:",
        )

    dbt = queries.pipeline("pipeline_dbt_runs").sort_values("started_at", ascending=False)
    ui.section("Transformations (dbt)")
    if dbt.empty:
        ui.empty("No dbt runs recorded yet.")
    else:
        last = dbt.iloc[0]
        cols = st.columns(4)
        ui.metric(cols[0], "Last build", str(last["status"]).upper(), ui.fmt_age(last["finished_at"]), neutral=True)
        ui.metric(cols[1], "Tests passed", ui.fmt_int(last["tests_pass"]))
        ui.metric(cols[2], "Tests failed", ui.fmt_int(last["tests_fail"]), inverse=True)
        ui.metric(cols[3], "Build time", f"{last['elapsed_sec']:.0f} s" if pd.notna(last["elapsed_sec"]) else "—")
        if last["status"] != "success":
            try:
                failures = json.loads(last["failures"] or "[]")
            except ValueError:
                failures = []
            for failure in failures[:5]:
                st.error(
                    f"{failure.get('node')}: {failure.get('message') or failure.get('status')}", icon=":material/error:"
                )
        recent = dbt.head(200).assign(started=ui.to_local(dbt.head(200)["started_at"]))
        fig = px.scatter(
            recent,
            x="started",
            y="elapsed_sec",
            color="status",
            color_discrete_map={"success": "#10B981", "error": "#DC2626"},
            labels={"started": "", "elapsed_sec": "dbt build (s)"},
        )
        ui.plot(fig, key="health_dbt", height=240)

    runs = queries.pipeline("pipeline_fetch_runs")
    ui.section("Collection attempts (last 7 days)")
    if runs.empty:
        ui.empty("No collection attempts recorded.")
    else:
        runs["started"] = ui.to_local(runs["started_at"])
        runs["feed_label"] = runs["feed"].map(FEED_LABELS).fillna(runs["feed"])
        left, right = st.columns(2)
        with left:
            fig = px.scatter(
                runs,
                x="started",
                y="rows_inserted",
                color="status",
                facet_row="feed_label",
                color_discrete_map={
                    "success": "#10B981",
                    "warning": "#F59E0B",
                    "failed": "#DC2626",
                    "unchanged": "#94A3B8",
                    "empty": "#64748B",
                },
                labels={"started": "", "rows_inserted": "New rows"},
                height=520,
            )
            fig.update_yaxes(matches=None)
            fig.for_each_annotation(lambda a: a.update(text=a.text.split("=")[-1]))
            ui.plot(fig, key="health_rows")
        with right:
            fig = px.scatter(
                runs,
                x="started",
                y="feed_lag_sec",
                color="feed_label",
                labels={"started": "", "feed_lag_sec": "Feed age at collection (s)", "feed_label": ""},
                height=520,
            )
            ui.plot(fig, key="health_lag")
        failures = runs[runs["status"] == "failed"].sort_values("started_at", ascending=False)
        if not failures.empty:
            with st.expander(f"{len(failures)} failed attempts"):
                st.dataframe(failures[["started", "feed", "http_status", "error_type"]], hide_index=True)

    volume = queries.pipeline("pipeline_daily_volume")
    if not volume.empty:
        ui.section("Daily volume")
        volume["feed_label"] = volume["feed"].map(FEED_LABELS).fillna(volume["feed"])
        fig = px.bar(
            volume,
            x="collection_date",
            y="rows_inserted",
            color="feed_label",
            labels={"collection_date": "", "rows_inserted": "New rows", "feed_label": ""},
        )
        ui.plot(fig, key="health_volume", xaxis="date", height=300)
        expected = 288
        coverage = volume[volume["feed"] == "trip_updates"].assign(
            completeness=lambda f: 100 * (f["attempts"] - f["failures"]) / expected
        )
        st.caption(
            "Collection runs every 5 minutes (288 attempts per day). Latest day completeness: "
            + (
                ui.fmt_pct(coverage.sort_values("collection_date")["completeness"].iloc[-1])
                if not coverage.empty
                else "—"
            )
        )

    left, right = st.columns(2)
    with left:
        ui.section("Quarantined records (7 days)")
        quarantine = queries.pipeline("pipeline_quarantine")
        if quarantine.empty:
            st.success("No records rejected.", icon=":material/check_circle:")
        else:
            st.dataframe(
                quarantine.sort_values("records", ascending=False),
                hide_index=True,
                column_config={"records": st.column_config.NumberColumn("Records", format="localized")},
            )
    with right:
        ui.section("GTFS reference loads")
        loads = queries.pipeline("pipeline_gtfs_loads").sort_values("started_at", ascending=False)
        if loads.empty:
            ui.empty("GTFS has not been loaded yet.")
        else:
            st.dataframe(
                loads.head(10).assign(started=ui.to_local(loads.head(10)["started_at"]).dt.strftime("%d %b %H:%M"))[
                    ["started", "status", "feed_version", "feed_end_date", "error_message"]
                ],
                hide_index=True,
                column_config={"feed_end_date": st.column_config.DateColumn("Valid until"), "error_message": "Note"},
            )
