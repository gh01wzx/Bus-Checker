{{
    config(
        materialized='incremental',
        unique_key='service_date',
        incremental_strategy='delete+insert',
        on_schema_change='fail',
        indexes=[{'columns': ['service_date']}, {'columns': ['ingested_at']}],
    )
}}

{#- One row per trip instance (service date + trip) seen in the realtime feed. -#}

with
{% if is_incremental() %}
changed as ({{ changed_dates(ref('stg_trip_updates')) }}),
{% endif %}

reports as (
    select *
    from {{ ref('stg_trip_updates') }}
    where true {{ in_changed() }}
),

latest as (
    select
        service_date,
        trip_id,
        route_id,
        route_key,
        direction_id,
        start_time,
        start_hour,
        vehicle_id,
        trip_schedule_relationship,
        row_number() over (
            partition by service_date, trip_id
            order by update_ts desc nulls last, feed_ts desc, update_id
        ) as report_rank
    from reports
),

summary as (
    select
        service_date,
        trip_id,
        count(*) as report_count,
        min(feed_ts) as first_seen_at,
        max(feed_ts) as last_seen_at,
        bool_or(trip_schedule_relationship = 'CANCELED') as ever_cancelled,
        max(ingested_at) as ingested_at
    from reports
    group by 1, 2
),

events as (
    select
        service_date,
        trip_id,
        count(*) as stops_observed,
        min(event_ts) as first_event_ts,
        max(event_ts) as last_event_ts,
        avg(delay_sec) as avg_delay_sec,
        max(delay_sec) as max_delay_sec,
        min(delay_sec) as min_delay_sec,
        max(case when first_rank = 1 then delay_sec end) as first_delay_sec,
        max(case when last_rank = 1 then delay_sec end) as last_delay_sec
    from (
        select
            service_date,
            trip_id,
            event_ts,
            delay_sec,
            row_number() over (
                partition by service_date, trip_id order by event_ts, stop_sequence
            ) as first_rank,
            row_number() over (
                partition by service_date, trip_id order by event_ts desc, stop_sequence desc
            ) as last_rank
        from {{ ref('fct_stop_events') }}
        where true {{ in_changed() }}
    ) as ordered
    group by 1, 2
)

select
    l.service_date,
    l.trip_id,
    l.route_id,
    l.route_key,
    l.direction_id,
    l.start_time,
    l.start_hour,
    l.vehicle_id,
    l.trip_schedule_relationship as final_schedule_relationship,
    (l.trip_schedule_relationship = 'CANCELED' and coalesce(e.stops_observed, 0) = 0) as is_cancelled,
    (l.trip_schedule_relationship = 'ADDED') as is_added,
    s.ever_cancelled,
    cast(s.report_count as integer) as report_count,
    s.first_seen_at,
    s.last_seen_at,
    cast(coalesce(e.stops_observed, 0) as integer) as stops_observed,
    e.first_event_ts,
    e.last_event_ts,
    e.avg_delay_sec,
    e.max_delay_sec,
    e.min_delay_sec,
    e.first_delay_sec,
    e.last_delay_sec,
    s.ingested_at
from latest as l
join summary as s
    on s.service_date = l.service_date and s.trip_id = l.trip_id
left join events as e
    on e.service_date = l.service_date and e.trip_id = l.trip_id
where l.report_rank = 1
