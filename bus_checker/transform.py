"""Run dbt against the configured warehouse and record the outcome in ``ops.dbt_runs``."""

from __future__ import annotations

import json
import logging
import os
import subprocess
import sys
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from bus_checker.config import Settings, postgres_parts
from bus_checker.ids import new_uuid
from bus_checker.schema import DBT_RUNS, ensure_ready
from bus_checker.warehouse import quote_identifier, session

logger = logging.getLogger(__name__)
FULL_HISTORY_TEST_DAYS = 36_500


class BuildFailed(RuntimeError):
    def __init__(self, summary: DbtSummary) -> None:
        super().__init__(f"dbt {summary.command} failed: {summary.status}")
        self.summary = summary


@dataclass
class DbtSummary:
    invocation_id: str
    command: str
    started_at: datetime
    finished_at: datetime
    elapsed_sec: float | None
    status: str
    models_ok: int = 0
    models_error: int = 0
    tests_pass: int = 0
    tests_fail: int = 0
    tests_warn: int = 0
    skipped: int = 0
    failures: list[dict[str, Any]] = field(default_factory=list)

    def as_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["started_at"] = self.started_at.isoformat()
        data["finished_at"] = self.finished_at.isoformat()
        return data


def dbt_environment(settings: Settings) -> dict[str, str]:
    env = dict(os.environ)
    env.update(
        BUS_BACKEND=settings.backend,
        DBT_SEND_ANONYMOUS_USAGE_STATS="false",
        DBT_PROFILES_DIR=str(settings.dbt_project_dir),
        PYTHONUTF8="1",
    )
    if settings.backend == "duckdb":
        env["BUS_DUCKDB_PATH"] = str(settings.duckdb_path)
    else:
        parts = postgres_parts(settings.postgres_url, env)
        env.update(
            BUS_PG_HOST=parts.host,
            BUS_PG_PORT=str(parts.port),
            BUS_PG_USER=parts.user,
            DBT_ENV_SECRET_PG_PASSWORD=parts.password,
            BUS_PG_DATABASE=parts.database,
            BUS_PG_SSLMODE=parts.sslmode,
        )
    return env


def _summarise(command: str, run_results: Path, started: datetime, returncode: int) -> DbtSummary:
    finished = datetime.now(UTC)
    summary = DbtSummary(
        invocation_id=new_uuid(),
        command=command,
        started_at=started,
        finished_at=finished,
        elapsed_sec=(finished - started).total_seconds(),
        status="success" if returncode == 0 else "error",
    )
    if not run_results.exists():
        summary.failures.append({"node": "dbt", "message": f"exit code {returncode}, no run_results.json"})
        return summary
    data = json.loads(run_results.read_text(encoding="utf-8"))
    summary.invocation_id = data.get("metadata", {}).get("invocation_id") or summary.invocation_id
    summary.elapsed_sec = data.get("elapsed_time", summary.elapsed_sec)
    for result in data.get("results", []):
        unique_id: str = result.get("unique_id", "")
        status = result.get("status")
        is_test = unique_id.startswith("test.")
        if status in ("success",):
            summary.models_ok += 1
        elif status == "pass":
            summary.tests_pass += 1
        elif status == "warn":
            summary.tests_warn += 1
        elif status == "skipped":
            summary.skipped += 1
        elif status in ("fail", "error", "runtime error"):
            if is_test:
                summary.tests_fail += 1
            else:
                summary.models_error += 1
            summary.failures.append(
                {
                    "node": unique_id,
                    "status": status,
                    "failures": result.get("failures"),
                    "message": (result.get("message") or "")[:500],
                }
            )
    if summary.models_error or summary.tests_fail:
        summary.status = "error"
    return summary


def _record(settings: Settings, summary: DbtSummary) -> None:
    values = {
        **asdict(summary),
        "failures": json.dumps(summary.failures[:50]),
    }
    columns = DBT_RUNS.column_names
    names = ", ".join(quote_identifier(c) for c in columns)
    try:
        with session(settings) as warehouse:
            warehouse.execute(
                f"INSERT INTO {DBT_RUNS.ref} ({names}) VALUES ({', '.join(':' + c for c in columns)})",
                {c: values.get(c) for c in columns},
            )
    except Exception:
        logger.exception("Could not record the dbt run summary")


def run_dbt(settings: Settings, command: list[str], record: bool = True) -> DbtSummary:
    target_dir = settings.dbt_target_dir
    target_dir.mkdir(parents=True, exist_ok=True)
    run_results = target_dir / "run_results.json"
    run_results.unlink(missing_ok=True)
    args = [
        sys.executable,
        "-c",
        "from dbt.cli.main import cli; cli()",
        *command,
        "--project-dir",
        str(settings.dbt_project_dir),
        "--profiles-dir",
        str(settings.dbt_project_dir),
        "--target",
        settings.backend,
        "--target-path",
        str(target_dir),
        "--log-path",
        str(target_dir / "logs"),
    ]
    started = datetime.now(UTC)
    logger.info("Running dbt %s", " ".join(command))
    # dbt's console output goes to stderr so stdout stays a clean JSON summary.
    completed = subprocess.run(
        args,
        env=dbt_environment(settings),
        cwd=settings.dbt_project_dir,
        stdout=sys.stderr,
        check=False,
    )
    summary = _summarise(command[0], run_results, started, completed.returncode)
    if completed.returncode != 0 and summary.status == "success":
        summary.status = "error"
    if record:
        _record(settings, summary)
    logger.info(
        "dbt %s %s: ok=%s errors=%s tests pass=%s fail=%s warn=%s skipped=%s in %.1fs",
        command[0],
        summary.status,
        summary.models_ok,
        summary.models_error,
        summary.tests_pass,
        summary.tests_fail,
        summary.tests_warn,
        summary.skipped,
        summary.elapsed_sec or 0,
    )
    return summary


def build(
    settings: Settings,
    *,
    full_refresh: bool = False,
    full_tests: bool = False,
    select: str | None = None,
) -> DbtSummary:
    """``dbt build``: seeds, models and tests in dependency order. Raises on failure."""
    ensure_ready(settings)
    command = ["build"]
    if full_refresh:
        command.append("--full-refresh")
    if select:
        command += ["--select", select]
    if full_tests:
        command += ["--vars", json.dumps({"test_window_days": FULL_HISTORY_TEST_DAYS})]
    summary = run_dbt(settings, command)
    if summary.status != "success":
        raise BuildFailed(summary)
    return summary


def generate_docs(settings: Settings) -> DbtSummary:
    return run_dbt(settings, ["docs", "generate"], record=False)
