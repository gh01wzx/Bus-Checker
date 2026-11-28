"""Run inside the dashboard container after a successful ``bus_realtime`` DAG run:

docker compose exec -T dashboard /opt/bus-venv/bin/python - < tests/stack/check_stack.py
"""

from streamlit.testing.v1 import AppTest

from bus_checker.config import get_settings
from bus_checker.warehouse import open_dashboard_source

PAGES = ["overview", "live", "alerts", "routes", "compare", "patterns", "stops", "operators",
         "delivery", "fleet", "health", "about"]  # fmt: skip


def main() -> None:
    settings = get_settings()
    source = open_dashboard_source(settings)
    try:
        daily = source.frame("SELECT * FROM marts.network_daily")
        assert daily["events"].sum() >= 4, daily
        assert source.scalar("SELECT count(*) FROM marts.live_vehicles") >= 4
        assert source.scalar("SELECT count(*) FROM marts.service_alerts") == 2
        feeds = source.frame("SELECT feed, last_status FROM marts.pipeline_feed_status")
        assert set(feeds["feed"]) == {"trip_updates", "vehicle_positions", "service_alerts"}, feeds
        if settings.backend == "postgres":
            # The dashboard role sees the marts and nothing else.
            assert not source.scalar("SELECT has_schema_privilege(current_user, 'raw', 'USAGE')")
            assert not source.scalar("SELECT has_table_privilege(current_user, 'marts.route_daily', 'INSERT')")
    finally:
        source.close()

    for page in PAGES:
        script = (
            f"from bus_checker.dashboard.views import {page}\n"
            "from bus_checker.dashboard.ui import guarded\n"
            f"guarded({page}.render)()"
        )
        app = AppTest.from_string(script, default_timeout=60).run()
        assert not app.exception, (page, [e.value for e in app.exception])
        assert not app.error, (page, [e.value for e in app.error])
    print(f"PASS: {settings.backend} stack — DAG output, reader permissions and {len(PAGES)} pages")


main()
