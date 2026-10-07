"""add hits, blocked_shots to skater_game_logs

Revision ID: e1a2b3c4d5f6
Revises: d6b2e4f8a012
Create Date: 2026-10-06 23:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'e1a2b3c4d5f6'
down_revision: Union[str, Sequence[str], None] = 'd6b2e4f8a012'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column('skater_game_logs', sa.Column('hits', sa.Integer(), nullable=True))
    op.add_column('skater_game_logs', sa.Column('blocked_shots', sa.Integer(), nullable=True))


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_column('skater_game_logs', 'blocked_shots')
    op.drop_column('skater_game_logs', 'hits')
