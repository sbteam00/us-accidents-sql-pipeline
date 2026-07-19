"""
ingest.py
----------
Loads the cleaned US_Accidents_cleaned.csv into a local PostgreSQL database
as a single flat table: us_accidents_db.raw.accidents

This is an intentionally simple, faithful load — no transformations happen
here. The star schema (dim_location, dim_time, dim_weather, dim_road,
fact_accidents) is built later by dbt in Phase 3. This script's only job
is to get the data into Postgres as fast and reliably as possible.

What this script does:
  1. Connects to local Postgres using psycopg2 (direct, no ORM overhead)
  2. Creates the database 'us_accidents_db' if it doesn't exist
  3. Creates the 'raw' schema inside it if it doesn't exist
  4. Drops and recreates raw.accidents with a precisely typed DDL
       - All CSV column names are renamed to clean snake_case SQL names
       - A Postgres SERIAL primary key 'id' is added
       - The original cleaned ID is kept as 'source_id' for traceability
         back to the raw Kaggle dataset
  5. Loads the cleaned CSV in chunks of 50K rows using COPY (the fastest
     Postgres bulk-load method, significantly faster than INSERT)
  6. Creates indexes on the most query-critical columns after the full
     load (creating indexes before load would slow every insert down)

Connection config:
  Edit the CONFIG block below to match your pgAdmin setup. Default assumes
  a local Postgres install with the standard postgres superuser. If you
  created a different user/password in pgAdmin, update accordingly.

Usage:
  python3 ingest.py

Requirements:
  pip install psycopg2-binary  (already in requirements.txt)
"""

import psycopg2
from psycopg2 import sql
import pandas as pd
import io
import os
import sys
import time

# ---------------------------------------------------------------------------
# Config — edit these to match your local pgAdmin / Postgres setup
# ---------------------------------------------------------------------------
CONFIG = {
    "host":     "localhost",
    "port":     5432,
    "user":     "postgres",       # your pgAdmin superuser name
    "password": "24112400",       # your pgAdmin password
    "database": "postgres",       # connect to default db first to create our db
}

TARGET_DB     = "us_accidents_db"
TARGET_SCHEMA = "raw"
TARGET_TABLE  = "accidents"
INPUT_FILE    = os.path.join("processed_data", "US_Accidents_cleaned.csv")
CHUNK_SIZE    = 50_000


# ---------------------------------------------------------------------------
# Column rename map: CSV column name -> Postgres column name
# All special characters removed, units folded into name, snake_case.
# ---------------------------------------------------------------------------
COLUMN_RENAME = {
    "ID":                       "source_id",
    "Source":                   "source",
    "Severity":                 "severity",
    "Start_Time":               "start_time",
    "End_Time":                 "end_time",
    "Start_Lat":                "start_lat",
    "Start_Lng":                "start_lng",
    "Distance(mi)":             "distance_mi",
    "Description":              "description",
    "Street":                   "street",
    "City":                     "city",
    "County":                   "county",
    "State":                    "state",
    "Zipcode":                  "zipcode",
    "Timezone":                 "timezone",
    "Airport_Code":             "airport_code",
    "Weather_Timestamp":        "weather_timestamp",
    "Temperature(F)":           "temperature_f",
    "Humidity(%)":              "humidity_pct",
    "Pressure(in)":             "pressure_in",
    "Visibility(mi)":           "visibility_mi",
    "Wind_Direction":           "wind_direction",
    "Wind_Speed(mph)":          "wind_speed_mph",
    "Precipitation(in)":        "precipitation_in",
    "Weather_Condition":        "weather_condition",
    "Amenity":                  "amenity",
    "Bump":                     "bump",
    "Crossing":                 "crossing",
    "Give_Way":                 "give_way",
    "Junction":                 "junction",
    "No_Exit":                  "no_exit",
    "Railway":                  "railway",
    "Roundabout":               "roundabout",
    "Station":                  "station",
    "Stop":                     "stop",
    "Traffic_Calming":          "traffic_calming",
    "Traffic_Signal":           "traffic_signal",
    "Turning_Loop":             "turning_loop",
    "Sunrise_Sunset":           "sunrise_sunset",
    "Civil_Twilight":           "civil_twilight",
    "Nautical_Twilight":        "nautical_twilight",
    "Astronomical_Twilight":    "astronomical_twilight",
    "duration_mins":            "duration_mins",
    "hour_of_day":              "hour_of_day",
    "day_of_week":              "day_of_week",
    "is_weekend":               "is_weekend",
    "is_rush_hour":             "is_rush_hour",
    "temp_bucket":              "temp_bucket",
    "visibility_bucket":        "visibility_bucket",
    "light_condition_category": "light_condition_category",
    "incident_context":         "incident_context"
}


