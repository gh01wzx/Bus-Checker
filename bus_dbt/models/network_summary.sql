select
    count(*) as total_trips,
    round(
        100.0 * count(*) filter (where {{ var('on_time_early') }} and {{ var('on_time_late') }}) / count(*),
        2
    ) as on_time_pct,
    round(avg(delay_sec), 2) as avg_delay_sec
from {{ ref('stg_trip_punctuality') }}

