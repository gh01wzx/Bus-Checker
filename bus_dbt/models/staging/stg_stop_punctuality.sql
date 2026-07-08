select
    stop_id,
    trip_id,
    route_id,
    stop_sequence,
    delay as delay_sec
from {{ source('public', 'stop_punctuality') }}
where route_id in (
    select route_id from {{ source('public', 'gtfs_routes') }}
    where route_type = 3
)