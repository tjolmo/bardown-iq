"""add player_prediction_log.market_source (which feed the logged prop line came from)

Revision ID: a7b8c9d0e1f2
Revises: f6a1b2c3d4e5
Create Date: 2026-10-07 20:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'a7b8c9d0e1f2'
down_revision: Union[str, Sequence[str], None] = 'f6a1b2c3d4e5'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    # "espn" (player_prop_snapshots) or "odds_api" (odds_api_prop_quotes consensus); NULL when no line was logged.
    # Rows logged before this column existed with a line came from ESPN.
    op.add_column('player_prediction_log', sa.Column('market_source', sa.String(), nullable=True))
    op.execute("UPDATE player_prediction_log SET market_source = 'espn' WHERE market_line IS NOT NULL")


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_column('player_prediction_log', 'market_source')
