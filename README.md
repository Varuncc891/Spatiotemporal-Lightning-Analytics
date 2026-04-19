# ⚡ NRSC Lightning Data Platform

> A production-grade geospatial lightning analytics platform built for ISRO NRSC using PostgreSQL 17, PostGIS, and Python.  
> 802ms → 167ms query performance · 1M+ rows · Time-based partitioning · Spatial join · ETL pipeline

---

<!-- add a picture here — dashboard screenshot showing scattered lightning points across India map -->

---

## What is this?

A production-engineering internship project built at **ISRO's National Remote Sensing Centre (NRSC)**. The platform ingests, stores, and analyzes lightning strike data across India at million-row scale.

The core focus is **database performance engineering** — not just storing data, but making it fast. Time-based partitioning, composite and partial indexing, materialized views, and spatial joins are layered together so queries that would take 800ms on a naive schema run in under 170ms on 1,000,000 rows.

A Python ETL pipeline handles validation, deduplication, and batch ingestion. Alembic manages schema evolution. Apache Superset provides a visualization layer with state-level filtering across a PostGIS-backed geospatial dataset.

---

## Highlights

- 🚀 Reduced time-series query time from **802ms → 167ms** using partition pruning (4.8× faster)
- 🗺️ PostGIS spatial join matching 344,000+ strike events to Indian state boundaries
- 🧱 Range partitioning across 6 years (2021–2026) with automatic partition routing
- ⚙️ Materialized views pre-aggregating 1M rows into 57,916 daily-state summaries
- 🐍 Python ETL pipeline with validation, deduplication, and 10k-row batch inserts
- 🔁 Alembic schema migrations with full upgrade/downgrade support
- 📊 Apache Superset dashboard with state + time-range filters on live map

---

## Performance Benchmarks

All benchmarks run with `EXPLAIN ANALYZE` on 1,000,000 rows. BEFORE = sequential scan forced via `SET enable_indexscan=off`. AFTER = normal execution with indexes.

| Query | Before | After | Improvement |
|---|---|---|---|
| Time range aggregation (single year) | 802ms | 167ms | **4.8× faster** |
| Composite filter (time + state) | 53ms | 69ms | Index scan confirmed |
| High intensity filter (multi-year) | 255ms | 161ms | **1.6× faster** |
| Grouped aggregation on materialized view | 308ms | 184ms | **1.7× faster** |

> Planning time improvement for multi-year query: **16.7ms → 0.67ms (25× faster)**

EXPLAIN output files: `benchmarks/before_optimization.md` · `benchmarks/after_optimization.md`

---

## Architecture

```
┌─────────────────────────────────────────────────────────┐
│                  DATA INGESTION LAYER                   │
│   CSV Files ──▶ ingest.py (validate + dedup + batch)   │
│   Synthetic ──▶ synthetic_generator.py (1M rows)       │
└────────────────────────┬────────────────────────────────┘
                         │
                         ▼
┌─────────────────────────────────────────────────────────┐
│               POSTGRESQL 17 + POSTGIS                   │
│                                                         │
│  lightning_strikes (PARTITION BY RANGE timestamp)       │
│  ├── lightning_strikes_2021                             │
│  ├── lightning_strikes_2022                             │
│  ├── lightning_strikes_2023                             │
│  ├── lightning_strikes_2024                             │
│  ├── lightning_strikes_2025                             │
│  ├── lightning_strikes_2026                             │
│  └── lightning_strikes_default                          │
│                                                         │
│  india_states (36 rows, MultiPolygon, SRID 4326)        │
│                                                         │
│  Materialized Views:                                    │
│  ├── lightning_master_mv       (1,000,000 rows)         │
│  └── lightning_daily_summary_mv  (57,916 rows)          │
└────────────────────────┬────────────────────────────────┘
                         │
                         ▼
┌─────────────────────────────────────────────────────────┐
│               VISUALIZATION LAYER                       │
│   Apache Superset 6.0                                   │
│   ├── Open Street Map (PostGIS scatter points)          │
│   ├── State filter (dropdown)                           │
│   └── Time range filter (last week / month / custom)   │
└─────────────────────────────────────────────────────────┘
```

---

## Features

### Time-Based Partitioning

`lightning_strikes` is partitioned by `RANGE(timestamp)` across 6 yearly partitions (2021–2026) plus a default partition. PostgreSQL performs automatic **partition pruning** — a query scoped to 2023 only scans `lightning_strikes_2023` (166,915 rows) instead of all 1,000,000 rows.

