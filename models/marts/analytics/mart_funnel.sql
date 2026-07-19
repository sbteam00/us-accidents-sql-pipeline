/*
    mart_funnel
    -----------
    Analytics mart — pre-aggregated severity funnel analysis table.
    Materialised as a table for fast dashboard queries.

    Contains four funnel dimensions in one table:
      - overall        : national totals (single row summary)
      - by_light       : funnel by lighting condition
      - by_context     : funnel by incident context (critical rate ranked)
      - monthly_cohort : monthly critical rate trend with LEAD()

    Key findings surfaced by this mart:
      - Full_Night has 4.05% critical rate vs Full_Day 2.18%
      - road_closure has 41.36% critical rate
      - COVID lockdown (Mar-Jun 2020) spiked critical rates to 3.77-4.71%

    Reads from: int_funnel
    Used by: Phase 4 dashboard — funnel charts and cohort trend line
*/

WITH base AS (
    SELECT * FROM {{ ref('int_funnel') }}
),

-- Overall national funnel — single summary row
overall AS (
    SELECT
        funnel_dimension,
        dimension_value,
        total,
        sev_2_plus,
        sev_3_plus,
        critical,
        pct_sev_2_plus,
        pct_sev_3_plus,
        critical_rate_pct,
        cohort_period,
        next_period_critical_rate,
        NULL::BIGINT                                    AS context_rank
    FROM base
    WHERE funnel_dimension = 'overall'
),

-- By light condition — all 3 rows
by_light AS (
    SELECT
        funnel_dimension,
        dimension_value,
        total,
        sev_2_plus,
        sev_3_plus,
        critical,
        pct_sev_2_plus,
        pct_sev_3_plus,
        critical_rate_pct,
        cohort_period,
        next_period_critical_rate,
        RANK() OVER (ORDER BY critical_rate_pct DESC)   AS context_rank
    FROM base
    WHERE funnel_dimension = 'by_light'
),

-- By incident context — ranked by critical rate
by_context AS (
    SELECT
        funnel_dimension,
        dimension_value,
        total,
        sev_2_plus,
        sev_3_plus,
        critical,
        pct_sev_2_plus,
        pct_sev_3_plus,
        critical_rate_pct,
        cohort_period,
        next_period_critical_rate,
        RANK() OVER (ORDER BY critical_rate_pct DESC)   AS context_rank
    FROM base
    WHERE funnel_dimension = 'by_context'
),

-- Monthly cohort — filtered to 2016-2022, sorted chronologically
monthly_cohort AS (
    SELECT
        funnel_dimension,
        dimension_value,
        total,
        sev_2_plus,
        sev_3_plus,
        critical,
        pct_sev_2_plus,
        pct_sev_3_plus,
        critical_rate_pct,
        cohort_period,
        next_period_critical_rate,
        NULL::BIGINT                                    AS context_rank
    FROM base
    WHERE funnel_dimension = 'monthly_cohort'
      -- 2023 already excluded in int_funnel; order chronologically
    ORDER BY cohort_period
)

SELECT * FROM overall
UNION ALL
SELECT * FROM by_light
UNION ALL
SELECT * FROM by_context
UNION ALL
SELECT * FROM monthly_cohort
ORDER BY funnel_dimension, context_rank NULLS LAST, cohort_period NULLS LAST
