select
    sp.stop_id,
    gs.stop_name,
    gs.stop_latitude,
    gs.stop_longitude,
    round(avg(sp.delay_sec), 2) as avg_delay_sec,
    count(*) as sample_count
from {{ ref('stg_stop_punctuality') }} sp
join {{ ref('stg_stops') }} gs on sp.stop_id = gs.stop_id
group by sp.stop_id, gs.stop_name, gs.stop_latitude, gs.stop_longitude