"""
generate_stats_report.py
-------------------------
Generates a JSON report of DESCRIPTIVE STATISTICS for the cleaned dataset
(US_Accidents_cleaned.csv). This is intentionally separate from
generate_null_report.py (which only checks for missing values) - that
script remains as a standalone regression check you can rerun any time you
touch preprocess.py again, and is not merged into this one.

Scope of this report (descriptive stats only - NO interpretation):
  - For CATEGORICAL columns (object/bool dtype, or low-cardinality numeric
    columns like Severity, hour_of_day): full value counts if the column
    has <= CATEGORICAL_FULL_THRESHOLD unique values, otherwise top-N values
    plus a single "other" bucket covering everything beyond the top-N.
  - For CONTINUOUS NUMERIC columns (high-cardinality numeric, e.g.
    Temperature(F), Distance(mi), duration_mins): min, max, mean, median,
    std, and quartiles.

This report does NOT draw conclusions ("Texas has the most accidents",
"fog correlates with severity") - it only produces the numbers. Business
interpretation is a separate, manual step once these statistics are
available (and may also feed the Phase 6 dashboard/README narrative
later, similar to how the EDA project's report fed its insights phase).

Column classification is automatic based on dtype + cardinality - see
classify_column() for the exact rule. No hardcoded column list, so this
keeps working even if upstream columns change.

Input  : processed_data/US_Accidents_cleaned.csv
Output : processed_data/stats_report.json
"""

import pandas as pd
import numpy as np
import json
import os
import sys
import time
from collections import Counter

INPUT_FILE = os.path.join("processed_data", "US_Accidents_cleaned.csv")
REPORT_FILE = os.path.join("processed_data", "stats_report.json")
CHUNK_SIZE = 500_000

# A categorical column with <= this many unique values gets a FULL
# breakdown. Above this, it gets top-N + "other".
CATEGORICAL_FULL_THRESHOLD = 20

# How many top values to show for high-cardinality categorical columns
TOP_N = 15

# Numeric columns are still treated as CATEGORICAL (not continuous) if their
# distinct value count is <= this threshold, e.g. Severity (1-4),
# hour_of_day (0-23), is_weekend (0/1).
NUMERIC_CATEGORICAL_CARDINALITY_THRESHOLD = 25

# Columns to skip entirely - free text / identifiers with no useful
# distributional summary (every value is ~unique by design).
SKIP_COLUMNS = ["ID", "Description"]


def log(msg):
    print(f"[{time.strftime('%H:%M:%S')}] {msg}", flush=True)


# ---------------------------------------------------------------------------
# Pass 1: classify every column as 'categorical' or 'numeric' using a
# single lightweight scan (distinct-value count + dtype), before doing the
# full chunked accumulation pass.
# ---------------------------------------------------------------------------
def classify_columns(sample_df):
    classification = {}
    for col in sample_df.columns:
        if col in SKIP_COLUMNS:
            continue

        dtype = sample_df[col].dtype
        is_numeric_dtype = pd.api.types.is_numeric_dtype(dtype)

        if not is_numeric_dtype:
            # object / bool / category / datetime -> categorical
            # (datetime columns are handled as categorical-by-skip below)
            classification[col] = "categorical"
            continue

        nunique_sample = sample_df[col].nunique(dropna=True)
        if nunique_sample <= NUMERIC_CATEGORICAL_CARDINALITY_THRESHOLD:
            classification[col] = "categorical"
        else:
            classification[col] = "numeric"

    return classification


# ---------------------------------------------------------------------------
# Pass 2: chunked accumulation of statistics based on classification
# ---------------------------------------------------------------------------
def accumulate_categorical(counters, col, series):
    if col not in counters:
        counters[col] = Counter()
    counters[col].update(series.dropna().astype(str).tolist())


def accumulate_numeric(numeric_accum, col, series):
    """
    Accumulates enough raw values to compute exact min/max/mean/std/median/
    quartiles at the end. For a 7M-row dataset this keeps one float64 array
    per numeric column in memory, which is acceptable (a handful of numeric
    columns x 7M floats is a few hundred MB at most) - it avoids needing a
    second full pass or approximate streaming quantile algorithms.
    """
    if col not in numeric_accum:
        numeric_accum[col] = []
    numeric_accum[col].append(series.dropna().to_numpy(dtype="float64"))


