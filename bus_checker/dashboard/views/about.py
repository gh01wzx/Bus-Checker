from __future__ import annotations

import streamlit as st

from bus_checker import __version__
from bus_checker.dashboard import ui


def render() -> None:
    ui.header("Methodology", "Definitions, data sources and known limitations.")
    st.markdown(
        """
### What is measured
* **Stop event** — one trip serving one stop. Auckland Transport's realtime feed reports the delay
  at the stop a vehicle has just served. Every five minutes the collector stores each report
  once; the warehouse keeps the **latest observed report per trip and stop**. Reports whose time
  is still in the future are *predictions* and are excluded from reliability figures.
* **On time** — a reported delay between **1 minute early and 5 minutes late** (−60 s to +300 s,
  inclusive). **Early** is more than 60 s early, **late** more than 300 s late.
* **Percentiles** (median, P90, P95) come from one-minute delay buckets of individual stop events,
  so they can be combined across any period or set of routes. The edge buckets hold the tails
  (≤ −15 min and ≥ +30 min).
* **Tracked trip** — a trip with at least one observed stop event. **Cancelled** — the feed's latest
  report cancels the trip and no stop was observed. **Scheduled** trips come from the GTFS timetable
  that applied on each date.
* **Routes** are keyed by their public number (``70``, ``NX1``); AT's contract/version suffix in
  the route id is dropped so history stays continuous across timetable versions. **Stops** are keyed
  by their public stop code.
* **Day types** — weekday, weekend and New Zealand public holidays (including Auckland Anniversary).
  Times are Pacific/Auckland. A trip that runs past midnight belongs to the service day it started.

### Caveats
* Delays are **self-reported by vehicles** and are not independently verified.
* A scheduled trip with no realtime data may simply lack tracking, or fall into a collection gap;
  it is not necessarily a missed trip.
* Collection runs every five minutes on a local machine. Gaps in collection (machine asleep,
  network outage) cannot be back-filled from the live feed.
* Occupancy and speed are position samples, not passenger counts.

### Pipeline
Collect (Airflow, every 5 min) → raw tables (DuckDB or PostgreSQL) → dbt (staging → core →
marts, with data tests) → this dashboard. Locally the dashboard reads a published snapshot of the
marts; the online version reads the same marts from a hosted PostgreSQL database.
        """
    )
    st.caption(
        f"Bus Checker {__version__}. Data: Auckland Transport, licensed under CC BY 4.0 "
        "(https://dev-portal.at.govt.nz/). Map data © OpenStreetMap contributors."
    )
