FROM apache/airflow:3.2.2-python3.11
USER airflow
WORKDIR /opt/airflow/bus-checker
COPY --chown=airflow:0 requirements.txt ./
# Keep application/dbt dependencies independent of Airflow's constraints.
RUN python -m venv /opt/airflow/bus-venv \
    && /opt/airflow/bus-venv/bin/pip install --no-cache-dir -r requirements.txt \
    && mkdir -p /opt/airflow/warehouse /opt/airflow/published /opt/airflow/state
COPY --chown=airflow:0 bus_checker/ bus_checker/
COPY --chown=airflow:0 bus_dbt/ bus_dbt/
COPY --chown=airflow:0 pipeline.py dashboard.py ./
COPY --chown=airflow:0 airflow/dags/ /opt/airflow/dags/
