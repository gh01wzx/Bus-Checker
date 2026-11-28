{{ config(materialized='incremental', unique_key='service_date', incremental_strategy='delete+insert', on_schema_change='fail', indexes=[{'columns': ['service_date']}]) }}

{#- Vehicles reporting positions in the Auckland region, by hour and mode, with crowding
    (occupancy) and average moving speed. Counts are position samples, not passengers. -#}

with
{% if is_incremental() %}
changed as ({{ changed_dates(ref('stg_vehicle_positions')) }}),
{% endif %}

positions as (
    select
        p.*,
        case
            when not p.in_service then 'Not in service'
            else coalesce(r.mode, 'Unknown')
        end as mode
    from {{ ref('stg_vehicle_positions') }} as p
    left join {{ ref('dim_routes') }} as r on r.route_key = p.route_key
    where p.in_region {{ in_changed('p.service_date') }}
)

select
    service_date,
    {{ day_type('service_date') }} as day_type,
    local_hour as hour,
    mode,
    cast(count(distinct vehicle_id) as bigint) as vehicles,
    cast(count(*) as bigint) as position_reports,
    cast(sum(case when occupancy_status is not null then 1 else 0 end) as bigint) as occupancy_reports,
    cast(sum(case when occupancy_status = 'EMPTY' then 1 else 0 end) as bigint) as occupancy_empty,
    cast(sum(case when occupancy_status = 'MANY_SEATS_AVAILABLE' then 1 else 0 end) as bigint) as occupancy_many_seats,
    cast(sum(case when occupancy_status = 'FEW_SEATS_AVAILABLE' then 1 else 0 end) as bigint) as occupancy_few_seats,
    cast(sum(case when occupancy_status in ('STANDING_ROOM_ONLY', 'CRUSHED_STANDING_ROOM_ONLY') then 1 else 0 end) as bigint) as occupancy_standing,
    cast(sum(case when occupancy_status in ('FULL', 'NOT_ACCEPTING_PASSENGERS') then 1 else 0 end) as bigint) as occupancy_full,
    avg(case when in_service and speed_kmh > 0 then speed_kmh end) as avg_moving_speed_kmh,
    max(ingested_at) as ingested_at
from positions
group by 1, 2, 3, 4
