# Spatiotemporal Lightning Analytics

> Production-shaped geospatial lightning analytics on PostgreSQL 17 + PostGIS.  
> Time-based partitioning · Composite indexing · Spatial joins · Python ETL

---

![Lightning Dashboard](docs/dashboard_1.png)

---

## What & Why

Lightning strike data arrives in high volumes, unevenly distributed across time and geography. A naive flat-table schema collapses under aggregation queries at scale: full sequential scans, no spatial awareness, no pre-computed summaries.

This platform stores 1,000,000 synthetic strike events in a partitioned PostGIS schema, spatially joins them to 36 Indian state boundaries, serves live point data through a view over the partitioned table, and pre-aggregates daily summaries into a materialized view. The ETL pipeline handles real-world messiness: out-of-bounds coordinates, bad timestamps, duplicate IDs, and partial data.

The engineering is in the database, the pipeline, and the benchmarks. Apache Superset is only the presentation layer.

---

## Highlights

- 🧱 Range partitioning by year (2021–2025) plus a default partition, with automatic partition routing
- 🗺️ PostGIS exact point-in-polygon (`ST_Within`) spatial join mapping strikes to 36 state boundaries
- 👁️ Dashboard map reads a live view over the partitioned base table: zero storage, always fresh, no refresh needed
- ⚙️ Daily materialized view pre-aggregating strikes into **57,916** daily-state summaries
- 🔒 Database-enforced deduplication via `UNIQUE (event_id, timestamp)`: atomic and race-free
- 🐍 Python ETL pipeline: validate → batch insert with `ON CONFLICT DO NOTHING` → spatial mapping → MV refresh → verify → `ANALYZE`, in one command
- ⏱️ Measured with `EXPLAIN (ANALYZE, BUFFERS)`: a selective day-plus-state query drops from **97.4 ms to 0.06 ms**, and whole-year aggregation runs **~2.6× faster** through partition pruning
- 📊 Apache Superset dashboard with state + time-range filters on a live map

---

## Quick Start

```bash
git clone https://github.com/Varuncc891/Spatiotemporal-Lightning-Analytics
cd Spatiotemporal-Lightning-Analytics

# 0. Set your database credentials in DB_CONFIG (ingestion/ingest.py)

# 1. Create the database
psql -U postgres -c "CREATE DATABASE lightning_db;"

# 2. Load state boundary shapefile
shp2pgsql -s 4326 shapefiles/India_State_Boundary.shp india_states_temp | psql -U postgres -d lightning_db
psql -U postgres -d lightning_db -c "
  INSERT INTO india_states (state_name, state_code, region, geom)
  SELECT name, type, NULL, ST_Multi(geom)::geometry(MultiPolygon, 4326) FROM india_states_temp;
  DROP TABLE india_states_temp;
"

# 3. Ingest data: loads, maps states, refreshes the daily MV, verifies, and runs ANALYZE in one command
python ingestion/ingest.py --file ingestion/test_data.csv

# Incremental load: only rows with timestamp >= the given date
python ingestion/ingest.py --file data.csv --since 2026-01-01
```

**Requirements:** PostgreSQL 17, PostGIS (includes `shp2pgsql`), Python 3.10, psycopg2

---

## Performance Benchmarks

Full methodology, queries, and `EXPLAIN (ANALYZE, BUFFERS)` output are in the [`benchmarks/`](benchmarks/) folder. Summary at 1M-row scale:

**Methodology:** the baseline is an unpartitioned copy of the table (`lightning_strikes_unpart`) with identical data and indexes. Each configuration is run 5 times, the first run is discarded as warmup, and the median is reported. Both sides are measured warm-cache, and `ANALYZE` is run before each benchmark.

### Whole-year aggregation (partitioning)

```sql
SELECT COUNT(*), AVG(radiance), MAX(radiance)
FROM lightning_strikes
WHERE timestamp BETWEEN '2023-01-01' AND '2023-12-31';
```

| Config | Plan | Median time |
|--------|------|-------------|
| Unpartitioned | Parallel Bitmap Heap Scan (full table) | 142.5 ms |
| Partitioned | Parallel Seq Scan on `lightning_strikes_2023` only | 54.8 ms |

