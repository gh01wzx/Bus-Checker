{#- Health of each collection feed, relative to the most recent fetch attempt. -#}

with runs as (
    select *
    from {{ ref('stg_fetch_runs') }}
    where started_at >= (select max(started_at) from {{ ref('stg_fetch_runs') }})
        - interval '{{ var("pipeline_history_days") }} days'
),

reference as (
    select max(started_at) as reference_ts from runs
),

ranked as (
    select runs.*, row_number() over (partition by feed order by started_at desc) as attempt_rank
    from runs
),

latest as (
    select feed, status, started_at, error_type, error_message
    from ranked
    where attempt_rank = 1
)

select
    r.feed,
    max(l.status) as last_status,
    max(l.started_at) as last_attempt_at,
    max(l.error_type) as last_error_type,
    max(l.error_message) as last_error_message,
    max(case when r.is_ok then r.finished_at end) as last_success_at,
    max(case when r.is_ok then r.feed_ts end) as last_feed_ts,
    cast(sum(case when r.started_at >= f.reference_ts - interval '24 hours' then 1 else 0 end) as bigint) as attempts_24h,
    cast(sum(case when r.started_at >= f.reference_ts - interval '24 hours' and not r.is_ok then 1 else 0 end) as bigint) as failures_24h,
    cast(sum(case when r.started_at >= f.reference_ts - interval '24 hours' then coalesce(r.rows_inserted, 0) else 0 end) as bigint) as rows_inserted_24h,
    avg(case when r.started_at >= f.reference_ts - interval '24 hours' then r.duration_sec end) as avg_duration_sec_24h,
    avg(case when r.started_at >= f.reference_ts - interval '24 hours' and r.is_ok then r.feed_lag_sec end) as avg_feed_lag_sec_24h,
    max(f.reference_ts) as reference_ts
from runs as r
cross join reference as f
join latest as l on l.feed = r.feed
group by r.feed
