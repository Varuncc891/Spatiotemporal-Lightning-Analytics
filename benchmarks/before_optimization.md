# Before Optimization — EXPLAIN ANALYZE Results
Database: nrsc_lightning_db
Rows: 1,000,000
Settings: enable_indexscan=off, enable_bitmapscan=off

---

## Query 1 — Time Range Aggregation (Single Year)
```sql
SELECT COUNT(*), AVG(radiance), MAX(radiance)
FROM lightning_strikes
WHERE timestamp BETWEEN '2023-01-01' AND '2023-12-31';
```
**Execution Time: 802.469 ms**
**Scan Type: Parallel Seq Scan on lightning_strikes_2023**
**Rows Scanned: 166,607**
```
Finalize Aggregate (cost=5986.42..5986.43 rows=1 width=72) (actual time=795.615..801.794 rows=1 loops=1)
  -> Gather (cost=5986.30..5986.41) (actual time=137.007..801.740 rows=2 loops=1)
      Workers Planned: 1 | Workers Launched: 1
      -> Partial Aggregate (actual time=66.768..66.769 rows=1 loops=2)
          -> Parallel Seq Scan on lightning_strikes_2023
               Filter: timestamp BETWEEN 2023-01-01 AND 2023-12-31
               Rows Removed by Filter: 107
Planning Time: 7.448 ms
Execution Time: 802.469 ms
```

---

## Query 2 — Composite Filter (Time + State)
```sql
SELECT COUNT(*), AVG(radiance)
FROM lightning_strikes
WHERE timestamp BETWEEN '2022-01-01' AND '2022-06-30'
AND state_id IS NOT NULL;
```
**Execution Time: 53.719 ms**
**Scan Type: Seq Scan on lightning_strikes_2022**
**Rows Scanned: 166,607 | Rows Removed by Filter: 166,607**
```
Aggregate (cost=5272.11..5272.12) (actual time=53.644..53.645 rows=1 loops=1)
  -> Seq Scan on lightning_strikes_2022
       Filter: state_id IS NOT NULL AND timestamp BETWEEN 2022-01-01 AND 2022-06-30
       Rows Removed by Filter: 166607
Planning Time: 2.331 ms
Execution Time: 53.719 ms
```

---

## Query 3 — High Intensity Filter (Multi-Year)
```sql
SELECT COUNT(*), AVG(radiance)
FROM lightning_strikes
WHERE intensity_category = 'High'
AND timestamp BETWEEN '2021-01-01' AND '2025-12-31';
```
**Execution Time: 255.890 ms**
**Scan Type: Parallel Seq Scan across 5 partitions**
**Workers: 2**
```
Finalize Aggregate (actual time=244.001..255.773 rows=1 loops=1)
  -> Gather (actual time=243.978..255.754 rows=3 loops=1)
      Workers Planned: 2 | Workers Launched: 2
      -> Parallel Append
          -> Parallel Seq Scan on lightning_strikes_2025 (Rows Removed: 80548)
          -> Parallel Seq Scan on lightning_strikes_2023 (Rows Removed: 80384)
          -> Parallel Seq Scan on lightning_strikes_2021 (Rows Removed: 26802)
          -> Parallel Seq Scan on lightning_strikes_2022 (Rows Removed: 80624)
          -> Parallel Seq Scan on lightning_strikes_2024 (Rows Removed: 80448)
Planning Time: 16.713 ms
Execution Time: 255.890 ms
```

---

## Query 4 — Grouped Aggregation on Materialized View
```sql
SELECT state_name, COUNT(*), AVG(radiance)
FROM lightning_master_mv
WHERE timestamp BETWEEN '2023-01-01' AND '2023-12-31'
GROUP BY state_name ORDER BY COUNT(*) DESC;
```
**Execution Time: 308.124 ms**
**Scan Type: Parallel Seq Scan on lightning_master_mv**
**Rows Scanned: ~166,701 | Rows Removed by Filter: 277,766**
```
Sort (actual time=300.431..307.186 rows=1 loops=1)
  -> Finalize GroupAggregate (actual time=300.425..307.179)
      -> Gather Merge (actual time=300.406..307.160)
          -> Partial HashAggregate (actual time=262.797..262.805)
              -> Parallel Seq Scan on lightning_master_mv
                   Filter: timestamp BETWEEN 2023-01-01 AND 2023-12-31
                   Rows Removed by Filter: 277766
Planning Time: 0.498 ms
Execution Time: 308.124 ms
```