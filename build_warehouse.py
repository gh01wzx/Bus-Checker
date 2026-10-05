import argparse
import os
import subprocess
import sys
import tempfile
from pathlib import Path
import yaml
from warehouse import ROOT, backend, bootstrap, connect, duckdb_path


def build(full_refresh=False, docs=False):
    with connect(write=True) as conn:
        bootstrap(conn)
    kind = backend()
    env = dict(os.environ, DBT_SEND_ANONYMOUS_USAGE_STATS="false")
    if kind == "duckdb":
        output = {
            "type": "duckdb",
            "path": duckdb_path(),
            "schema": "main",
            "threads": 1,
        }
    else:
        from sqlalchemy.engine import make_url

        url = make_url(os.environ["SUPABASE_DB_URL"])
        env.update(
            BUS_DBT_HOST=url.host or "localhost",
            BUS_DBT_PORT=str(url.port or 5432),
            BUS_DBT_USER=url.username or "",
            DBT_ENV_SECRET_BUS_PASSWORD=url.password or "",
            BUS_DBT_DATABASE=url.database or "postgres",
        )
        output = {
            "type": "postgres",
            "host": "{{ env_var('BUS_DBT_HOST') }}",
            "port": "{{ env_var('BUS_DBT_PORT') | int }}",
            "user": "{{ env_var('BUS_DBT_USER') }}",
            "password": "{{ env_var('DBT_ENV_SECRET_BUS_PASSWORD') }}",
            "dbname": "{{ env_var('BUS_DBT_DATABASE') }}",
            "schema": "public",
            "threads": 1,
            "sslmode": url.query.get("sslmode", "require"),
        }
    with tempfile.TemporaryDirectory(prefix="bus-dbt-") as temporary:
        Path(temporary, "profiles.yml").write_text(
            yaml.safe_dump({"bus_dbt": {"target": "bus", "outputs": {"bus": output}}}),
            encoding="utf-8",
        )
        args = [
            sys.executable,
            "-c",
            "from dbt.cli.main import cli; cli()",
            "docs" if docs else "build",
        ]
        if docs:
            args.append("generate")
        args += ["--project-dir", str(ROOT / "bus_dbt"), "--profiles-dir", temporary]
        if full_refresh and not docs:
            args.append("--full-refresh")
        subprocess.run(args, env=env, check=True, cwd=ROOT)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--full-refresh", action="store_true", help="Rebuild facts after logic changes"
    )
    parser.add_argument(
        "--docs",
        action="store_true",
        help="Generate dbt lineage and column documentation",
    )
    args = parser.parse_args()
    build(args.full_refresh, args.docs)
