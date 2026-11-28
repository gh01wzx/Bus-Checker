{#- Schemas are used exactly as configured (raw, ops, staging, core, marts) instead of
    dbt's default "<target>_<custom>" concatenation. -#}
{% macro generate_schema_name(custom_schema_name, node) -%}
    {%- if custom_schema_name is none -%}
        {{ target.schema }}
    {%- else -%}
        {{ custom_schema_name | trim }}
    {%- endif -%}
{%- endmacro %}


{#- Routine builds test only recent partitions; see var test_window_days. A data test opts in
    with `where: "service_date >= __test_window_start__"`. -#}
{% macro test_window_start() -%}
    {%- set days = var('test_window_days') | int -%}
    {%- set start = (modules.datetime.date.today() - modules.datetime.timedelta(days=days)).isoformat() -%}
    cast('{{ start }}' as date)
{%- endmacro %}


{% macro get_where_subquery(relation) -%}
    {%- set where = config.get('where') -%}
    {%- if where -%}
        {%- set where = where | replace('__test_window_start__', test_window_start()) -%}
        {%- set filtered -%}
            (select * from {{ relation }} where {{ where }}) dbt_subquery
        {%- endset -%}
        {%- do return(filtered) -%}
    {%- else -%}
        {%- do return(relation) -%}
    {%- endif -%}
{%- endmacro %}


{#- Service dates that received new source rows since this model's watermark.
    Incremental models delete and rebuild exactly these date partitions. -#}
{% macro changed_dates(relation, date_column='service_date', watermark='ingested_at') -%}
    select distinct {{ date_column }} as changed_date
    from {{ relation }}
    where {{ watermark }} > (
        select coalesce(max({{ watermark }}), cast('1970-01-01 00:00:00+00' as timestamp with time zone))
        from {{ this }}
    ) - interval '{{ var("watermark_lookback_minutes") }} minutes'
{%- endmacro %}


{% macro in_changed(date_column='service_date') -%}
    {%- if is_incremental() -%}
        and {{ date_column }} in (select changed_date from changed)
    {%- endif -%}
{%- endmacro %}


{% macro latest_of(columns) -%}
    {#- greatest() that ignores NULL inputs on both DuckDB and PostgreSQL -#}
    {%- set parts = [] -%}
    {%- for column in columns -%}
        {%- set others = columns | reject('equalto', column) | list -%}
        {%- do parts.append('coalesce(' ~ ([column] + others) | join(', ') ~ ')') -%}
    {%- endfor -%}
    greatest({{ parts | join(', ') }})
{%- endmacro %}
