with facts as (
    select service_date,
        sum(case when stops_observed > 0 then 1 else 0 end) as tracked,
        sum(case when is_cancelled then 1 else 0 end) as cancelled
    from {{ ref('fct_trips') }}
    where route_key is not null and service_date >= {{ test_window_start() }}
    group by 1
),
daily as (
    select service_date, sum(trips_tracked) as tracked, sum(trips_cancelled) as cancelled
    from {{ ref('route_daily') }}
    where service_date >= {{ test_window_start() }} group by 1
),
delivery as (
    select service_date, sum(trips_tracked) as tracked, sum(trips_cancelled) as cancelled
    from {{ ref('service_delivery_hourly') }}
    where service_date >= {{ test_window_start() }} group by 1
)
select f.service_date
from facts as f
left join daily as d on d.service_date = f.service_date
left join delivery as v on v.service_date = f.service_date
where coalesce(d.tracked, -1) <> f.tracked or coalesce(d.cancelled, -1) <> f.cancelled
   or coalesce(v.tracked, -1) <> f.tracked or coalesce(v.cancelled, -1) <> f.cancelled
