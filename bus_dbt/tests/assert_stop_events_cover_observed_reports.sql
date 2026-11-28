-- Every observed stop report (trip x stop x service date) is represented exactly once.
with source_keys as (
    select count(*) as n
    from (
        select distinct service_date, trip_id, stop_event_key
        from {{ ref('stg_trip_updates') }}
        where is_observed and stop_delay_sec is not null and stop_event_key is not null
            and service_date >= {{ test_window_start() }}
    ) as k
),
modelled as (
    select count(*) as n from {{ ref('fct_stop_events') }}
    where service_date >= {{ test_window_start() }}
)
select s.n as source_rows, m.n as modelled_rows
from source_keys as s cross join modelled as m
where s.n <> m.n
