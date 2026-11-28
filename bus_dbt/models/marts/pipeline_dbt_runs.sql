{#- Recent dbt invocations, recorded by the pipeline after each build. Reflects builds up to
    the previous run, because a build cannot record itself before it finishes. -#}

select *
from {{ ref('stg_dbt_runs') }}
where started_at >= (select max(started_at) from {{ ref('stg_dbt_runs') }})
    - interval '{{ var("pipeline_history_days") }} days'
