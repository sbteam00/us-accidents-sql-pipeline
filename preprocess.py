"""
preprocess.py
-------------
Cleans and transforms the raw US_Accidents dataset for the SQL analytics
pipeline project.

Input  : US_Accidents.csv          (raw Kaggle dataset, ~7.7M rows, 46 cols)
Output : processed_data/US_Accidents_cleaned.csv

Pipeline order (per chunk):
  1. Drop columns: End_Lat, End_Lng, Country, Wind_Chill(F)
       - No analytical value (End_Lat/Lng, Country) or ~88%+ null with no
         clean signal (Wind_Chill).
  2. Parse Start_Time / End_Time robustly (handles mixed nanosecond-suffix
     formatting present in the raw data - see parse_datetime_column()).
  3. Clean ID ('A-1' -> 1), Zipcode (truncate hyphenated suffix, kept as
     string), Timezone ('US/Eastern' -> 'Eastern').
  4. Precipitation(in) null -> 0.0 (semantic fix: null means "no
     precipitation recorded", not "missing data" - done BEFORE the row-drop
     step so these rows are not discarded).
  5. Blanket row deletion: any row with a null remaining in ANY source
     column is dropped entirely (quality-over-quantity decision; overall
     null percentage across the dataset is small and nulls tend to cluster
     in the same rows across several weather columns together).
  6. Feature engineering (every derived column below is guaranteed null-free
     by construction, since step 5 already removed any row with incomplete
     source data):
       - duration_mins (rounded to 2 decimal places)
       - hour_of_day, day_of_week, is_weekend, is_rush_hour
       - temp_bucket, visibility_bucket
       - light_condition_category (from the 4 twilight columns)
       - incident_context (two-stage: keyword rules from Description, then
         POI-based fallback for remaining 'other' rows using Junction /
         Crossing / Traffic_Signal columns and exit/ramp patterns)
  7. Boolean column type enforcement (13 POI flags)

Net result: the cleaned CSV has zero missing values in any column, with no
separate imputation logic needed downstream.
"""

import pandas as pd
import numpy as np
import re
import os
import sys
import time

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------
RAW_FILE = "US_Accidents.csv"
OUTPUT_DIR = "processed_data"
OUTPUT_FILE = os.path.join(OUTPUT_DIR, "US_Accidents_cleaned.csv")
CHUNK_SIZE = 200_000  # rows per chunk, safe for 7.7M row file on limited RAM

# Columns confirmed for outright removal
COLUMNS_TO_DROP = ["End_Lat", "End_Lng", "Country", "Wind_Chill(F)"]

# The 13 boolean POI / road-feature columns in the raw dataset
BOOLEAN_COLUMNS = [
    "Amenity", "Bump", "Crossing", "Give_Way", "Junction", "No_Exit",
    "Railway", "Roundabout", "Station", "Stop", "Traffic_Calming",
    "Traffic_Signal", "Turning_Loop",
]

# The 4 twilight columns used to derive light_condition_category
TWILIGHT_COLUMNS = [
    "Sunrise_Sunset", "Civil_Twilight", "Nautical_Twilight", "Astronomical_Twilight"
]

# Rush hour windows (24h clock)
RUSH_HOUR_RANGES = [(7, 9), (16, 18)]  # 7-9am, 4-6pm inclusive of start, exclusive of end+1 handled below

# Keyword rules for incident_context (expanded rule-based classification).
# Order matters — first match wins. All patterns are case-insensitive.
#
# Two-stage logic:
#   Stage 1 (here): keyword match against Description text.
#   Stage 2 (POI fallback in compute_incident_context): for rows that
#            reach "other" after stage 1, fall back to the boolean POI
#            columns (Junction, Crossing, Traffic_Signal) and description
#            location patterns (exit, ramp) to derive a road-context label.
#
# Column is named incident_context (not incident_category) to reflect that
# it combines incident-type signal (stage 1) with road-context signal
# (stage 2) - a hybrid that's more honest to what the dataset actually
# contains. The majority of descriptions are machine-generated API strings
# that describe WHERE the accident happened, not WHAT happened, so pure
# incident-type classification has a hard ceiling regardless of rule quality.
INCIDENT_KEYWORD_RULES = [
    # Road / lane impact — checked first since these are the most actionable
    ("road_closure",     [r"road closed", r"closed due to", r"all lanes (?:blocked|closed)"]),
    ("lane_closure",     [r"\b(?:right|left|center) lane\b", r"lane (?:blocked|closed)"]),
    ("shoulder_blocked", [r"\b(?:right|left) shoulder\b"]),
    # Injury signal
    ("injury_reported",  [r"with injur", r"injur\w+ report", r"serious accident"]),
    # Vehicle-type incidents
    ("vehicle_type",     [r"overturned", r"jackknif", r"tractor.trailer", r"\btruck\b", r"big rig"]),
    # Pedestrian / hit-and-run
    ("pedestrian",       [r"pedestrian", r"vs\.? pedestrian", r"hit.and.run"]),
    # Road work / infrastructure activity
    ("road_work",        [r"construct\w+", r"utility work", r"road work", r"lane shift"]),
    # Weather-driven hazard
    ("weather_related",  [r"black ice", r"flood\w*", r"reduced visibility", r"\bfog\b"]),
    # Congestion / slow traffic with no other signal
    ("slow_traffic",     [r"slow traffic", r"traffic slower", r"congestion due to", r"rear.end"]),
    # Multi-vehicle (narrowed to avoid false-positives like 'emergency vehicles')
    ("multi_vehicle",    [r"multi.vehicle", r"\d+.vehicle"]),
    # Disabled / on-fire vehicle
    ("disabled_vehicle", [r"\bstalled\b", r"disabled vehicle", r"vehicle fire"]),
    # Debris / road hazard
    ("debris_hazard",    [r"\bdebris\b", r"object on road", r"\bhazard\b", r"fallen tree"]),
]


