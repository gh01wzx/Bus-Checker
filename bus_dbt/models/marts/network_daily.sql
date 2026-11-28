{{ config(materialized='incremental', unique_key='service_date', incremental_strategy='delete+insert', on_schema_change='fail', indexes=[{'columns': ['service_date']}]) }}

{#- Network-wide daily KPIs per transport mode. Percentiles come from individual events. -#}

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
        e.service_date,
        r.mode,
        {{ punctuality_counts('e.punctuality') }},
        cast(sum(e.delay_sec) as bigint) as delay_sum_sec,
        percentile_cont(0.5) within group (order by e.delay_sec) as delay_p50_sec,
        percentile_cont(0.9) within group (order by e.delay_sec) as delay_p90_sec,
        percentile_cont(0.95) within group (order by e.delay_sec) as delay_p95_sec,
        max(e.ingested_at) as ingested_at
    from {{ ref('fct_stop_events') }} as e
    join {{ ref('dim_routes') }} as r on r.route_key = e.route_key
    where true {{ in_changed('e.service_date') }}
    group by 1, 2
),

trips as (
    select
        t.service_date,
        r.mode,
        cast(count(*) as bigint) as trips_reported,
        cast(sum(case when t.stops_observed > 0 then 1 else 0 end) as bigint) as trips_tracked,
        cast(sum(case when t.is_cancelled then 1 else 0 end) as bigint) as trips_cancelled,
        cast(count(distinct t.vehicle_id) as bigint) as vehicles,
        cast(count(distinct case when t.stops_observed > 0 then t.route_key end) as bigint) as routes_tracked,
        max(t.ingested_at) as ingested_at
    from {{ ref('fct_trips') }} as t
    join {{ ref('dim_routes') }} as r on r.route_key = t.route_key
    where true {{ in_changed('t.service_date') }}
    group by 1, 2
),

scheduled as (
    select
        s.service_date,
        r.mode,
        cast(sum(s.trips_scheduled) as bigint) as trips_scheduled,
        max(s.ingested_at) as ingested_at
    from {{ ref('fct_scheduled_service') }} as s
    join {{ ref('dim_routes') }} as r on r.route_key = s.route_key
    where true {{ in_changed('s.service_date') }}
    group by 1, 2
),

keys as (
    select service_date, mode from events
    union
    select service_date, mode from trips
    union
    select service_date, mode from scheduled
)

select
    k.service_date,
    {{ day_type('k.service_date') }} as day_type,
    k.mode,
    coalesce(e.events, 0) as events,
    coalesce(e.on_time, 0) as on_time,
    coalesce(e.early, 0) as early,
    coalesce(e.late, 0) as late,
    coalesce(e.delay_sum_sec, 0) as delay_sum_sec,
    e.delay_p50_sec,
    e.delay_p90_sec,
    e.delay_p95_sec,
    coalesce(t.trips_reported, 0) as trips_reported,
    coalesce(t.trips_tracked, 0) as trips_tracked,
    coalesce(t.trips_cancelled, 0) as trips_cancelled,
    coalesce(t.vehicles, 0) as vehicles,
    coalesce(t.routes_tracked, 0) as routes_tracked,
    coalesce(s.trips_scheduled, 0) as trips_scheduled,
    {{ latest_of(['e.ingested_at', 't.ingested_at', 's.ingested_at']) }} as ingested_at
from keys as k
left join events as e on e.service_date = k.service_date and e.mode = k.mode
left join trips as t on t.service_date = k.service_date and t.mode = k.mode
left join scheduled as s on s.service_date = k.service_date and s.mode = k.mode
