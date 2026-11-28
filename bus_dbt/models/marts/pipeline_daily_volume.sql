select
    started_local_date as collection_date,
    feed,
    cast(count(*) as bigint) as attempts,
    cast(sum(case when not is_ok then 1 else 0 end) as bigint) as failures,
    cast(sum(case when status = 'unchanged' then 1 else 0 end) as bigint) as unchanged,
    cast(sum(coalesce(rows_inserted, 0)) as bigint) as rows_inserted,
    cast(sum(coalesce(rows_duplicate, 0)) as bigint) as rows_duplicate,
    cast(sum(coalesce(rows_rejected, 0)) as bigint) as rows_rejected,
    cast(sum(coalesce(payload_bytes, 0)) as bigint) as payload_bytes,
    avg(duration_sec) as avg_duration_sec
from {{ ref('stg_fetch_runs') }}
where started_at >= (select max(started_at) from {{ ref('stg_fetch_runs') }})
    - interval '{{ var("pipeline_volume_days") }} days'
group by 1, 2
