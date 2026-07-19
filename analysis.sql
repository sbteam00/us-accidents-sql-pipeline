-- =============================================================================
-- US ACCIDENTS — PHASE 2: CORE SQL ANALYTICS
-- Database : us_accidents_db
-- Schema   : raw
-- Table    : raw.accidents (~7.05M rows post-cleaning)
--
-- Run each block independently in pgAdmin using the query tool.
-- These queries form the foundation of the dbt models built in Phase 3.
-- Results from each block feed the Phase 6 dashboard and insight narrative.
-- =============================================================================

-- =============================================================================
-- BLOCK 1: AGGREGATIONS & DISTRIBUTIONS
-- Purpose : Understand the basic shape of the data before applying any window
--           functions. These are the first numbers you will quote in the README.
-- =============================================================================

-- 1.1  Overall row count sanity check — should match ingest output
SELECT COUNT(*) AS total_accidents
FROM raw.accidents;


-- 1.2  Accident count and percentage by severity level (1=least, 4=most severe)
--      Expect severity 2 to dominate (~70-75% based on dataset documentation)
SELECT
    severity,
    COUNT(*)                                            AS accident_count,
    ROUND(COUNT(*) * 100.0 / SUM(COUNT(*)) OVER (), 2) AS pct_of_total
FROM raw.accidents
GROUP BY severity
ORDER BY severity;


-- 1.3  Accident count by US state, ranked highest to lowest
--      Reveals geographic concentration — CA, TX, FL typically dominate
SELECT
    state,
    COUNT(*)                                   AS accident_count,
    ROUND(COUNT(*) * 100.0 / SUM(COUNT(*)) OVER (), 2) AS pct_of_total,
    RANK() OVER (ORDER BY COUNT(*) DESC)       AS state_rank
FROM raw.accidents
GROUP BY state
ORDER BY accident_count DESC;


-- 1.4  Accident count by source (MapQuest vs Bing)
--      Useful context — source affects description format and geographic bias
SELECT
    source,
    COUNT(*)                                            AS accident_count,
    ROUND(COUNT(*) * 100.0 / SUM(COUNT(*)) OVER (), 2) AS pct_of_total
FROM raw.accidents
GROUP BY source
ORDER BY accident_count DESC;


-- 1.5  Incident context distribution
--      Validates the two-stage classification from preprocessing.
--      Check what % remains as 'other' on the real 7M row dataset.
SELECT
    incident_context,
    COUNT(*)                                            AS accident_count,
    ROUND(COUNT(*) * 100.0 / SUM(COUNT(*)) OVER (), 2) AS pct_of_total
FROM raw.accidents
GROUP BY incident_context
ORDER BY accident_count DESC;


-- 1.6  Hourly accident distribution across all records
--      Expect clear rush hour spikes at 7-9am and 4-6pm
SELECT
    hour_of_day,
    COUNT(*)                                            AS accident_count,
    ROUND(COUNT(*) * 100.0 / SUM(COUNT(*)) OVER (), 2) AS pct_of_total
FROM raw.accidents
GROUP BY hour_of_day
ORDER BY hour_of_day;


-- 1.7  Accident count by day of week
--      Weekday vs weekend pattern — typically fewer accidents on weekends
--      despite comparable traffic hours, due to commuter vs leisure driving
SELECT
    day_of_week,
    COUNT(*)                                            AS accident_count,
    ROUND(COUNT(*) * 100.0 / SUM(COUNT(*)) OVER (), 2) AS pct_of_total
FROM raw.accidents
GROUP BY day_of_week
ORDER BY
    CASE day_of_week
        WHEN 'Monday'    THEN 1
        WHEN 'Tuesday'   THEN 2
        WHEN 'Wednesday' THEN 3
        WHEN 'Thursday'  THEN 4
        WHEN 'Friday'    THEN 5
        WHEN 'Saturday'  THEN 6
        WHEN 'Sunday'    THEN 7
    END;


-- 1.8  Weather condition breakdown — top 15
--      'Clear' typically accounts for the majority (counterintuitive but true
--      since clear weather = more vehicles on the road overall)
SELECT
    weather_condition,
    COUNT(*)                                            AS accident_count,
    ROUND(COUNT(*) * 100.0 / SUM(COUNT(*)) OVER (), 2) AS pct_of_total,
    ROUND(AVG(severity), 3)                             AS avg_severity
FROM raw.accidents
GROUP BY weather_condition
ORDER BY accident_count DESC
LIMIT 15;


