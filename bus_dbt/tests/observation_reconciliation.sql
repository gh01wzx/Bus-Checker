select o.observation_id
from {{ source('public', 'bus_observations') }} o
left join {{ ref('fct_trip_observation') }} f on o.observation_id = f.observation_id
where o.observation_type = 'trip'
  and (f.observation_id is null or f.delay_sec <> o.delay or f.captured_at <> o.captured_at)
