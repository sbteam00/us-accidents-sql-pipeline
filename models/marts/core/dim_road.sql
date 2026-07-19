/*
    dim_road
    --------
    Road features dimension table — star schema core layer.

    Contains one row per unique combination of road infrastructure
    flags and incident context. Groups all 13 POI boolean columns
    together with the incident classification.

    Referenced by: fact_accidents (via road_id foreign key)
*/

WITH road_base AS (
    SELECT DISTINCT
        incident_context,
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
        turning_loop
    FROM {{ ref('stg_accidents') }}
)

SELECT
    MD5(
        COALESCE(incident_context, 'null')  || '|' ||
        amenity::TEXT                       || '|' ||
        bump::TEXT                          || '|' ||
        crossing::TEXT                      || '|' ||
        give_way::TEXT                      || '|' ||
        junction::TEXT                      || '|' ||
        no_exit::TEXT                       || '|' ||
        railway::TEXT                       || '|' ||
        roundabout::TEXT                    || '|' ||
        station::TEXT                       || '|' ||
        stop::TEXT                          || '|' ||
        traffic_calming::TEXT               || '|' ||
        traffic_signal::TEXT                || '|' ||
        turning_loop::TEXT
    )                               AS road_id,
    incident_context,
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
    turning_loop
FROM road_base
