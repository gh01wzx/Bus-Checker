{{ config(materialized='incremental', unique_key='service_date', incremental_strategy='delete+insert', on_schema_change='fail', indexes=[{'columns': ['service_date']}]) }}

{#- One-minute delay buckets per route and day. Tails are clamped into the edge buckets, so
    totals always reconcile with route_daily and percentiles work over any date range. -#}

with
{% if is_incremental() %}
changed as ({{ changed_dates(ref('fct_stop_events')) }}),
{% endif %}

buckets as (
    select
        service_date,
        route_key,
        {{ delay_bucket('delay_sec') }} as delay_bucket_min,
        cast(count(*) as bigint) as events,
        max(ingested_at) as ingested_at
    from {{ ref('fct_stop_events') }}
    where route_key is not null {{ in_changed() }}
    group by 1, 2, 3
)

select * from buckets
