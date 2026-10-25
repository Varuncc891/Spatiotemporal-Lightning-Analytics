# ============================================================
# NRSC Lightning Data Platform
# ingest.py — CSV ingestion pipeline with spatial enrichment
# Usage: python ingestion/ingest.py --file data.csv [--since YYYY-MM-DD]
# ============================================================

import psycopg2
from psycopg2.extras import execute_values
import csv
import argparse
import logging
import time
import os
from datetime import datetime, timezone

# ============================================================
# CONFIG
# ============================================================
DB_CONFIG = {
    "host":     "localhost",
    "port":     5432,
    "dbname":   "nrsc_lightning_db",
    "user":     "postgres",
    "password": "postgres123"
}

BATCH_SIZE = 5000

LAT_MIN, LAT_MAX = 6.5,  35.5
LON_MIN, LON_MAX = 68.0, 97.5

VALID_FLASH_TYPES   = {'CG', 'IC', 'CC'}
VALID_QUALITY_FLAGS = {'0', '1', '2'}

REQUIRED_COLUMNS = {
    'event_id', 'latitude', 'longitude',
    'timestamp', 'radiance', 'flash_type', 'quality_flag'
}

# ============================================================
# LOGGING
# ============================================================
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s — %(levelname)s — %(message)s',
    datefmt='%H:%M:%S'
)
log = logging.getLogger(__name__)

# ============================================================
# VALIDATION
# ============================================================
def validate_row(row, row_num):
    errors = []

    try:
        lat = float(row['latitude'])
        lon = float(row['longitude'])
    except (ValueError, KeyError):
        errors.append("invalid lat/lon")
        return None, errors

    if not (LAT_MIN <= lat <= LAT_MAX):
        errors.append(f"latitude {lat} outside India bounds")
    if not (LON_MIN <= lon <= LON_MAX):
        errors.append(f"longitude {lon} outside India bounds")

    try:
        event_id = int(row['event_id'])
    except (ValueError, KeyError):
        errors.append("invalid event_id")
        return None, errors

    try:
        radiance = float(row['radiance'])
        if radiance < 0:
            errors.append("radiance cannot be negative")
    except (ValueError, KeyError):
        errors.append("invalid radiance")
        return None, errors

    flash_type = row.get('flash_type', '').strip().upper()
    if flash_type not in VALID_FLASH_TYPES:
        errors.append(f"invalid flash_type: {flash_type}")

    quality_flag = row.get('quality_flag', '').strip()
    if quality_flag not in VALID_QUALITY_FLAGS:
        errors.append(f"invalid quality_flag: {quality_flag}")

    try:
        ts = datetime.fromisoformat(row['timestamp'])
        if ts.tzinfo is None:
            ts = ts.replace(tzinfo=timezone.utc)
    except (ValueError, KeyError):
        errors.append("invalid timestamp format")
        return None, errors

    if errors:
        return None, errors

    return {
        'event_id':     event_id,
        'latitude':     lat,
        'longitude':    lon,
        'timestamp':    ts,
        'radiance':     radiance,
        'flash_type':   flash_type,
        'quality_flag': int(quality_flag),
        'geom':         f"SRID=4326;POINT({lon} {lat})"
    }, []

# ============================================================
# BATCH INSERT — ON CONFLICT DO NOTHING
# ============================================================
def insert_batch(cur, conn, batch):
    batch = list({(r['event_id'], r['timestamp']): r for r in batch}.values())

    execute_values(
        cur,
        """
        INSERT INTO lightning_strikes
            (event_id, latitude, longitude, timestamp,
             radiance, flash_type, quality_flag, geom, state_id)
        VALUES %s
        ON CONFLICT (event_id, timestamp) DO NOTHING
        """,
        batch,
        template="""(
            %(event_id)s, %(latitude)s, %(longitude)s, %(timestamp)s,
            %(radiance)s, %(flash_type)s, %(quality_flag)s,
            ST_GeomFromEWKT(%(geom)s), NULL
        )""",
        page_size=len(batch)
    )

    inserted = cur.rowcount
    skipped  = len(batch) - inserted
    conn.commit()
    return inserted, skipped

# ============================================================
# POST-LOAD: spatial map, MV refresh, verify
# ============================================================
def spatial_map(cur, conn):
    log.info("Running spatial mapping...")
    cur.execute("""
        UPDATE lightning_strikes ls
        SET state_id = ist.state_id
        FROM india_states ist
        WHERE ls.state_id IS NULL
          AND ST_Within(ls.geom, ist.geom);
    """)
    mapped = cur.rowcount
    conn.commit()
    log.info(f"Spatial mapping: {mapped:,} rows assigned to states")
    return mapped

