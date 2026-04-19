# ============================================================
# NRSC Lightning Data Platform
# synthetic_generator.py — Generate and insert synthetic data
# ============================================================

import psycopg2
from psycopg2.extras import execute_values
from datetime import datetime, timezone
import random
import time

# ============================================================
# CONFIG
# ============================================================
DB_CONFIG = {
    "host":     "localhost",
    "port":     5432,
    "dbname":   "nrsc_lightning_db",
    "user":     "postgres",
    "password": "postgres123"          # <-- CHANGE IF NEEDED
}

TOTAL_ROWS    = 1_000_000
BATCH_SIZE    = 10_000

# India bounding box – these must be floats
LAT_MIN, LAT_MAX = 6.5, 35.5
LON_MIN, LON_MAX = 68.0, 97.5

FLASH_TYPES    = ['CG', 'IC', 'CC']
FLASH_WEIGHTS  = [0.60, 0.30, 0.10]

QUALITY_FLAGS  = [0, 1, 2]
QUALITY_WEIGHTS = [0.90, 0.08, 0.02]

# Monsoon weighting (Jun–Sep 4x)
MONTH_WEIGHTS = [1, 1, 1, 1, 2, 4, 4, 4, 4, 2, 1, 1]

def random_timestamp():
    year = random.randint(2021, 2026)
    month = random.choices(range(1, 13), weights=MONTH_WEIGHTS)[0]
    days_in_month = [31, 28, 31, 30, 31, 30, 31, 31, 30, 31, 30, 31]
    day = random.randint(1, days_in_month[month - 1])
    return datetime(year, month, day,
                    random.randint(0, 23),
                    random.randint(0, 59),
                    random.randint(0, 59),
                    tzinfo=timezone.utc)

def generate_batch(batch_size, start_id, batch_num):
    rows = []
    batch_lats = []      # for debugging
    for i in range(batch_size):
        event_id = start_id + i
        lat = round(random.uniform(LAT_MIN, LAT_MAX), 6)
        lon = round(random.uniform(LON_MIN, LON_MAX), 6)
        batch_lats.append(lat)

        rows.append((
            event_id,
            lat,
            lon,
            random_timestamp(),
            round(random.uniform(10.0, 300.0), 4),
            random.choices(FLASH_TYPES, weights=FLASH_WEIGHTS)[0],
            random.choices(QUALITY_FLAGS, weights=QUALITY_WEIGHTS)[0],
            f"SRID=4326;POINT({lon} {lat})",
            None
        ))

    # Sanity check for this batch
    min_lat = min(batch_lats)
    max_lat = max(batch_lats)
    if min_lat < LAT_MIN - 0.0001 or max_lat > LAT_MAX + 0.0001:
        print(f"⚠️ BATCH {batch_num} latitude range outside bounds: {min_lat} – {max_lat}")
    else:
        print(f"✓ BATCH {batch_num} latitude range: {min_lat:.6f} – {max_lat:.6f}")

    return rows

def main():
    print("Connecting to database...")
    conn = psycopg2.connect(**DB_CONFIG)
    cur = conn.cursor()

    # Optional: Truncate existing bad data (uncomment if needed)
    # cur.execute("TRUNCATE TABLE lightning_strikes;")
    # conn.commit()
    # print("Truncated old data.")

    print(f"Generating {TOTAL_ROWS:,} rows in batches of {BATCH_SIZE:,}...")
    total_inserted = 0
    start_time = time.time()
    num_batches = TOTAL_ROWS // BATCH_SIZE

    for batch_num in range(num_batches):
        start_id = batch_num * BATCH_SIZE + 1
        rows = generate_batch(BATCH_SIZE, start_id, batch_num + 1)

        execute_values(
            cur,
            """
            INSERT INTO lightning_strikes
                (event_id, latitude, longitude, timestamp, radiance,
                 flash_type, quality_flag, geom, state_id)
            VALUES %s
            """,
            rows,
            template="(%s, %s, %s, %s, %s, %s, %s, ST_GeomFromEWKT(%s), %s)"
        )
        conn.commit()

        total_inserted += len(rows)
        elapsed = time.time() - start_time
        rate = total_inserted / elapsed
        print(f"Batch {batch_num + 1}/{num_batches} — {total_inserted:,} rows inserted — {rate:,.0f} rows/sec")

    cur.close()
    conn.close()
    print(f"\n✅ Done. {total_inserted:,} rows inserted in {time.time() - start_time:.1f} seconds.")

if __name__ == "__main__":
    main()