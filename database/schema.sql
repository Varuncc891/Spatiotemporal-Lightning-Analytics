-- ============================================================
-- NRSC Lightning Data Platform
-- schema.sql — Core table definitions
-- ============================================================

-- Enable PostGIS if not already enabled
CREATE EXTENSION IF NOT EXISTS postgis;

-- ============================================================
-- DIMENSION TABLE: india_states
-- ============================================================
CREATE TABLE india_states (
    state_id        serial PRIMARY KEY,
    state_name      text NOT NULL,
    state_code      text,
    region          text,
    geom            geometry(MultiPolygon, 4326)
);

-- ============================================================
-- FACT TABLE: lightning_strikes (partitioned parent)
-- ============================================================
CREATE TABLE lightning_strikes (
    event_id            bigint NOT NULL,
    latitude            numeric(9,6) NOT NULL,
    longitude           numeric(9,6) NOT NULL,
    timestamp           timestamptz NOT NULL,
    radiance            numeric(10,4),
    flash_type          text CHECK (flash_type IN ('CG', 'IC', 'CC')),
    intensity_category  text GENERATED ALWAYS AS (
                            CASE
                                WHEN radiance < 50  THEN 'Low'
                                WHEN radiance < 150 THEN 'Medium'
                                ELSE 'High'
                            END
                        ) STORED,
    quality_flag        smallint DEFAULT 0 CHECK (quality_flag IN (0, 1, 2)),
    geom                geometry(Point, 4326),
    state_id            integer REFERENCES india_states(state_id),
    created_at          timestamptz DEFAULT now()
) PARTITION BY RANGE (timestamp);