```sql
CREATE TABLE lightning_strikes (
    event_id            bigint NOT NULL,
    latitude            numeric(9,6) NOT NULL,
    longitude           numeric(9,6) NOT NULL,
    timestamp           timestamptz NOT NULL,
    radiance            numeric(10,4),
    flash_type          text CHECK (flash_type IN ('CG', 'IC', 'CC')),
    intensity_category  text GENERATED ALWAYS AS (
                            CASE WHEN radiance < 50 THEN 'Low'
                                 WHEN radiance < 150 THEN 'Medium'
                                 ELSE 'High' END
                        ) STORED,
    quality_flag        smallint DEFAULT 0 CHECK (quality_flag IN (0, 1, 2)),
    geom                geometry(Point, 4326),
    state_id            integer REFERENCES india_states(state_id),
    created_at          timestamptz DEFAULT now()
) PARTITION BY RANGE (timestamp);
```

### Indexing Strategy

Five indexes covering the most common query patterns:

| Index | Type | Purpose |
|---|---|---|
| `idx_lightning_timestamp_state` | Composite B-tree | Time + state filtered queries |
| `idx_lightning_high_intensity` | Partial B-tree | High-radiance only queries (smaller index) |
| `idx_lightning_geom` | GiST | Spatial distance and containment queries |
| `idx_lightning_flash_type` | B-tree | Flash type filtering (CG / IC / CC) |
| `idx_states_geom` | GiST | State boundary spatial joins |

### Materialized Views

Regular views re-run the full query on every call. Materialized views pre-compute and store results on disk. At 1M rows, a regular view takes seconds; a materialized view returns in milliseconds.

```sql
-- Refreshes both MVs concurrently (no downtime)
SELECT refresh_lightning_views();
```

`CONCURRENTLY` mode keeps the old data live during refresh. Requires a unique index on each MV (`idx_mv_master_event_id`, `idx_mv_daily_date_state`).

### Spatial Join (PostGIS)

Strike points are matched to Indian state polygons via a two-pass spatial join:

```sql
-- Pass 1: exact containment
UPDATE lightning_strikes ls
SET state_id = ist.state_id
FROM india_states ist
WHERE ST_Within(ls.geom, ist.geom);
-- Matched: 333,357 rows

-- Pass 2: near-boundary sweep (0.05° tolerance)
UPDATE lightning_strikes ls
SET state_id = ist.state_id
FROM india_states ist
WHERE ls.state_id IS NULL
  AND ST_DWithin(ls.geom, ist.geom, 0.05);
-- Additional: 11,022 rows
```

Final match: **344,379 / 1,000,000** rows assigned to states. Remaining 655,621 rows fall outside India's land boundary (ocean, neighboring countries) — expected for synthetic data generated across the full bounding box rectangle.

### ETL Pipeline

`ingestion/ingest.py` implements a full Extract → Validate → Dedup → Transform → Load pipeline:

**Validation rules:** latitude in [6.5, 35.5], longitude in [68.0, 97.5], flash_type ∈ {CG, IC, CC}, quality_flag ∈ {0, 1, 2}, radiance ≥ 0, valid ISO timestamp, valid integer event_id.

**Deduplication:** checks existing `event_id` values before each batch insert. Rejected rows are written to `_rejected.csv` with error reasons.

**Batch insert:** uses `psycopg2.extras.execute_values` in batches of 5,000 rows.

```bash
python ingestion/ingest.py --file ingestion/your_file.csv
```

Pipeline test results:

| Test | Input | Result |
|---|---|---|
| Duplicate detection | 1,000 rows already in DB | Inserted: 0 · Dupes: 1,000 · Rejected: 0 ✅ |
| New insert | 500 rows with new IDs | Inserted: 500 · Dupes: 0 · Rejected: 0 ✅ |
| Bad data rejection | 100 rows with lat=999, flash=XX | Inserted: 0 · Dupes: 0 · Rejected: 100 ✅ |

### Schema Migrations (Alembic)

Three migrations manage the full schema lifecycle:

```
<base> → 5566ece10587  create_lightning_strikes_partitioned
         5566ece10587 → bdb65b394328  add_indexes
         bdb65b394328 → 48b26036eceb  add_materialized_views  (head)
```

```bash
python -m alembic upgrade head    # apply all migrations
python -m alembic downgrade -1    # roll back one step
python -m alembic history         # view migration chain
```

> Note: Use `python -m alembic`, not `alembic` directly, to avoid Python version conflicts.

---

## Database Schema

```
india_states
├── state_id     serial PK
├── state_name   text
├── state_code   text
├── region       text
└── geom         geometry(MultiPolygon, 4326)

lightning_strikes  [PARTITIONED BY RANGE(timestamp)]
├── event_id            bigint NOT NULL
├── latitude            numeric(9,6)
├── longitude           numeric(9,6)
├── timestamp           timestamptz
├── radiance            numeric(10,4)
├── flash_type          text  -- CG / IC / CC
├── intensity_category  text  -- GENERATED STORED
├── quality_flag        smallint  -- 0 / 1 / 2
├── geom                geometry(Point, 4326)
├── state_id            FK → india_states
└── created_at          timestamptz
```

---

## Project Structure