# ---------------------------------------------------------------------------
# DDL — precisely typed CREATE TABLE statement
# 'id' SERIAL is the Postgres-owned primary key (contiguous, no gaps).
# 'source_id' is the original cleaned dataset ID kept for traceability.
# ---------------------------------------------------------------------------
DDL = """
CREATE TABLE {schema}.{table} (

    -- Postgres-owned primary key (contiguous, no gaps from row deletion)
    id                       SERIAL            PRIMARY KEY,

    -- Original dataset identifier (may have gaps from preprocessing)
    source_id                BIGINT,
    source                   TEXT,

    -- Accident core fields
    severity                 SMALLINT          NOT NULL,
    start_time               TIMESTAMP         NOT NULL,
    end_time                 TIMESTAMP,
    duration_mins            NUMERIC(10, 2),

    -- Location
    start_lat                DOUBLE PRECISION,
    start_lng                DOUBLE PRECISION,
    distance_mi              NUMERIC(8, 3),
    street                   TEXT,
    city                     TEXT,
    county                   TEXT,
    state                    CHAR(2),
    zipcode                  VARCHAR(10),
    timezone                 TEXT,
    airport_code             VARCHAR(10),

    -- Weather measurements at time of accident
    weather_timestamp        TIMESTAMP,
    temperature_f            NUMERIC(5, 2),
    humidity_pct             NUMERIC(5, 2),
    pressure_in              NUMERIC(5, 2),
    visibility_mi            NUMERIC(6, 2),
    wind_direction           VARCHAR(20),
    wind_speed_mph           NUMERIC(6, 2),
    precipitation_in         NUMERIC(6, 2),
    weather_condition        TEXT,

    -- Road infrastructure boolean flags (13 POI columns)
    amenity                  BOOLEAN,
    bump                     BOOLEAN,
    crossing                 BOOLEAN,
    give_way                 BOOLEAN,
    junction                 BOOLEAN,
    no_exit                  BOOLEAN,
    railway                  BOOLEAN,
    roundabout               BOOLEAN,
    station                  BOOLEAN,
    stop                     BOOLEAN,
    traffic_calming          BOOLEAN,
    traffic_signal           BOOLEAN,
    turning_loop             BOOLEAN,

    -- Light / twilight condition columns
    sunrise_sunset           VARCHAR(10),
    civil_twilight           VARCHAR(10),
    nautical_twilight        VARCHAR(10),
    astronomical_twilight    VARCHAR(10),

    -- Engineered columns (derived during preprocessing)
    hour_of_day              SMALLINT,
    day_of_week              VARCHAR(10),
    is_weekend               BOOLEAN,
    is_rush_hour             BOOLEAN,
    temp_bucket              VARCHAR(15),
    visibility_bucket        VARCHAR(15),
    light_condition_category VARCHAR(25),
    incident_context         VARCHAR(40),

    -- Free-text description (kept for row-level display queries)
    description              TEXT
);
"""

