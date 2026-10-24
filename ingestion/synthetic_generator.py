# Spatiotemporal Lightning Analytics

> Production-grade geospatial lightning analytics on PostgreSQL 17 + PostGIS.  
> Time-based partitioning · Composite indexing · Spatial joins · Python ETL

---

![Lightning Dashboard](docs/dashboard_1.png)

---

## What & Why

Lightning strike data arrives in high volumes, unevenly distributed across time and geography. A naive flat-table schema collapses under aggregation queries at scale — full sequential scans, no spatial awareness, no pre-computed summaries.

This platform solves that. It stores 1M+ strike events in a partitioned PostGIS schema, spatially joins them to state boundaries, serves live point data through a view over the partitioned table, and pre-aggregates daily summaries into a materialized view. The ETL pipeline handles real-world messiness: out-of-bounds coordinates, bad timestamps, duplicate IDs, and partial data.

Designed for weather analytics, research, and government monitoring use cases where query speed and data quality both matter.

---

## Highlights

- 🧱 Range partitioning by year (2021–2025) with automatic partition routing
- 🗺️ PostGIS exact point-in-polygon (`ST_Within`) spatial join mapping strikes to 36 state boundaries
- 👁️ Dashboard map reads a live view over the partitioned base table — zero storage, always fresh, no refresh needed
- ⚙️ Daily materialized view pre-aggregating strikes into **57,916** daily-state summaries
- 🔒 Database-enforced deduplication via `UNIQUE (event_id, timestamp)` — atomic and race-free
- 🐍 Python ETL pipeline: validation → batch insert with `ON CONFLICT DO NOTHING` → spatial mapping → MV refresh → verification, in one command
- 🔁 Alembic as the single source of truth for schema, with upgrade/downgrade paths
- 📊 Apache Superset dashboard with state + time-range filters on a live map

---

## Quick Start

```bash
git clone https://github.com/Varuncc891/Spatiotemporal-Lightning-Analytics
cd Spatiotemporal-Lightning-Analytics

# 1. Create the database
psql -U postgres -c "CREATE DATABASE lightning_db;"

# 2. Apply all migrations (schema + indexes + views)
python -m alembic upgrade head

# 3. Load state boundary shapefile
shp2pgsql -s 4326 shapefiles/India_State_Boundary.shp india_states_temp | psql -U postgres -d lightning_db
psql -U postgres -d lightning_db -c "
  INSERT INTO india_states (state_name, state_code, region, geom)
  SELECT name, type, NULL, ST_Multi(geom)::geometry(MultiPolygon, 4326) FROM india_states_temp;
  DROP TABLE india_states_temp;
"

# 4. Ingest data — loads, maps states, refreshes the daily MV, and verifies in one command
python ingestion/ingest.py --file ingestion/test_data.csv
```

**Requirements:** PostgreSQL 17, PostGIS, Python 3.10, psycopg2, Alembic

---

## Performance Benchmarks

Benchmark methodology, queries, `EXPLAIN (ANALYZE, BUFFERS)` output and results are available in the [`benchmarks/`](benchmarks/) folder. Please refer to it for details.

---

## Architecture

