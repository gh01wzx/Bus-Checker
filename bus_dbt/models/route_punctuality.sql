SELECT
    route_id,
    ROUND(AVG(delay_sec), 2) AS avg_delay_sec,
    COUNT(*) AS trip_count
FROM {{ ref('stg_trip_punctuality') }}
GROUP BY route_id
ORDER BY avg_delay_sec DESC