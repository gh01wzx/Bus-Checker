{{ config(materialized='table') }}
select
    cast(route_id as varchar) as route_id,
    max(cast(route_short_name as varchar)) as route_no
from {{ source('public', 'gtfs_routes') }}
where route_type = 3
group by 1
