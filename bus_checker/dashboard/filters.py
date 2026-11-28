"""Sidebar filters shared by the analysis pages.

Streamlit forgets a widget's value when a page that does not render it is shown, so each
filter keeps its value in a separate session key and re-seeds the widget on every render.
"""

from __future__ import annotations

from datetime import date, timedelta
from typing import Any

import streamlit as st

from bus_checker.dashboard import queries
from bus_checker.dashboard.model import DAY_TYPES, Filters

PERIODS = {"7 days": 7, "30 days": 30, "90 days": 90, "All": None, "Custom": -1}
DAY_CHOICES = {
    "All days": DAY_TYPES,
    "Weekdays": ("Weekday",),
    "Weekends & holidays": ("Weekend", "Holiday"),
}


def _bound(name: str, default: Any) -> str:
    store = f"filter::{name}"
    widget = f"widget::{name}"
    if store not in st.session_state:
        st.session_state[store] = default
    st.session_state[widget] = st.session_state[store]
    return widget


def _save(name: str) -> None:
    st.session_state[f"filter::{name}"] = st.session_state[f"widget::{name}"]


def _clamp(day: date, low: date, high: date) -> date:
    return min(max(day, low), high)


def sidebar(*, modes: bool = True, day_types: bool = True, default_days: int = 7) -> Filters | None:
    """Render the shared filters and return the selection, or None when there is no data."""
    bounds = queries.date_bounds()
    if bounds is None:
        st.info(
            "No reliability data has been published yet. The first build after collection starts will fill this page.",
            icon=":material/hourglass_empty:",
        )
        return None
    first, last = bounds
    with st.sidebar:
        st.markdown("**Filters**")
        default_period = next((k for k, v in PERIODS.items() if v == default_days), "7 days")
        period = (
            st.segmented_control(
                "Period",
                list(PERIODS),
                key=_bound("period", default_period),
                on_change=_save,
                args=("period",),
                required=True,
            )
            or default_period
        )
        if PERIODS[period] == -1:
            stored = st.session_state.get("filter::custom_dates", (max(first, last - timedelta(days=6)), last))
            seeded = (_clamp(stored[0], first, last), _clamp(stored[-1], first, last))
            picked = st.date_input(
                "Dates",
                key=_bound("custom_dates", seeded),
                min_value=first,
                max_value=last,
                on_change=_save,
                args=("custom_dates",),
            )
            if isinstance(picked, (tuple, list)) and len(picked) == 2:
                start, end = picked
            else:
                start, end = seeded
        elif PERIODS[period] is None:
            start, end = first, last
        else:
            start, end = max(first, last - timedelta(days=PERIODS[period] - 1)), last

        selected_modes: tuple[str, ...] = ()
        if modes:
            available = queries.modes()
            default_modes = ["Bus"] if "Bus" in available else available
            stored_modes = [m for m in st.session_state.get("filter::modes", default_modes) if m in available]
            st.session_state["filter::modes"] = stored_modes
            chosen = st.pills(
                "Mode",
                available,
                selection_mode="multi",
                key=_bound("modes", stored_modes),
                on_change=_save,
                args=("modes",),
            )
            selected_modes = tuple(chosen or available)

        selected_days: tuple[str, ...] = DAY_TYPES
        if day_types:
            day_choice = (
                st.segmented_control(
                    "Days",
                    list(DAY_CHOICES),
                    key=_bound("days", "All days"),
                    on_change=_save,
                    args=("days",),
                    required=True,
                )
                or "All days"
            )
            selected_days = DAY_CHOICES[day_choice]
        st.caption(f"{start:%d %b %Y} – {end:%d %b %Y} · data from {first:%d %b %Y}")
    return Filters(start=start, end=end, modes=selected_modes, day_types=selected_days)


def minimum_events(label: str = "Minimum observations", default: int = 30, key: str = "min_events") -> int:
    return int(
        st.number_input(
            label,
            min_value=1,
            max_value=100_000,
            step=10,
            key=_bound(key, default),
            on_change=_save,
            args=(key,),
            help="Groups with fewer observed stop events are hidden to avoid noisy rankings.",
        )
    )
