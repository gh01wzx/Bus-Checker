{{ config(materialized='incremental', unique_key='service_date', incremental_strategy='delete+insert', on_schema_change='fail', indexes=[{'columns': ['service_date']}]) }}

with
{% if is_incremental() %}
changed as ({{ changed_dates(ref('fct_stop_events')) }}),
{% endif %}

events as (
    select
        service_date,
        event_hour as hour,
        route_key,
        direction_id,
        {{ punctuality_counts() }},
        cast(sum(delay_sec) as bigint) as delay_sum_sec,
        max(ingested_at) as ingested_at
    from {{ ref('fct_stop_events') }}
    where route_key is not null {{ in_changed() }}
    group by 1, 2, 3, 4
)

select
    service_date,
    {{ day_type('service_date') }} as day_type,
    hour,
    route_key,
    direction_id,
    events,
    on_time,
    early,
    late,
    delay_sum_sec,
    ingested_at
from events
