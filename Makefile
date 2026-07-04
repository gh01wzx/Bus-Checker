collect:
	python pipeline.py

load-gtfs:
	python load_gtfs.py

dbt-run:
	cd bus_dbt && dbt run

dbt-test:
	cd bus_dbt && dbt test

dashboard:
	streamlit run dashboard.py

airflow-up:
	cd airflow && docker compose up -d

airflow-down:
	cd airflow && docker compose down