def log(msg):
    print(f"[{time.strftime('%H:%M:%S')}] {msg}", flush=True)


# ---------------------------------------------------------------------------
# Per-chunk transformation
# ---------------------------------------------------------------------------
def clean_id(series):
    """'A-1' -> 1 (int). Strips any leading non-digit characters."""
    return series.astype(str).str.replace(r"^[A-Za-z\-]+", "", regex=True).astype("Int64")


def clean_zipcode(series):
    """'12345-6789' -> '12345'. Kept as string to preserve leading zeros.

    IMPORTANT: when this cleaned CSV is read back later (report generation,
    Postgres ingestion, etc.), Zipcode MUST be read with dtype=str /
    dtype={'Zipcode': str}. Otherwise pandas will auto-infer the column as
    float64 and silently corrupt values like '02134' -> 2134.0, '78701' ->
    78701.0. The value is written correctly here; this is purely a
    read-side gotcha to watch for downstream.
    """
    return series.astype(str).str.split("-").str[0]


def clean_timezone(series):
    """'US/Eastern' -> 'Eastern'."""
    return series.astype(str).str.replace(r"^US/", "", regex=True)


def parse_datetime_column(series):
    """
    Robustly parses Start_Time / End_Time columns.

    The raw dataset mixes two formats in the same column:
        'YYYY-MM-DD HH:MM:SS'
        'YYYY-MM-DD HH:MM:SS.000000000'   (nanosecond suffix)

    Relying on pandas' automatic format inference across chunked reads is
    unreliable here - when a chunk has a mix of both formats, inference can
    silently fail on some rows and produce NaT even though the row is
    perfectly parseable. To avoid that, we deterministically strip any
    trailing '.<digits>' fractional-seconds suffix BEFORE parsing, so every
    row reduces to the same plain 'YYYY-MM-DD HH:MM:SS' format regardless of
    how many digits of sub-second precision the original had.
    """
    cleaned = series.astype(str).str.replace(r"\.\d+$", "", regex=True)
    return pd.to_datetime(cleaned, format="%Y-%m-%d %H:%M:%S", errors="coerce")


def compute_duration_mins(df):
    """End_Time - Start_Time in minutes, rounded to 2 decimal places.

    Note: this can still legitimately be negative or unrealistically large
    on the real dataset (a documented quirk where some End_Time values are
    placeholder/default rather than real measurements). The blanket
    null-drop step does NOT catch this, since these rows have valid
    (non-null) timestamps - they're just logically inconsistent. Outlier
    handling for duration_mins specifically is intentionally deferred to a
    later pass; check the distribution in the report before deciding how to
    treat it.
    """
    delta = (df["End_Time"] - df["Start_Time"]).dt.total_seconds() / 60.0
    return delta.round(2)


def compute_hour_day_features(df):
    hour = df["Start_Time"].dt.hour
    dow_name = df["Start_Time"].dt.day_name()  # 'Monday', 'Tuesday', ...
    is_weekend = df["Start_Time"].dt.dayofweek >= 5  # 5=Sat, 6=Sun

    is_rush = pd.Series(False, index=df.index)
    for start, end in RUSH_HOUR_RANGES:
        is_rush = is_rush | ((hour >= start) & (hour <= end))

    return hour, dow_name, is_weekend, is_rush


def compute_temp_bucket(temp_series):
    """Bucket Temperature(F) into readable categories. NaNs stay NaN."""
    bins = [-np.inf, 32, 50, 70, 90, np.inf]
    labels = ["Freezing", "Cold", "Mild", "Warm", "Hot"]
    return pd.cut(temp_series, bins=bins, labels=labels)


