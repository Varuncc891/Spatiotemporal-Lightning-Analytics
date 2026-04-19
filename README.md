# ⚡ Lightning Data Platform

> Production-grade geospatial lightning analytics on PostgreSQL 17 + PostGIS.  
> 802ms → 167ms · 1M rows · Time-based partitioning · Spatial joins · Python ETL

---

<!-- add a picture here -->

---

## Highlights

- 🚀 Reduced time-series query time from **802ms → 167ms** via partition pruning (4.8× faster)
- 🗺️ PostGIS spatial join matching 344k+ strike events to state boundaries
- 🧱 Range partitioning across 6 years with automatic partition routing
- ⚙️ Materialized views pre-aggregating 1M rows into 57,916 daily-state summaries
- 🐍 Python ETL pipeline with validation, deduplication, and 10k-row batch inserts
- 🔁 Alembic schema migrations with full upgrade/downgrade support
- 📊 Apache Superset dashboard with state + time-range filters on a live map

---

## Performance Benchmarks

Benchmarked with `EXPLAIN ANALYZE` on 1,000,000 rows. BEFORE = sequential scan forced. AFTER = indexes enabled.

| Query | Before | After | Improvement |
|---|---|---|---|
| Time range aggregation (single year) | 802ms | 167ms | **4.8× faster** |
| Composite filter (time + state) | 53ms | 69ms | Index scan confirmed |
| High intensity filter (multi-year) | 255ms | 161ms | **1.6× faster** |
| Grouped aggregation on MV | 308ms | 184ms | **1.7× faster** |

> Planning time on multi-year query: 16.7ms → 0.67ms **(25× faster)**

---

## Architecture

```
CSV / Synthetic Data
        │
        ▼
  ingest.py / synthetic_generator.py
  (validate → dedup → batch insert)
        │
        ▼
PostgreSQL 17 + PostGIS
├── lightning_strikes  [PARTITIONED BY RANGE(timestamp)]
│   ├── 2021 · 2022 · 2023 · 2024 · 2025 · 2026 · default
├── india_states  [36 state polygons, GiST indexed]
├── lightning_master_mv          (1,000,000 rows)
└── lightning_daily_summary_mv     (57,916 rows)
        │
        ▼
  Apache Superset 6.0
  (scatter map · state filter · time-range filter)
```

---

## Key Features

### Time-Based Partitioning
`lightning_strikes` is partitioned by `RANGE(timestamp)` across yearly child tables. Queries scoped to a single year only scan that partition — the biggest single performance win in the project.

### Indexing Strategy

| Index | Type | Purpose |
|---|---|---|
| `idx_lightning_timestamp_state` | Composite B-tree | Time + state queries |
| `idx_lightning_high_intensity` | Partial B-tree | High-radiance filter (smaller index) |
| `idx_lightning_geom` | GiST | Spatial containment / distance |
| `idx_lightning_flash_type` | B-tree | Flash type filtering |
| `idx_states_geom` | GiST | State boundary spatial joins |

### Materialized Views
Two MVs pre-compute expensive aggregations. Refreshed concurrently (no downtime) via a stored function:
```sql
SELECT refresh_lightning_views();
```

### Spatial Join (PostGIS)
Two-pass join matching strike points to state polygons — exact containment first, then a 0.05° boundary sweep for edge cases. Matched 344,379 / 1,000,000 rows to states.

### ETL Pipeline
`ingest.py` validates coordinates, flash type, quality flags, and timestamps; deduplicates against existing `event_id`s; batch inserts via `execute_values`; writes rejected rows to `_rejected.csv`.

```bash
python ingestion/ingest.py --file your_file.csv
```

### Schema Migrations (Alembic)
```
<base> → create_lightning_strikes_partitioned → add_indexes → add_materialized_views (head)
```

---

## Schema

```sql
lightning_strikes (PARTITIONED BY RANGE timestamp)
├── event_id            bigint
├── latitude/longitude  numeric(9,6)
├── timestamp           timestamptz
├── radiance            numeric(10,4)
├── flash_type          text  -- CG / IC / CC
├── intensity_category  text  -- GENERATED STORED (Low / Medium / High)
├── quality_flag        smallint  -- 0 / 1 / 2
├── geom                geometry(Point, 4326)
└── state_id            FK → india_states
```

---

## Project Structure

```
nrsc-lightning/
├── database/
│   ├── schema.sql · partitions.sql · indexes.sql · materialized_views.sql
│   └── migrations/
├── ingestion/
│   ├── synthetic_generator.py   # 1M row generator
│   └── ingest.py                # ETL pipeline
└── benchmarks/
    ├── before_optimization.md
    └── after_optimization.md
```

---

## Tech Stack

**Database:** PostgreSQL 17 · PostGIS  
**Language:** Python 3.10  
**Libraries:** psycopg2 · NumPy · Alembic · SQLAlchemy  
**Visualization:** Apache Superset 6.0
