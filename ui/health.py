from datetime import datetime, timezone
import pandas as pd
import plotly.express as px
import streamlit as st
from data_queries import query


def render_health():
    st.header("Data health")
    st.caption(
        "Check whether the reported results are current and whether collection is working."
    )
    if st.button("Refresh status"):
        query.clear()
    try:
        runs = query(
            "SELECT * FROM bus_ingestion_runs ORDER BY started_at DESC LIMIT 100"
        )
        summary = query(
            """SELECT max(captured_at) AS source_time, max(loaded_at) AS loaded_time,
                          count(*) AS observations FROM bus_observations"""
        ).iloc[0]
        quarantined = query(
            "SELECT reason, count(*) AS records FROM bus_quarantine GROUP BY reason ORDER BY records DESC"
        )
    except Exception:
        st.info("Run python pipeline.py to initialise collection and its audit tables.")
        return
    if runs.empty:
        st.info("No collection attempts recorded yet.")
        return
    threshold = st.number_input(
        "Source freshness threshold (minutes)", min_value=1, value=30
    )
    source_time = pd.to_datetime(summary.source_time, utc=True)
    age = (
        None
        if pd.isna(source_time)
        else (datetime.now(timezone.utc) - source_time.to_pydatetime()).total_seconds()
        / 60
    )
    status_metric, freshness_metric, quarantine_metric = st.columns(3)
    status_metric.metric("Latest collection", runs.iloc[0].status)
    freshness_metric.metric(
        "Source age", "No observations" if age is None else f"{max(age, 0):.0f} min"
    )
    quarantine_metric.metric(
        "Quarantined records",
        int(quarantined.records.sum()) if not quarantined.empty else 0,
    )
    if runs.iloc[0].status == "failed":
        st.error(
            "The latest collection failed. Check the run history and collector logs."
        )
    if age is None or age > threshold:
        st.warning(
            "Source data is stale or unavailable. Collection schedules and overnight gaps can cause this."
        )
    elif age < -5:
        st.warning(
            "Source timestamp is in the future. Check the feed timestamp and system clock."
        )
    else:
        st.success("Source data is within the selected freshness threshold.")
    try:
        coverage = query(
            """SELECT count(*) AS source_rows,
            sum(CASE WHEN f.observation_id IS NOT NULL THEN 1 ELSE 0 END) AS modelled_rows
            FROM bus_observations o LEFT JOIN fct_trip_observation f
            ON o.observation_id=f.observation_id WHERE o.observation_type='trip' """
        ).iloc[0]
        source_rows = int(coverage.source_rows)
        modelled = 0 if pd.isna(coverage.modelled_rows) else int(coverage.modelled_rows)
        st.metric("Trip observations transformed", f"{modelled:,} / {source_rows:,}")
        if modelled != source_rows:
            st.warning(
                "Analytics are behind collection. Run the dbt build and check its tests."
            )
        unmatched = query(
            """SELECT o.route_id, count(*) AS observations FROM bus_observations o
            LEFT JOIN gtfs_routes r ON cast(r.route_id as varchar)=o.route_id
            WHERE o.observation_type='trip' AND r.route_id IS NULL GROUP BY o.route_id"""
        )
        if not unmatched.empty:
            st.warning(
                "Some observed routes are absent from the current GTFS reference and are excluded from bus analysis."
            )
            st.dataframe(unmatched, hide_index=True)
    except Exception:
        st.info("Analytics have not been built yet. Run python build_warehouse.py.")
    st.subheader("Recent collection attempts")
    run_chart = runs.copy()
    run_chart["started_at"] = pd.to_datetime(
        run_chart.started_at, utc=True
    ).dt.tz_convert("Pacific/Auckland")
    run_chart["duration_sec"] = (
        pd.to_datetime(run_chart.finished_at, utc=True)
        - pd.to_datetime(runs.started_at, utc=True)
    ).dt.total_seconds()
    left, right = st.columns(2)
    with left:
        st.plotly_chart(
            px.bar(
                run_chart.sort_values("started_at"),
                x="started_at",
                y=["accepted_rows", "rejected_rows", "duplicate_rows"],
                labels={
                    "started_at": "Attempt started (Auckland)",
                    "value": "Records",
                    "variable": "Outcome",
                },
                title="Accepted, rejected and duplicate records",
            ),
            width="stretch",
        )
    with right:
        st.plotly_chart(
            px.scatter(
                run_chart,
                x="started_at",
                y="duration_sec",
                color="status",
                labels={
                    "started_at": "Attempt started (Auckland)",
                    "duration_sec": "Duration (seconds)",
                },
                title="Ingestion duration and status",
            ),
            width="stretch",
        )
    st.caption(
        "Includes history imports and replay attempts; volume here is processing activity, not service frequency."
    )
    st.dataframe(
        runs[
            [
                "started_at",
                "status",
                "accepted_rows",
                "rejected_rows",
                "duplicate_rows",
                "error_code",
            ]
        ],
        hide_index=True,
    )
    st.subheader("Rejected data by reason")
    if quarantined.empty:
        st.success("No quarantined records.")
    else:
        st.dataframe(quarantined, hide_index=True)
    st.caption(
        "Raw feed payloads are retained for diagnosis. The dashboard shows rejection reasons without exposing payloads or credentials."
    )
