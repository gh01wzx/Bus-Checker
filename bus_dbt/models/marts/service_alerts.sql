{#- The latest version of every alert seen recently. An alert is "published" while it is still
    in the feed and "active" when one of its active periods covered the last sighting. -#}

with versions as (
    select * from {{ ref('stg_service_alerts') }}
),

latest_seen as (
    select max(last_seen_at) as latest from versions
),

ranked as (
    select
        v.*,
        row_number() over (partition by alert_id order by last_seen_at desc, first_seen_at desc) as version_rank,
        min(first_seen_at) over (partition by alert_id) as alert_first_seen_at,
        count(*) over (partition by alert_id) as version_count
    from versions as v
),

route_names as (
    select distinct
        x.alert_version_id,
        coalesce(r.route_short_name, x.route_key) as route_name
    from {{ ref('stg_service_alert_entities') }} as x
    left join {{ ref('dim_routes') }} as r on r.route_key = x.route_key
    where x.route_key is not null
),

routes as (
    select
        alert_version_id,
        cast(count(*) as integer) as route_count,
        string_agg(route_name, ', ' order by route_name) as route_list
    from route_names
    group by 1
),

stops as (
    select alert_version_id, cast(count(distinct stop_key) as integer) as stop_count
    from {{ ref('stg_service_alert_entities') }}
    where stop_key is not null
    group by 1
)

select
    c.alert_id,
    c.alert_version_id,
    c.cause,
    c.effect,
    coalesce(c.severity, 'UNKNOWN_SEVERITY') as severity,
    c.header_text,
    c.description_text,
    c.effect_detail,
    c.url,
    c.active_periods,
    c.period_start,
    c.period_end,
    c.alert_first_seen_at as first_seen_at,
    c.last_seen_at,
    cast(c.version_count as integer) as version_count,
    c.last_seen_at >= l.latest - interval '10 minutes' as is_published,
    c.last_seen_at >= l.latest - interval '10 minutes' and c.active_at_last_seen as is_active,
    coalesce(rt.route_count, 0) as route_count,
    rt.route_list,
    coalesce(st.stop_count, 0) as stop_count
from ranked as c
cross join latest_seen as l
left join routes as rt on rt.alert_version_id = c.alert_version_id
left join stops as st on st.alert_version_id = c.alert_version_id
where c.version_rank = 1
    and c.last_seen_at >= l.latest - interval '{{ var("alert_history_days") }} days'
