-- ============================================================
-- REFERENCE ONLY — Authoritative DDL is in database/migrations/
-- ============================================================

ALTER TABLE lightning_strikes
    ADD CONSTRAINT uq_strikes_event_ts UNIQUE (event_id, timestamp);

CREATE INDEX idx_lightning_timestamp_state
    ON lightning_strikes (timestamp, state_id);

CREATE INDEX idx_lightning_geom
    ON lightning_strikes USING GIST (geom);

CREATE INDEX idx_states_geom
    ON india_states USING GIST (geom);
