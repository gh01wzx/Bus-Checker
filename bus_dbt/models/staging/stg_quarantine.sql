select
    rejection_id,
    fetch_id,
    feed,
    reason,
    created_at
from {{ source('ops', 'quarantine') }}
