#!/usr/bin/env bash
# End-to-end stack test: build, start Airflow + warehouse + dashboard against the fixture
# server, run the realtime DAG through the scheduler, then verify through the dashboard role.
# Usage: BUS_BACKEND=postgres|duckdb tests/stack/run_stack.sh
set -euo pipefail
export MSYS_NO_PATHCONV=1  # Git Bash on Windows must not rewrite container paths
cd "$(dirname "$0")/../.."
export BUS_BACKEND="${BUS_BACKEND:-postgres}"
export COMPOSE_PROJECT_NAME="bus-checker-stack-${BUS_BACKEND}"
compose() { docker compose -f compose.yaml -f tests/stack/compose.fixture.yaml "$@"; }

cleanup() {
  status=$?
  if [ "$status" -ne 0 ]; then
    compose logs --tail=80 airflow-scheduler airflow-apiserver airflow-init || true
    compose exec -T airflow-scheduler bash -c \
      'find /opt/airflow/logs -path "*dag_id=bus_realtime*" -name "*.log" -exec tail -n 40 {} +' || true
  fi
  compose down -v --remove-orphans >/dev/null 2>&1 || true
  exit "$status"
}
trap cleanup EXIT

compose up -d --build --wait --wait-timeout 420
run_id="stack_$(date +%s)"
for _ in $(seq 1 30); do
  if compose exec -T airflow-scheduler airflow dags trigger bus_realtime --run-id "$run_id" >/dev/null 2>&1; then
    break
  fi
  sleep 5
done
for _ in $(seq 1 90); do
  state=$(compose exec -T airflow-scheduler airflow dags state bus_realtime "$run_id" 2>/dev/null | tail -n 1 | tr -d '\r')
  case "$state" in
    success) echo "DAG run $run_id succeeded"; break ;;
    failed) echo "DAG run $run_id failed"; exit 1 ;;
  esac
  sleep 5
done
[ "${state:-}" = "success" ] || { echo "DAG run did not finish (state: ${state:-unknown})"; exit 1; }
compose exec -T dashboard /opt/bus-venv/bin/python - < tests/stack/check_stack.py
