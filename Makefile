collect:
	python pipeline.py

load-gtfs:
	python load_gtfs.py

dbt-run:
	python build_warehouse.py

dbt-test:
	python build_warehouse.py

test:
	python -m unittest discover -s tests -v

dbt-docs:
	python build_warehouse.py --docs

dashboard:
	streamlit run dashboard.py

airflow-up:
	cd airflow && docker compose up -d

airflow-down:
	cd airflow && docker compose down