About **2.6× faster** by scanning one partition instead of the whole table. The plan difference confirms pruning.

### Selective day-plus-state query (indexing)

```sql
SELECT COUNT(*)
FROM lightning_strikes
WHERE timestamp >= '2023-06-15' AND timestamp < '2023-06-16'
  AND state_id = 8;
```

| Config | Plan | Median time (warm) | Heap fetches |
|--------|------|--------------------|--------------|
| Neither (seq scan) | Parallel Seq Scan on 1M rows | 97.4 ms | n/a |
| Index only | Index Only Scan on the unpartitioned table | 0.058 ms | 0 |
| Partition only | Parallel Seq Scan on the 2023 partition | 60.9 ms | n/a |
| Both (final) | Index Only Scan on the 2023 partition | 0.059 ms | 0 |

About **1,650× faster** for the combined path. At this selectivity the composite `(timestamp, state_id)` index does nearly all the work, and partitioning's contribution is shrinking the index from 1M to about 167k entries. Partitioning alone gives roughly 2.6× on broad queries.

### Daily aggregate MV
A year-range aggregation over `lightning_daily_summary_mv` uses an index scan on `idx_mv_daily_date` across the 57k-row view instead of scanning the base table.

---

## Architecture

```
CSV Data
   │
   ▼
ingest.py
(validate → batch insert ON CONFLICT DO NOTHING → spatial map → refresh MV → verify → ANALYZE)
   │
   ▼
PostgreSQL 17 + PostGIS
├── lightning_strikes  [PARTITIONED BY RANGE(timestamp)]
│   ├── 2021 · 2022 · 2023 · 2024 · 2025 · default
│   └── UNIQUE (event_id, timestamp)
├── india_states  [36 state polygons, GiST indexed]
├── lightning_points_v            (view over base table + states, 0 rows stored)
└── lightning_daily_summary_mv    (57,916 rows)
   │
   ▼
Apache Superset 6.0
(scatter map · state filter · time-range filter · trend charts)
```

**Why a view instead of a materialized view for the map:** an earlier design used a 1M-row materialized view for point data. It duplicated the base table, went stale after each ingest, and could not be partitioned. The state join is against only 36 rows, so a live view over the partitioned table is cheaper to maintain, is always current, and lets the planner prune partitions before the join. The daily aggregate stays materialized because it collapses 1M rows into about 58k (roughly 17× smaller).

---

## Key Features

### Time-Based Partitioning
`lightning_strikes` is partitioned by `RANGE(timestamp)` across yearly child tables (2021–2025) plus a default partition. A query scoped to a single year scans only that year's partition instead of the whole table. Partitioning also enables instant retention (drop or detach an old year) and per-partition maintenance as data grows.

### Indexing Strategy
Every index is tied to a specific query pattern.

| Index | Type | Purpose |
|---|---|---|
| `uq_strikes_event_ts` | UNIQUE (event_id, timestamp) | Atomic deduplication, the `ON CONFLICT` target |
| `idx_lightning_timestamp_state` | Composite B-tree | Time + state queries (dashboard workhorse) |
| `idx_lightning_geom` | GiST | Spatial mapping (`ST_Within`) |
| `india_states_pkey` | Primary key | Equality join from the base table |
| `idx_states_geom` | GiST | State boundary side of the spatial join |
| `idx_mv_daily_date_state` | UNIQUE B-tree (MV) | Daily stats table + `REFRESH CONCURRENTLY` support |
| `idx_mv_daily_date` | B-tree (MV) | 30-day trend chart |

Two indexes (a partial high-intensity index and a `flash_type` index) were dropped after `pg_stat_user_indexes` showed zero scans under a representative workload. The old master materialized view and its four indexes were dropped with it, taking the total from 12 indexes to 7.

### Views and Materialized Views

```sql
-- Live point data for the dashboard map (always fresh, zero storage)
SELECT * FROM lightning_points_v WHERE timestamp >= '2023-06-01';

-- Pre-aggregated daily x state summaries (57,916 rows)
REFRESH MATERIALIZED VIEW lightning_daily_summary_mv;
```

Window functions run on the pre-aggregated view, for example a 7-day rolling average per state:

