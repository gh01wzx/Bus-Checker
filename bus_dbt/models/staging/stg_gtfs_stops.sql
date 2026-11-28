select
    stop_id,
    {{ stop_key('stop_id') }} as stop_key,
    stop_code,
    coalesce(stop_name, stop_id) as stop_name,
    stop_lat as latitude,
    stop_lon as longitude,
    coalesce(location_type, 0) as location_type,
    parent_station
from {{ source('raw', 'gtfs_stops') }}
