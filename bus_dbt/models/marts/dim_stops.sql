{#- One row per public stop code; platforms preferred over parent stations. -#}

with ranked as (
    select
        *,
        row_number() over (
            partition by stop_key order by location_type, stop_id desc
        ) as stop_rank
    from {{ ref('stg_gtfs_stops') }}
)

select
    stop_key,
    stop_id,
    stop_code,
    stop_name,
    stop_name || ' (' || stop_key || ')' as stop_label,
    latitude,
    longitude,
    location_type,
    parent_station
from ranked
where stop_rank = 1
