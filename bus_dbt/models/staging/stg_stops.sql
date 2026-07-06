select 
    stop_id,
    stop_name,
    stop_lat as stop_latitude,
    stop_lon as stop_longitude
from {{source('main', 'gtfs_stops')}}