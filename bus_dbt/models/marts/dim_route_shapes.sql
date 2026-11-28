with shapes as (
    select
        *,
        dense_rank() over (partition by route_key, direction_id order by route_id) as shape_rank
    from {{ ref('stg_gtfs_route_shapes') }}
)

select route_key, direction_id, point_order, latitude, longitude
from shapes
where shape_rank = 1
