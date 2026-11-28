{#- Which routes each published alert affects (for route-level alert panels). -#}

select distinct
    a.alert_id,
    x.route_key,
    a.effect,
    a.severity,
    a.header_text,
    a.is_active
from {{ ref('service_alerts') }} as a
join {{ ref('stg_service_alert_entities') }} as x on x.alert_version_id = a.alert_version_id
where a.is_published and x.route_key is not null