-- 1.9  Temp bucket vs average severity
--      Tests whether extreme temperatures correlate with worse accidents
SELECT
    temp_bucket,
    COUNT(*)                AS accident_count,
    ROUND(AVG(severity), 3) AS avg_severity,
    ROUND(AVG(duration_mins) FILTER (WHERE duration_mins > 0 AND duration_mins < 1440), 2)
                            AS avg_duration_mins
FROM raw.accidents
GROUP BY temp_bucket
ORDER BY
    CASE temp_bucket
        WHEN 'Freezing' THEN 1
        WHEN 'Cold'     THEN 2
        WHEN 'Mild'     THEN 3
        WHEN 'Warm'     THEN 4
        WHEN 'Hot'      THEN 5
    END;


-- =============================================================================
-- BLOCK 2: TEMPORAL ANALYSIS WITH WINDOW FUNCTIONS
-- Purpose : Detect trends over time using LAG, LEAD, running totals, and
--           DATE_TRUNC. The COVID-2020 traffic dip is the headline finding here.
-- Technique: LAG(), SUM() OVER(), RANK() OVER(), DATE_TRUNC()
-- =============================================================================

-- 2.1  Monthly accident counts with month-over-month change using LAG()
--      The COVID dip should show a sharp negative MoM % in March/April 2020
--      and a recovery signal through late 2020 into 2021
WITH monthly_counts AS (
    SELECT
        DATE_TRUNC('month', start_time)::DATE AS accident_month,
        COUNT(*)                               AS accident_count
    FROM raw.accidents
    GROUP BY 1
),
with_lag AS (
    SELECT
        accident_month,
        accident_count,
        LAG(accident_count) OVER (ORDER BY accident_month) AS prev_month_count
    FROM monthly_counts
)
SELECT
    accident_month,
    accident_count,
    prev_month_count,
    accident_count - prev_month_count                              AS mom_change,
    ROUND(
        (accident_count - prev_month_count) * 100.0
        / NULLIF(prev_month_count, 0),
    2)                                                             AS mom_pct_change
FROM with_lag
ORDER BY accident_month;


-- 2.2  Year-over-year accident totals
--      Confirms the COVID-2020 dip at the annual level and shows the post-2021
--      recovery. A cleaner summary to put in the README than monthly granularity.
WITH yearly AS (
    SELECT
        EXTRACT(YEAR FROM start_time)::INT AS accident_year,
        COUNT(*)                           AS accident_count
    FROM raw.accidents
    GROUP BY 1
)
SELECT
    accident_year,
    accident_count,
    LAG(accident_count) OVER (ORDER BY accident_year) AS prev_year_count,
    accident_count
        - LAG(accident_count) OVER (ORDER BY accident_year) AS yoy_change,
    ROUND(
        (accident_count
            - LAG(accident_count) OVER (ORDER BY accident_year)) * 100.0
        / NULLIF(LAG(accident_count) OVER (ORDER BY accident_year), 0),
    2)                                                     AS yoy_pct_change
FROM yearly
ORDER BY accident_year;


-- 2.3  Running total of accidents over time (cumulative growth curve)
--      Good for the dashboard — shows the dataset's full timeline as a
--      monotonically increasing line chart
WITH monthly AS (
    SELECT
        DATE_TRUNC('month', start_time)::DATE AS accident_month,
        COUNT(*)                               AS monthly_count
    FROM raw.accidents
    GROUP BY 1
)
SELECT
    accident_month,
    monthly_count,
    SUM(monthly_count) OVER (ORDER BY accident_month) AS running_total
FROM monthly
ORDER BY accident_month;


-- 2.4  Top 5 most dangerous hours by average severity (not just count)
--      High-count hours (rush hour) vs high-severity hours often differ —
--      late night hours (1-4am) typically have lower volume but worse severity
SELECT
    hour_of_day,
    COUNT(*)                AS accident_count,
    ROUND(AVG(severity), 3) AS avg_severity,
    RANK() OVER (ORDER BY AVG(severity) DESC) AS severity_rank,
    RANK() OVER (ORDER BY COUNT(*) DESC)      AS volume_rank
FROM raw.accidents
GROUP BY hour_of_day
ORDER BY avg_severity DESC;


