select
    p.captured_at,
    p.route_id,
    p.trip_id,
    p.delay as delay_sec,
    p.direction_id
from {{ source('main', 'trip_punctuality') }} p
where p.route_id in (
    select route_id from {{ source('main', 'gtfs_routes') }}
)