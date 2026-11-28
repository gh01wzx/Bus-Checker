{{
    config(
        materialized='incremental',
        unique_key='service_date',
        incremental_strategy='delete+insert',
        on_schema_change='fail',
        indexes=[{'columns': ['service_date']}, {'columns': ['ingested_at']}],
    )
}}

{#-
    One row per trip per stop it has actually served: the most recent observed report of
    the delay at that stop. Predictions (event time later than the feed) are excluded, and
    the many identical snapshots of one stop event collapse into a single row.
-#}

with
{% if is_incremental() %}
changed as ({{ changed_dates(ref('stg_trip_updates')) }}),
{% endif %}

reports as (
    select *
    from {{ ref('stg_trip_updates') }}
    where is_observed
        and stop_delay_sec is not null
        and stop_event_key is not null
        {{ in_changed() }}
),

ranked as (
    select
        reports.*,
        row_number() over (
            partition by service_date, trip_id, stop_event_key
            order by update_ts desc nulls last, feed_ts desc, update_id
        ) as report_rank,
        count(*) over (partition by service_date, trip_id, stop_event_key) as report_count,
        max(ingested_at) over (partition by service_date, trip_id, stop_event_key) as last_ingested_at
    from reports
)

select
    service_date,
    trip_id,
    stop_event_key,
    route_id,
    route_key,
    direction_id,
    stop_id,
    stop_key,
    stop_sequence,
    vehicle_id,
    stop_event_ts as event_ts,
    {{ local_hour('stop_event_ts') }} as event_hour,
    stop_delay_sec as delay_sec,
    {{ punctuality('stop_delay_sec') }} as punctuality,
    cast(report_count as integer) as report_count,
    last_ingested_at as ingested_at
from ranked
where report_rank = 1