def compute_visibility_bucket(vis_series):
    """Bucket Visibility(mi) into readable categories. NaNs stay NaN."""
    bins = [-np.inf, 1, 5, np.inf]
    labels = ["Low", "Moderate", "Clear"]
    return pd.cut(vis_series, bins=bins, labels=labels)


def compute_light_condition_category(df):
    """
    Compares Sunrise_Sunset against the 3 twilight columns to detect the
    dawn/dusk transition window, which is a distinct (and more dangerous)
    lighting condition than plain day or night.

    Logic:
      - All 4 columns == 'Day'   -> 'Full_Day'
      - All 4 columns == 'Night' -> 'Full_Night'
      - Mixed (Sunrise_Sunset says Night/Day but at least one twilight
        column disagrees) -> 'Dawn_Dusk_Transition'

    Note: by the time this runs, drop_rows_with_nulls() has already removed
    any row with a null in any of the 4 twilight columns, so every row here
    has complete data - no NaN branch is needed.
    """
    cols = [df[c] for c in TWILIGHT_COLUMNS]

    all_day = pd.concat([c == "Day" for c in cols], axis=1).all(axis=1)
    all_night = pd.concat([c == "Night" for c in cols], axis=1).all(axis=1)

    category = pd.Series(np.where(all_day, "Full_Day",
                          np.where(all_night, "Full_Night", "Dawn_Dusk_Transition")),
                          index=df.index)
    return category


def compute_incident_context(df):
    """
    Two-stage hybrid classifier producing the incident_context column.

    Stage 1 — keyword match against Description text (order matters):
      Catches lane/road closures, injuries, vehicle type, pedestrian,
      road work, weather hazards, slow traffic, multi-vehicle, disabled
      vehicles, and debris. First match wins.

    Stage 2 — POI fallback for rows still labelled 'other' after stage 1:
      Uses the boolean Junction / Crossing / Traffic_Signal columns and
      exit/ramp patterns in the description to derive a road-context label.
      This recovers a large portion of the location-only API strings
      (e.g. 'Accident on I-75 at Exit 21') that contain no incident-type
      keywords but DO have POI flags set.

      Fallback priority:
        highway_exit   — Junction=True AND description contains 'exit'/'ramp'
        junction       — Junction=True (no exit/ramp keyword)
        crossing       — Crossing=True
        signalized     — Traffic_Signal=True
        other          — genuinely unclassifiable (bare 'Accident.' strings)

    Column is named incident_context rather than incident_category because
    it is a deliberate hybrid of incident-type signal (stage 1) and
    road-context signal (stage 2). Documenting this distinction in the
    README is recommended.
    """
    desc_lower = df["Description"].astype(str).str.lower()
    context = pd.Series("other", index=df.index)

    # ── Stage 1: keyword rules ──────────────────────────────────────────────
    for label, patterns in INCIDENT_KEYWORD_RULES:
        combined = "|".join(patterns)
        matched = desc_lower.str.contains(combined, regex=True, na=False)
        still_other = context == "other"
        context[matched & still_other] = label

    # ── Stage 2: POI fallback for remaining 'other' rows ───────────────────
    is_other = context == "other"
    if is_other.any():
        has_exit_ramp = desc_lower.str.contains(r"\bexit\b|\bramp\b", regex=True, na=False)
        junction      = df["Junction"].astype(bool)
        crossing      = df["Crossing"].astype(bool)
        signal        = df["Traffic_Signal"].astype(bool)

        # Apply fallbacks in priority order; only touch rows still 'other'
        context[is_other & junction & has_exit_ramp] = "location_highway_exit"
        is_other = context == "other"

        context[is_other & junction] = "location_junction"
        is_other = context == "other"

        context[is_other & crossing] = "location_crossing"
        is_other = context == "other"

        context[is_other & signal] = "location_signalized_intersection"

    return context


def drop_rows_with_nulls(chunk):
    """
    Blanket row-deletion rule: any row with a null in ANY remaining source
    column is discarded entirely, rather than imputed.

    This is intentionally run BEFORE feature engineering, for two reasons:
      1. Precipitation(in) nulls are already filled with 0.0 earlier in the
         pipeline (semantic fix, not "missing data"), so it is correctly
         exempt from this check by the time we get here.
      2. Running this check before deriving temp_bucket, visibility_bucket,
         light_condition_category, etc. guarantees every derived column is
         null-free by construction - a row only survives if its underlying
         source data was complete, so there's nothing left for the derived
         columns to inherit as null.

    Net effect: every column in the final cleaned CSV is guaranteed to have
    zero missing values, with no separate imputation logic required.
    """
    before = len(chunk)
    chunk = chunk.dropna(axis=0, how="any")
    after = len(chunk)
    return chunk, before, after


