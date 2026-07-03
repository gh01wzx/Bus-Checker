select
    route_id,
    round(avg(delay_sec), 2) as avg_delay_sec,
    count(*) as trip_count
from {{ ref('stg_trip_punctuality') }}
group by route_id
order by avg_delay_sec desc