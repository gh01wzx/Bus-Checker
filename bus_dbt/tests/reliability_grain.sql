select observation_date, local_hour, route_id, direction_id, count(*)
from {{ ref('route_hourly_reliability') }}
group by 1,2,3,4
having count(*) > 1
