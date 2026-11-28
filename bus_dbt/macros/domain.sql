{% macro local_ts(column) -%}
    ({{ column }} at time zone '{{ var("local_timezone") }}')
{%- endmacro %}

{% macro local_date(column) -%}
    cast({{ local_ts(column) }} as date)
{%- endmacro %}

{% macro local_hour(column) -%}
    cast(extract(hour from {{ local_ts(column) }}) as integer)
{%- endmacro %}

{% macro seconds_between(later, earlier) -%}
    cast(extract(epoch from ({{ later }} - {{ earlier }})) as double precision)
{%- endmacro %}

{#- AT route ids carry a contract/version suffix ("101-202", "122-203"). The public route
    number is stable across GTFS versions and operator contracts. -#}
{% macro route_key(route_id) -%}
    regexp_replace({{ route_id }}, '-[0-9]+$', '')
{%- endmacro %}

{#- AT stop ids are "<stop code>-<version hash>"; the code is the stable public identifier. -#}
{% macro stop_key(stop_id) -%}
    split_part({{ stop_id }}, '-', 1)
{%- endmacro %}

{% macro punctuality(delay) -%}
    case
        when {{ delay }} is null then null
        when {{ delay }} < {{ var('on_time_early_sec') }} then 'early'
        when {{ delay }} > {{ var('on_time_late_sec') }} then 'late'
        else 'on_time'
    end
{%- endmacro %}

{% macro punctuality_counts(column='punctuality') -%}
    cast(count(*) as bigint) as events,
    cast(sum(case when {{ column }} = 'on_time' then 1 else 0 end) as bigint) as on_time,
    cast(sum(case when {{ column }} = 'early' then 1 else 0 end) as bigint) as early,
    cast(sum(case when {{ column }} = 'late' then 1 else 0 end) as bigint) as late
{%- endmacro %}

{% macro delay_bucket(delay) -%}
    greatest(
        {{ var('histogram_min_minutes') }},
        least({{ var('histogram_max_minutes') }}, cast(floor({{ delay }} / 60.0) as integer))
    )
{%- endmacro %}

{#- GTFS route_type (basic and extended) to a passenger-facing mode. -#}
{% macro transport_mode(route_type) -%}
    case
        when {{ route_type }} is null then 'Unknown'
        when {{ route_type }} = 3 or {{ route_type }} = 11
            or {{ route_type }} between 700 and 799 or {{ route_type }} between 200 and 299 then 'Bus'
        when {{ route_type }} in (1, 2) or {{ route_type }} between 100 and 199
            or {{ route_type }} between 400 and 499 then 'Train'
        when {{ route_type }} = 4 or {{ route_type }} between 1000 and 1099
            or {{ route_type }} = 1200 then 'Ferry'
        when {{ route_type }} = 0 or {{ route_type }} between 900 and 999 then 'Light rail'
        else 'Other'
    end
{%- endmacro %}

{% macro day_type(date_column) -%}
    case
        when {{ date_column }} in (select holiday_date from {{ ref('nz_public_holidays') }}) then 'Holiday'
        when extract(isodow from {{ date_column }}) in (6, 7) then 'Weekend'
        else 'Weekday'
    end
{%- endmacro %}

{% macro in_region(lat, lon) -%}
    (
        {{ lat }} between {{ var('region_bbox')['min_lat'] }} and {{ var('region_bbox')['max_lat'] }}
        and {{ lon }} between {{ var('region_bbox')['min_lon'] }} and {{ var('region_bbox')['max_lon'] }}
    )
{%- endmacro %}
