{#- One row per public route (route_key), described by its current GTFS routes. Routes seen
    in realtime but missing from the current GTFS are kept with mode "Unknown". -#}

with routes as (
    select
        *,
        row_number() over (partition by route_key order by route_id desc) as version_rank
    from {{ ref('stg_gtfs_routes') }}
),

operators as (
    select
        r.route_key,
        count(distinct r.agency_id) as operator_count,
        min(coalesce(a.agency_name, r.agency_id)) as first_operator,
        max(coalesce(a.agency_name, r.agency_id)) as last_operator
    from {{ ref('stg_gtfs_routes') }} as r
    left join {{ ref('stg_gtfs_agency') }} as a on a.agency_id = r.agency_id
    group by 1
),

headsign_counts as (
    select route_key, direction_id, trip_headsign, count(*) as trips
    from {{ ref('stg_gtfs_trips') }}
    where trip_headsign is not null
    group by 1, 2, 3
),

headsigns as (
    select
        route_key,
        direction_id,
        trip_headsign,
        row_number() over (
            partition by route_key, direction_id order by trips desc, trip_headsign
        ) as headsign_rank
    from headsign_counts
),

observed as (
    select distinct route_key from {{ ref('fct_trips') }} where route_key is not null
),

all_routes as (
    select route_key from routes
    union
    select route_key from observed
)

select
    k.route_key,
    coalesce(r.route_short_name, k.route_key) as route_short_name,
    coalesce(r.mode, 'Unknown') as mode,
    r.route_type,
    case
        when o.operator_count > 1 then o.first_operator || ' / ' || o.last_operator
        else coalesce(o.first_operator, 'Unknown operator')
    end as operator_name,
    r.route_color,
    h0.trip_headsign as headsign_0,
    h1.trip_headsign as headsign_1,
    coalesce(r.route_short_name, k.route_key)
        || coalesce(' · ' || coalesce(h0.trip_headsign, h1.trip_headsign), '') as route_label,
    r.route_key is not null as in_current_gtfs
from all_routes as k
left join routes as r on r.route_key = k.route_key and r.version_rank = 1
left join operators as o on o.route_key = k.route_key
left join headsigns as h0
    on h0.route_key = k.route_key and h0.direction_id = 0 and h0.headsign_rank = 1
left join headsigns as h1
    on h1.route_key = k.route_key and h1.direction_id = 1 and h1.headsign_rank = 1
