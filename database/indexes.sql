-- ============================================================
-- NRSC Lightning Data Platform
-- indexes.sql — Index definitions
-- ============================================================

-- 1. Composite index: most common query pattern
-- "show me strikes in state X between date A and B"
CREATE INDEX idx_lightning_timestamp_state
    ON lightning_strikes (timestamp, state_id);

-- 2. Partial index: only high intensity strikes
-- smaller index, faster for intensity-filtered queries
CREATE INDEX idx_lightning_high_intensity
    ON lightning_strikes (timestamp)
    WHERE intensity_category = 'High';

-- 3. GiST spatial index: enables fast spatial joins + proximity queries
CREATE INDEX idx_lightning_geom
    ON lightning_strikes USING GIST (geom);

-- 4. Index on flash_type for type-based filtering
CREATE INDEX idx_lightning_flash_type
    ON lightning_strikes (flash_type);

-- 5. Index on india_states geometry for spatial joins
CREATE INDEX idx_states_geom
    ON india_states USING GIST (geom);