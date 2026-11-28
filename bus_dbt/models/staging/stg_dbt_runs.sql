select
    invocation_id,
    command,
    started_at,
    finished_at,
    elapsed_sec,
    status,
    models_ok,
    models_error,
    tests_pass,
    tests_fail,
    tests_warn,
    skipped,
    failures
from {{ source('ops', 'dbt_runs') }}
