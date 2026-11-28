"""Shared presentation: colours, number formats and small layout components."""

from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime
from typing import Any

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

PUNCTUALITY_COLORS = {
    "Early": "#6366F1",
    "On time": "#10B981",
    "Late": "#F97316",
    "Unknown": "#94A3B8",
}
PUNCTUALITY_LABELS = {"early": "Early", "on_time": "On time", "late": "Late", "unknown": "Unknown"}
MODE_COLORS = {
    "Bus": "#0EA5E9",
    "Train": "#8B5CF6",
    "Ferry": "#14B8A6",
    "Light rail": "#EC4899",
    "Other": "#64748B",
    "Unknown": "#94A3B8",
    "Not in service": "#CBD5E1",
}
OCCUPANCY_LABELS = {
    "EMPTY": "Empty",
    "MANY_SEATS_AVAILABLE": "Many seats",
    "FEW_SEATS_AVAILABLE": "Few seats",
    "STANDING_ROOM_ONLY": "Standing only",
    "CRUSHED_STANDING_ROOM_ONLY": "Crushed standing",
    "FULL": "Full",
    "NOT_ACCEPTING_PASSENGERS": "Not accepting",
    "NO_DATA_AVAILABLE": "No data",
    "NOT_BOARDABLE": "Not boardable",
}
OCCUPANCY_COLORS = {
    "Empty": "#A7F3D0",
    "Many seats": "#34D399",
    "Few seats": "#FBBF24",
    "Standing only": "#F97316",
    "Crushed standing": "#DC2626",
    "Full": "#7F1D1D",
}
DIRECTION_LABELS = {0: "Direction 0", 1: "Direction 1", -1: "Unknown direction"}
SEQUENTIAL = ["#FEF3C7", "#FCD34D", "#F59E0B", "#EA580C", "#9A3412"]
RELIABILITY_SCALE = [[0, "#EA580C"], [0.5, "#FDE68A"], [1, "#059669"]]


# ----------------------------------------------------------------------------- formats
def fmt_pct(value: float | None, digits: int = 1) -> str:
    return "—" if value is None or pd.isna(value) else f"{value:.{digits}f}%"


def fmt_int(value: float | None) -> str:
    return "—" if value is None or pd.isna(value) else f"{round(value):,}"


def fmt_minutes(seconds: float | None, signed: bool = True) -> str:
    if seconds is None or pd.isna(seconds):
        return "—"
    minutes = seconds / 60
    sign = "+" if signed and minutes > 0 else ""
    return f"{sign}{minutes:.1f} min".replace("-", "−")


def fmt_age(moment: Any) -> str:
    if moment is None or pd.isna(moment):
        return "never"
    timestamp = pd.Timestamp(moment)
    if timestamp.tzinfo is None:
        timestamp = timestamp.tz_localize("UTC")
    seconds = (datetime.now(UTC) - timestamp.to_pydatetime()).total_seconds()
    if seconds < 0:
        return "just now"
    if seconds < 90:
        return f"{seconds:.0f} s ago"
    if seconds < 5400:
        return f"{seconds / 60:.0f} min ago"
    if seconds < 172_800:
        return f"{seconds / 3600:.1f} h ago"
    return f"{seconds / 86_400:.0f} days ago"


def local_time(moment: Any, fmt: str = "%d %b %H:%M") -> str:
    if moment is None or pd.isna(moment):
        return "—"
    timestamp = pd.Timestamp(moment)
    if timestamp.tzinfo is None:
        timestamp = timestamp.tz_localize("UTC")
    return timestamp.tz_convert("Pacific/Auckland").strftime(fmt)


def to_local(series: pd.Series) -> pd.Series:
    converted = pd.to_datetime(series, utc=True)
    return converted.dt.tz_convert("Pacific/Auckland")


def delta_pp(value: float | None) -> str | None:
    return None if value is None or pd.isna(value) else f"{value:+.1f} pp"


def delta_minutes(seconds: float | None) -> str | None:
    if seconds is None or pd.isna(seconds):
        return None
    return f"{seconds / 60:+.1f} min".replace("-", "−")


# ----------------------------------------------------------------------------- layout
def header(title: str, caption: str) -> None:
    st.title(title)
    st.caption(caption)


def section(title: str, caption: str | None = None) -> None:
    st.subheader(title)
    if caption:
        st.caption(caption)


def metric(
    container: Any,
    label: str,
    value: str,
    delta: str | None = None,
    *,
    help: str | None = None,
    inverse: bool = False,
    neutral: bool = False,
    chart: list[float] | None = None,
) -> None:
    container.metric(
        label,
        value,
        delta=delta,
        delta_color="off" if neutral else ("inverse" if inverse else "normal"),
        delta_arrow="off" if neutral else "auto",
        help=help,
        border=True,
        chart_data=chart if chart and len(chart) > 1 else None,
        chart_type="area",
    )


def empty(message: str, icon: str = ":material/info:") -> None:
    st.info(message, icon=icon)


def grid(count: int, per_row: int = 3) -> list[Any]:
    """Metric tiles in rows of ``per_row`` so values never truncate on laptop screens."""
    cells: list[Any] = []
    while len(cells) < count:
        cells.extend(st.columns(per_row))
    return cells[:count]


def _x_values(fig: go.Figure) -> pd.Series:
    values: list[Any] = []
    for trace in fig.data:
        x = getattr(trace, "x", None)
        if x is not None:  # numpy arrays have no truth value
            values.extend(list(x))
    return pd.Series(values)


def plot(
    fig: go.Figure,
    *,
    key: str | None = None,
    height: int | None = None,
    xaxis: str | None = None,
) -> None:
    """Render a Plotly figure with the house layout.

    ``xaxis="date"`` formats a daily axis (one tick per day for short ranges);
    ``xaxis="hour"`` fixes an hour-of-day axis to 0–23.
    """
    fig.update_layout(
        margin={"l": 8, "r": 8, "t": 36, "b": 8},
        legend={"orientation": "h", "yanchor": "bottom", "y": 1.02, "x": 0, "title_text": ""},
        hoverlabel={"namelength": -1},
        font={"size": 12},
    )
    if xaxis == "date":
        days = pd.to_datetime(_x_values(fig), errors="coerce").dt.normalize().nunique()
        fig.update_xaxes(tickformat="%d %b", hoverformat="%a %d %b %Y", title_text="")
        if days <= 14:
            fig.update_xaxes(dtick=86_400_000)
    elif xaxis == "hour":
        fig.update_xaxes(range=[-0.5, 23.5], dtick=2)
    if height:
        fig.update_layout(height=height)
    st.plotly_chart(fig, key=key, config={"displaylogo": False})


def guarded(render: Callable[[], None]) -> Callable[[], None]:
    """Wrap a page so a missing or unreachable data source shows guidance, not a traceback."""
    from bus_checker.dashboard.data import DataUnavailable

    def page() -> None:
        try:
            render()
        except DataUnavailable as error:
            st.warning(
                f"{error} Run the pipeline (`python -m bus_checker run-once`) or wait for the next scheduled build.",
                icon=":material/database:",
            )

    page.__name__ = render.__name__
    return page


def download(frame: pd.DataFrame, filename: str, label: str = "Download CSV") -> None:
    st.download_button(
        label,
        frame.to_csv(index=False).encode("utf-8"),
        file_name=filename,
        mime="text/csv",
        icon=":material/download:",
    )
