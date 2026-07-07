select
    stp.route_id,
    stp.direction_id,
    t.trip_headsign,
    round(avg(stp.delay_sec), 2) as avg_delay_sec,
    round(100.0 * count(*) filter (
        where stp.delay_sec between {{ var('on_time_early') }} and {{ var('on_time_late') }}
    ) / count(*), 2) as on_time_pct,
    count(*) as trip_count
from {{ ref("stg_trip_punctuality") }} stp
left join {{ ref("stg_trips_by_direction") }} t
    on stp.route_id = t.route_id and stp.direction_id = t.direction_id
group by stp.route_id, stp.direction_id, t.trip_headsign
