{% test unique_combination_of_columns(model, combination_of_columns) %}
    select {{ combination_of_columns | join(', ') }}, count(*) as duplicate_count
    from {{ model }}
    group by {{ combination_of_columns | join(', ') }}
    having count(*) > 1
{% endtest %}


{#- Every event lands in exactly one punctuality class. -#}
{% test punctuality_partition(model, total='events') %}
    select *
    from {{ model }}
    where {{ total }} < 0
       or on_time < 0 or early < 0 or late < 0
       or {{ total }} <> on_time + early + late
{% endtest %}


{% test non_negative(model, column_name) %}
    select * from {{ model }} where {{ column_name }} < 0
{% endtest %}
