SELECT
    captured_at,
    route_id,
    trip_id,
    delay AS delay_sec
FROM {{ source('main', 'trip_punctuality') }}