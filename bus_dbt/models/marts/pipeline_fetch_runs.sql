select
    fetch_id,
    feed,
    source,
    started_at,
    duration_sec,
    status,
    http_status,
    feed_ts,
    feed_lag_sec,
    entity_count,
    rows_parsed,
    rows_inserted,
    rows_duplicate,
    rows_rejected,
    payload_bytes,
    error_type
from {{ ref('stg_fetch_runs') }}
where started_at >= (select max(started_at) from {{ ref('stg_fetch_runs') }})
    - interval '{{ var("pipeline_history_days") }} days'
