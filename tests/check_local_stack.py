"""Run inside the fixture stack's dashboard container after a successful DAG run."""

from streamlit.testing.v1 import AppTest

from bus_checker.database import backend, read_frame


def check():
    summary = read_frame("SELECT * FROM network_summary").iloc[0]
    assert summary.total_trips == 1 and summary.on_time_pct == 100
    assert read_frame("SELECT count(*) n FROM bus_raw_batches").iloc[0].n == 1
    if backend() == "postgres":
        assert not read_frame(
            "SELECT has_table_privilege(current_user, 'bus_raw_batches', 'INSERT') AS writable"
        ).iloc[0].writable
    app = AppTest.from_file("dashboard.py", default_timeout=30).run()
    for page in app.sidebar.radio[0].options:
        app.sidebar.radio[0].set_value(page).run()
        assert not app.exception, (page, app.exception)
        assert not app.error, (page, app.error)
        if page == "Route comparison":
            assert len(app.get("plotly_chart")) == 5
    print(f"PASS: {backend()} fixture ingestion, dbt metrics and six dashboard pages")


if __name__ == "__main__":
    check()
