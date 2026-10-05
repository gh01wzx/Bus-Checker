select observation_date, route_id, stop_id, count(*)
from {{ ref('stop_daily_reliability') }}
group by 1,2,3 having count(*) > 1
