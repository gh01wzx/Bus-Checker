{{ config(materialized='incremental', unique_key='service_date', incremental_strategy='delete+insert', on_schema_change='fail', indexes=[{'columns': ['service_date']}]) }}

{#- Reliability per operator. Operators hold contracts per route id, so this joins on the
    exact GTFS route id rather than the public route number. -#}

with
{% if is_incremental() %}
changed as (
    {{ changed_dates(ref('fct_stop_events')) }}
    union
    {{ changed_dates(ref('fct_trips')) }}
),
{% endif %}

operators as (
    select
        r.route_id,
        coalesce(a.agency_name, r.agency_id, 'Unknown operator') as operator_name,
        r.mode
    from {{ ref('stg_gtfs_routes') }} as r
    left join {{ ref('stg_gtfs_agency') }} as a on a.agency_id = r.agency_id
),

events as (
    select
        e.service_date,
        coalesce(o.operator_name, 'Unknown operator') as operator_name,
        coalesce(o.mode, 'Unknown') as mode,
        {{ punctuality_counts('e.punctuality') }},
        cast(sum(e.delay_sec) as bigint) as delay_sum_sec,
        cast(count(distinct e.route_key) as bigint) as routes,
        max(e.ingested_at) as ingested_at
    from {{ ref('fct_stop_events') }} as e
    left join operators as o on o.route_id = e.route_id
    where true {{ in_changed('e.service_date') }}
    group by 1, 2, 3
),

trips as (
    select
        t.service_date,
        coalesce(o.operator_name, 'Unknown operator') as operator_name,
        coalesce(o.mode, 'Unknown') as mode,
        cast(sum(case when t.stops_observed > 0 then 1 else 0 end) as bigint) as trips_tracked,
        cast(sum(case when t.is_cancelled then 1 else 0 end) as bigint) as trips_cancelled,
        max(t.ingested_at) as ingested_at
    from {{ ref('fct_trips') }} as t
    left join operators as o on o.route_id = t.route_id
    where true {{ in_changed('t.service_date') }}
    group by 1, 2, 3
),

keys as (
    select service_date, operator_name, mode from events
    union
    select service_date, operator_name, mode from trips
)

select
    k.service_date,
    {{ day_type('k.service_date') }} as day_type,
    k.operator_name,
    k.mode,
    coalesce(e.events, 0) as events,
    coalesce(e.on_time, 0) as on_time,
    coalesce(e.early, 0) as early,
    coalesce(e.late, 0) as late,
    coalesce(e.delay_sum_sec, 0) as delay_sum_sec,
    coalesce(e.routes, 0) as routes,
    coalesce(t.trips_tracked, 0) as trips_tracked,
    coalesce(t.trips_cancelled, 0) as trips_cancelled,
    {{ latest_of(['e.ingested_at', 't.ingested_at']) }} as ingested_at
from keys as k
left join events as e
    on e.service_date = k.service_date and e.operator_name = k.operator_name and e.mode = k.mode
left join trips as t
    on t.service_date = k.service_date and t.operator_name = k.operator_name and t.mode = k.mode
