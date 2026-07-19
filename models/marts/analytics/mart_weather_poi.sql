/*
    mart_weather_poi
    ----------------
    Analytics mart — pre-aggregated weather and POI analysis table.
    Materialised as a table for fast dashboard queries.

    Contains four analysis types in one table:
      - weather_condition : top 15 conditions by count + avg severity
      - visibility_bucket : severity and duration by visibility range
      - light_condition   : severity funnel by lighting category
      - poi features      : avg severity TRUE vs FALSE per road feature

    Key findings surfaced by this mart:
      - Clear weather has higher avg severity (2.363) than rain/fog
      - Junctions highest POI severity (2.286)
      - Roundabouts lowest POI severity (2.073)

    Reads from: int_weather_poi
    Used by: Phase 4 dashboard — weather and infrastructure panels
*/

WITH base AS (
    SELECT * FROM {{ ref('int_weather_poi') }}
),

-- Weather conditions — top 15 by accident count
weather AS (
    SELECT
        analysis_type,
        category,
        accident_count,
        avg_severity,
        avg_duration_mins,
        critical_count,
        critical_rate_pct,
        avg_sev_false,
        pct_of_total,
        RANK() OVER (ORDER BY accident_count DESC)      AS display_rank
    FROM base
    WHERE analysis_type = 'weather_condition'
),

-- Visibility and light conditions — keep all rows
env AS (
    SELECT
        analysis_type,
        category,
        accident_count,
        avg_severity,
        avg_duration_mins,
        critical_count,
        critical_rate_pct,
        avg_sev_false,
        pct_of_total,
        RANK() OVER (
            PARTITION BY analysis_type
            ORDER BY avg_severity DESC
        )                                               AS display_rank
    FROM base
    WHERE analysis_type IN ('visibility_bucket', 'light_condition')
),

-- POI features — ordered by avg_severity TRUE desc
poi AS (
    SELECT
        analysis_type,
        category,
        accident_count,
        avg_severity,
        avg_duration_mins,
        critical_count,
        critical_rate_pct,
        avg_sev_false,
        pct_of_total,
        RANK() OVER (ORDER BY avg_severity DESC NULLS LAST) AS display_rank
    FROM base
    WHERE analysis_type NOT IN (
        'weather_condition', 'visibility_bucket', 'light_condition'
    )
)

SELECT * FROM weather WHERE display_rank <= 15
UNION ALL
SELECT * FROM env
UNION ALL
SELECT * FROM poi
ORDER BY analysis_type, display_rank
