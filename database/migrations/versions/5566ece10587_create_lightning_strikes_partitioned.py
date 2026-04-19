"""create_lightning_strikes_partitioned

Revision ID: 5566ece10587
Revises:
Create Date: 2026-03-09

"""
from alembic import op
import sqlalchemy as sa

revision = '5566ece10587'
down_revision = None
branch_labels = None
depends_on = None


def upgrade():
    # india_states dimension table
    op.execute("""
        CREATE TABLE IF NOT EXISTS india_states (
            state_id    serial PRIMARY KEY,
            state_name  text NOT NULL,
            state_code  text,
            region      text,
            geom        geometry(MultiPolygon, 4326)
        )
    """)

    # partitioned fact table
    op.execute("""
        CREATE TABLE IF NOT EXISTS lightning_strikes (
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
        ) PARTITION BY RANGE (timestamp)
    """)

    # partitions
    op.execute("CREATE TABLE IF NOT EXISTS lightning_strikes_2021 PARTITION OF lightning_strikes FOR VALUES FROM ('2021-01-01') TO ('2022-01-01')")
    op.execute("CREATE TABLE IF NOT EXISTS lightning_strikes_2022 PARTITION OF lightning_strikes FOR VALUES FROM ('2022-01-01') TO ('2023-01-01')")
    op.execute("CREATE TABLE IF NOT EXISTS lightning_strikes_2023 PARTITION OF lightning_strikes FOR VALUES FROM ('2023-01-01') TO ('2024-01-01')")
    op.execute("CREATE TABLE IF NOT EXISTS lightning_strikes_2024 PARTITION OF lightning_strikes FOR VALUES FROM ('2024-01-01') TO ('2025-01-01')")
    op.execute("CREATE TABLE IF NOT EXISTS lightning_strikes_2025 PARTITION OF lightning_strikes FOR VALUES FROM ('2025-01-01') TO ('2026-01-01')")
    op.execute("CREATE TABLE IF NOT EXISTS lightning_strikes_2026 PARTITION OF lightning_strikes FOR VALUES FROM ('2026-01-01') TO ('2027-01-01')")
    op.execute("CREATE TABLE IF NOT EXISTS lightning_strikes_default PARTITION OF lightning_strikes DEFAULT")


def downgrade():
    op.execute("DROP TABLE IF EXISTS lightning_strikes CASCADE")
    op.execute("DROP TABLE IF EXISTS india_states CASCADE")