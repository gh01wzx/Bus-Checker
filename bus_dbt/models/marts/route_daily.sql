{{ config(materialized='incremental', unique_key='service_date', incremental_strategy='delete+insert', on_schema_change='fail', indexes=[{'columns': ['service_date']}]) }}

{#- Daily reliability and service delivery per route direction. -#}

with
{% if is_incremental() %}
changed as (
    {{ changed_dates(ref('fct_stop_events')) }}
    union
    {{ changed_dates(ref('fct_trips')) }}
),
{% endif %}

events as (
    select
        service_date,
        route_key,
        direction_id,
        {{ punctuality_counts() }},
        cast(sum(delay_sec) as bigint) as delay_sum_sec,
        sum(cast(delay_sec as double precision) * delay_sec) as delay_sq_sum,
        percentile_cont(0.5) within group (order by delay_sec) as delay_p50_sec,
        percentile_cont(0.9) within group (order by delay_sec) as delay_p90_sec,
        max(delay_sec) as delay_max_sec,
        max(ingested_at) as ingested_at
    from {{ ref('fct_stop_events') }}
    where route_key is not null {{ in_changed() }}
    group by 1, 2, 3
),

trips as (
    select
        service_date,
        route_key,
        direction_id,
        cast(count(*) as bigint) as trips_reported,
        cast(sum(case when stops_observed > 0 then 1 else 0 end) as bigint) as trips_tracked,
        cast(sum(case when is_cancelled then 1 else 0 end) as bigint) as trips_cancelled,
        cast(sum(case when is_added then 1 else 0 end) as bigint) as trips_added,
        cast(count(distinct vehicle_id) as bigint) as vehicles,
        max(ingested_at) as ingested_at
    from {{ ref('fct_trips') }}
    where route_key is not null {{ in_changed() }}
    group by 1, 2, 3
),

scheduled as (
    select
        service_date,
        route_key,
        direction_id,
        cast(sum(trips_scheduled) as bigint) as trips_scheduled,
        max(ingested_at) as ingested_at
    from {{ ref('fct_scheduled_service') }}
    where true {{ in_changed() }}
    group by 1, 2, 3
),

keys as (
    select service_date, route_key, direction_id from events
    union
    select service_date, route_key, direction_id from trips
    union
    select service_date, route_key, direction_id from scheduled
)

select
    k.service_date,
    {{ day_type('k.service_date') }} as day_type,
    k.route_key,
    k.direction_id,
    coalesce(e.events, 0) as events,
    coalesce(e.on_time, 0) as on_time,
    coalesce(e.early, 0) as early,
    coalesce(e.late, 0) as late,
    coalesce(e.delay_sum_sec, 0) as delay_sum_sec,
    coalesce(e.delay_sq_sum, 0) as delay_sq_sum,
    e.delay_p50_sec,
    e.delay_p90_sec,
    e.delay_max_sec,
    coalesce(t.trips_reported, 0) as trips_reported,
    coalesce(t.trips_tracked, 0) as trips_tracked,
    coalesce(t.trips_cancelled, 0) as trips_cancelled,
    coalesce(t.trips_added, 0) as trips_added,
    coalesce(t.vehicles, 0) as vehicles,
    coalesce(s.trips_scheduled, 0) as trips_scheduled,
    {{ latest_of(['e.ingested_at', 't.ingested_at', 's.ingested_at']) }} as ingested_at
from keys as k
left join events as e
    on e.service_date = k.service_date and e.route_key = k.route_key and e.direction_id = k.direction_id
left join trips as t
    on t.service_date = k.service_date and t.route_key = k.route_key and t.direction_id = k.direction_id
left join scheduled as s
    on s.service_date = k.service_date and s.route_key = k.route_key and s.direction_id = k.direction_id
