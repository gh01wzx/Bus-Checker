"""Streamlit entry point: page registry, navigation and the shared sidebar footer."""

from __future__ import annotations

import pandas as pd
import streamlit as st

from bus_checker import __version__
from bus_checker.dashboard import navigation, queries, ui
from bus_checker.dashboard.data import DataUnavailable
from bus_checker.dashboard.views import (
    about,
    alerts,
    compare,
    delivery,
    fleet,
    health,
    live,
    operators,
    overview,
    patterns,
    routes,
    stops,
)

PAGES = {
    "Overview": [
        ("overview", overview.render, "Network pulse", ":material/monitoring:", True),
    ],
    "Live": [
        ("live", live.render, "Live map", ":material/map:", False),
        ("alerts", alerts.render, "Service alerts", ":material/campaign:", False),
    ],
    "Reliability": [
        ("routes", routes.render, "Routes", ":material/route:", False),
        ("compare", compare.render, "Compare routes", ":material/compare_arrows:", False),
        ("patterns", patterns.render, "Time patterns", ":material/calendar_month:", False),
        ("stops", stops.render, "Stop hotspots", ":material/location_on:", False),
        ("operators", operators.render, "Operators", ":material/apartment:", False),
    ],
    "Service": [
        ("delivery", delivery.render, "Service delivery", ":material/fact_check:", False),
        ("fleet", fleet.render, "Fleet & crowding", ":material/directions_bus:", False),
    ],
    "Data": [
        ("health", health.render, "Pipeline health", ":material/health_and_safety:", False),
        ("about", about.render, "Methodology", ":material/menu_book:", False),
    ],
}


def _footer() -> None:
    with st.sidebar:
        st.divider()
        try:
            info = queries.publication_info()
            bounds = queries.date_bounds()
        except DataUnavailable:
            info, bounds = None, None
        if info is not None and pd.notna(info.get("latest_ingested_at")):
            st.caption(f"Data collected {ui.fmt_age(info['latest_ingested_at'])}")
        elif bounds is not None:
            st.caption(f"Data through {bounds[1]:%d %b %Y}")
        st.caption(f"Bus Checker {__version__} · Data © Auckland Transport (CC BY 4.0)")


def main() -> None:
    st.set_page_config(
        page_title="Bus Checker · Auckland transit reliability",
        page_icon=":material/directions_bus:",
        layout="wide",
        initial_sidebar_state="expanded",
    )
    sections = {}
    for section, entries in PAGES.items():
        pages = []
        for key, render, title, icon, default in entries:
            page = st.Page(ui.guarded(render), title=title, icon=icon, url_path=key, default=default)
            navigation.REGISTRY[key] = page
            pages.append(page)
        sections[section] = pages
    current = st.navigation(sections, position="sidebar", expanded=True)
    current.run()
    _footer()
