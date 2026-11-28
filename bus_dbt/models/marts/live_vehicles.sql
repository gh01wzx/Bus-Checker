{#- The latest position of every vehicle in the most recent collection window, enriched with
    its route and the delay it last reported at a stop. Rebuilt on every run (small). -#}

with latest as (
    select max(ingested_at) as latest_ingested_at
    from {{ ref('stg_vehicle_positions') }}
),

recent as (
    select p.*
    from {{ ref('stg_vehicle_positions') }} as p
    cross join latest as l
    where p.ingested_at >= l.latest_ingested_at - interval '{{ var("live_window_minutes") }} minutes'
        and p.in_region
),

ranked as (
    select
        recent.*,
        row_number() over (partition by vehicle_id order by position_ts desc, feed_ts desc) as position_rank
    from recent
),

vehicles as (
    select * from ranked where position_rank = 1
),

as_of as (
    select max(feed_ts) as as_of from recent
),

trip_events as (
    select
        e.service_date,
        e.trip_id,
        e.delay_sec,
        e.punctuality,
        e.stop_key,
        e.event_ts,
        row_number() over (partition by e.service_date, e.trip_id order by e.event_ts desc) as event_rank
    from {{ ref('fct_stop_events') }} as e
    where e.service_date in (select distinct service_date from vehicles where trip_id is not null)
        and e.trip_id in (select trip_id from vehicles where trip_id is not null)
)

select
    v.vehicle_id,
    v.vehicle_label,
    v.license_plate,
    v.trip_id,
    v.route_id,
    v.route_key,
    coalesce(r.route_short_name, v.route_key) as route_short_name,
    r.route_label,
    case
        when not v.in_service then 'Not in service'
        else coalesce(r.mode, 'Unknown')
    end as mode,
    r.route_color,
    v.direction_id,
    v.latitude,
    v.longitude,
    v.bearing,
    v.speed_kmh,
    v.occupancy_status,
    v.position_ts,
    v.in_service,
    te.delay_sec,
    coalesce(te.punctuality, 'unknown') as punctuality,
    te.stop_key as last_stop_key,
    s.stop_name as last_stop_name,
    te.event_ts as last_stop_event_ts,
    a.as_of,
    {{ seconds_between('a.as_of', 'v.position_ts') }} as position_age_sec
from vehicles as v
cross join as_of as a
left join {{ ref('dim_routes') }} as r on r.route_key = v.route_key
left join trip_events as te
    on te.service_date = v.service_date and te.trip_id = v.trip_id and te.event_rank = 1
left join {{ ref('dim_stops') }} as s on s.stop_key = te.stop_key