def process_chunk(chunk, totals):
    # --- 1. Drop unneeded columns -----------------------------------------
    chunk = chunk.drop(columns=[c for c in COLUMNS_TO_DROP if c in chunk.columns])

    # --- 2. Datetime conversion (robust to nanosecond-suffix rows) ---------
    chunk["Start_Time"] = parse_datetime_column(chunk["Start_Time"])
    chunk["End_Time"] = parse_datetime_column(chunk["End_Time"])

    # --- 3. ID / Zipcode / Timezone cleanup ---------------------------------
    chunk["ID"] = clean_id(chunk["ID"])
    chunk["Zipcode"] = clean_zipcode(chunk["Zipcode"])
    chunk["Timezone"] = clean_timezone(chunk["Timezone"])

    # --- 4. Precipitation null -> 0.0 (semantic fix, exempt from row drop) -
    if "Precipitation(in)" in chunk.columns:
        chunk["Precipitation(in)"] = chunk["Precipitation(in)"].fillna(0.0)

    # --- 5. Blanket row deletion: drop any row with a remaining null in a
    #        source column, BEFORE feature engineering (see function docstring
    #        for why ordering matters here) -----------------------------------
    chunk, before_count, after_count = drop_rows_with_nulls(chunk)
    totals["rows_seen"] += before_count
    totals["rows_dropped"] += (before_count - after_count)
    totals["rows_kept"] += after_count

    if len(chunk) == 0:
        # Entire chunk was dropped - nothing left to feature-engineer
        return chunk

    # --- 6. Feature engineering ---------------------------------------------
    chunk["duration_mins"] = compute_duration_mins(chunk)

    hour, dow_name, is_weekend, is_rush = compute_hour_day_features(chunk)
    chunk["hour_of_day"] = hour
    chunk["day_of_week"] = dow_name
    chunk["is_weekend"] = is_weekend
    chunk["is_rush_hour"] = is_rush

    chunk["temp_bucket"] = compute_temp_bucket(chunk["Temperature(F)"])
    chunk["visibility_bucket"] = compute_visibility_bucket(chunk["Visibility(mi)"])
    chunk["light_condition_category"] = compute_light_condition_category(chunk)
    chunk["incident_context"] = compute_incident_context(chunk)

    # Description is intentionally KEPT (not dropped) - incident_context is
    # for fast analytical GROUP BY usage, Description remains for detailed
    # row-level / display queries (e.g. "show full info for accident X").
    # These serve different query patterns, so both are retained.

    # --- 7. Boolean column enforcement --------------------------------------
    for col in BOOLEAN_COLUMNS:
        if col in chunk.columns:
            chunk[col] = chunk[col].astype("boolean")  # pandas nullable boolean

    return chunk


# ---------------------------------------------------------------------------
# Main driver - chunked read/write to handle 7.7M rows safely
# ---------------------------------------------------------------------------
def main():
    if not os.path.exists(RAW_FILE):
        log(f"ERROR: '{RAW_FILE}' not found in current directory. "
            f"Place the raw Kaggle CSV here and re-run.")
        sys.exit(1)

    os.makedirs(OUTPUT_DIR, exist_ok=True)

    log(f"Starting chunked preprocessing of '{RAW_FILE}' (chunk size = {CHUNK_SIZE:,} rows)")

    total_rows_written = 0
    first_chunk = True
    totals = {"rows_seen": 0, "rows_dropped": 0, "rows_kept": 0}

    reader = pd.read_csv(RAW_FILE, chunksize=CHUNK_SIZE, low_memory=False)

    for i, chunk in enumerate(reader, start=1):
        cleaned_chunk = process_chunk(chunk, totals)

        if len(cleaned_chunk) == 0:
            log(f"Chunk {i:>3}: all rows dropped (nulls) - nothing to write")
            continue

        # Write header only on first chunk; append mode thereafter
        cleaned_chunk.to_csv(
            OUTPUT_FILE,
            mode="w" if first_chunk else "a",
            header=first_chunk,
            index=False,
        )
        first_chunk = False

        total_rows_written += len(cleaned_chunk)
        log(f"Chunk {i:>3} processed -> {len(cleaned_chunk):,} rows kept "
            f"(running total written: {total_rows_written:,})")

    drop_pct = round((totals["rows_dropped"] / totals["rows_seen"]) * 100, 3) if totals["rows_seen"] else 0.0
    log(f"Done. Rows seen: {totals['rows_seen']:,} | "
        f"Rows dropped (nulls): {totals['rows_dropped']:,} ({drop_pct}%) | "
        f"Rows written: {total_rows_written:,}")
    log(f"Output: '{OUTPUT_FILE}'")


if __name__ == "__main__":
    main()