def finalize_categorical(col, counter, total_non_null):
    items = counter.most_common()
    if len(items) <= CATEGORICAL_FULL_THRESHOLD:
        breakdown = [
            {"value": val, "count": cnt, "pct": round(cnt / total_non_null * 100, 3)}
            for val, cnt in items
        ]
        truncated = False
    else:
        top_items = items[:TOP_N]
        other_count = sum(cnt for _, cnt in items[TOP_N:])
        breakdown = [
            {"value": val, "count": cnt, "pct": round(cnt / total_non_null * 100, 3)}
            for val, cnt in top_items
        ]
        breakdown.append({
            "value": "__other__",
            "count": other_count,
            "pct": round(other_count / total_non_null * 100, 3),
        })
        truncated = True

    return {
        "type": "categorical",
        "unique_values_total": len(items),
        "truncated_to_top_n": truncated,
        "breakdown": breakdown,
    }


def finalize_numeric(col, arrays):
    full = np.concatenate(arrays) if arrays else np.array([])
    if full.size == 0:
        return {"type": "numeric", "count": 0}

    return {
        "type": "numeric",
        "count": int(full.size),
        "min": round(float(np.min(full)), 3),
        "max": round(float(np.max(full)), 3),
        "mean": round(float(np.mean(full)), 3),
        "median": round(float(np.median(full)), 3),
        "std": round(float(np.std(full)), 3),
        "q1_25pct": round(float(np.percentile(full, 25)), 3),
        "q3_75pct": round(float(np.percentile(full, 75)), 3),
    }


def main():
    if not os.path.exists(INPUT_FILE):
        log(f"ERROR: '{INPUT_FILE}' not found. Run preprocess.py first.")
        sys.exit(1)

    log("Reading a sample chunk to classify columns (categorical vs numeric)...")
    sample = pd.read_csv(INPUT_FILE, nrows=50_000, dtype={"Zipcode": str}, low_memory=False)
    classification = classify_columns(sample)

    log(f"Classified {len(classification)} columns: "
        f"{sum(1 for v in classification.values() if v == 'categorical')} categorical, "
        f"{sum(1 for v in classification.values() if v == 'numeric')} numeric")

    counters = {}        # col -> Counter (categorical)
    numeric_accum = {}   # col -> list of np arrays (numeric)
    total_rows = 0

    reader = pd.read_csv(
        INPUT_FILE,
        chunksize=CHUNK_SIZE,
        low_memory=False,
        dtype={"Zipcode": str},
    )

    log(f"Scanning '{INPUT_FILE}' in chunks of {CHUNK_SIZE:,} rows for descriptive statistics...")

    for i, chunk in enumerate(reader, start=1):
        for col, kind in classification.items():
            if col not in chunk.columns:
                continue
            if kind == "categorical":
                accumulate_categorical(counters, col, chunk[col])
            else:
                accumulate_numeric(numeric_accum, col, chunk[col])

        total_rows += len(chunk)
        log(f"Chunk {i:>3} scanned (running total: {total_rows:,} rows)")

    log("Finalizing statistics...")

    per_column_report = {}
    for col, kind in classification.items():
        if kind == "categorical":
            counter = counters.get(col, Counter())
            total_non_null = sum(counter.values())
            per_column_report[col] = finalize_categorical(col, counter, total_non_null)
        else:
            arrays = numeric_accum.get(col, [])
            per_column_report[col] = finalize_numeric(col, arrays)

    report = {
        "generated_at": time.strftime("%Y-%m-%d %H:%M:%S"),
        "source_file": INPUT_FILE,
        "total_rows": total_rows,
        "total_columns_analyzed": len(per_column_report),
        "columns_skipped": SKIP_COLUMNS,
        "per_column": per_column_report,
    }

    os.makedirs("processed_data", exist_ok=True)
    with open(REPORT_FILE, "w") as f:
        json.dump(report, f, indent=2)

    log(f"Report written to '{REPORT_FILE}'")
    log(f"Total rows: {total_rows:,} | Columns analyzed: {len(per_column_report)}")


if __name__ == "__main__":
    main()
