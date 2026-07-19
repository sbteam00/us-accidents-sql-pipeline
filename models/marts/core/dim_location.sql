/*
    dim_location
    ------------
    Location dimension table — star schema core layer.

    Contains one row per unique combination of city, county, state,
    zipcode, street, and timezone. A surrogate key (location_id) is
    generated using MD5 hashing of the natural key columns so joins
    from fact_accidents are on a single key rather than multiple strings.

    Referenced by: fact_accidents (via location_id foreign key)
*/

WITH location_base AS (
    SELECT DISTINCT
        city,
        county,
        state,
        zipcode,
        street,
        timezone,
        airport_code
    FROM {{ ref('stg_accidents') }}
)

SELECT
    MD5(
        COALESCE(city,         'null') || '|' ||
        COALESCE(county,       'null') || '|' ||
        COALESCE(state,        'null') || '|' ||
        COALESCE(zipcode,      'null') || '|' ||
        COALESCE(street,       'null') || '|' ||
        COALESCE(timezone,     'null') || '|' ||
        COALESCE(airport_code, 'null')
    )                           AS location_id,
    city,
    county,
    state,
    zipcode,
    street,
    timezone,
    airport_code
FROM location_base
