"""
generate_report.py
-------------------
Generates a JSON report on the cleaned dataset (US_Accidents_cleaned.csv).

Current scope (per project plan):
  - Total row / column count
  - Per-column null/missing value count and percentage
  - Per-column dtype (sanity check that boolean / datetime conversions held)

This report exists right now purely to drive the upcoming null-handling
decisions. It is expected to be EXTENDED later into a fuller data-quality /
insights report (value distributions, outlier flags, etc.) once the null
strategy is finalized - that is intentionally out of scope for this pass.

Input  : processed_data/US_Accidents_cleaned.csv
Output : processed_data/cleaning_report.json
"""

import pandas as pd
import json
import os
import sys
import time

INPUT_FILE = os.path.join("processed_data", "US_Accidents_cleaned.csv")
REPORT_FILE = os.path.join("processed_data", "cleaning_report.json")
CHUNK_SIZE = 500_000


def log(msg):
    print(f"[{time.strftime('%H:%M:%S')}] {msg}", flush=True)


def main():
    if not os.path.exists(INPUT_FILE):
        log(f"ERROR: '{INPUT_FILE}' not found. Run preprocess.py first.")
        sys.exit(1)

    log(f"Scanning '{INPUT_FILE}' in chunks of {CHUNK_SIZE:,} rows for null counts...")

    total_rows = 0
    null_counts = None
    dtypes = None

    reader = pd.read_csv(
        INPUT_FILE,
        chunksize=CHUNK_SIZE,
        low_memory=False,
        dtype={"Zipcode": str},  # prevent float auto-inference corrupting values
    )

    for i, chunk in enumerate(reader, start=1):
        if null_counts is None:
            null_counts = chunk.isna().sum()
            dtypes = chunk.dtypes.astype(str)
        else:
            null_counts = null_counts.add(chunk.isna().sum(), fill_value=0)

        total_rows += len(chunk)
        log(f"Chunk {i:>3} scanned (running total: {total_rows:,} rows)")

    null_counts = null_counts.astype(int)

    per_column_report = {}
    for col in null_counts.index:
        missing = int(null_counts[col])
        pct = round((missing / total_rows) * 100, 3) if total_rows else 0.0
        per_column_report[col] = {
            "dtype": dtypes[col],
            "missing_count": missing,
            "missing_pct": pct,
        }

    # Sort columns by missing_pct descending so the worst offenders are
    # immediately visible at the top of the JSON
    per_column_report = dict(
        sorted(per_column_report.items(), key=lambda kv: kv[1]["missing_pct"], reverse=True)
    )

    report = {
        "generated_at": time.strftime("%Y-%m-%d %H:%M:%S"),
        "source_file": INPUT_FILE,
        "total_rows": total_rows,
        "total_columns": len(null_counts),
        "columns_with_missing_values": sum(1 for v in per_column_report.values() if v["missing_count"] > 0),
        "per_column": per_column_report,
    }

    os.makedirs("processed_data", exist_ok=True)
    with open(REPORT_FILE, "w") as f:
        json.dump(report, f, indent=2)

    log(f"Report written to '{REPORT_FILE}'")
    log(f"Total rows: {total_rows:,} | Total columns: {len(null_counts)} | "
        f"Columns with at least 1 null: {report['columns_with_missing_values']}")


if __name__ == "__main__":
    main()
