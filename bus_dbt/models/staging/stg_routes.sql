select 
    route_id,
    route_short_name,
    route_type
from {{source('public', 'gtfs_routes')}}