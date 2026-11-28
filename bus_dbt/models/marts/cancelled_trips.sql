{{ config(materialized='incremental', unique_key='service_date', incremental_strategy='delete+insert', on_schema_change='fail', indexes=[{'columns': ['service_date']}]) }}

with
{% if is_incremental() %}
changed as ({{ changed_dates(ref('fct_trips')) }}),
{% endif %}

cancelled as (
    select *
    from {{ ref('fct_trips') }}
    where is_cancelled {{ in_changed() }}
)

select
    c.service_date,
    {{ day_type('c.service_date') }} as day_type,
    c.trip_id,
    c.route_key,
    c.direction_id,
    c.start_time,
    c.start_hour,
    g.trip_headsign,
    c.first_seen_at,
    c.last_seen_at,
    c.ingested_at
from cancelled as c
left join {{ ref('stg_gtfs_trips') }} as g on g.trip_id = c.trip_id
