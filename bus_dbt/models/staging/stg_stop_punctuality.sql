select
    stop_id,
    trip_id,
    route_id,
    stop_sequence,
    delay as delay_sec
from {{ source('main', 'stop_punctuality') }}