select *
from {{ ref('stg_gtfs_loads') }}
where started_at >= (select max(started_at) from {{ ref('stg_gtfs_loads') }}) - interval '90 days'
