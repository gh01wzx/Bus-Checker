with source_keys as (
    select count(*) as n
    from (
        select distinct service_date, trip_id from {{ ref('stg_trip_updates') }}
        where service_date >= {{ test_window_start() }}
    ) as k
),
modelled as (
    select count(*) as n from {{ ref('fct_trips') }}
    where service_date >= {{ test_window_start() }}
)
select s.n as source_rows, m.n as modelled_rows
from source_keys as s cross join modelled as m
where s.n <> m.n
