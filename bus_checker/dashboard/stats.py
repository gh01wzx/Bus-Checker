"""Pure calculations behind the dashboard. Rates are always ratios of summed counts."""

from __future__ import annotations

import math
from collections.abc import Iterable, Sequence

import pandas as pd

COUNT_COLUMNS = ("events", "on_time", "early", "late", "delay_sum_sec")


def ratio(numerator: float, denominator: float) -> float | None:
    if denominator is None or denominator == 0 or pd.isna(denominator):
        return None
    return float(numerator) / float(denominator)


def with_rates(frame: pd.DataFrame) -> pd.DataFrame:
    """Add on_time_pct, early_pct, late_pct and mean_delay_sec from summed counts."""
    result = frame.copy()
    events = result["events"].where(result["events"] > 0)
    result["on_time_pct"] = 100 * result["on_time"] / events
    result["early_pct"] = 100 * result["early"] / events
    result["late_pct"] = 100 * result["late"] / events
    if "delay_sum_sec" in result:
        result["mean_delay_sec"] = result["delay_sum_sec"] / events
    return result


def rollup(frame: pd.DataFrame, keys: Sequence[str], extra: Iterable[str] = ()) -> pd.DataFrame:
    """Sum the count columns by ``keys`` and recompute rates. Never averages percentages."""
    columns = [c for c in (*COUNT_COLUMNS, *extra) if c in frame.columns]
    if frame.empty:
        empty = pd.DataFrame(columns=[*keys, *columns])
        return with_rates(empty) if "events" in columns else empty
    summed = frame.groupby(list(keys), dropna=False)[columns].sum().reset_index()
    return with_rates(summed)


def totals(frame: pd.DataFrame, extra: Iterable[str] = ()) -> dict[str, float | None]:
    columns = [c for c in (*COUNT_COLUMNS, *extra) if c in frame.columns]
    sums = {c: float(frame[c].sum()) if not frame.empty else 0.0 for c in columns}
    events = sums.get("events", 0.0)
    sums["on_time_pct"] = _pct(sums.get("on_time", 0.0), events)
    sums["late_pct"] = _pct(sums.get("late", 0.0), events)
    sums["early_pct"] = _pct(sums.get("early", 0.0), events)
    sums["mean_delay_sec"] = ratio(sums.get("delay_sum_sec", 0.0), events)
    return sums


def _pct(numerator: float, denominator: float) -> float | None:
    value = ratio(numerator, denominator)
    return None if value is None else 100 * value


def histogram_quantiles(
    buckets: pd.Series, counts: pd.Series, quantiles: Sequence[float] = (0.5, 0.9, 0.95)
) -> dict[float, float | None]:
    """Approximate delay quantiles (seconds) from one-minute histogram buckets.

    Bucket ``b`` holds delays in ``[60*b, 60*(b+1))`` seconds; edge buckets hold the clamped
    tails. Values are linearly interpolated inside the bucket.
    """
    frame = (
        pd.DataFrame({"bucket": buckets.to_numpy(), "count": counts.to_numpy()})
        .groupby("bucket", as_index=False)["count"]
        .sum()
        .sort_values("bucket")
    )
    total = float(frame["count"].sum())
    result: dict[float, float | None] = {}
    if total <= 0:
        return dict.fromkeys(quantiles)
    cumulative = frame["count"].cumsum().to_numpy()
    starts = frame["bucket"].to_numpy()
    sizes = frame["count"].to_numpy()
    for q in quantiles:
        target = q * total
        index = int((cumulative >= target).argmax())
        before = cumulative[index] - sizes[index]
        fraction = (target - before) / sizes[index] if sizes[index] else 0.0
        result[q] = float((starts[index] + fraction) * 60)
    return result


def delay_std(events: float, total: float, squares: float) -> float | None:
    if not events or events < 2:
        return None
    variance = (squares - total * total / events) / (events - 1)
    return math.sqrt(max(variance, 0.0))


def change(current: float | None, previous: float | None) -> float | None:
    if current is None or previous is None:
        return None
    return current - previous
