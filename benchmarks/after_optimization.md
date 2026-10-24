# Benchmarks — EXPLAIN (ANALYZE, BUFFERS) Results

Database: `nrsc_lightning_db` (PostgreSQL 17 + PostGIS)
Rows: ~1,000,000
Environment: Windows 10, local disk

## Method

- Every query is run with `EXPLAIN (ANALYZE, BUFFERS)`.
- The baseline is an unpartitioned copy of the table (`lightning_strikes_unpart`) with identical data, so each comparison changes one variable.
- Warm cache: the second run is reported.
- Index on/off configurations are compared on the same data so the effect of the index is isolated.

---

## 1. Partitioning — whole-year aggregation

```sql
SELECT COUNT(*), AVG(radiance), MAX(radiance)
FROM lightning_strikes
WHERE timestamp BETWEEN '2023-01-01' AND '2023-12-31';
```

| Config | Plan | Execution Time | Rows Matched |
|---|---|---|---|
| Unpartitioned (`lightning_strikes_unpart`) | Parallel Bitmap Heap Scan | 142.5 ms | 166,553 |
| Partitioned (`lightning_strikes`) | Parallel Seq Scan on `lightning_strikes_2023` only | 54.8 ms | ~166,915 |

**Result:** 142.5 ms → 54.8 ms (~2.6×). The partitioned plan touches only `lightning_strikes_2023`; the unpartitioned plan reads from the full table.

---

## 2. Selective day-plus-state query

```sql
SELECT COUNT(*)
FROM lightning_strikes
WHERE timestamp >= '2023-06-15' AND timestamp < '2023-06-16'
  AND state_id = 8;
```

| Config | Table | Index | Plan | Execution Time | Rows | Heap Fetches |
|---|---|---|---|---|---|---|
| A — neither | unpartitioned | off | Parallel Seq Scan (1M rows) | 97.4 ms | 18 | — |
| B — index only | unpartitioned | on | Index Only Scan | 0.058 ms | 18 | 0 |
| C — partition only | partitioned | off | Parallel Seq Scan (2023 partition) | 60.9 ms | 18 | — |
| D — both | partitioned | on | Index Only Scan on 2023 partition | 0.059 ms | 18 | 0 |

**Result:** 97.4 ms → 0.059 ms (~1,650×) for the combined partitioned + indexed path.

**Attribution**

- Partitioning alone (A → C): 97.4 → 60.9 ms, ~1.6× — one partition scanned instead of the full table.
- Indexing alone (A → B): 97.4 → 0.058 ms, ~1,680× — the index-only scan eliminated 99.99% of rows.
- Both (A → D): statistically identical to indexing alone, because at this selectivity the index does nearly all the work and partitioning has nothing left to skip.

The two mechanisms serve different query shapes: partitioning helps broad time-range queries, and the composite `(timestamp, state_id)` index helps selective filters. They are complementary, not additive on the same query.

---

## 3. Daily materialized view aggregation

```sql
SELECT state_name, SUM(total_strikes), AVG(avg_radiance)
FROM lightning_daily_summary_mv
WHERE strike_date BETWEEN '2023-01-01' AND '2023-12-31'
GROUP BY state_name
ORDER BY SUM(total_strikes) DESC;
```

Plan: `Index Scan using idx_mv_daily_date` on the 57k-row materialized view — a real plan change (seq scan → index scan) at the aggregate layer.

---

## Summary

| Query | Baseline | Optimized | Mechanism |
|---|---|---|---|
| Whole-year aggregation | 142.5 ms (unpartitioned, indexed) | 54.8 ms (partitioned, indexed) | Partition pruning |
| Selective day + state | 97.4 ms (unpartitioned, no index) | 0.059 ms (partitioned, indexed) | Index-only scan on one partition |
| Daily MV aggregation | — | — | MV index scan |

---

## Note on the original benchmark

The first benchmark used a BEFORE/AFTER method (`enable_indexscan = off` vs on, one run each, BEFORE first). Both Q1 plans were `Parallel Seq Scan` on the same partition, so the earlier 802 ms → 167 ms difference was cache warming, not partitioning. It has been replaced by the partitioned-vs-unpartitioned comparison above.
