-- ============================================================
-- REFERENCE ONLY — Authoritative DDL is in database/migrations/
-- ============================================================

CREATE VIEW lightning_points_v AS
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
    ls.state_id,
    COALESCE(ist.state_name, 'Ocean/Unknown') AS state_name,
    ist.region
FROM lightning_strikes ls
LEFT JOIN india_states ist ON ls.state_id = ist.state_id;

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

CREATE UNIQUE INDEX idx_mv_daily_date_state
    ON lightning_daily_summary_mv (strike_date, state_name);

CREATE INDEX idx_mv_daily_date
    ON lightning_daily_summary_mv (strike_date);
