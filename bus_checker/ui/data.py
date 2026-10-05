import logging
import pandas as pd
import streamlit as st
from bus_checker.database import read_frame

logger = logging.getLogger(__name__)


def route_parameters(params: dict, routes: list[str]) -> tuple[str, dict]:
    placeholders = []
    bound = dict(params)
    for index, route_id in enumerate(routes):
        name = f"r{index}"
        placeholders.append(f":{name}")
        bound[name] = route_id
    return ",".join(placeholders), bound


@st.cache_data(ttl=30)
def query(sql: str, params: dict | None = None) -> pd.DataFrame:
    try:
        return read_frame(sql, params)
    except Exception as error:
        logger.warning("Warehouse read failed: %s", type(error).__name__)
        raise


def hourly_data(params):
    return query(
        "SELECT * FROM route_hourly_reliability WHERE observation_date BETWEEN :start AND :end",
        params,
    )


def route_stats(params, routes):
    if not routes:
        return pd.DataFrame()
    slots, bound = route_parameters(params, routes)
    return query(
        f"""SELECT f.route_id, r.route_no, count(*) AS sample_count,
        avg(f.delay_sec)/60.0 AS mean_min,
        percentile_cont(0.5) WITHIN GROUP (ORDER BY f.delay_sec)/60.0 AS median_min,
        percentile_cont(0.9) WITHIN GROUP (ORDER BY f.delay_sec)/60.0 AS p90_min,
        percentile_cont(0.95) WITHIN GROUP (ORDER BY f.delay_sec)/60.0 AS p95_min,
        100.0*sum(CASE WHEN f.punctuality='On time' THEN 1 ELSE 0 END)/count(*) AS on_time_pct
        FROM fct_trip_observation f JOIN dim_route r ON f.route_id=r.route_id
        WHERE f.observation_date BETWEEN :start AND :end AND f.route_id IN ({slots})
        GROUP BY f.route_id,r.route_no""",
        bound,
    )


def delay_distribution(params, routes):
    if not routes:
        return pd.DataFrame()
    slots, bound = route_parameters(params, routes)
    return query(
        f"""SELECT route_id,
        CASE WHEN delay_sec < -900 THEN -16 WHEN delay_sec >= 1800 THEN 30
             ELSE cast(floor(delay_sec/60.0) AS integer) END AS minute_bucket,
        count(*) AS observations FROM fct_trip_observation
        WHERE observation_date BETWEEN :start AND :end AND route_id IN ({slots})
        GROUP BY 1,2 ORDER BY 1,2""",
        bound,
    )


def weighted(frame: pd.DataFrame, keys: list[str]) -> pd.DataFrame:
    result = (
        frame.groupby(keys, dropna=False)[
            [
                "sample_count",
                "on_time_count",
                "late_count",
                "early_count",
                "total_delay_sec",
            ]
        ]
        .sum()
        .reset_index()
    )
    result["on_time_pct"] = (100 * result.on_time_count / result.sample_count).round(1)
    result["avg_delay_sec"] = (result.total_delay_sec / result.sample_count).round(1)
    return result


def composition(frame: pd.DataFrame) -> pd.DataFrame:
    return pd.DataFrame(
        {
            "Status": ["Early", "On time", "Late"],
            "Observations": [
                int(frame.early_count.sum()),
                int(frame.on_time_count.sum()),
                int(frame.late_count.sum()),
            ],
        }
    )


def heatmap_data(data: pd.DataFrame, minimum: int) -> tuple[pd.DataFrame, pd.DataFrame]:
    enriched = data.copy()
    enriched["weekday"] = pd.to_datetime(enriched.observation_date).dt.dayofweek
    groups = weighted(enriched, ["weekday", "local_hour"])
    rate = groups.pivot(
        index="weekday", columns="local_hour", values="on_time_pct"
    ).reindex(index=range(7), columns=range(24))
    counts = groups.pivot(
        index="weekday", columns="local_hour", values="sample_count"
    ).reindex(index=range(7), columns=range(24))
    return rate.where(counts >= minimum), counts