```
nrsc-lightning/
├── database/
│   ├── schema.sql
│   ├── partitions.sql
│   ├── indexes.sql
│   ├── materialized_views.sql
│   └── migrations/
│       ├── 5566ece10587_create_lightning_strikes_partitioned.py
│       ├── bdb65b394328_add_indexes.py
│       └── 48b26036eceb_add_materialized_views.py
├── ingestion/
│   ├── synthetic_generator.py   # generates 1M synthetic rows
│   ├── ingest.py                # ETL pipeline (validate + dedup + load)
│   ├── test_data.csv
│   ├── test_new_data.csv
│   └── test_bad_data.csv
└── benchmarks/
    ├── before_optimization.md
    └── after_optimization.md
```

---

## Setup

### Prerequisites

- PostgreSQL 17 with PostGIS extension
- Python 3.10
- Apache Superset 6.0 (optional, for visualization)

### Database Setup

```bash
# Create database
psql -U postgres -c "CREATE DATABASE nrsc_lightning_db;"

# Apply schema migrations
cd C:\Users\varun\nrsc-lightning
python -m alembic upgrade head
```

### Load Shapefile (State Boundaries)

```bash
# Generate SQL from shapefile
shp2pgsql -s 4326 shapefiles/India_State_Boundary.shp india_states_temp > india_states_load.sql

# Load into DB
psql -U postgres -d nrsc_lightning_db -f india_states_load.sql

# Copy into india_states with column mapping (run in pgAdmin)
INSERT INTO india_states (state_name, state_code, region, geom)
SELECT name, type, NULL, ST_Multi(geom)::geometry(MultiPolygon, 4326)
FROM india_states_temp;

DROP TABLE india_states_temp;
```

### Generate Synthetic Data

```bash
python ingestion/synthetic_generator.py
# Inserts 1,000,000 rows in ~95 seconds
```

### Run Spatial Join

```sql
-- Match strike points to state polygons
UPDATE lightning_strikes ls
SET state_id = ist.state_id
FROM india_states ist
WHERE ST_Within(ls.geom, ist.geom);

UPDATE lightning_strikes ls
SET state_id = ist.state_id
FROM india_states ist
WHERE ls.state_id IS NULL
  AND ST_DWithin(ls.geom, ist.geom, 0.05);

-- Refresh materialized views
SELECT refresh_lightning_views();
```

### Ingest Real Data

```bash
python ingestion/ingest.py --file ingestion/your_file.csv
```

---

## Current Data State

| Table / View | Rows |
|---|---|
| `lightning_strikes` (total) | 1,000,000 |
| `lightning_strikes_2021` | 166,274 |
| `lightning_strikes_2022` | 166,607 |
| `lightning_strikes_2023` | 166,915 |
| `lightning_strikes_2024` | 166,526 |
| `lightning_strikes_2025` | 167,023 |
| `lightning_strikes_2026` | 167,115 |
| `india_states` | 36 |
| `lightning_master_mv` | 1,000,000 |
| `lightning_daily_summary_mv` | 57,916 |

**State match:** 344,379 rows assigned to states · 655,621 = Ocean/Unknown

**Top states by strike count:** Rajasthan (36,379) · MP (32,319) · Maharashtra (31,068) · UP (25,389) · Gujarat (19,003)

---

## Dashboard

<!-- add a picture here — Superset dashboard showing lightning scatter map across India with state and time filters -->

**Dashboard:** Lightning Network INDIA (FINAL)

- Open Street Map with scattered strike points across India
- State filter (dropdown)
- Time range filter (last week / last month / last 6 months / custom)

**Key fix:** Superset's map charts force at least one aggregation metric, which collapsed all points to a horizontal line at the average latitude. Fixed by creating a `lightning_raw_points` view with raw coordinates and using Custom SQL mode to bypass forced metrics.

---

## Tech Stack

**Database:** PostgreSQL 17 · PostGIS  
**Language:** Python 3.10  
**Libraries:** psycopg2 · NumPy · Alembic · SQLAlchemy  
**Visualization:** Apache Superset 6.0  
**Tools:** shp2pgsql · pgAdmin · SQL Lab  
**OS:** Windows 10

---

## Interview Summary

> *"I built a production-grade geospatial lightning data platform for ISRO NRSC using PostgreSQL 17 and PostGIS. I implemented time-based partitioning across 2021–2026, composite and partial indexing, and converted aggregation layers into materialized views. I benchmarked performance using EXPLAIN ANALYZE and reduced heavy time-series queries from 802ms to 167ms at million-row scale. I developed a Python ETL pipeline with validation, deduplication, and batch inserts of 10k rows, and introduced Alembic for schema migrations. The biggest technical challenge was Superset's visualization layer forcing aggregation on map charts, causing a horizontal line instead of scattered points — I solved it by creating raw point views and using Custom SQL mode to bypass forced metrics, then rebuilt the dashboard with working state and time-range filters."*

---

*Built during ISRO NRSC internship — 2026*
