/*
    int_temporal
    ------------
    Intermediate model — temporal aggregations over stg_accidents.

    Produces three result sets unioned into one table with a
    'granularity' column to distinguish them:
      - monthly : accident counts + MoM change via LAG()
      - yearly  : accident counts + YoY change via LAG()
      - hourly  : accident counts + avg severity by hour of day

    Used by: mart_temporal
*/

-- Monthly counts with month-over-month change
WITH monthly_counts AS (
    SELECT
        'monthly'                                       AS granularity,
        DATE_TRUNC('month', start_time)::DATE           AS period,
        COUNT(*)                                        AS accident_count,
        ROUND(AVG(severity), 3)                         AS avg_severity,
        NULL::NUMERIC                                   AS avg_duration_mins
    FROM {{ ref('stg_accidents') }}
    GROUP BY 2
),
monthly_with_lag AS (
    SELECT
        granularity,
        period,
        accident_count,
        avg_severity,
        avg_duration_mins,
        LAG(accident_count) OVER (ORDER BY period)      AS prev_period_count,
        ROUND(
            (accident_count - LAG(accident_count) OVER (ORDER BY period))
            * 100.0
            / NULLIF(LAG(accident_count) OVER (ORDER BY period), 0),
        2)                                              AS pct_change
    FROM monthly_counts
),

-- Yearly counts with year-over-year change
yearly_counts AS (
    SELECT
        'yearly'                                        AS granularity,
        DATE_TRUNC('year', start_time)::DATE            AS period,
        COUNT(*)                                        AS accident_count,
        ROUND(AVG(severity), 3)                         AS avg_severity,
        NULL::NUMERIC                                   AS avg_duration_mins
    FROM {{ ref('stg_accidents') }}
    -- Exclude 2023 — partial year, dataset ends early 2023
    WHERE EXTRACT(YEAR FROM start_time) < 2023
    GROUP BY 2
),
yearly_with_lag AS (
    SELECT
        granularity,
        period,
        accident_count,
        avg_severity,
        avg_duration_mins,
        LAG(accident_count) OVER (ORDER BY period)      AS prev_period_count,
        ROUND(
            (accident_count - LAG(accident_count) OVER (ORDER BY period))
            * 100.0
            / NULLIF(LAG(accident_count) OVER (ORDER BY period), 0),
        2)                                              AS pct_change
    FROM yearly_counts
),

-- Hourly distribution with severity rank vs volume rank
hourly_counts AS (
    SELECT
        'hourly'                                        AS granularity,
        -- Store hour as a date-like period for schema consistency
        -- actual hour value kept in avg_duration_mins column (reused as int)
        DATE_TRUNC('day', '2000-01-01'::DATE)
            + (hour_of_day || ' hours')::INTERVAL       AS period,
        COUNT(*)                                        AS accident_count,
        ROUND(AVG(severity), 3)                         AS avg_severity,
        -- Reuse avg_duration_mins column to carry hour_of_day value
        -- (avoids schema mismatch in UNION — mart_temporal unpacks this)
        hour_of_day::NUMERIC                            AS avg_duration_mins,
        NULL::BIGINT                                    AS prev_period_count,
        NULL::NUMERIC                                   AS pct_change
    FROM {{ ref('stg_accidents') }}
    GROUP BY hour_of_day
)

SELECT * FROM monthly_with_lag
UNION ALL
SELECT * FROM yearly_with_lag
UNION ALL
SELECT * FROM hourly_counts
ORDER BY granularity, period
