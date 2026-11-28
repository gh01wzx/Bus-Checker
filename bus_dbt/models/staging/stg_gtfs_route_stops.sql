select
    route_id,
    {{ route_key('route_id') }} as route_key,
    direction_id,
    stop_order,
    stop_id,
    {{ stop_key('stop_id') }} as stop_key,
    pattern_trip_count
from {{ source('raw', 'gtfs_route_stops') }}
