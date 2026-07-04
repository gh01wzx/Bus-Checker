select
    route_id,
    any_value(trip_headsign) as trip_headsign
from {{ source('main', 'gtfs_trips') }}
group by route_id