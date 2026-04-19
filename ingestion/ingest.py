# ============================================================
# NRSC Lightning Data Platform
# ingest.py — Production-grade CSV ingestion pipeline
# Usage: python ingestion/ingest.py --file data.csv
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

# India bounding box
LAT_MIN, LAT_MAX = 6.5,  35.5
LON_MIN, LON_MAX = 68.0, 97.5

VALID_FLASH_TYPES   = {'CG', 'IC', 'CC'}
VALID_QUALITY_FLAGS = {'0', '1', '2'}

REQUIRED_COLUMNS = {
    'event_id', 'latitude', 'longitude',
    'timestamp', 'radiance', 'flash_type', 'quality_flag'
}

# ============================================================
# LOGGING SETUP
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
        'event_id':    event_id,
        'latitude':    lat,
        'longitude':   lon,
        'timestamp':   ts,
        'radiance':    radiance,
        'flash_type':  flash_type,
        'quality_flag': int(quality_flag),
        'geom':        f"SRID=4326;POINT({lon} {lat})"
    }, []

# ============================================================
# DEDUPLICATION — fetch existing event_ids in bulk
# ============================================================
def get_existing_ids(cur, event_ids):
    if not event_ids:
        return set()
    cur.execute(
        "SELECT event_id FROM lightning_strikes WHERE event_id = ANY(%s)",
        (list(event_ids),)
    )
    return {row[0] for row in cur.fetchall()}

# ============================================================
# MAIN PIPELINE
# ============================================================
def main():
    parser = argparse.ArgumentParser(description='NRSC Lightning Data Ingestion Pipeline')
    parser.add_argument('--file', required=True, help='Path to input CSV file')
    args = parser.parse_args()

    if not os.path.exists(args.file):
        log.error(f"File not found: {args.file}")
        return

    log.info(f"Starting ingestion: {args.file}")

    # Rejected rows output file
    rejected_file = args.file.replace('.csv', '_rejected.csv')

    conn = psycopg2.connect(**DB_CONFIG)
    cur  = conn.cursor()

    stats = {
        'total':      0,
        'inserted':   0,
        'duplicates': 0,
        'rejected':   0
    }

    start_time    = time.time()
    batch_valid   = []
    batch_raw     = []
    rejected_rows = []

    with open(args.file, newline='', encoding='utf-8') as csvfile:
        reader = csv.DictReader(csvfile)

        # Check required columns exist
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

            batch_valid.append(validated)
            batch_raw.append(row)

            # Process batch
            if len(batch_valid) >= BATCH_SIZE:
                inserted, dupes = insert_batch(cur, conn, batch_valid)
                stats['inserted']   += inserted
                stats['duplicates'] += dupes
                log.info(f"Row {row_num}: {stats['inserted']:,} inserted, "
                         f"{stats['duplicates']:,} dupes, "
                         f"{stats['rejected']:,} rejected")
                batch_valid = []
                batch_raw   = []

        # Final batch
        if batch_valid:
            inserted, dupes = insert_batch(cur, conn, batch_valid)
            stats['inserted']   += inserted
            stats['duplicates'] += dupes

    # Write rejected rows to CSV
    if rejected_rows:
        with open(rejected_file, 'w', newline='', encoding='utf-8') as rf:
            fieldnames = list(rejected_rows[0].keys())
            writer = csv.DictWriter(rf, fieldnames=fieldnames)
            writer.writeheader()
            writer.writerows(rejected_rows)
        log.info(f"Rejected rows written to: {rejected_file}")

    cur.close()
    conn.close()

    elapsed = time.time() - start_time
    log.info("=" * 50)
    log.info(f"Ingestion complete in {elapsed:.1f}s")
    log.info(f"Total rows processed : {stats['total']:,}")
    log.info(f"Inserted             : {stats['inserted']:,}")
    log.info(f"Duplicates skipped   : {stats['duplicates']:,}")
    log.info(f"Rejected (invalid)   : {stats['rejected']:,}")
    log.info("=" * 50)

def insert_batch(cur, conn, batch):
    event_ids = {r['event_id'] for r in batch}
    existing  = get_existing_ids(cur, event_ids)

    clean = [r for r in batch if r['event_id'] not in existing]
    dupes = len(batch) - len(clean)

    if clean:
        execute_values(
            cur,
            """
            INSERT INTO lightning_strikes
                (event_id, latitude, longitude, timestamp,
                 radiance, flash_type, quality_flag, geom, state_id)
            VALUES %s
            """,
            clean,
            template="""(
                %(event_id)s, %(latitude)s, %(longitude)s, %(timestamp)s,
                %(radiance)s, %(flash_type)s, %(quality_flag)s,
                ST_GeomFromEWKT(%(geom)s), NULL
            )"""
        )
        conn.commit()

    return len(clean), dupes

if __name__ == "__main__":
    main()