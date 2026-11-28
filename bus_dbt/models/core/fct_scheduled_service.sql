{{
    config(
        materialized='incremental',
        unique_key='service_date',
        incremental_strategy='delete+insert',
        on_schema_change='fail',
        indexes=[{'columns': ['service_date']}],
    )
}}

{#-
    Trips the GTFS timetable schedules on each date that has realtime data, by route,
    direction and scheduled start hour. Computed when the date is first observed, so later
    GTFS refreshes do not rewrite the timetable that applied at the time.
-#}

with
{% if is_incremental() %}
changed as ({{ changed_dates(ref('fct_trips')) }}),
{% endif %}

dates as (
    -- Only dates with observed service: advance cancellations for tomorrow must not
    -- create a timetable for a day that has not happened yet.
    select service_date, max(ingested_at) as ingested_at
    from {{ ref('fct_trips') }}
    where true {{ in_changed() }}
    group by 1
    having sum(stops_observed) > 0
),

weekly as (
    select d.service_date, c.service_id
    from dates as d
    join {{ ref('stg_gtfs_calendar') }} as c
        on d.service_date between c.start_date and c.end_date
    where case cast(extract(isodow from d.service_date) as integer)
        when 1 then c.monday
        when 2 then c.tuesday
        when 3 then c.wednesday
        when 4 then c.thursday
        when 5 then c.friday
        when 6 then c.saturday
        else c.sunday
    end
),

exceptions as (
    select cd.service_date, cd.service_id, cd.exception_type
    from {{ ref('stg_gtfs_calendar_dates') }} as cd
    join dates as d on d.service_date = cd.service_date
),

active as (
    select service_date, service_id from weekly
    union
    select service_date, service_id from exceptions where exception_type = 1
),

running as (
    select a.service_date, a.service_id
    from active as a
    where not exists (
        select 1 from exceptions as x
        where x.service_date = a.service_date
            and x.service_id = a.service_id
            and x.exception_type = 2
    )
)

select
    r.service_date,
    t.route_key,
    t.direction_id,
    coalesce(t.start_hour, -1) as start_hour,
    cast(count(*) as bigint) as trips_scheduled,
    max(d.ingested_at) as ingested_at
from running as r
join {{ ref('stg_gtfs_trips') }} as t on t.service_id = r.service_id
join dates as d on d.service_date = r.service_date
group by 1, 2, 3, 4