-- 2.5  Rush hour vs non-rush hour comparison
--      Quantifies the actual severity difference between peak and off-peak
SELECT
    is_rush_hour,
    COUNT(*)                                            AS accident_count,
    ROUND(COUNT(*) * 100.0 / SUM(COUNT(*)) OVER (), 2) AS pct_of_total,
    ROUND(AVG(severity), 3)                             AS avg_severity,
    ROUND(AVG(duration_mins) FILTER (WHERE duration_mins > 0 AND duration_mins < 1440), 2)
                                                        AS avg_duration_mins
FROM raw.accidents
GROUP BY is_rush_hour
ORDER BY is_rush_hour;


-- 2.6  Weekday vs weekend severity and duration comparison
SELECT
    is_weekend,
    COUNT(*)                AS accident_count,
    ROUND(AVG(severity), 3) AS avg_severity,
    ROUND(AVG(duration_mins) FILTER (WHERE duration_mins > 0 AND duration_mins < 1440), 2)
                            AS avg_duration_mins
FROM raw.accidents
GROUP BY is_weekend;


-- =============================================================================
-- BLOCK 3: GEOGRAPHIC HOTSPOT ANALYSIS WITH CTEs
-- Purpose : Identify the most dangerous cities and states using nested CTEs
--           and window functions. Demonstrates multi-step CTE logic which is
--           a core interview pattern at analytics engineering roles.
-- Technique: Nested CTEs, RANK() OVER (PARTITION BY), DENSE_RANK()
-- =============================================================================

-- 3.1  Top 20 most dangerous cities by accident count
--      Multi-step CTE: aggregate → rank → filter
--      The nesting here is what makes this an interview-worthy query
WITH city_counts AS (
    SELECT
        city,
        state,
        COUNT(*)                AS accident_count,
        ROUND(AVG(severity), 3) AS avg_severity,
        ROUND(AVG(duration_mins) FILTER (WHERE duration_mins > 0 AND duration_mins < 1440), 2)
                                AS avg_duration_mins
    FROM raw.accidents
    GROUP BY city, state
),
city_ranked AS (
    SELECT
        city,
        state,
        accident_count,
        avg_severity,
        avg_duration_mins,
        RANK() OVER (ORDER BY accident_count DESC) AS city_rank
    FROM city_counts
)
SELECT *
FROM city_ranked
WHERE city_rank <= 20
ORDER BY city_rank;


-- 3.2  Top 5 most dangerous cities WITHIN EACH STATE
--      PARTITION BY state means the rank resets per state —
--      finds local hotspots that a global ranking would miss
WITH city_state_counts AS (
    SELECT
        state,
        city,
        COUNT(*)                AS accident_count,
        ROUND(AVG(severity), 3) AS avg_severity
    FROM raw.accidents
    GROUP BY state, city
),
ranked AS (
    SELECT
        state,
        city,
        accident_count,
        avg_severity,
        RANK() OVER (PARTITION BY state ORDER BY accident_count DESC) AS rank_within_state
    FROM city_state_counts
)
SELECT *
FROM ranked
WHERE rank_within_state <= 5
ORDER BY state, rank_within_state;


-- 3.3  State-level severity ranking
--      Which states have the worst accidents on average, not just the most
--      DENSE_RANK used here so tied states share the same rank position
SELECT
    state,
    COUNT(*)                                           AS accident_count,
    ROUND(AVG(severity), 3)                            AS avg_severity,
    DENSE_RANK() OVER (ORDER BY AVG(severity) DESC)    AS severity_rank,
    DENSE_RANK() OVER (ORDER BY COUNT(*) DESC)         AS volume_rank
FROM raw.accidents
GROUP BY state
ORDER BY avg_severity DESC;


-- 3.4  States where severity rank and volume rank diverge the most
--      Surfaces states that have fewer accidents but disproportionately
--      severe ones — a nuanced finding most people miss
WITH state_stats AS (
    SELECT
        state,
        COUNT(*)                                        AS accident_count,
        ROUND(AVG(severity), 3)                         AS avg_severity,
        DENSE_RANK() OVER (ORDER BY AVG(severity) DESC) AS severity_rank,
        DENSE_RANK() OVER (ORDER BY COUNT(*) DESC)      AS volume_rank
    FROM raw.accidents
    GROUP BY state
)
SELECT
    state,
    accident_count,
    avg_severity,
    severity_rank,
    volume_rank,
    ABS(severity_rank - volume_rank) AS rank_divergence
FROM state_stats
ORDER BY rank_divergence DESC
LIMIT 15;


