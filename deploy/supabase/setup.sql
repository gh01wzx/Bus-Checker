-- One-time setup for publishing Bus Checker to Supabase (or any hosted PostgreSQL).
-- Run in the Supabase SQL editor as the `postgres` user. Replace both passwords first.
--
--   bus_publisher  writes the marts schema (used by `python -m bus_checker sync-remote`)
--   bus_dashboard  reads the marts schema only (used by the online Streamlit app)
--
-- The marts schema is not exposed through Supabase's REST API (only `public` is by default),
-- so the data is reachable only through these database roles.

CREATE ROLE bus_publisher LOGIN PASSWORD 'replace-with-a-long-random-password';
CREATE ROLE bus_dashboard LOGIN PASSWORD 'replace-with-another-long-random-password';

-- Required on PostgreSQL 16+ so `postgres` may create objects owned by the publisher.
GRANT bus_publisher TO postgres;

CREATE SCHEMA IF NOT EXISTS marts AUTHORIZATION bus_publisher;
GRANT USAGE ON SCHEMA marts TO bus_dashboard;
ALTER DEFAULT PRIVILEGES FOR ROLE bus_publisher IN SCHEMA marts GRANT SELECT ON TABLES TO bus_dashboard;

-- Publications replace a few days of partitions in one transaction; allow them time.
ALTER ROLE bus_publisher SET statement_timeout = '15min';
-- The dashboard only ever reads, and should never hold a query for long.
ALTER ROLE bus_dashboard SET default_transaction_read_only = on;
ALTER ROLE bus_dashboard SET statement_timeout = '30s';

-- Connection strings (Project Settings -> Database -> Connection string -> Session pooler):
--   publisher: postgresql://bus_publisher.<project-ref>:<password>@aws-0-<region>.pooler.supabase.com:5432/postgres?sslmode=require
--   dashboard: postgresql://bus_dashboard.<project-ref>:<password>@aws-0-<region>.pooler.supabase.com:5432/postgres?sslmode=require
