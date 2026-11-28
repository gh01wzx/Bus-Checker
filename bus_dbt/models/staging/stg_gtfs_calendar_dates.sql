select
    service_id,
    service_date,
    exception_type
from {{ source('raw', 'gtfs_calendar_dates') }}
