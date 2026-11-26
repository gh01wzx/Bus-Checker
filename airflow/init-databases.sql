\set ON_ERROR_STOP on
\getenv airflow_password AIRFLOW_DB_PASSWORD
\getenv writer_password BUS_WRITER_PASSWORD
\getenv reader_password BUS_READER_PASSWORD

CREATE ROLE orchestrator LOGIN PASSWORD :'airflow_password';
CREATE ROLE bus_writer LOGIN PASSWORD :'writer_password';
CREATE ROLE bus_reader LOGIN PASSWORD :'reader_password';
CREATE DATABASE airflow OWNER orchestrator;
CREATE DATABASE bus OWNER bus_writer;
REVOKE CONNECT ON DATABASE airflow FROM PUBLIC;
REVOKE CONNECT ON DATABASE bus FROM PUBLIC;
GRANT CONNECT ON DATABASE bus TO bus_reader;

\connect bus
GRANT USAGE ON SCHEMA public TO bus_reader;
ALTER DEFAULT PRIVILEGES FOR ROLE bus_writer IN SCHEMA public
    GRANT SELECT ON TABLES TO bus_reader;
