select
    sp.route_id,
    sp.stop_id,
    ss.stop_name,
    r.route_short_name as route_no,
    t.trip_headsign as route_name,
    round(avg(sp.delay_sec), 2) as avg_delay_sec,
    count(*) as sample_count,
    min(sp.stop_sequence) as stop_sequence
from {{ ref('stg_stop_punctuality') }} sp
left join {{ ref('stg_stops') }} ss on sp.stop_id = ss.stop_id
left join {{ ref('stg_routes') }} r on sp.route_id = r.route_id
left join {{ ref('stg_trips') }} t on sp.route_id = t.route_id
group by sp.route_id, sp.stop_id, ss.stop_name, r.route_short_name, t.trip_headsign
order by avg_delay_sec desc