/*
    dim_time
    --------
    Time dimension table — star schema core layer.

    One row per unique start_time timestamp. All derived temporal
    attributes are computed from start_time alone — they are
    deterministic so no DISTINCT needed across them.

    Surrogate key: MD5(start_time::TEXT)
    Referenced by: fact_accidents (via time_id foreign key)
*/

WITH time_base AS (
    SELECT DISTINCT
        start_time
    FROM {{ ref('stg_accidents') }}
)

SELECT
    MD5(start_time::TEXT)                           AS time_id,
    start_time,
    EXTRACT(HOUR    FROM start_time)::INT           AS hour_of_day,
    TO_CHAR(start_time, 'Day')                      AS day_of_week,
    EXTRACT(DOW     FROM start_time) IN (0, 6)      AS is_weekend,
    EXTRACT(HOUR    FROM start_time) IN (7,8,16,17,18)
                                                    AS is_rush_hour,
    EXTRACT(MONTH   FROM start_time)::INT           AS month_num,
    TRIM(TO_CHAR(start_time, 'Month'))              AS month_name,
    EXTRACT(YEAR    FROM start_time)::INT           AS year_num,
    EXTRACT(QUARTER FROM start_time)::INT           AS quarter_num,
    DATE_TRUNC('month', start_time)::DATE           AS month_start,
    DATE_TRUNC('year',  start_time)::DATE           AS year_start,
    CASE
        WHEN EXTRACT(YEAR  FROM start_time) = 2020
         AND EXTRACT(MONTH FROM start_time) BETWEEN 3 AND 6
        THEN TRUE ELSE FALSE
    END                                             AS is_covid_lockdown_period
FROM time_base
