{{ config(materialized='table') }}
select
    f.observation_date, f.local_hour, f.day_type, f.route_id, r.route_no,
    coalesce(f.direction_id, -1) as direction_id,
    count(*) as sample_count,
    sum(case when f.punctuality = 'On time' then 1 else 0 end) as on_time_count,
    sum(case when f.punctuality = 'Late' then 1 else 0 end) as late_count,
    sum(case when f.punctuality = 'Early' then 1 else 0 end) as early_count,
    sum(f.delay_sec) as total_delay_sec,
    max(f.captured_at) as latest_observation
from {{ ref('fct_trip_observation') }} f
join {{ ref('dim_route') }} r on f.route_id = r.route_id
group by 1,2,3,4,5,6