```sql
WITH daily AS (
    SELECT strike_date, state_name, total_strikes
    FROM lightning_daily_summary_mv
    WHERE strike_date >= CURRENT_DATE - INTERVAL '30 days'
)
SELECT state_name, strike_date, total_strikes,
       AVG(total_strikes) OVER (
           PARTITION BY state_name
           ORDER BY strike_date
           ROWS BETWEEN 6 PRECEDING AND CURRENT ROW
       ) AS rolling_7d_avg
FROM daily
ORDER BY state_name, strike_date;
```

### Spatial Join (PostGIS)
Single-pass exact point-in-polygon mapping:

```sql
UPDATE lightning_strikes ls SET state_id = ist.state_id
FROM india_states ist
WHERE ls.state_id IS NULL AND ST_Within(ls.geom, ist.geom);
```

Points outside every state polygon keep `state_id = NULL` and appear as `Ocean/Unknown` in the views.

A degree-based `ST_DWithin` boundary fallback was removed: its tolerance was in degrees (not meters), so it assigned ocean and cross-border points to states.

### ETL Pipeline
`ingest.py` runs the full pipeline in one command:

1. **Validate**: coordinates within India bounds (lat 6.5–35.5, lon 68.0–97.5), `flash_type` in {CG, IC, CC}, `quality_flag` in {0, 1, 2}, `radiance` ≥ 0, valid ISO timestamp, valid integer `event_id`
2. **Load**: 5,000-row batches with `INSERT ... ON CONFLICT (event_id, timestamp) DO NOTHING`, with `page_size=len(batch)` so `cur.rowcount` is exact for the whole batch
3. **Spatial map**: assign `state_id` via `ST_Within`
4. **Refresh**: `REFRESH MATERIALIZED VIEW lightning_daily_summary_mv`
5. **Verify**: log total / mapped / unmapped counts
6. **Analyze**: `ANALYZE lightning_strikes` so planner statistics are fresh after the bulk load
7. **Reject**: invalid rows are written to `_rejected.csv` with per-row error reasons

**Three-layer deduplication:** duplicates inside a batch are collapsed in Python, the `UNIQUE (event_id, timestamp)` constraint enforces uniqueness atomically, and `ON CONFLICT DO NOTHING` lets PostgreSQL skip existing rows. Python orchestrates, and PostgreSQL is the correctness authority. There is no SELECT round trip per batch, and loading the same CSV twice inserts zero new rows.

**Transaction boundaries:** batch inserts commit per 5,000 rows. The spatial map and MV refresh commit separately and are both idempotent (`WHERE state_id IS NULL`, re-runnable `REFRESH`), so a failure at the map step never loses inserted rows.

**Incremental loads:** `--since YYYY-MM-DD` filters CSV rows to `timestamp >= since` before batching, enabling daily loads without reprocessing the whole file.

---

## Schema

```sql
lightning_strikes  (PARTITIONED BY RANGE timestamp)
├── event_id            bigint
├── latitude/longitude  numeric(9,6)
├── timestamp           timestamptz
├── radiance            numeric(10,4)
├── flash_type          text        -- CG / IC / CC
├── intensity_category  text        -- GENERATED STORED (Low / Medium / High)
├── quality_flag        smallint    -- 0 / 1 / 2
├── geom                geometry(Point, 4326)
├── state_id            FK → india_states
├── created_at          timestamptz
└── UNIQUE (event_id, timestamp)

india_states  (36 rows)
├── state_id            serial PRIMARY KEY
├── state_name          text
├── state_code          text
├── region              text
└── geom                geometry(MultiPolygon, 4326)
```

---

## Dashboard (Superset)

| Component | Source | Purpose |
|---|---|---|
| Map (points) | `lightning_points_v` | Scattered points with state + time filters |
| 30-day trend | `lightning_daily_summary_mv` | Daily strike counts |
| Daily stats table | `lightning_daily_summary_mv` | Date × state tabular view |
| Rolling 7-day average | `lightning_daily_summary_mv` (window query) | Trend smoothing per state |

Filters: state, time range, and optionally intensity category. The map uses Custom SQL mode to bypass Superset's forced-metric aggregation, which otherwise collapses raw points into a horizontal line.

---

