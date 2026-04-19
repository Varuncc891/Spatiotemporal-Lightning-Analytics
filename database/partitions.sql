-- ============================================================
-- NRSC Lightning Data Platform
-- partitions.sql — Yearly partition definitions
-- ============================================================

CREATE TABLE lightning_strikes_2021
    PARTITION OF lightning_strikes
    FOR VALUES FROM ('2021-01-01') TO ('2022-01-01');

CREATE TABLE lightning_strikes_2022
    PARTITION OF lightning_strikes
    FOR VALUES FROM ('2022-01-01') TO ('2023-01-01');

CREATE TABLE lightning_strikes_2023
    PARTITION OF lightning_strikes
    FOR VALUES FROM ('2023-01-01') TO ('2024-01-01');

CREATE TABLE lightning_strikes_2024
    PARTITION OF lightning_strikes
    FOR VALUES FROM ('2024-01-01') TO ('2025-01-01');

CREATE TABLE lightning_strikes_2025
    PARTITION OF lightning_strikes
    FOR VALUES FROM ('2025-01-01') TO ('2026-01-01');

CREATE TABLE lightning_strikes_2026
    PARTITION OF lightning_strikes
    FOR VALUES FROM ('2026-01-01') TO ('2027-01-01');

-- Catch-all for anything outside defined ranges
CREATE TABLE lightning_strikes_default
    PARTITION OF lightning_strikes
    DEFAULT;