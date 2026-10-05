select * from {{ ref('stop_daily_reliability') }}
where sample_count <= 0 or sample_count <> on_time_count + early_count + late_count
