{{ config(materialized='table') }}
select
    cast(p.captured_at at time zone 'Pacific/Auckland' as date) as observation_date,
    p.route_id, r.route_no, p.stop_id,
    count(*) as sample_count,
    sum(case when p.delay_sec between {{ var('on_time_early') }} and {{ var('on_time_late') }} then 1 else 0 end) as on_time_count,
    sum(case when p.delay_sec > {{ var('on_time_late') }} then 1 else 0 end) as late_count,
    sum(case when p.delay_sec < {{ var('on_time_early') }} then 1 else 0 end) as early_count,
    sum(p.delay_sec) as total_delay_sec
from {{ ref('stg_stop_punctuality') }} p
join {{ ref('dim_route') }} r on cast(p.route_id as varchar) = r.route_id
group by 1,2,3,4
