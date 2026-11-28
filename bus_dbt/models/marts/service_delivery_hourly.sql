{{ config(materialized='incremental', unique_key='service_date', incremental_strategy='delete+insert', on_schema_change='fail', indexes=[{'columns': ['service_date']}]) }}

{#- Scheduled versus realtime-tracked trips by scheduled start hour. A scheduled trip with
    no realtime data is not necessarily a missed trip: it may simply lack tracking. -#}

with
{% if is_incremental() %}
changed as ({{ changed_dates(ref('fct_trips')) }}),
{% endif %}

trips as (
    select
        service_date,
        coalesce(start_hour, -1) as start_hour,
        route_key,
        direction_id,
        cast(count(*) as bigint) as trips_reported,
        cast(sum(case when stops_observed > 0 then 1 else 0 end) as bigint) as trips_tracked,
        cast(sum(case when is_cancelled then 1 else 0 end) as bigint) as trips_cancelled,
        max(ingested_at) as ingested_at
    from {{ ref('fct_trips') }}
    where route_key is not null {{ in_changed() }}
    group by 1, 2, 3, 4
),

scheduled as (
    select service_date, start_hour, route_key, direction_id, trips_scheduled, ingested_at
    from {{ ref('fct_scheduled_service') }}
    where true {{ in_changed() }}
),

keys as (
    select service_date, start_hour, route_key, direction_id from trips
    union
    select service_date, start_hour, route_key, direction_id from scheduled
)

select
    k.service_date,
    {{ day_type('k.service_date') }} as day_type,
    k.start_hour,
    k.route_key,
    k.direction_id,
    coalesce(s.trips_scheduled, 0) as trips_scheduled,
    coalesce(t.trips_reported, 0) as trips_reported,
    coalesce(t.trips_tracked, 0) as trips_tracked,
    coalesce(t.trips_cancelled, 0) as trips_cancelled,
    {{ latest_of(['t.ingested_at', 's.ingested_at']) }} as ingested_at
from keys as k
left join trips as t
    on t.service_date = k.service_date and t.start_hour = k.start_hour
    and t.route_key = k.route_key and t.direction_id = k.direction_id
left join scheduled as s
    on s.service_date = k.service_date and s.start_hour = k.start_hour
    and s.route_key = k.route_key and s.direction_id = k.direction_id
