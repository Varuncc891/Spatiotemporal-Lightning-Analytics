"""add_indexes

Revision ID: bdb65b394328
Revises: 5566ece10587
Create Date: 2026-03-09

"""
from alembic import op

revision = 'bdb65b394328'
down_revision = '5566ece10587'
branch_labels = None
depends_on = None


def upgrade():
    op.execute("CREATE INDEX IF NOT EXISTS idx_lightning_timestamp_state ON lightning_strikes (timestamp, state_id)")
    op.execute("CREATE INDEX IF NOT EXISTS idx_lightning_high_intensity ON lightning_strikes (timestamp) WHERE intensity_category = 'High'")
    op.execute("CREATE INDEX IF NOT EXISTS idx_lightning_geom ON lightning_strikes USING GIST (geom)")
    op.execute("CREATE INDEX IF NOT EXISTS idx_lightning_flash_type ON lightning_strikes (flash_type)")
    op.execute("CREATE INDEX IF NOT EXISTS idx_states_geom ON india_states USING GIST (geom)")


def downgrade():
    op.execute("DROP INDEX IF EXISTS idx_lightning_timestamp_state")
    op.execute("DROP INDEX IF EXISTS idx_lightning_high_intensity")
    op.execute("DROP INDEX IF EXISTS idx_lightning_geom")
    op.execute("DROP INDEX IF EXISTS idx_lightning_flash_type")
    op.execute("DROP INDEX IF EXISTS idx_states_geom")