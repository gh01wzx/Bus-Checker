import os
from pathlib import Path
import subprocess
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from bus_checker.ingestion import run_pipeline
from bus_checker.database import connect, read_frame
from test_ingestion import feed


def check():
    with tempfile.TemporaryDirectory(prefix="bus-integration-") as temporary:
        os.environ["BUS_BACKEND"] = "duckdb"
        os.environ["BUS_DUCKDB_PATH"] = str(Path(temporary) / "integration.duckdb")
        run_pipeline(feed())
        with connect(write=True) as conn:
            conn.execute(
                "CREATE TABLE gtfs_routes (route_id VARCHAR, route_short_name VARCHAR, route_type INTEGER)"
            )
            conn.execute("INSERT INTO gtfs_routes VALUES ('101','101',3)")
            conn.execute(
                "CREATE TABLE gtfs_trips (route_id VARCHAR, trip_headsign VARCHAR, direction_id INTEGER)"
            )
            conn.execute("INSERT INTO gtfs_trips VALUES ('101','City',0)")
            conn.execute(
                "CREATE TABLE gtfs_stops (stop_id VARCHAR, stop_name VARCHAR, stop_lat DOUBLE PRECISION, stop_lon DOUBLE PRECISION)"
            )
            conn.execute(
                "INSERT INTO gtfs_stops VALUES ('001','Test stop',-36.8,174.7)"
            )
        subprocess.run([sys.executable, str(ROOT / "pipeline.py"), "build"], check=True)
        assert (
            read_frame("SELECT count(*) AS n FROM fct_trip_observation").iloc[0].n == 1
        )
        import pandas as pd

        expected = pd.Timestamp(1783396800, unit="s", tz="UTC").tz_convert(
            "Pacific/Auckland"
        )
        actual = read_frame(
            "SELECT observation_date, local_hour FROM fct_trip_observation"
        ).iloc[0]
        assert pd.Timestamp(actual.observation_date).date() == expected.date()
        assert actual.local_hour == expected.hour
        run_pipeline(feed())
        run_pipeline(feed(timestamp=1700000000, trip_id="late", delay=400))
        subprocess.run([sys.executable, str(ROOT / "pipeline.py"), "build"], check=True)
        assert (
            read_frame("SELECT count(*) AS n FROM fct_trip_observation").iloc[0].n == 2
        )
        assert (
            read_frame("SELECT sum(sample_count) AS n FROM route_hourly_reliability")
            .iloc[0]
            .n
            == 2
        )
        assert (
            read_frame(
                "SELECT punctuality FROM fct_trip_observation WHERE trip_id='late'"
            )
            .iloc[0]
            .punctuality
            == "Late"
        )
        from streamlit.testing.v1 import AppTest

        app = AppTest.from_file(str(ROOT / "dashboard.py"), default_timeout=30).run()
        assert not app.exception, str(app.exception)
        assert len(app.get("plotly_chart")) >= 4
        app.sidebar.radio[0].set_value("Route comparison").run()
        assert not app.exception, str(app.exception)
        assert len(app.get("plotly_chart")) == 5
        app.multiselect[0].set_value([]).run()
        assert not app.exception and len(app.info) >= 1
        app.sidebar.radio[0].set_value("Stop hotspots").run()
        app.number_input[0].set_value(1).run()
        assert not app.exception, str(app.exception)
        assert len(app.get("plotly_chart")) == 4
        app.sidebar.radio[0].set_value("Overview").run()
        assert not app.exception, str(app.exception)
        app.sidebar.radio[0].set_value("Route reliability").run()
        assert not app.exception, str(app.exception)
        app.number_input[0].set_value(1).run()
        assert not app.exception, str(app.exception)
        app.selectbox[0].set_value("Weekend").run()
        assert not app.exception, str(app.exception)
        app.sidebar.radio[0].set_value("Data health").run()
        assert not app.exception, str(app.exception)
        print(
            "PASS: initial/incremental dbt builds, reconciliation, six dashboard pages and empty-selection handling"
        )


if __name__ == "__main__":
    check()
