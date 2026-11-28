select
    load_id,
    started_at,
    finished_at,
    status,
    feed_version,
    feed_start_date,
    feed_end_date,
    row_counts,
    error_message
from {{ source('ops', 'gtfs_loads') }}
