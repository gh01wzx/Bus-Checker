{{ config(materialized='incremental', unique_key='service_date', incremental_strategy='delete+insert', on_schema_change='fail', indexes=[{'columns': ['service_date']}]) }}

with
{% if is_incremental() %}
changed as ({{ changed_dates(ref('route_hourly')) }}),
{% endif %}

hourly as (
    select
        h.service_date,
        h.day_type,
        h.hour,
        r.mode,
        cast(sum(h.events) as bigint) as events,
        cast(sum(h.on_time) as bigint) as on_time,
        cast(sum(h.early) as bigint) as early,
        cast(sum(h.late) as bigint) as late,
        cast(sum(h.delay_sum_sec) as bigint) as delay_sum_sec,
        max(h.ingested_at) as ingested_at
    from {{ ref('route_hourly') }} as h
    join {{ ref('dim_routes') }} as r on r.route_key = h.route_key
    where true {{ in_changed('h.service_date') }}
    group by 1, 2, 3, 4
)

select * from hourly
