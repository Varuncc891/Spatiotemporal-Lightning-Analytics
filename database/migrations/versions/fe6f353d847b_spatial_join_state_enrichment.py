"""spatial_join_state_enrichment

Revision ID: fe6f353d847b
Revises: 48b26036eceb
Create Date: 2026-03-09

"""
from alembic import op

revision = 'fe6f353d847b'
down_revision = '48b26036eceb'
branch_labels = None
depends_on = None


def upgrade():
    op.execute("""
        UPDATE lightning_strikes ls
        SET state_id = s.state_id
        FROM india_states s
        WHERE ls.state_id IS NULL
          AND ls.geom && s.geom
          AND ST_Within(ls.geom, s.geom)
    """)
    op.execute("SELECT refresh_lightning_views()")


def downgrade():
    op.execute("UPDATE lightning_strikes SET state_id = NULL")
    op.execute("SELECT refresh_lightning_views()")