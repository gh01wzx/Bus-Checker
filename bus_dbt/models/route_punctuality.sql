select
    r.route_id,
    coalesce(rt.route_short_name, r.route_id) as route_no,
    coalesce(t.trip_headsign, r.route_id) as route_name,
    round(avg(r.delay_sec), 2) as avg_delay_sec,
    count(*) as trip_count
from {{ ref('stg_trip_punctuality') }} r
left join {{ ref('stg_trips') }} t on r.route_id = t.route_id
left join {{ ref("stg_routes")}} rt on r.route_id = rt.route_id
group by r.route_id, rt.route_short_name, t.trip_headsign
order by avg_delay_sec desc