# Indexes created AFTER the full load for maximum insert throughput.
# Chosen based on the query patterns planned in Phases 2-4:
#   state/city          -> geographic GROUP BY and ranking queries
#   severity            -> severity distribution and window functions
#   start_time          -> temporal analysis, LAG/LEAD, DATE_TRUNC
#   incident_context    -> categorical aggregation
#   junction/crossing   -> POI infrastructure analysis
#   state + severity    -> composite for state-level severity breakdowns
INDEXES = [
    ("idx_accidents_state",     "state"),
    ("idx_accidents_city",      "city"),
    ("idx_accidents_severity",  "severity"),
    ("idx_accidents_start_time","start_time"),
    ("idx_accidents_incident",  "incident_context"),
    ("idx_accidents_junction",  "junction"),
    ("idx_accidents_crossing",  "crossing"),
    ("idx_accidents_hour",      "hour_of_day"),
]
# Composite index defined separately (can't use single-column shorthand)
COMPOSITE_INDEXES = [
    ("idx_accidents_state_sev", "state, severity"),
]


def log(msg):
    print(f"[{time.strftime('%H:%M:%S')}] {msg}", flush=True)


# ---------------------------------------------------------------------------
# Database / schema helpers
# ---------------------------------------------------------------------------
def create_database_if_not_exists():
    """
    Connects to the default 'postgres' database to check/create our target
    database. CREATE DATABASE must run outside a transaction block, hence
    autocommit=True for this one connection only.
    """
    conn = psycopg2.connect(**CONFIG)
    conn.autocommit = True
    cur = conn.cursor()

    cur.execute("SELECT 1 FROM pg_database WHERE datname = %s", (TARGET_DB,))
    if cur.fetchone():
        log(f"Database '{TARGET_DB}' already exists.")
    else:
        cur.execute(
            sql.SQL("CREATE DATABASE {}").format(sql.Identifier(TARGET_DB))
        )
        log(f"Database '{TARGET_DB}' created.")

    cur.close()
    conn.close()


def get_target_conn():
    """Open a connection to the target database."""
    return psycopg2.connect(**{**CONFIG, "database": TARGET_DB})


def setup_schema_and_table(conn):
    """
    Creates the raw schema if it doesn't exist, then drops and recreates
    the accidents table so re-runs always start from a clean state.
    """
    cur = conn.cursor()

    cur.execute(
        sql.SQL("CREATE SCHEMA IF NOT EXISTS {}").format(
            sql.Identifier(TARGET_SCHEMA)
        )
    )

    # DROP CASCADE handles any views/indexes that depend on the old table
    cur.execute(
        sql.SQL("DROP TABLE IF EXISTS {}.{} CASCADE").format(
            sql.Identifier(TARGET_SCHEMA),
            sql.Identifier(TARGET_TABLE),
        )
    )

    # Format DDL with schema/table names safely
    cur.execute(
        DDL.replace("{schema}", TARGET_SCHEMA).replace("{table}", TARGET_TABLE)
    )

    conn.commit()
    cur.close()
    log(f"Schema '{TARGET_SCHEMA}' ready. Table '{TARGET_SCHEMA}.{TARGET_TABLE}' created.")


# ---------------------------------------------------------------------------
# Core load — COPY via in-memory StringIO buffer
# ---------------------------------------------------------------------------
def load_chunk(conn, chunk_df):
    """
    Loads one DataFrame chunk using PostgreSQL COPY FROM STDIN.

    COPY is the fastest bulk-load method in Postgres — it bypasses the query
    planner entirely and writes directly to table storage. Benchmarks on
    similar datasets typically show 5-10x faster throughput vs. INSERT.

    The 'id' column is SERIAL (auto-assigned by Postgres) so it is excluded
    from the COPY column list — Postgres fills it automatically.

    Nulls are written as empty strings in the CSV buffer and the COPY command
    maps empty strings back to NULL via NULL ''.
    """
    chunk_df = chunk_df.rename(columns=COLUMN_RENAME)

    # Maintain column order matching the DDL (id excluded — SERIAL)
    pg_columns = list(COLUMN_RENAME.values())
    chunk_df = chunk_df[pg_columns]

    # Write to in-memory CSV buffer
    buffer = io.StringIO()
    chunk_df.to_csv(buffer, index=False, header=False, na_rep="")
    buffer.seek(0)

    cur = conn.cursor()
    col_list = ", ".join(f'"{c}"' for c in pg_columns)
    copy_sql = (
        f"COPY {TARGET_SCHEMA}.{TARGET_TABLE} ({col_list}) "
        f"FROM STDIN WITH (FORMAT CSV, NULL '')"
    )
    cur.copy_expert(copy_sql, buffer)
    conn.commit()
    cur.close()


