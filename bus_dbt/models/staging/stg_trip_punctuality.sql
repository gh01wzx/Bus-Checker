select
    p.captured_at,
    p.route_id,
    p.trip_id,
    p.delay as delay_sec,
    p.direction_id
from {{ source('public', 'trip_punctuality') }} p
where p.route_id in (
    select route_id from {{ source('public', 'gtfs_routes') }}
    where route_type = 3
)