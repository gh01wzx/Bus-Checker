-- route_daily, route_hourly, the delay histogram and stop_daily all count the same events.
with facts as (
    select service_date, count(*) as n from {{ ref('fct_stop_events') }}
    where route_key is not null and service_date >= {{ test_window_start() }}
    group by 1
),
daily as (
    select service_date, sum(events) as n from {{ ref('route_daily') }}
    where service_date >= {{ test_window_start() }} group by 1
),
hourly as (
    select service_date, sum(events) as n from {{ ref('route_hourly') }}
    where service_date >= {{ test_window_start() }} group by 1
),
histogram as (
    select service_date, sum(events) as n from {{ ref('route_delay_histogram') }}
    where service_date >= {{ test_window_start() }} group by 1
),
stops as (
    select service_date, sum(events) as n from {{ ref('stop_daily') }}
    where service_date >= {{ test_window_start() }} group by 1
),
network as (
    select service_date, sum(events) as n from {{ ref('network_daily') }}
    where service_date >= {{ test_window_start() }} group by 1
)
select f.service_date, f.n as facts, d.n as daily, h.n as hourly, g.n as histogram, n.n as network
from facts as f
left join daily as d on d.service_date = f.service_date
left join hourly as h on h.service_date = f.service_date
left join histogram as g on g.service_date = f.service_date
left join network as n on n.service_date = f.service_date
where coalesce(d.n, -1) <> f.n
   or coalesce(h.n, -1) <> f.n
   or coalesce(g.n, -1) <> f.n
   or coalesce(n.n, -1) <> f.n