```
CSV Data
   │
   ▼
ingest.py
(validate → batch insert ON CONFLICT DO NOTHING → spatial map → refresh MV → verify)
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

**Why a view instead of a materialized view for the map:** an earlier design used a 1M-row materialized view for point data. It duplicated the base table, went stale after each ingest, and could not be partitioned. The state join is against only 36 rows, so a live view over the partitioned table is cheaper to maintain and is always current. The daily aggregate stays materialized because it collapses 1M rows into about 58k.

---

## Key Features

### Time-Based Partitioning
`lightning_strikes` is partitioned by `RANGE(timestamp)` across yearly child tables (2021–2025) plus a default partition. A query scoped to a single year scans only that year's partition instead of the whole table. Partitioning also enables instant retention (drop or detach an old year) and per-partition maintenance as data grows.

### Indexing Strategy

| Index | Type | Purpose |
|---|---|---|
| `uq_strikes_event_ts` | UNIQUE (event_id, timestamp) | Atomic deduplication for `ON CONFLICT DO NOTHING` |
| `idx_lightning_timestamp_state` | Composite B-tree | Time + state queries (dashboard workhorse) |
| `idx_lightning_geom` | GiST | Spatial mapping (`ST_Within`) |
| `idx_states_geom` | GiST | State boundary side of the spatial join |
| `idx_mv_daily_date_state` | UNIQUE B-tree (MV) | Daily stats table + `REFRESH CONCURRENTLY` support |
| `idx_mv_daily_date` | B-tree (MV) | 30-day trend chart |

Indexes that no query used (a partial high-intensity index and a `flash_type` index) were dropped after review.

### Views and Materialized Views

```sql
-- Live point data for the dashboard map (always fresh, zero storage)
SELECT * FROM lightning_points_v WHERE timestamp >= '2023-06-01';

-- Pre-aggregated daily x state summaries
REFRESH MATERIALIZED VIEW lightning_daily_summary_mv;
-- lightning_daily_summary_mv: 57,916 rows
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

1. **Validate** — coordinates within India bounds (lat 6.5–35.5, lon 68.0–97.5), `flash_type` ∈ {CG, IC, CC}, `quality_flag` ∈ {0, 1, 2}, `radiance` ≥ 0, valid ISO timestamp, valid integer `event_id`
2. **Load** — 5,000-row batches with `INSERT ... ON CONFLICT (event_id, timestamp) DO NOTHING`; the database enforces uniqueness atomically, with no SELECT round trip per batch
3. **Spatial map** — assign `state_id` via `ST_Within`
4. **Refresh** — `REFRESH MATERIALIZED VIEW lightning_daily_summary_mv`
5. **Verify** — log total / mapped / unmapped counts
6. **Reject** — invalid rows written to `_rejected.csv` with error reasons

```bash
python ingestion/ingest.py --file your_file.csv
# Inserted: 500 | Skipped: 0 | Rejected: 0 | Time: 2.1s
```

### Schema Migrations (Alembic)
Alembic is the single source of truth for the schema. The `.sql` files in `database/` are reference-only.

```
<base> → create_lightning_strikes_partitioned
       → add_indexes
       → add_materialized_views
       → add_unique_event_timestamp_constraint
       → drop_master_mv_create_points_view
       → prune_unused_indexes  (head)
```

```bash
python -m alembic upgrade head   # apply
python -m alembic downgrade -1   # rollback
python -m alembic history        # audit trail
```

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
```

---

## Known Limitations

- **Composite uniqueness:** the same `event_id` with a different timestamp would be treated as a new event.
- **MV refresh:** `ingest.py` uses a plain `REFRESH`, which briefly blocks reads on the daily summary.

---

## Project Structure

```
spatiotemporal_dashboard/
├── database/
│ ├── schema.sql              (reference only)
│ ├── partitions.sql          (reference only)
│ ├── indexes.sql             (reference only)
│ ├── materialized_views.sql  (reference only)
│ ├── load_states.sql
│ └── migrations/
│ ├── 5566ece10587_create_lightning_strikes_partitioned.py
│ ├── bdb65b394328_add_indexes.py
│ ├── 48b26036eceb_add_materialized_views.py
│ └── (+ unique constraint, points view, index prune migrations)
├── ingestion/
│ ├── ingest.py
│ ├── test_data.csv
│ ├── test_new_data.csv
│ └── test_bad_data.csv
├── benchmarks/
├── shapefiles/
│ ├── India_State_Boundary.shp
│ ├── India_State_Boundary.shx
│ ├── India_State_Boundary.dbf
│ └── India_State_Boundary.prj
├── docs/
│ └── dashboard_1.png
├── alembic.ini
└── README.md
```

---

## Tech Stack

**Database:** PostgreSQL 17 · PostGIS  
**Language:** Python 3.10  
**Libraries:** psycopg2 · Alembic · SQLAlchemy  
**Visualization:** Apache Superset 6.0
