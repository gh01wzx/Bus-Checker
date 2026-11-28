select
    feed,
    reason,
    cast(count(*) as bigint) as records,
    max(created_at) as last_seen_at
from {{ ref('stg_quarantine') }}
where created_at >= (select max(created_at) from {{ ref('stg_quarantine') }})
    - interval '{{ var("pipeline_history_days") }} days'
group by 1, 2