-- =============================================================================
-- BLOCK 4: WEATHER & POI INFRASTRUCTURE IMPACT
-- Purpose : Quantify the effect of environmental and road-feature conditions
--           on accident severity. The 13 boolean POI columns are unique to
--           this dataset — this analysis is a genuine portfolio differentiator.
-- Technique: CASE pivoting, GROUP BY on booleans, conditional aggregation
-- =============================================================================

-- 4.1  Visibility bucket vs average severity
--      Low visibility should correlate with higher severity
SELECT
    visibility_bucket,
    COUNT(*)                AS accident_count,
    ROUND(AVG(severity), 3) AS avg_severity,
    ROUND(AVG(distance_mi), 3) AS avg_distance_mi
FROM raw.accidents
GROUP BY visibility_bucket
ORDER BY
    CASE visibility_bucket
        WHEN 'Low'      THEN 1
        WHEN 'Moderate' THEN 2
        WHEN 'Clear'    THEN 3
    END;


-- 4.2  Light condition category vs severity
--      Tests the hypothesis that Dawn_Dusk_Transition is the most dangerous
--      lighting condition (glare + low contrast)
SELECT
    light_condition_category,
    COUNT(*)                AS accident_count,
    ROUND(AVG(severity), 3) AS avg_severity
FROM raw.accidents
GROUP BY light_condition_category
ORDER BY avg_severity DESC;


-- 4.3  POI infrastructure analysis — average severity per road feature
--      For each of the 13 boolean columns, compares avg severity when the
--      feature is TRUE vs FALSE.
--      FILTER(WHERE ...) is cleaner than CASE WHEN for this pattern.
SELECT
    'junction'        AS poi_feature,
    ROUND(AVG(severity) FILTER (WHERE junction        = TRUE),  3) AS avg_sev_true,
    ROUND(AVG(severity) FILTER (WHERE junction        = FALSE), 3) AS avg_sev_false,
    COUNT(*)          FILTER (WHERE junction        = TRUE)        AS count_true
FROM raw.accidents
UNION ALL
SELECT 'crossing',
    ROUND(AVG(severity) FILTER (WHERE crossing        = TRUE),  3),
    ROUND(AVG(severity) FILTER (WHERE crossing        = FALSE), 3),
    COUNT(*)          FILTER (WHERE crossing        = TRUE)
FROM raw.accidents
UNION ALL
SELECT 'traffic_signal',
    ROUND(AVG(severity) FILTER (WHERE traffic_signal  = TRUE),  3),
    ROUND(AVG(severity) FILTER (WHERE traffic_signal  = FALSE), 3),
    COUNT(*)          FILTER (WHERE traffic_signal  = TRUE)
FROM raw.accidents
UNION ALL
SELECT 'roundabout',
    ROUND(AVG(severity) FILTER (WHERE roundabout      = TRUE),  3),
    ROUND(AVG(severity) FILTER (WHERE roundabout      = FALSE), 3),
    COUNT(*)          FILTER (WHERE roundabout      = TRUE)
FROM raw.accidents
UNION ALL
SELECT 'stop',
    ROUND(AVG(severity) FILTER (WHERE stop            = TRUE),  3),
    ROUND(AVG(severity) FILTER (WHERE stop            = FALSE), 3),
    COUNT(*)          FILTER (WHERE stop            = TRUE)
FROM raw.accidents
UNION ALL
SELECT 'give_way',
    ROUND(AVG(severity) FILTER (WHERE give_way        = TRUE),  3),
    ROUND(AVG(severity) FILTER (WHERE give_way        = FALSE), 3),
    COUNT(*)          FILTER (WHERE give_way        = TRUE)
FROM raw.accidents
UNION ALL
SELECT 'railway',
    ROUND(AVG(severity) FILTER (WHERE railway         = TRUE),  3),
    ROUND(AVG(severity) FILTER (WHERE railway         = FALSE), 3),
    COUNT(*)          FILTER (WHERE railway         = TRUE)
FROM raw.accidents
UNION ALL
SELECT 'station',
    ROUND(AVG(severity) FILTER (WHERE station         = TRUE),  3),
    ROUND(AVG(severity) FILTER (WHERE station         = FALSE), 3),
    COUNT(*)          FILTER (WHERE station         = TRUE)
FROM raw.accidents
UNION ALL
SELECT 'amenity',
    ROUND(AVG(severity) FILTER (WHERE amenity         = TRUE),  3),
    ROUND(AVG(severity) FILTER (WHERE amenity         = FALSE), 3),
    COUNT(*)          FILTER (WHERE amenity         = TRUE)
