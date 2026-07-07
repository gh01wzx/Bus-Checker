select
    route_id,
    any_value(trip_headsign) as trip_headsign
from {{ source('public', 'gtfs_trips') }}
group by route_id