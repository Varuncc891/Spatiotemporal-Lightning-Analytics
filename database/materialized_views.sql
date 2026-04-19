-- ============================================================
-- NRSC Lightning Data Platform
-- materialized_views.sql
-- ============================================================

-- ============================================================
-- MV 1: lightning_master_mv
-- Enriched strike data with state info
-- ============================================================
CREATE MATERIALIZED VIEW lightning_master_mv AS
SELECT
    ls.event_id,
    ls.latitude,
    ls.longitude,
    ls.timestamp,
    ls.radiance,
    ls.flash_type,
    ls.intensity_category,
    ls.quality_flag,
    ls.geom,
    COALESCE(ist.state_name, 'Ocean/Unknown') AS state_name,
    ist.region,
    ls.state_id,
    ls.created_at
FROM lightning_strikes ls
LEFT JOIN india_states ist ON ls.state_id = ist.state_id
WITH DATA;

-- Index on materialized view for fast Superset queries
CREATE INDEX idx_mv_master_timestamp
    ON lightning_master_mv (timestamp);

CREATE INDEX idx_mv_master_state
    ON lightning_master_mv (state_name);

CREATE INDEX idx_mv_master_intensity
    ON lightning_master_mv (intensity_category);

-- ============================================================
-- MV 2: lightning_daily_summary_mv
-- Daily aggregated stats per state
-- ============================================================
CREATE MATERIALIZED VIEW lightning_daily_summary_mv AS
SELECT
    DATE(ls.timestamp)              AS strike_date,
    COALESCE(ist.state_name, 'Ocean/Unknown') AS state_name,
    ist.region,
    COUNT(*)                        AS total_strikes,
    AVG(ls.radiance)                AS avg_radiance,
    MAX(ls.radiance)                AS max_radiance,
    COUNT(*) FILTER (WHERE ls.intensity_category = 'Low')    AS low_count,
    COUNT(*) FILTER (WHERE ls.intensity_category = 'Medium') AS medium_count,
    COUNT(*) FILTER (WHERE ls.intensity_category = 'High')   AS high_count,
    COUNT(*) FILTER (WHERE ls.flash_type = 'CG')             AS cg_count,
    COUNT(*) FILTER (WHERE ls.flash_type = 'IC')             AS ic_count,
    COUNT(*) FILTER (WHERE ls.flash_type = 'CC')             AS cc_count
FROM lightning_strikes ls
LEFT JOIN india_states ist ON ls.state_id = ist.state_id
GROUP BY DATE(ls.timestamp), ist.state_name, ist.region
WITH DATA;

-- Index for fast date range queries
CREATE UNIQUE INDEX idx_mv_daily_date_state
    ON lightning_daily_summary_mv (strike_date, state_name);

CREATE INDEX idx_mv_daily_date
    ON lightning_daily_summary_mv (strike_date);

-- ============================================================
-- REFRESH FUNCTION
-- Call this after every ingestion batch
-- ============================================================
CREATE OR REPLACE FUNCTION refresh_lightning_views()
RETURNS void AS $$
BEGIN
    REFRESH MATERIALIZED VIEW CONCURRENTLY lightning_master_mv;
    REFRESH MATERIALIZED VIEW CONCURRENTLY lightning_daily_summary_mv;
END;
$$ LANGUAGE plpgsql;