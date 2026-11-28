select
    route_id,
    {{ route_key('route_id') }} as route_key,
    direction_id,
    shape_id,
    point_order,
    latitude,
    longitude
from {{ source('raw', 'gtfs_route_shapes') }}
