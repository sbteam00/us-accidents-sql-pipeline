/*
    int_funnel
    ----------
    Intermediate model — severity funnel aggregations over stg_accidents.

    Produces funnel breakdowns at three levels:
      - overall         : national funnel totals
      - by_light        : funnel segmented by light_condition_category
      - by_context      : funnel segmented by incident_context
      - monthly_cohort  : monthly critical rate trend with LEAD()

    Used by: mart_funnel
*/

-- Overall national severity funnel
WITH overall AS (
    SELECT
        'overall'                                       AS funnel_dimension,
        'all'                                           AS dimension_value,
        COUNT(*)                                        AS total,
        COUNT(*) FILTER (WHERE severity >= 2)           AS sev_2_plus,
        COUNT(*) FILTER (WHERE severity >= 3)           AS sev_3_plus,
        COUNT(*) FILTER (WHERE severity  = 4)           AS critical,
        ROUND(
            COUNT(*) FILTER (WHERE severity >= 2)
            * 100.0 / NULLIF(COUNT(*), 0),
        2)                                              AS pct_sev_2_plus,
        ROUND(
            COUNT(*) FILTER (WHERE severity >= 3)
            * 100.0 / NULLIF(COUNT(*), 0),
        2)                                              AS pct_sev_3_plus,
        ROUND(
            COUNT(*) FILTER (WHERE severity  = 4)
            * 100.0 / NULLIF(COUNT(*), 0),
        2)                                              AS critical_rate_pct,
        NULL::DATE                                      AS cohort_period,
        NULL::NUMERIC                                   AS next_period_critical_rate
    FROM {{ ref('stg_accidents') }}
),

-- Funnel by light condition category
by_light AS (
    SELECT
        'by_light'                                      AS funnel_dimension,
        light_condition_category                        AS dimension_value,
        COUNT(*)                                        AS total,
        COUNT(*) FILTER (WHERE severity >= 2)           AS sev_2_plus,
        COUNT(*) FILTER (WHERE severity >= 3)           AS sev_3_plus,
        COUNT(*) FILTER (WHERE severity  = 4)           AS critical,
        ROUND(
            COUNT(*) FILTER (WHERE severity >= 2)
            * 100.0 / NULLIF(COUNT(*), 0),
        2)                                              AS pct_sev_2_plus,
        ROUND(
            COUNT(*) FILTER (WHERE severity >= 3)
            * 100.0 / NULLIF(COUNT(*), 0),
        2)                                              AS pct_sev_3_plus,
        ROUND(
            COUNT(*) FILTER (WHERE severity  = 4)
            * 100.0 / NULLIF(COUNT(*), 0),
        2)                                              AS critical_rate_pct,
        NULL::DATE                                      AS cohort_period,
        NULL::NUMERIC                                   AS next_period_critical_rate
    FROM {{ ref('stg_accidents') }}
    GROUP BY light_condition_category
),

-- Funnel by incident context
by_context AS (
    SELECT
        'by_context'                                    AS funnel_dimension,
        incident_context                                AS dimension_value,
        COUNT(*)                                        AS total,
        COUNT(*) FILTER (WHERE severity >= 2)           AS sev_2_plus,
        COUNT(*) FILTER (WHERE severity >= 3)           AS sev_3_plus,
        COUNT(*) FILTER (WHERE severity  = 4)           AS critical,
        ROUND(
            COUNT(*) FILTER (WHERE severity >= 2)
            * 100.0 / NULLIF(COUNT(*), 0),
        2)                                              AS pct_sev_2_plus,
        ROUND(
            COUNT(*) FILTER (WHERE severity >= 3)
            * 100.0 / NULLIF(COUNT(*), 0),
        2)                                              AS pct_sev_3_plus,
        ROUND(
            COUNT(*) FILTER (WHERE severity  = 4)
            * 100.0 / NULLIF(COUNT(*), 0),
        2)                                              AS critical_rate_pct,
        NULL::DATE                                      AS cohort_period,
        NULL::NUMERIC                                   AS next_period_critical_rate
    FROM {{ ref('stg_accidents') }}
    GROUP BY incident_context
),

-- Monthly cohort critical rate trend with LEAD()
monthly_base AS (
    SELECT
        DATE_TRUNC('month', start_time)::DATE           AS cohort_period,
        COUNT(*)                                        AS total,
        COUNT(*) FILTER (WHERE severity = 4)            AS critical
    FROM {{ ref('stg_accidents') }}
    WHERE EXTRACT(YEAR FROM start_time) < 2023
    GROUP BY 1
),
monthly_cohort AS (
    SELECT
        'monthly_cohort'                                AS funnel_dimension,
        TO_CHAR(cohort_period, 'YYYY-MM')               AS dimension_value,
        total,
        NULL::BIGINT                                    AS sev_2_plus,
        NULL::BIGINT                                    AS sev_3_plus,
        critical,
        NULL::NUMERIC                                   AS pct_sev_2_plus,
        NULL::NUMERIC                                   AS pct_sev_3_plus,
        ROUND(critical * 100.0 / NULLIF(total, 0), 2)  AS critical_rate_pct,
        cohort_period,
        ROUND(
            LEAD(critical * 100.0 / NULLIF(total, 0))
            OVER (ORDER BY cohort_period),
        2)                                              AS next_period_critical_rate
    FROM monthly_base
)

SELECT * FROM overall
UNION ALL
SELECT * FROM by_light
UNION ALL
SELECT * FROM by_context
UNION ALL
SELECT * FROM monthly_cohort
ORDER BY funnel_dimension, critical_rate_pct DESC NULLS LAST
