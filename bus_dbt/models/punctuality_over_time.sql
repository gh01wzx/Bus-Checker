select
    date_trunc('hour', captured_at) as hour,
    round(
        100.0 * count(*) filter (where {{ var('on_time_early') }} and {{ var('on_time_late') }}) / count(*),
        2
    ) as on_time_pct,
    count(*) as trip_count
from {{ ref('stg_trip_punctuality') }}
group by date_trunc('hour', captured_at)
order by hour