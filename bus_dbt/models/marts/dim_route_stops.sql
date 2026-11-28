{#- Ordered stops of the dominant pattern of each route direction (for stop profiles). -#}

with patterns as (
    select
        *,
        dense_rank() over (
            partition by route_key, direction_id order by pattern_trip_count desc, route_id
        ) as pattern_rank
    from {{ ref('stg_gtfs_route_stops') }}
)

select
    p.route_key,
    p.direction_id,
    p.stop_order,
    p.stop_key,
    coalesce(s.stop_name, p.stop_id) as stop_name,
    s.latitude,
    s.longitude,
    p.pattern_trip_count
from patterns as p
left join {{ ref('dim_stops') }} as s on s.stop_key = p.stop_key
where p.pattern_rank = 1
