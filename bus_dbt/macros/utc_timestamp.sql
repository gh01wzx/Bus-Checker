{% macro utc_timestamp(column) %}
case
{% if target.type == 'duckdb' %}
when typeof({{ column }}) = 'TIMESTAMP'
{% else %}
when cast(pg_typeof({{ column }}) as text) = 'timestamp without time zone'
{% endif %}
then {{ column }} at time zone 'UTC'
else cast({{ column }} as timestamp with time zone)
end
{% endmacro %}
