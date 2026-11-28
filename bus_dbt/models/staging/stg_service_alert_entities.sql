select
    alert_version_id,
    entity_index,
    route_id,
    {{ route_key('route_id') }} as route_key,
    stop_id,
    {{ stop_key('stop_id') }} as stop_key,
    trip_id,
    direction_id
from {{ source('raw', 'service_alert_entities') }}
