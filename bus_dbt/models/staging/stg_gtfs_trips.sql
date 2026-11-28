select
    trip_id,
    route_id,
    {{ route_key('route_id') }} as route_key,
    service_id,
    trip_headsign,
    coalesce(direction_id, -1) as direction_id,
    shape_id,
    first_departure_sec,
    last_arrival_sec,
    stop_count,
    first_stop_id,
    last_stop_id,
    case
        when first_departure_sec is not null
            then cast(floor(first_departure_sec / 3600.0) as integer) % 24
    end as start_hour
from {{ source('raw', 'gtfs_trips') }}