def create_indexes(conn):
    """Creates all single-column and composite indexes after the full load."""
    cur = conn.cursor()

    for name, column in INDEXES:
        log(f"  Creating index: {name} ...")
        cur.execute(
            f'CREATE INDEX {name} ON {TARGET_SCHEMA}.{TARGET_TABLE} ("{column}");'
        )
        conn.commit()

    for name, columns in COMPOSITE_INDEXES:
        log(f"  Creating composite index: {name} ...")
        cur.execute(
            f"CREATE INDEX {name} ON {TARGET_SCHEMA}.{TARGET_TABLE} ({columns});"
        )
        conn.commit()

    cur.close()
    log(f"All {len(INDEXES) + len(COMPOSITE_INDEXES)} indexes created.")


# ---------------------------------------------------------------------------
# Verification query — quick sanity check after load
# ---------------------------------------------------------------------------
def verify_load(conn):
    cur = conn.cursor()

    cur.execute(f"SELECT COUNT(*) FROM {TARGET_SCHEMA}.{TARGET_TABLE};")
    count = cur.fetchone()[0]

    cur.execute(
        f"SELECT severity, COUNT(*) FROM {TARGET_SCHEMA}.{TARGET_TABLE} "
        f"GROUP BY severity ORDER BY severity;"
    )
    severity_dist = cur.fetchall()

    cur.execute(
        f"SELECT state, COUNT(*) as cnt FROM {TARGET_SCHEMA}.{TARGET_TABLE} "
        f"GROUP BY state ORDER BY cnt DESC LIMIT 5;"
    )
    top_states = cur.fetchall()

    cur.close()

    log(f"Verification: {count:,} total rows loaded.")
    log(f"Severity distribution: {dict(severity_dist)}")
    log(f"Top 5 states by accident count: {top_states}")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------
def main():
    if not os.path.exists(INPUT_FILE):
        log(f"ERROR: '{INPUT_FILE}' not found. Run preprocess.py first.")
        sys.exit(1)

    log("=" * 60)
    log("US Accidents — Postgres Ingestion")
    log("=" * 60)

    # Step 1: ensure database exists
    log("Step 1/4: Checking / creating database...")
    create_database_if_not_exists()

    # Step 2: create schema + table
    log("Step 2/4: Setting up schema and table...")
    conn = get_target_conn()
    setup_schema_and_table(conn)

    # Step 3: chunked COPY load
    log(f"Step 3/4: Loading data (chunk size = {CHUNK_SIZE:,} rows)...")
    total_rows = 0
    start = time.time()

    reader = pd.read_csv(
        INPUT_FILE,
        chunksize=CHUNK_SIZE,
        low_memory=False,
        dtype={"Zipcode": str},  # preserve leading zeros
    )

    for i, chunk in enumerate(reader, start=1):
        load_chunk(conn, chunk)
        total_rows += len(chunk)
        elapsed = time.time() - start
        rate = int(total_rows / elapsed) if elapsed > 0 else 0
        log(f"  Chunk {i:>3} → {total_rows:>9,} rows loaded  ({rate:,} rows/sec)")

    elapsed_total = time.time() - start
    log(f"Load complete: {total_rows:,} rows in {elapsed_total:.1f}s "
        f"({int(total_rows / elapsed_total):,} rows/sec avg)")

    # Step 4: indexes
    log("Step 4/4: Creating indexes...")
    create_indexes(conn)

    # Bonus: quick verification
    log("Running verification queries...")
    verify_load(conn)

    conn.close()

    log("")
    log("=" * 60)
    log("Ingestion complete. raw.accidents is ready in us_accidents_db.")
    log("Open pgAdmin and verify with:")
    log("  SELECT COUNT(*) FROM raw.accidents;")
    log("  SELECT * FROM raw.accidents LIMIT 5;")
    log("=" * 60)


if __name__ == "__main__":
    main()
