# syntax=docker/dockerfile:1
# One image for the Airflow components and the dashboard. The application runs in its own
# virtualenv (/opt/bus-venv) so dbt/pandas versions never fight Airflow's constraints.
ARG AIRFLOW_IMAGE=apache/airflow:3.2.2
FROM ${AIRFLOW_IMAGE}

USER root
RUN mkdir -p /opt/bus-venv /opt/bus-checker /opt/bus-data/warehouse /opt/bus-data/published \
        /opt/bus-data/archive /opt/airflow/state \
    && chown -R airflow:0 /opt/bus-venv /opt/bus-checker /opt/bus-data /opt/airflow/state

USER airflow
COPY --chown=airflow:0 requirements.txt requirements-pipeline.txt /opt/bus-checker/
RUN python -m venv /opt/bus-venv \
    && /opt/bus-venv/bin/pip install --no-cache-dir --upgrade pip \
    && /opt/bus-venv/bin/pip install --no-cache-dir -r /opt/bus-checker/requirements-pipeline.txt

WORKDIR /opt/bus-checker
COPY --chown=airflow:0 bus_checker/ bus_checker/
COPY --chown=airflow:0 bus_dbt/ bus_dbt/
COPY --chown=airflow:0 .streamlit/ .streamlit/
COPY --chown=airflow:0 streamlit_app.py pyproject.toml ./
COPY --chown=airflow:0 airflow/dags/ /opt/airflow/dags/

ENV BUS_APP_DIR=/opt/bus-checker \
    BUS_CLI="/opt/bus-venv/bin/python -m bus_checker" \
    BUS_DUCKDB_PATH=/opt/bus-data/warehouse/bus.duckdb \
    BUS_SNAPSHOT_PATH=/opt/bus-data/published/bus_dashboard.duckdb \
    BUS_ARCHIVE_DIR=/opt/bus-data/archive \
    PYTHONUNBUFFERED=1 \
    PYTHONUTF8=1

# Fail the build early if the application or the dbt project cannot even be imported/parsed.
RUN /opt/bus-venv/bin/python -m bus_checker --version \
    && BUS_BACKEND=duckdb BUS_DUCKDB_PATH=/tmp/parse.duckdb /opt/bus-venv/bin/python -c \
       "from dbt.cli.main import cli; cli()" parse --project-dir bus_dbt --profiles-dir bus_dbt \
       --target duckdb --target-path /tmp/dbt-parse --log-path /tmp/dbt-parse \
    && rm -rf /tmp/dbt-parse /tmp/parse.duckdb*