FROM raw.accidents
UNION ALL
SELECT 'bump',
    ROUND(AVG(severity) FILTER (WHERE bump            = TRUE),  3),
    ROUND(AVG(severity) FILTER (WHERE bump            = FALSE), 3),
    COUNT(*)          FILTER (WHERE bump            = TRUE)
FROM raw.accidents
UNION ALL
SELECT 'no_exit',
    ROUND(AVG(severity) FILTER (WHERE no_exit         = TRUE),  3),
    ROUND(AVG(severity) FILTER (WHERE no_exit         = FALSE), 3),
    COUNT(*)          FILTER (WHERE no_exit         = TRUE)
FROM raw.accidents
UNION ALL
SELECT 'traffic_calming',
    ROUND(AVG(severity) FILTER (WHERE traffic_calming = TRUE),  3),
    ROUND(AVG(severity) FILTER (WHERE traffic_calming = FALSE), 3),
    COUNT(*)          FILTER (WHERE traffic_calming = TRUE)
FROM raw.accidents
UNION ALL
SELECT 'turning_loop',
    ROUND(AVG(severity) FILTER (WHERE turning_loop    = TRUE),  3),
    ROUND(AVG(severity) FILTER (WHERE turning_loop    = FALSE), 3),
    COUNT(*)          FILTER (WHERE turning_loop    = TRUE)
FROM raw.accidents
ORDER BY avg_sev_true DESC NULLS LAST;


-- 4.4  Compound POI risk — accidents near BOTH a junction AND a traffic signal
--      vs either alone vs neither. Compound infrastructure = compound risk?
SELECT
    CASE
        WHEN junction = TRUE  AND traffic_signal = TRUE  THEN 'junction + signal'
        WHEN junction = TRUE  AND traffic_signal = FALSE THEN 'junction only'
        WHEN junction = FALSE AND traffic_signal = TRUE  THEN 'signal only'
        ELSE 'neither'
    END                     AS road_context,
    COUNT(*)                AS accident_count,
    ROUND(AVG(severity), 3) AS avg_severity,
    ROUND(AVG(duration_mins) FILTER (WHERE duration_mins > 0 AND duration_mins < 1440), 2)
                            AS avg_duration_mins
FROM raw.accidents
GROUP BY 1
ORDER BY avg_severity DESC;


-- 4.5  Weather condition pivot — accident count by weather for top 5 states
--      Demonstrates CASE-based pivoting: rows to columns
--      Edit the state list to match the top 5 from query 1.3
WITH weather_by_state AS (
    SELECT
        state,
        SUM(CASE WHEN weather_condition ILIKE '%clear%'       THEN 1 ELSE 0 END) AS clear,
        SUM(CASE WHEN weather_condition ILIKE '%rain%'
                  OR weather_condition ILIKE '%shower%'        THEN 1 ELSE 0 END) AS rain,
        SUM(CASE WHEN weather_condition ILIKE '%snow%'
                  OR weather_condition ILIKE '%sleet%'         THEN 1 ELSE 0 END) AS snow,
        SUM(CASE WHEN weather_condition ILIKE '%fog%'
                  OR weather_condition ILIKE '%mist%'          THEN 1 ELSE 0 END) AS fog,
        SUM(CASE WHEN weather_condition ILIKE '%cloud%'
                  OR weather_condition ILIKE '%overcast%'      THEN 1 ELSE 0 END) AS cloudy,
        COUNT(*)                                                                   AS total
    FROM raw.accidents
    WHERE state IN ('CA', 'FL', 'TX', 'SC', 'NY')  -- update from query 1.3 results
    GROUP BY state
)
SELECT
    state,
    clear,
    rain,
    snow,
    fog,
    cloudy,
    total
FROM weather_by_state
ORDER BY total DESC;


-- =============================================================================
-- BLOCK 5: FUNNEL & SEVERITY ESCALATION ANALYSIS
-- Purpose : Model severity as a funnel (total → moderate → serious → critical)
--           and analyse how contextual factors shift the distribution.
--           Demonstrates cohort-style filtering and conditional aggregation.
-- Technique: Funnel CTEs, LEAD(), conditional COUNT, severity cohorts
-- =============================================================================

