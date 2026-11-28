from __future__ import annotations

import json

import plotly.express as px
import streamlit as st

from bus_checker.dashboard import queries, ui

SEVERITY_ORDER = {"SEVERE": 0, "WARNING": 1, "INFO": 2, "UNKNOWN_SEVERITY": 3}
SEVERITY_BADGE = {"SEVERE": "red", "WARNING": "orange", "INFO": "blue", "UNKNOWN_SEVERITY": "gray"}


def _title(value: str | None) -> str:
    return (value or "Unknown").replace("_", " ").capitalize()


def _periods(raw: str | None) -> str:
    try:
        periods = json.loads(raw or "[]")
    except ValueError:
        return ""
    parts = []
    for start, end in periods[:4]:
        left = ui.local_time(start, "%a %d %b %H:%M") if start else "now"
        right = ui.local_time(end, "%a %d %b %H:%M") if end else "until further notice"
        parts.append(f"{left} → {right}")
    if len(periods) > 4:
        parts.append(f"… and {len(periods) - 4} more periods")
    return "  \n".join(parts)


def render() -> None:
    ui.header(
        "Service alerts",
        "Disruptions published by Auckland Transport: detours, stop closures and cancellations.",
    )
    alerts = queries.service_alerts()
    if alerts.empty:
        ui.empty("No service alerts have been collected yet.")
        return
    published = alerts[alerts["is_published"]]
    active = published[published["is_active"]]

    cols = st.columns(4)
    ui.metric(cols[0], "Active now", ui.fmt_int(len(active)))
    ui.metric(cols[1], "Severe", ui.fmt_int((active["severity"] == "SEVERE").sum()))
    ui.metric(cols[2], "Scheduled (not yet active)", ui.fmt_int(len(published) - len(active)))
    ui.metric(
        cols[3],
        "Routes affected now",
        ui.fmt_int(active["route_count"].sum()),
        help="Sum over active alerts; a route under two alerts counts twice.",
    )

    left, right = st.columns(2)
    with left:
        ui.section("Active alerts by effect")
        if not active.empty:
            effects = active.assign(effect=active["effect"].map(_title), severity=active["severity"].map(_title))
            fig = px.histogram(
                effects,
                y="effect",
                color="severity",
                orientation="h",
                color_discrete_map={"Severe": "#DC2626", "Warning": "#F59E0B", "Info": "#3B82F6"},
                labels={"effect": "", "count": "Alerts"},
            )
            fig.update_layout(yaxis={"categoryorder": "total ascending"})
            ui.plot(fig, key="alerts_effect", height=320)
    with right:
        ui.section("New alerts per day", "By the day an alert first appeared in the feed.")
        first_seen = ui.to_local(alerts["first_seen_at"]).dt.date.value_counts().sort_index()
        fig = px.bar(x=first_seen.index, y=first_seen.values, labels={"x": "", "y": "New alerts"})
        ui.plot(fig, key="alerts_daily", xaxis="date", height=320)

    ui.section("Alerts")
    controls = st.columns([2, 2, 3])
    scope = controls[0].segmented_control(
        "Show", ["Active", "Published", "History"], default="Active", required=True, key="alert_scope"
    )
    severities = controls[1].pills(
        "Severity", ["SEVERE", "WARNING", "INFO"], selection_mode="multi", format_func=_title, key="alert_severity"
    )
    search = controls[2].text_input("Search text or route", key="alert_search", placeholder="e.g. 70 or Queen Street")
    frame = {"Active": active, "Published": published, "History": alerts}[scope or "Active"]
    if severities:
        frame = frame[frame["severity"].isin(severities)]
    if search:
        needle = search.strip().lower()
        text = (
            frame["header_text"].fillna("")
            + " "
            + frame["description_text"].fillna("")
            + " "
            + frame["route_list"].fillna("")
        ).str.lower()
        frame = frame[text.str.contains(needle, regex=False)]
    frame = frame.assign(rank=frame["severity"].map(SEVERITY_ORDER).fillna(9)).sort_values(
        ["rank", "last_seen_at"], ascending=[True, False]
    )
    st.caption(f"{len(frame)} alert(s)")
    for row in frame.head(100).itertuples(index=False):
        with st.container(border=True):
            top = st.columns([6, 2])
            top[0].markdown(f"**{row.header_text or 'Untitled alert'}**")
            with top[1]:
                st.badge(_title(row.severity), color=SEVERITY_BADGE.get(row.severity, "gray"))
            details = [_title(row.effect), _title(row.cause)]
            if row.route_list:
                details.append(f"Routes: {row.route_list}")
            st.caption(" · ".join(details))
            with st.expander("Details"):
                if row.description_text:
                    st.write(row.description_text)
                if row.effect_detail:
                    st.caption(row.effect_detail)
                periods = _periods(row.active_periods)
                if periods:
                    st.markdown("**When**  \n" + periods)
                st.caption(
                    f"First seen {ui.local_time(row.first_seen_at)} · last seen {ui.fmt_age(row.last_seen_at)} · "
                    f"{row.stop_count} stop(s) · {row.version_count} revision(s)"
                )
    if len(frame) > 100:
        st.caption("Showing the first 100 alerts; refine the filters to see more.")
    ui.download(frame.drop(columns=["rank"]), "service-alerts.csv")