## Operations

These are set up manually. Both `pg_cron` and `pg_stat_statements` must be installed and listed in `shared_preload_libraries`.

**Scheduled MV refresh.** `ingest.py` refreshes the daily MV after every load, and `pg_cron` refreshes it nightly as a fallback:

```sql
CREATE EXTENSION IF NOT EXISTS pg_cron;

SELECT cron.schedule(
    'refresh-daily-mv',
    '0 2 * * *',
    $$REFRESH MATERIALIZED VIEW CONCURRENTLY lightning_daily_summary_mv$$
);
```

**Structured logging.** `ingest.py` emits JSON log events that are easy to filter and aggregate:

```json
{"ts":"2026-04-11T14:22:01Z","level":"INFO","event":"batch_insert","inserted":5000,"skipped":0,"batch_num":1}
{"ts":"2026-04-11T14:22:05Z","level":"INFO","event":"spatial_map","mapped":5000}
{"ts":"2026-04-11T14:22:06Z","level":"INFO","event":"mv_refresh","duration_ms":842}
{"ts":"2026-04-11T14:22:06Z","level":"INFO","event":"verify","total":1000000,"mapped":344153,"unmapped":655847}
```

**Query telemetry and index monitoring:**

```sql
CREATE EXTENSION IF NOT EXISTS pg_stat_statements;

-- Top 10 queries by total execution time
SELECT query, calls, mean_exec_time, total_exec_time
FROM pg_stat_statements
ORDER BY total_exec_time DESC
LIMIT 10;

-- Index usage (how the two unused indexes were found)
SELECT indexrelname, idx_scan, pg_size_pretty(pg_relation_size(indexrelid))
FROM pg_stat_user_indexes
WHERE relname LIKE 'lightning%'
ORDER BY idx_scan DESC;
```

---

## Known Limitations

- **Synthetic data:** about 65% of strikes have a `NULL` `state_id` because points were sampled from the India bounding rectangle, which includes ocean and neighboring countries. The pipeline handles this correctly (`Ocean/Unknown` in the views). A production-grade generator would use rejection sampling via `ST_Contains` plus a modeled offshore fraction.
- **Composite uniqueness:** partitioned tables need the partition key in unique constraints, so the same `event_id` with a different timestamp is treated as a new event.
- **MV refresh:** `ingest.py` uses a plain `REFRESH`, which briefly blocks reads on the daily summary. The nightly `pg_cron` job uses `CONCURRENTLY`.
- **Single-node PostgreSQL:** no read replica and no HA/failover. This is adequate for 1M rows.
- **1M-row scale:** partitioning and indexing effects are measurable at this size, but the trade-offs shift at 10M+ rows (BRIN indexes, columnar aggregation, incremental MV maintenance).
- **Superset Custom SQL:** the map dataset uses Custom SQL to bypass the forced-metric requirement. It works, but a proper dataset configuration would be cleaner.

---

## Roadmap

- Rejection-sample the synthetic data via `ST_Contains` (all points on land, plus a modeled offshore share)
- Read replica and failover story for the dashboard read path
- Benchmark at 10M rows to validate the scaling assumptions
- Incremental MV refresh instead of a full refresh
- Mermaid architecture diagram

---

## Project Structure

```
Spatiotemporal-Lightning-Analytics/
├── database/
│   ├── schema.sql              (reference only)
│   ├── partitions.sql          (reference only)
│   ├── indexes.sql             (reference only)
│   ├── materialized_views.sql  (reference only)
│   └── load_states.sql
├── ingestion/
│   ├── ingest.py
│   ├── test_data.csv
│   ├── test_new_data.csv
│   └── test_bad_data.csv
├── benchmarks/
├── shapefiles/
│   ├── India_State_Boundary.shp
│   ├── India_State_Boundary.shx
│   ├── India_State_Boundary.dbf
│   └── India_State_Boundary.prj
├── docs/
│   └── dashboard_1.png
└── README.md
```

---

## Tech Stack

**Database:** PostgreSQL 17 · PostGIS · pg_cron · pg_stat_statements  
**Language:** Python 3.10  
**Libraries:** psycopg2 · SQLAlchemy  
**Visualization:** Apache Superset 6.0
