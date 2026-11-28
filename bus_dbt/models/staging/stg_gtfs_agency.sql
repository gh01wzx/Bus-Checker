select
    agency_id,
    coalesce(agency_name, agency_id) as agency_name,
    agency_url
from {{ source('raw', 'gtfs_agency') }}
