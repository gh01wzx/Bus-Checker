select
    date_trunc('hour', captured_at at time zone 'UTC' at time zone 'Pacific/Auckland') as hour,
    round(100.0 * count(*) filter (
        where delay_sec between {{ var('on_time_early') }} and {{ var('on_time_late') }}
    ) / count(*), 2) as on_time_pct,
    count(*) as trip_count
from {{ ref('stg_trip_punctuality') }}
group by 1
order by 1