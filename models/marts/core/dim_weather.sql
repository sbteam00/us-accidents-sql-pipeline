/*
    dim_weather
    -----------
    Weather dimension table — star schema core layer.

    Contains one row per unique combination of weather attributes
    at the time of each accident. Groups all environmental measurement
    and condition columns together.

    Referenced by: fact_accidents (via weather_id foreign key)
*/

WITH weather_base AS (
    SELECT DISTINCT
        weather_condition,
        wind_direction,
        temp_bucket,
        visibility_bucket,
        light_condition_category,
        sunrise_sunset,
        civil_twilight,
        nautical_twilight,
        astronomical_twilight
    FROM {{ ref('stg_accidents') }}
)

SELECT
    MD5(
        COALESCE(weather_condition,        'null') || '|' ||
        COALESCE(wind_direction,           'null') || '|' ||
        COALESCE(temp_bucket,              'null') || '|' ||
        COALESCE(visibility_bucket,        'null') || '|' ||
        COALESCE(light_condition_category, 'null') || '|' ||
        COALESCE(sunrise_sunset,           'null') || '|' ||
        COALESCE(civil_twilight,           'null') || '|' ||
        COALESCE(nautical_twilight,        'null') || '|' ||
        COALESCE(astronomical_twilight,    'null')
    )                               AS weather_id,
    weather_condition,
    wind_direction,
    temp_bucket,
    visibility_bucket,
    light_condition_category,
    sunrise_sunset,
    civil_twilight,
    nautical_twilight,
    astronomical_twilight
FROM weather_base
