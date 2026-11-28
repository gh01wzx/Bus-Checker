select
    update_id,
    fetch_id,
    ingested_at,
    feed_ts,
    service_date,
    trip_id,
    route_id,
    {{ route_key('route_id') }} as route_key,
    coalesce(direction_id, -1) as direction_id,
    start_time,
    case
        when start_time is not null then cast(split_part(start_time, ':', 1) as integer) % 24
    end as start_hour,
    trip_schedule_relationship,
    vehicle_id,
    vehicle_label,
    update_ts,
    trip_delay_sec,
    stop_id,
    {{ stop_key('stop_id') }} as stop_key,
    stop_sequence,
    stop_schedule_relationship,
    arrival_delay_sec,
    arrival_ts,
    departure_delay_sec,
    departure_ts,
    coalesce(arrival_delay_sec, departure_delay_sec) as stop_delay_sec,
    coalesce(arrival_ts, departure_ts) as stop_event_ts,
    coalesce(cast(stop_sequence as varchar), 'stop:' || stop_id) as stop_event_key,
    -- An event whose time is still in the future (relative to the feed) is a prediction.
    coalesce(
        coalesce(arrival_ts, departure_ts)
            <= feed_ts + interval '{{ var("observed_tolerance_sec") }} seconds'
        and coalesce(stop_schedule_relationship, 'SCHEDULED') not in ('SKIPPED', 'NO_DATA'),
        false
    ) as is_observed
from {{ source('raw', 'trip_updates') }}
