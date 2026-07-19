
/*
    stg_accidents
    -------------
    Staging layer — clean pointer to raw.accidents.

    This model does NOT transform, aggregate, or filter data.
    Its only jobs are:
      1. Declare raw.accidents as the single source of truth via source()
         so dbt can build the lineage graph correctly
      2. Select all columns explicitly (no SELECT *) so column changes
         in raw surface here first and are visible in dbt docs
      3. Apply minor casts where the raw type needs adjustment for
         downstream models (start_time, end_time cast to TIMESTAMP)

    Every model above this layer references ref('stg_accidents')
    instead of raw.accidents directly. If raw.accidents ever changes,
    only this file needs updating.
*/

SELECT
    -- Primary keys
    id                          AS accident_id,
    source_id,

    -- Source / data provenance
    source,

    -- Severity and timing
    severity,
    start_time::TIMESTAMP       AS start_time,
    end_time::TIMESTAMP         AS end_time,
    duration_mins,

    -- Location
    start_lat,
    start_lng,
    distance_mi,
    street,
    city,
    county,
    state,
    zipcode,
    timezone,
    airport_code,

    -- Weather measurements
    weather_timestamp::TIMESTAMP AS weather_timestamp,
    temperature_f,
    humidity_pct,
    pressure_in,
    visibility_mi,
    wind_direction,
    wind_speed_mph,
    precipitation_in,
    weather_condition,

    -- Road infrastructure flags (13 POI boolean columns)
    amenity,
    bump,
    crossing,
    give_way,
    junction,
    no_exit,
    railway,
    roundabout,
    station,
    stop,
    traffic_calming,
    traffic_signal,
    turning_loop,

    -- Light and twilight conditions
    sunrise_sunset,
    civil_twilight,
    nautical_twilight,
    astronomical_twilight,

    -- Engineered columns from preprocessing
    hour_of_day,
    day_of_week,
    is_weekend,
    is_rush_hour,
    temp_bucket,
    visibility_bucket,
    light_condition_category,
    incident_context,

    -- Free-text description (kept for row-level display queries)
    description

FROM {{ source('raw', 'accidents') }}
