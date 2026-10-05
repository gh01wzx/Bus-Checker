collect:
	python pipeline.py collect

load-gtfs:
	python pipeline.py load-gtfs

dbt-run:
	python pipeline.py build

dbt-test:
	python pipeline.py build

test:
	python -m unittest discover -s tests -v

dbt-docs:
	python pipeline.py build --docs

dashboard:
	streamlit run dashboard.py

airflow-up:
	cd airflow && docker compose up -d

airflow-down:
	cd airflow && docker compose down
