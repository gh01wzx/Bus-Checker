{{ config(materialized='incremental', unique_key='service_date', incremental_strategy='delete+insert', on_schema_change='fail', indexes=[{'columns': ['service_date']}]) }}

with
{% if is_incremental() %}
changed as ({{ changed_dates(ref('stg_vehicle_positions')) }}),
{% endif %}

reports as (
    select
        service_date,
        route_key,
        occupancy_status,
        cast(count(*) as bigint) as reports,
        max(ingested_at) as ingested_at
    from {{ ref('stg_vehicle_positions') }}
    where in_service and in_region and route_key is not null and occupancy_status is not null
        {{ in_changed() }}
    group by 1, 2, 3
)

select * from reports
