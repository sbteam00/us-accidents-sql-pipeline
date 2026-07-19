# US Accidents SQL Analytics Pipeline

An end-to-end data engineering and analytics pipeline built on 7.05 million US accident records (2016–2022), covering data preprocessing, PostgreSQL ingestion, SQL analytics, dbt modelling, and interactive dashboards.

---

## Project Overview

This project simulates the work of a data/analytics engineer at a company like Razorpay or Flipkart — ingesting a large raw dataset, transforming it through a structured pipeline, and surfacing insights via a tested, documented data model and two dashboards.

**Dataset:** [US Accidents (2016–2023)](https://www.kaggle.com/datasets/sobhanmoosavi/us-accidents) by Sobhan Moosavi — 7.7M rows, 46 columns, sourced from MapQuest and Bing traffic APIs across 49 US states.

**Analytical Dashboard:** [View on Looker Studio →](https://datastudio.google.com/reporting/7b686c3e-eadf-4ee5-9f2d-85ed5ef17c60) &nbsp;|&nbsp; [Download PDF](looker/US_Accidents_Analytics_Dashboard.pdf)

---

## Pipeline Architecture

```
Raw CSV (7.7M rows, 46 cols)
        ↓
  preprocess.py          Python preprocessing — cleaning, feature engineering
        ↓
  US_Accidents_cleaned.csv   7.05M rows, 52 cols (8.76% rows dropped)
        ↓
  ingest.py              Chunked PostgreSQL bulk load via COPY
        ↓
  raw.accidents          PostgreSQL source table (us_accidents_db)
        ↓
  dbt run                14 models across 4 layers
        ↓
  ┌─ analytics_staging    ─ stg_accidents (view)
  ├─ analytics_intermediate ─ 4 intermediate views
  ├─ analytics_core      ─ star schema (4 dims + fact table)
  └─ analytics_analytics ─ 4 pre-aggregated mart tables
        ↓
  ┌─ Looker Studio        Analytical dashboard (4 pages)
  └─ Streamlit + PyDeck   Interactive map dashboard
```

---

## Tech Stack

| Layer | Tool |
|---|---|
| Preprocessing | Python, pandas, numpy, regex |
| Ingestion | Python, psycopg2, PostgreSQL COPY |
| Database | PostgreSQL 16 (local), pgAdmin |
| Transformation | dbt Core 1.12 (dbt-postgres) |
| Analytics SQL | PostgreSQL — window functions, CTEs, funnels |
| Analytical Dashboard | Google Looker Studio |
| Map Dashboard | Streamlit, PyDeck (deck.gl) |

---

## Repository Structure

```
US accidents pipeline/
├── US_Accidents.csv                       Raw Kaggle dataset (not committed — download separately)
├── preprocess.py                          Data cleaning and feature engineering
├── ingest.py                              PostgreSQL bulk loader
├── generate_null_report.py                Null value audit report generator
├── generate_stats_report.py               Descriptive statistics report generator
├── analysis.sql                           20 analytical SQL queries (Phase 2)
├── app.py                                 Streamlit + PyDeck interactive map dashboard
├── requirements.txt                       Python dependencies
├── README.md                              This file
├── looker/
│   ├── analytics_analytics.mart_funnel.csv
│   ├── analytics_analytics.mart_geo.csv
│   ├── analytics_analytics.mart_temporal.csv
│   ├── analytics_analytics.mart_weather_poi.csv
│   └── US_Accidents_Analytics_Dashboard.pdf   Looker Studio dashboard export
├── processed_data/
│   ├── US_Accidents_cleaned.csv           Cleaned dataset output (7.05M rows)
│   ├── cleaning_report.json               Null audit report
│   └── stats_report.json                  Descriptive statistics report
└── us_accidents_dbt/
    ├── dbt_project.yml
    ├── README.md
    └── models/
        ├── staging/
        │   ├── stg_accidents.sql
        │   ├── sources.yml
        │   └── stg_accidents.yml
        ├── intermediate/
        │   ├── int_temporal.sql
        │   ├── int_geo_hotspots.sql
        │   ├── int_weather_poi.sql
        │   ├── int_funnel.sql
        │   └── intermediate.yml
        └── marts/
            ├── core/
            │   ├── dim_location.sql
            │   ├── dim_time.sql
            │   ├── dim_weather.sql
            │   ├── dim_road.sql
            │   ├── fact_accidents.sql
            │   └── core.yml
            └── analytics/
                ├── mart_temporal.sql
                ├── mart_geo.sql
                ├── mart_weather_poi.sql
                ├── mart_funnel.sql
                └── analytics.yml
```

> **Note:** `US_Accidents.csv` and `processed_data/US_Accidents_cleaned.csv` are not committed to the repository due to file size. Download the raw dataset from Kaggle and run `preprocess.py` to reproduce the cleaned file.

---

## Setup & Reproduction

### Prerequisites

- Python 3.10+
- PostgreSQL 16 (local install with pgAdmin)
- dbt-postgres (`pip install dbt-postgres`)
- Kaggle account to download the dataset

### 1. Download the dataset

Download [US Accidents (2016–2023)](https://www.kaggle.com/datasets/sobhanmoosavi/us-accidents) from Kaggle and place `US_Accidents.csv` in the project root.

### 2. Install Python dependencies

```bash
pip install -r requirements.txt
```

### 3. Preprocess the raw data

```bash
python preprocess.py
```

Output: `processed_data/US_Accidents_cleaned.csv` (7.05M rows)
Logs: rows seen, rows dropped, drop percentage

### 4. Generate data quality reports (optional)

```bash
python generate_null_report.py      # Null audit on cleaned data
python generate_stats_report.py     # Descriptive statistics per column
```

### 5. Load into PostgreSQL

Update the `CONFIG` block in `ingest.py` with your Postgres credentials:

```python
CONFIG = {
    "host":     "localhost",
    "port":     5432,
    "user":     "postgres",
    "password": "your_password",
    "database": "postgres",
}
```

Then run:

```bash
python ingest.py
```

Creates `us_accidents_db` database with `raw.accidents` table (7.05M rows) and 9 indexes.

### 6. Configure dbt

Create `~/.dbt/profiles.yml`:

```yaml
us_accidents_dbt:
  target: dev
  outputs:
    dev:
      type: postgres
      host: localhost
      port: 5432
      user: postgres
      password: your_password
      dbname: us_accidents_db
      schema: analytics
      threads: 4
```

### 7. Run dbt pipeline

```bash
cd us_accidents_dbt
dbt run       # Builds all 14 models
dbt test      # Runs all 85 data tests
dbt docs generate && dbt docs serve    # Browse lineage graph at localhost:8080
```

### 8. Run the Streamlit map dashboard

Update the password in `app.py`:

```python
DB_CONFIG = {
    ...
    "password": "your_password",
    ...
}
```

Then:

```bash
streamlit run app.py
```

Opens at `http://localhost:8501`

---

## Preprocessing Decisions

The raw dataset (7.7M rows, 46 columns) required the following transformations before loading:

**Columns dropped:**
- `End_Lat`, `End_Lng` — 44% null, no analytical value
- `Country` — constant value (`US`) across all rows
- `Wind_Chill(F)` — 88%+ null, overlaps with `Temperature(F)`

**Columns transformed:**
- `ID` — stripped `A-` prefix, stored as integer (`source_id`)
- `Zipcode` — truncated hyphenated suffix (`78701-1234` → `78701`), kept as string to preserve leading zeros
- `Timezone` — stripped `US/` prefix (`US/Eastern` → `Eastern`)
- `Precipitation(in)` — nulls set to `0.0` (no precipitation recorded, not missing data)
- `Start_Time` / `End_Time` — nanosecond suffix stripped, converted to `datetime64`

**Engineered columns added:**
- `duration_mins` — `End_Time - Start_Time` in minutes (rounded to 2 decimal places)
- `hour_of_day`, `day_of_week`, `is_weekend`, `is_rush_hour`
- `temp_bucket` — Freezing / Cold / Mild / Warm / Hot
- `visibility_bucket` — Low / Moderate / Clear
- `light_condition_category` — Full_Day / Full_Night / Dawn_Dusk_Transition (derived from all 4 twilight columns)
- `incident_context` — two-stage hybrid classifier: keyword rules on `Description` text (stage 1) + POI boolean fallback (stage 2)

**Row deletion:** Any row with a null in any remaining source column was dropped (blanket deletion). Rows with clustered nulls in weather columns accounted for most deletions.

```
Rows seen:    7,728,394
Rows dropped:   676,838  (8.76%)
Rows written: 7,051,556
```

---

## dbt Pipeline

### Layer structure

| Schema | Models | Materialisation | Purpose |
|---|---|---|---|
| `analytics_staging` | `stg_accidents` | View | Clean pointer to raw source |
| `analytics_intermediate` | 4 models | View | Aggregation and join logic |
| `analytics_core` | 5 models | Table | Star schema (dims + fact) |
| `analytics_analytics` | 4 models | Table | Pre-aggregated mart tables |

### Star schema (analytics_core)

```
dim_location    653,626 rows   city, county, state, zipcode, street, timezone
dim_time      5,274,158 rows   start_time + all temporal attributes pre-computed
dim_weather      27,398 rows   weather condition, wind, temp/visibility buckets, twilight
dim_road          1,492 rows   13 POI boolean flags + incident_context
fact_accidents  7,051,556 rows  numeric facts + FK to all 4 dims
```

### Analytics marts (analytics_analytics)

| Mart | Rows | Contents |
|---|---|---|
| `mart_temporal` | 118 | Monthly/yearly/hourly aggregations with LAG-based change metrics |
| `mart_geo` | 295 | State + top city rankings with severity/volume rank divergence |
| `mart_weather_poi` | 26 | Weather conditions, visibility, light, POI severity comparisons |
| `mart_funnel` | 105 | Severity funnel overall + by light condition + by incident context + monthly cohort |

### dbt lineage graph

![dbt Lineage Graph](us_accidents_dbt/docs/lineage_graph.png)

### Test results

```
85 data tests across all 14 models — 85/85 PASS
Test types: not_null, unique, accepted_values, relationships
```

---

## SQL Analytics (Phase 2)

20 analytical queries across 5 blocks in `analysis.sql`, run directly against `raw.accidents` in pgAdmin:

| Block | Techniques | Key queries |
|---|---|---|
| Block 1 — Distributions | `GROUP BY`, `SUM() OVER()`, `RANK() OVER()` | Severity distribution, state ranking, incident context breakdown |
| Block 2 — Temporal | `LAG()`, `LEAD()`, `DATE_TRUNC`, running totals | Monthly MoM change, YoY growth, COVID dip detection |
| Block 3 — Geographic | Nested CTEs, `RANK() OVER (PARTITION BY)`, `DENSE_RANK()` | Top 20 cities, top 5 cities per state, severity vs volume rank divergence |
| Block 4 — Weather & POI | `FILTER (WHERE ...)`, `UNION ALL`, CASE pivoting | POI infrastructure severity comparison, weather condition pivot |
| Block 5 — Funnel | Funnel CTEs, severity cohorts, `LEAD()` | National severity funnel, monthly critical rate trend, state-level funnel |

---

## Key Findings

10 findings derived from the full 7.05M row dataset:

1. **California accounts for 22% of all US accidents** (1,557,414 records) but has only a **0.70% critical rate** — the highest-volume, lowest-severity state. Dense urban infrastructure and emergency response density explain the disconnect.

2. **Clear weather has higher average severity (2.363) than rain (2.253), snow, or fog.** Counter-intuitive but well-supported: clear conditions enable higher speeds, so accidents that do occur are worse. Bad weather slows traffic down.

3. **Nighttime accidents are nearly twice as likely to be critical (4.05%) vs daytime (2.18%).** Despite similar average severity scores, darkness fundamentally shifts the worst-case outcome probability.

4. **COVID lockdown (March–June 2020) spiked critical rates to 3.77–4.71%** despite stable or lower total volumes. Emptier roads enabled higher speeds — fewer accidents but significantly worse outcomes when they occurred.

5. **Late evening hours (7–10pm) rank highest on average severity** despite mid-table accident volume. Rush hours (7–8am) generate the most accidents but at lower severity — congestion slows traffic. Late evening accidents happen at speed on emptier roads.

6. **Roundabouts have the lowest average severity (2.073) of all 13 road infrastructure features** — directly supporting traffic engineering evidence that roundabouts reduce fatal collisions. Junctions are highest at 2.286.

7. **Junction + traffic signal compound risk produces severity 2.324** — the worst combination of any road context, higher than either feature alone.

8. **Road closure incidents have a 41.36% critical rate** — the highest of any incident context classification. Full road closures are strongly correlated with the most severe underlying accidents.

9. **Weekends have 45% fewer accidents but consistently worse severity (2.237 vs 2.196)** and longer durations (114.89 vs 107.51 mins) than weekdays. Leisure driving patterns produce fewer but worse accidents.

10. **Wyoming, South Dakota, and Wisconsin show disproportionately high critical rates (15–18%)** relative to their low accident volumes — rural highway speeds and long emergency response times are the likely drivers.

---

## Data Quality Notes

- **`incident_context` — ~48% classified as `other`:** The raw `Description` column is machine-generated by MapQuest and Bing traffic APIs, typically formatted as "Accident on I-X at Exit Y" with no incident type signal. A two-stage classifier (keyword rules + POI fallback) recovers ~52% into meaningful categories. The remaining "other" rows genuinely contain no classifiable signal. This is documented as a known limitation.

- **July 2020 data collection gap:** A sharp drop in accident counts in July 2020 (−65.65% MoM) reflects a MapQuest/Bing API data collection gap rather than a genuine traffic pattern. Lockdowns had largely eased by July 2020, making this an implausible traffic explanation.

- **2023 data is partial:** The dataset was last updated in early 2023. All temporal analyses exclude 2023 or note it explicitly. The `dim_time` model flags this via the `is_covid_lockdown_period` column.

- **Source bias:** Source1 (MapQuest) covers 57% of records, Source2 (Bing) covers 41%. Geographic coverage reflects API deployment areas, which partially explains California and Florida's dominance in accident counts.

- **`turning_loop` POI column:** Zero TRUE values in the cleaned dataset. Retained for schema completeness but analytically inert.

---

## Dashboards

### 1. Google Looker Studio (Analytical Dashboard)

**[View Live Dashboard →](https://lookerstudio.google.com/your-link-here)**

If the link is inaccessible or you prefer an offline copy: **[Download PDF](looker/US_Accidents_Analytics_Dashboard.pdf)**

Four-page analytical dashboard built from the four mart table CSVs (stored in `looker/`):

- **Page 1 — Temporal Trends:** Monthly accident count line chart with COVID dip visible, YoY percentage change bar chart, hourly distribution bar chart, 4 scorecards (total accidents, peak year, best/worst monthly change)
- **Page 2 — Geographic Analysis:** US state choropleth map, top 20 cities horizontal bar chart, state severity vs volume rank divergence table with heatmap colouring
- **Page 3 — Weather & Infrastructure:** Accident count by weather condition, average severity by weather condition, POI infrastructure bar chart, POI scatter plot (severity present vs absent per road feature)
- **Page 4 — Severity Funnel:** Incident context donut chart, critical rate by incident context horizontal bar, monthly critical rate trend line chart, critical rate by light condition bar chart

### 2. Streamlit + PyDeck (Interactive Map Dashboard)

Single-page interactive map dashboard connecting live to the local PostgreSQL database. Run with `streamlit run app.py`.

**Map layers (toggleable from sidebar):**
- **Hexagon (Density)** — ColumnLayer on server-side pre-aggregated grid cells. 3D columns where height = accident count per cell, colour = avg severity. Renders the entire US dataset without browser memory limits
- **Scatter (Individual)** — ScatterplotLayer on raw coordinates (up to 50K random sample), colour-coded by severity: 🟢 Minor → 🟡 Moderate → 🟠 Serious → 🔴 Critical
- **Heatmap (Intensity)** — HeatmapLayer on pre-aggregated grid, continuous heat intensity from blue (low) to red (high)

**Sidebar filters (auto-apply on change):** State multiselect, year range, hour of day range, weekend / rush hour toggles, severity levels, duration range, weather condition, incident context, junction toggle, max points slider

**Info panel tabs:**
- **Accident Detail** — full record retrieval from `raw.accidents` by ID, including description, all weather columns, all 13 POI flags, time context
- **Filter Statistics** — live severity breakdown with progress bars for the current active filter
- **Analytics Highlights** — 6 key findings pulled from mart tables on app load, with supporting numbers

---

## How to Run Everything

```bash
# 1. Preprocess
python preprocess.py

# 2. Ingest
python ingest.py

# 3. dbt full pipeline
cd us_accidents_dbt && dbt run && dbt test

# 4. Streamlit dashboard
cd .. && streamlit run app.py
```

---

## Dataset Citation

Moosavi, Sobhan, Mohammad Hossein Samavatian, Srinivasan Parthasarathy, and Rajiv Ramnath. "A Countrywide Traffic Accident Dataset.", 2019.

Moosavi, Sobhan, Mohammad Hossein Samavatian, Srinivasan Parthasarathy, Radu Teodorescu, and Rajiv Ramnath. "Accident Risk Prediction based on Heterogeneous Sparse Data: New Dataset and Insights." In proceedings of the 27th ACM SIGSPATIAL International Conference on Advances in Geographic Information Systems, ACM, 2019.

---

## Author

Shubham — Data Science & Data Engineering Portfolio Project  
Mumbai, India · 2025
