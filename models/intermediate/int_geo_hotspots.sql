/*
    int_geo_hotspots
    ----------------
    Intermediate model — geographic aggregations over stg_accidents.

    Produces two result sets:
      - city level  : accident count, avg severity, avg duration per city
      - state level : accident count, avg severity, critical rate per state

    Both include window-function rankings. Used by: mart_geo
*/

WITH city_agg AS (
    SELECT
        'city'                                          AS geo_level,
        city,
        state,
        COUNT(*)                                        AS accident_count,
        ROUND(AVG(severity), 3)                         AS avg_severity,
        ROUND(
            AVG(duration_mins)
            FILTER (WHERE duration_mins > 0 AND duration_mins < 1440),
        2)                                              AS avg_duration_mins,
        COUNT(*) FILTER (WHERE severity = 4)            AS critical_count,
        ROUND(
            COUNT(*) FILTER (WHERE severity = 4)
            * 100.0 / NULLIF(COUNT(*), 0),
        2)                                              AS critical_rate_pct
    FROM {{ ref('stg_accidents') }}
    GROUP BY city, state
),
city_ranked AS (
    SELECT
        geo_level,
        city,
        state,
        accident_count,
        avg_severity,
        avg_duration_mins,
        critical_count,
        critical_rate_pct,
        RANK() OVER (ORDER BY accident_count DESC)              AS volume_rank,
        RANK() OVER (ORDER BY avg_severity DESC)                AS severity_rank,
        RANK() OVER (
            PARTITION BY state ORDER BY accident_count DESC
        )                                                       AS rank_within_state
    FROM city_agg
),

state_agg AS (
    SELECT
        'state'                                         AS geo_level,
        NULL                                            AS city,
        state,
        COUNT(*)                                        AS accident_count,
        ROUND(AVG(severity), 3)                         AS avg_severity,
        ROUND(
            AVG(duration_mins)
            FILTER (WHERE duration_mins > 0 AND duration_mins < 1440),
        2)                                              AS avg_duration_mins,
        COUNT(*) FILTER (WHERE severity = 4)            AS critical_count,
        ROUND(
            COUNT(*) FILTER (WHERE severity = 4)
            * 100.0 / NULLIF(COUNT(*), 0),
        2)                                              AS critical_rate_pct
    FROM {{ ref('stg_accidents') }}
    GROUP BY state
),
state_ranked AS (
    SELECT
        geo_level,
        city,
        state,
        accident_count,
        avg_severity,
        avg_duration_mins,
        critical_count,
        critical_rate_pct,
        RANK() OVER (ORDER BY accident_count DESC)              AS volume_rank,
        DENSE_RANK() OVER (ORDER BY avg_severity DESC)          AS severity_rank,
        RANK() OVER (
            ORDER BY critical_rate_pct DESC
        )                                                       AS rank_within_state
    FROM state_agg
)

SELECT * FROM city_ranked
UNION ALL
SELECT * FROM state_ranked
ORDER BY geo_level DESC, volume_rank
