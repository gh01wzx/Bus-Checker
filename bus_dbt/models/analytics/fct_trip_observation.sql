{{ config(materialized='incremental', unique_key='observation_id',
          incremental_strategy='delete+insert', on_schema_change='fail') }}

select
    o.observation_id, o.batch_id, o.captured_at, o.loaded_at,
    o.route_id, o.trip_id, o.direction_id, o.delay as delay_sec,
    cast(o.captured_at at time zone 'Pacific/Auckland' as date) as observation_date,
    cast(extract(hour from o.captured_at at time zone 'Pacific/Auckland') as integer) as local_hour,
    case when extract(isodow from o.captured_at at time zone 'Pacific/Auckland') in (6, 7)
         then 'Weekend' else 'Weekday' end as day_type,
    case when o.delay < {{ var('on_time_early') }} then 'Early'
         when o.delay > {{ var('on_time_late') }} then 'Late'
         else 'On time' end as punctuality
from {{ source('public', 'bus_observations') }} o
where o.observation_type = 'trip'
{% if is_incremental() %}
and o.loaded_at >= (select coalesce(max(loaded_at), cast('1970-01-01' as timestamp with time zone))
                   - interval '1 second' from {{ this }})
{% endif %}