def refresh_views(cur, conn):
    log.info("Refreshing daily summary MV...")
    cur.execute("REFRESH MATERIALIZED VIEW lightning_daily_summary_mv;")
    conn.commit()
    log.info("MV refreshed")

def verify(cur):
    cur.execute("""
        SELECT COUNT(*),
               COUNT(*) FILTER (WHERE state_id IS NOT NULL),
               COUNT(*) FILTER (WHERE state_id IS NULL)
        FROM lightning_strikes;
    """)
    total, mapped, unmapped = cur.fetchone()
    pct = (mapped / total * 100) if total else 0
    log.info(f"Verify: {total:,} total, {mapped:,} mapped ({pct:.1f}%), "
             f"{unmapped:,} unmapped")
    return total, mapped, unmapped

# ============================================================
# MAIN
# ============================================================
def main():
    parser = argparse.ArgumentParser(description='NRSC Lightning Data Ingestion')
    parser.add_argument('--file', required=True, help='Path to input CSV')
    parser.add_argument('--since', help='Only ingest rows with timestamp >= YYYY-MM-DD')
    args = parser.parse_args()

    if not os.path.exists(args.file):
        log.error(f"File not found: {args.file}")
        return

    since_ts = None
    if args.since:
        since_ts = datetime.fromisoformat(args.since).replace(tzinfo=timezone.utc)
        log.info(f"Incremental mode: only rows with timestamp >= {since_ts.isoformat()}")

    log.info(f"Starting ingestion: {args.file}")

    rejected_file = args.file.replace('.csv', '_rejected.csv')

    conn = psycopg2.connect(**DB_CONFIG)
    cur  = conn.cursor()

    stats = {'total': 0, 'inserted': 0, 'skipped': 0, 'rejected': 0, 'filtered': 0}

    start_time    = time.time()
    batch_valid   = []
    rejected_rows = []

    with open(args.file, newline='', encoding='utf-8') as csvfile:
        reader = csv.DictReader(csvfile)

        missing = REQUIRED_COLUMNS - set(reader.fieldnames or [])
        if missing:
            log.error(f"CSV missing required columns: {missing}")
            return

        for row_num, row in enumerate(reader, start=1):
            stats['total'] += 1

            validated, errors = validate_row(row, row_num)

            if errors:
                stats['rejected'] += 1
                row['_errors'] = '; '.join(errors)
                rejected_rows.append(row)
                continue

            # Incremental filter
            if since_ts and validated['timestamp'] < since_ts:
                stats['filtered'] += 1
                continue

            batch_valid.append(validated)

            if len(batch_valid) >= BATCH_SIZE:
                inserted, skipped = insert_batch(cur, conn, batch_valid)
                stats['inserted'] += inserted
                stats['skipped']  += skipped
                log.info(f"Row {row_num}: {stats['inserted']:,} inserted, "
                         f"{stats['skipped']:,} skipped, "
                         f"{stats['rejected']:,} rejected")
                batch_valid = []

        if batch_valid:
            inserted, skipped = insert_batch(cur, conn, batch_valid)
            stats['inserted'] += inserted
            stats['skipped']  += skipped

    if rejected_rows:
        with open(rejected_file, 'w', newline='', encoding='utf-8') as rf:
            writer = csv.DictWriter(rf, fieldnames=list(rejected_rows[0].keys()))
            writer.writeheader()
            writer.writerows(rejected_rows)
        log.info(f"Rejected rows written to: {rejected_file}")

    # Post-load
    spatial_map(cur, conn)
    refresh_views(cur, conn)
    verify(cur)

    # Fresh planner statistics
    log.info("Running ANALYZE...")
    cur.execute("ANALYZE lightning_strikes;")
    conn.commit()

    cur.close()
    conn.close()

    elapsed = time.time() - start_time
    log.info("=" * 50)
    log.info(f"Ingestion complete in {elapsed:.1f}s")
    log.info(f"Total rows processed : {stats['total']:,}")
    log.info(f"Inserted             : {stats['inserted']:,}")
    log.info(f"Skipped (duplicates) : {stats['skipped']:,}")
    log.info(f"Rejected (invalid)   : {stats['rejected']:,}")
    log.info(f"Filtered (--since)   : {stats['filtered']:,}")
    log.info("=" * 50)


if __name__ == "__main__":
    main()
