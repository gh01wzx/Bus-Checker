select
    route_id,
    {{ route_key('route_id') }} as route_key,
    agency_id,
    route_short_name,
    route_long_name,
    route_type,
    {{ transport_mode('route_type') }} as mode,
    case
        when route_color is not null and length(route_color) = 6 then '#' || upper(route_color)
    end as route_color
from {{ source('raw', 'gtfs_routes') }}
