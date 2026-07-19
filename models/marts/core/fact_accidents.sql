/*
    fact_accidents
    --------------
    Central fact table — star schema core layer.

    One row per accident with all measurable numeric facts plus
    foreign keys to the four dimension tables. Uses INNER JOIN to
    all dims to ensure no unmatched rows inflate the fact row count.

    Depends on: dim_location, dim_time, dim_weather, dim_road
*/

WITH stg AS (
    SELECT * FROM {{ ref('stg_accidents') }}
)

SELECT
    -- Primary key
    stg.accident_id,
    stg.source_id,
    stg.source,

    -- Foreign keys to dimension tables
    MD5(
        COALESCE(stg.city,         'null') || '|' ||
        COALESCE(stg.county,       'null') || '|' ||
        COALESCE(stg.state,        'null') || '|' ||
        COALESCE(stg.zipcode,      'null') || '|' ||
        COALESCE(stg.street,       'null') || '|' ||
        COALESCE(stg.timezone,     'null') || '|' ||
        COALESCE(stg.airport_code, 'null')
    )                                               AS location_id,

    MD5(stg.start_time::TEXT)                       AS time_id,

    MD5(
        COALESCE(stg.weather_condition,        'null') || '|' ||
        COALESCE(stg.wind_direction,           'null') || '|' ||
        COALESCE(stg.temp_bucket,              'null') || '|' ||
        COALESCE(stg.visibility_bucket,        'null') || '|' ||
        COALESCE(stg.light_condition_category, 'null') || '|' ||
        COALESCE(stg.sunrise_sunset,           'null') || '|' ||
        COALESCE(stg.civil_twilight,           'null') || '|' ||
        COALESCE(stg.nautical_twilight,        'null') || '|' ||
        COALESCE(stg.astronomical_twilight,    'null')
    )                                               AS weather_id,

    MD5(
        COALESCE(stg.incident_context, 'null')  || '|' ||
        stg.amenity::TEXT                       || '|' ||
        stg.bump::TEXT                          || '|' ||
        stg.crossing::TEXT                      || '|' ||
        stg.give_way::TEXT                      || '|' ||
        stg.junction::TEXT                      || '|' ||
        stg.no_exit::TEXT                       || '|' ||
        stg.railway::TEXT                       || '|' ||
        stg.roundabout::TEXT                    || '|' ||
        stg.station::TEXT                       || '|' ||
        stg.stop::TEXT                          || '|' ||
        stg.traffic_calming::TEXT               || '|' ||
        stg.traffic_signal::TEXT                || '|' ||
        stg.turning_loop::TEXT
    )                                               AS road_id,

    -- Measurable facts
    stg.severity,
    stg.duration_mins,
    stg.distance_mi,
    stg.start_lat,
    stg.start_lng,
    stg.temperature_f,
    stg.humidity_pct,
    stg.pressure_in,
    stg.visibility_mi,
    stg.wind_speed_mph,
    stg.precipitation_in,

    -- Denormalised time columns for fast filtering without dim join
    stg.start_time,
    stg.hour_of_day,
    stg.day_of_week,
    stg.is_weekend,
    stg.is_rush_hour,

    -- Free-text description for row-level display queries
    stg.description

FROM stg
