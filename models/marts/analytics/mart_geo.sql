/*
    mart_geo
    --------
    Analytics mart — pre-aggregated geographic hotspot table.
    Materialised as a table for fast dashboard queries.

    Contains city-level and state-level aggregations with rankings.
    Dashboard use cases:
      - US state choropleth map (state rows)
      - Top 20 dangerous cities bar chart (city rows, volume_rank <= 20)
      - Top 5 cities per state drilldown (rank_within_state <= 5)
      - Severity vs volume rank divergence scatter (state rows)

    Reads from: int_geo_hotspots
    Used by: Phase 4 dashboard — geographic analysis panels
*/

WITH base AS (
    SELECT * FROM {{ ref('int_geo_hotspots') }}
),

-- State level: add rank divergence metric at mart layer
state_level AS (
    SELECT
        geo_level,
        NULL                                            AS city,
        state,
        accident_count,
        avg_severity,
        avg_duration_mins,
        critical_count,
        critical_rate_pct,
        volume_rank,
        severity_rank,
        -- rank_within_state repurposed as critical_rate_rank for states
        rank_within_state                               AS critical_rate_rank,
        ABS(volume_rank - severity_rank)                AS rank_divergence
    FROM base
    WHERE geo_level = 'state'
),

-- City level: top 20 global + top 5 per state filter applied here
city_level AS (
    SELECT
        geo_level,
        city,
        state,
        accident_count,
        avg_severity,
        avg_duration_mins,
        critical_count,
        critical_rate_pct,
        volume_rank,
        severity_rank,
        rank_within_state,
        NULL::BIGINT                                    AS rank_divergence
    FROM base
    WHERE geo_level = 'city'
      -- Keep top 20 globally OR top 5 within their state
      AND (volume_rank <= 20 OR rank_within_state <= 5)
)

SELECT * FROM state_level
UNION ALL
SELECT * FROM city_level
ORDER BY geo_level DESC, volume_rank
