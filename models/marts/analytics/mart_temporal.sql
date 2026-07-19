/*
    mart_temporal
    -------------
    Analytics mart — pre-aggregated temporal analysis table.
    Materialised as a table so dashboard queries run instantly
    without rescanning 7M rows.

    Contains three granularities in one table:
      - monthly : counts + MoM change, 2016-2022
      - yearly  : counts + YoY change, 2016-2022 (2023 excluded)
      - hourly  : counts + avg severity + volume/severity ranks

    Reads from: int_temporal (view over stg_accidents)
    Used by: Phase 4 dashboard — trend charts, COVID dip visual
*/

WITH base AS (
    SELECT * FROM {{ ref('int_temporal') }}
),

-- Monthly with running total added at mart layer
monthly AS (
    SELECT
        granularity,
        period                                          AS period_date,
        accident_count,
        avg_severity,
        prev_period_count,
        pct_change                                      AS mom_pct_change,
        SUM(accident_count) OVER (
            ORDER BY period
            ROWS BETWEEN UNBOUNDED PRECEDING AND CURRENT ROW
        )                                               AS running_total,
        NULL::NUMERIC                                   AS severity_rank,
        NULL::NUMERIC                                   AS volume_rank
    FROM base
    WHERE granularity = 'monthly'
),

-- Yearly
yearly AS (
    SELECT
        granularity,
        period                                          AS period_date,
        accident_count,
        avg_severity,
        prev_period_count,
        pct_change                                      AS mom_pct_change,
        NULL::BIGINT                                    AS running_total,
        NULL::NUMERIC                                   AS severity_rank,
        NULL::NUMERIC                                   AS volume_rank
    FROM base
    WHERE granularity = 'yearly'
),

-- Hourly with severity and volume ranks
hourly AS (
    SELECT
        granularity,
        period                                          AS period_date,
        accident_count,
        avg_severity,
        NULL::BIGINT                                    AS prev_period_count,
        NULL::NUMERIC                                   AS mom_pct_change,
        NULL::BIGINT                                    AS running_total,
        RANK() OVER (ORDER BY avg_severity DESC)        AS severity_rank,
        RANK() OVER (ORDER BY accident_count DESC)      AS volume_rank
    FROM base
    WHERE granularity = 'hourly'
)

SELECT * FROM monthly
UNION ALL
SELECT * FROM yearly
UNION ALL
SELECT * FROM hourly
ORDER BY granularity, period_date
