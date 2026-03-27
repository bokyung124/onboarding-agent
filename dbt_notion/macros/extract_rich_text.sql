{% macro extract_rich_text(json_col, type_col) %}
    (
        select string_agg(json_value(rt, '$.plain_text'), '')
        from unnest(
            json_query_array({{ json_col }},
                '$.' || {{ type_col }} || '.rich_text')
        ) as rt
    )
{% endmacro %}
