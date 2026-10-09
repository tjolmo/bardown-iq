"""add shots_on_goal, pp_toi, pp_points to skater_game_logs

Revision ID: c5a1d3e7f901
Revises: b4e8c2d17a35
Create Date: 2026-10-06 22:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'c5a1d3e7f901'
down_revision: Union[str, Sequence[str], None] = 'b4e8c2d17a35'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column('skater_game_logs', sa.Column('shots_on_goal', sa.Integer(), nullable=True))
    op.add_column('skater_game_logs', sa.Column('pp_toi', sa.Float(), nullable=True))
    op.add_column('skater_game_logs', sa.Column('pp_points', sa.Integer(), nullable=True))


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_column('skater_game_logs', 'pp_points')
    op.drop_column('skater_game_logs', 'pp_toi')
    op.drop_column('skater_game_logs', 'shots_on_goal')