-- 5.1  Severity funnel — absolute counts and drop-off at each level
--      Visualise as a funnel chart in Looker Studio
WITH funnel AS (
    SELECT
        COUNT(*)                                    AS total_accidents,
        COUNT(*) FILTER (WHERE severity >= 2)       AS severity_2_plus,
        COUNT(*) FILTER (WHERE severity >= 3)       AS severity_3_plus,
        COUNT(*) FILTER (WHERE severity  = 4)       AS severity_4_critical
    FROM raw.accidents
)
SELECT
    total_accidents,
    severity_2_plus,
    severity_3_plus,
    severity_4_critical,
    ROUND(severity_2_plus    * 100.0 / total_accidents,  2) AS pct_sev_2_plus,
    ROUND(severity_3_plus    * 100.0 / total_accidents,  2) AS pct_sev_3_plus,
    ROUND(severity_4_critical* 100.0 / total_accidents,  2) AS pct_sev_4
FROM funnel;


-- 5.2  Severity funnel broken down by light condition
--      Does darkness shift the funnel toward higher severity?
WITH funnel_by_light AS (
    SELECT
        light_condition_category,
        COUNT(*)                                    AS total,
        COUNT(*) FILTER (WHERE severity >= 2)       AS sev_2_plus,
        COUNT(*) FILTER (WHERE severity >= 3)       AS sev_3_plus,
        COUNT(*) FILTER (WHERE severity  = 4)       AS sev_4
    FROM raw.accidents
    GROUP BY light_condition_category
)
SELECT
    light_condition_category,
    total,
    sev_2_plus,
    sev_3_plus,
    sev_4,
    ROUND(sev_4 * 100.0 / NULLIF(total, 0), 2) AS pct_critical
FROM funnel_by_light
ORDER BY pct_critical DESC;


-- 5.3  Severity funnel by incident context
--      Which incident types escalate to critical (severity 4) most often?
WITH context_funnel AS (
    SELECT
        incident_context,
        COUNT(*)                                    AS total,
        COUNT(*) FILTER (WHERE severity >= 3)       AS serious_or_worse,
        COUNT(*) FILTER (WHERE severity  = 4)       AS critical
    FROM raw.accidents
    GROUP BY incident_context
)
SELECT
    incident_context,
    total,
    serious_or_worse,
    critical,
    ROUND(critical * 100.0 / NULLIF(total, 0), 2) AS critical_rate_pct
FROM context_funnel
ORDER BY critical_rate_pct DESC;


-- 5.4  Monthly severity cohort — how does the severity mix shift over time?
--      Each month is a cohort; we track its severity-4 rate
--      A rising critical_rate over the years signals worsening accident quality
WITH monthly_cohort AS (
    SELECT
        DATE_TRUNC('month', start_time)::DATE       AS cohort_month,
        COUNT(*)                                    AS total,
        COUNT(*) FILTER (WHERE severity = 4)        AS critical
    FROM raw.accidents
    GROUP BY 1
)
SELECT
    cohort_month,
    total,
    critical,
    ROUND(critical * 100.0 / NULLIF(total, 0), 2)  AS critical_rate_pct,
    -- LEAD to see what the next month's critical rate looks like
    ROUND(
        LEAD(critical * 100.0 / NULLIF(total, 0))
        OVER (ORDER BY cohort_month),
    2)                                              AS next_month_critical_rate
FROM monthly_cohort
ORDER BY cohort_month;


-- 5.5  State-level severity funnel — which states have the worst critical rate?
--      Combines geographic ranking (Block 3) with funnel logic (Block 5)
--      This is the most complex query in the file — a good dbt mart candidate
WITH state_funnel AS (
    SELECT
        state,
        COUNT(*)                                    AS total,
        COUNT(*) FILTER (WHERE severity >= 2)       AS sev_2_plus,
        COUNT(*) FILTER (WHERE severity >= 3)       AS sev_3_plus,
        COUNT(*) FILTER (WHERE severity  = 4)       AS critical,
        ROUND(AVG(severity), 3)                     AS avg_severity
    FROM raw.accidents
    GROUP BY state
),
ranked AS (
    SELECT
        *,
        ROUND(critical * 100.0 / NULLIF(total, 0), 2) AS critical_rate_pct,
        RANK() OVER (ORDER BY critical * 1.0 / NULLIF(total, 0) DESC)
                                                        AS critical_rate_rank
    FROM state_funnel
)
SELECT
    state,
    total          AS total_accidents,
    critical,
    critical_rate_pct,
    critical_rate_rank,
    avg_severity
FROM ranked
ORDER BY critical_rate_rank;
