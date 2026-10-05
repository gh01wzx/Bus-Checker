select * from {{ ref('route_hourly_reliability') }}
where sample_count <= 0
   or sample_count <> on_time_count + late_count + early_count
   or local_hour not between 0 and 23
