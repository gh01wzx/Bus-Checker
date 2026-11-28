{#- Calendar of every service date with data, with day type and holiday names. -#}

select
    d.service_date,
    {{ day_type('d.service_date') }} as day_type,
    h.holiday_name,
    cast(extract(isodow from d.service_date) as integer) as iso_weekday
from (select distinct service_date from {{ ref('network_daily') }}) as d
left join {{ ref('nz_public_holidays') }} as h on h.holiday_date = d.service_date
