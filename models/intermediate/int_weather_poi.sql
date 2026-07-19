/*
    int_weather_poi
    ---------------
    Intermediate model — weather condition and POI infrastructure
    aggregations over stg_accidents.

    Produces two result sets:
      - weather : severity and count by weather condition and buckets
      - poi     : avg severity TRUE vs FALSE for each of 13 POI features

    Used by: mart_weather_poi
*/

-- Weather condition aggregation
WITH weather_agg AS (
    SELECT
        'weather_condition'                             AS analysis_type,
        weather_condition                               AS category,
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
        2)                                              AS critical_rate_pct,
        NULL::NUMERIC                                   AS avg_sev_false,
        ROUND(
            COUNT(*) * 100.0 / SUM(COUNT(*)) OVER (),
        2)                                              AS pct_of_total
    FROM {{ ref('stg_accidents') }}
    GROUP BY weather_condition
),

-- Visibility bucket aggregation
visibility_agg AS (
    SELECT
        'visibility_bucket'                             AS analysis_type,
        visibility_bucket                               AS category,
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
        2)                                              AS critical_rate_pct,
        NULL::NUMERIC                                   AS avg_sev_false,
        ROUND(
            COUNT(*) * 100.0 / SUM(COUNT(*)) OVER (),
        2)                                              AS pct_of_total
    FROM {{ ref('stg_accidents') }}
    GROUP BY visibility_bucket
),

-- Light condition aggregation
light_agg AS (
    SELECT
        'light_condition'                               AS analysis_type,
        light_condition_category                        AS category,
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
        2)                                              AS critical_rate_pct,
        NULL::NUMERIC                                   AS avg_sev_false,
        ROUND(
            COUNT(*) * 100.0 / SUM(COUNT(*)) OVER (),
        2)                                              AS pct_of_total
    FROM {{ ref('stg_accidents') }}
    GROUP BY light_condition_category
),

-- POI feature analysis — avg severity TRUE vs FALSE for all 13 features
poi_agg AS (
    SELECT 'junction'       AS analysis_type,
        'junction'          AS category,
        COUNT(*) FILTER (WHERE junction        = TRUE)  AS accident_count,
        ROUND(AVG(severity) FILTER (WHERE junction        = TRUE),  3) AS avg_severity,
        NULL::NUMERIC       AS avg_duration_mins,
        NULL::BIGINT        AS critical_count,
        NULL::NUMERIC       AS critical_rate_pct,
        ROUND(AVG(severity) FILTER (WHERE junction        = FALSE), 3) AS avg_sev_false,
        NULL::NUMERIC       AS pct_of_total
    FROM {{ ref('stg_accidents') }}
    UNION ALL
    SELECT 'crossing', 'crossing',
        COUNT(*) FILTER (WHERE crossing        = TRUE),
        ROUND(AVG(severity) FILTER (WHERE crossing        = TRUE),  3),
        NULL, NULL, NULL,
        ROUND(AVG(severity) FILTER (WHERE crossing        = FALSE), 3),
        NULL
    FROM {{ ref('stg_accidents') }}
    UNION ALL
    SELECT 'traffic_signal', 'traffic_signal',
        COUNT(*) FILTER (WHERE traffic_signal  = TRUE),
        ROUND(AVG(severity) FILTER (WHERE traffic_signal  = TRUE),  3),
        NULL, NULL, NULL,
        ROUND(AVG(severity) FILTER (WHERE traffic_signal  = FALSE), 3),
        NULL
    FROM {{ ref('stg_accidents') }}
    UNION ALL
    SELECT 'roundabout', 'roundabout',
        COUNT(*) FILTER (WHERE roundabout      = TRUE),
        ROUND(AVG(severity) FILTER (WHERE roundabout      = TRUE),  3),
        NULL, NULL, NULL,
        ROUND(AVG(severity) FILTER (WHERE roundabout      = FALSE), 3),
        NULL
    FROM {{ ref('stg_accidents') }}
    UNION ALL
    SELECT 'junction_and_signal', 'junction + signal',
        COUNT(*) FILTER (WHERE junction = TRUE AND traffic_signal = TRUE),
        ROUND(AVG(severity) FILTER (WHERE junction = TRUE AND traffic_signal = TRUE),  3),
        NULL, NULL, NULL,
        ROUND(AVG(severity) FILTER (WHERE junction = FALSE AND traffic_signal = FALSE), 3),
        NULL
    FROM {{ ref('stg_accidents') }}
)

SELECT * FROM weather_agg
UNION ALL
SELECT * FROM visibility_agg
UNION ALL
SELECT * FROM light_agg
UNION ALL
SELECT * FROM poi_agg
ORDER BY analysis_type, avg_severity DESC NULLS LAST
