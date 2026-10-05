import pandas as pd


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
