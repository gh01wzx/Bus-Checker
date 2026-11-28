-- Runs once, when the PostgreSQL volume is first initialised.
-- Separate databases and owners for Airflow metadata and the bus warehouse, plus a
-- read-only role that can see only the dashboard contract (the marts schema).
\set ON_ERROR_STOP on
\getenv airflow_password AIRFLOW_DB_PASSWORD
\getenv writer_password BUS_WRITER_PASSWORD
\getenv reader_password BUS_READER_PASSWORD

CREATE ROLE orchestrator LOGIN PASSWORD :'airflow_password';
CREATE ROLE bus_writer LOGIN PASSWORD :'writer_password';
CREATE ROLE bus_reader LOGIN PASSWORD :'reader_password';
CREATE DATABASE airflow OWNER orchestrator;
CREATE DATABASE bus OWNER bus_writer;
REVOKE ALL ON DATABASE airflow FROM PUBLIC;
REVOKE ALL ON DATABASE bus FROM PUBLIC;
GRANT CONNECT ON DATABASE bus TO bus_reader;

\connect bus
REVOKE CREATE ON SCHEMA public FROM PUBLIC;
SET ROLE bus_writer;
CREATE SCHEMA IF NOT EXISTS raw;
CREATE SCHEMA IF NOT EXISTS ops;
CREATE SCHEMA IF NOT EXISTS staging;
CREATE SCHEMA IF NOT EXISTS core;
CREATE SCHEMA IF NOT EXISTS marts;
GRANT USAGE ON SCHEMA marts TO bus_reader;
ALTER DEFAULT PRIVILEGES FOR ROLE bus_writer IN SCHEMA marts GRANT SELECT ON TABLES TO bus_reader;
RESET ROLE;
ALTER ROLE bus_reader SET default_transaction_read_only = on;
ALTER ROLE bus_reader SET statement_timeout = '60s';
