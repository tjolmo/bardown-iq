"""add player_injuries (ESPN injury report snapshots)

Revision ID: e5f6a1b2c3d4
Revises: d4e5f6a1b2c3
Create Date: 2026-10-07 13:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'e5f6a1b2c3d4'
down_revision: Union[str, Sequence[str], None] = 'd4e5f6a1b2c3'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table(
        'player_injuries',
        sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
        sa.Column('fetched_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('espn_athlete_id', sa.Integer(), nullable=False),
        sa.Column('player_id', sa.Integer(), nullable=True),
        sa.Column('team', sa.String(), nullable=True),
        sa.Column('full_name', sa.String(), nullable=True),
        sa.Column('position', sa.String(), nullable=True),
        sa.Column('status', sa.String(), nullable=False),
        sa.Column('espn_status', sa.String(), nullable=True),
        sa.Column('fantasy_status', sa.String(), nullable=True),
        sa.Column('injury_type', sa.String(), nullable=True),
        sa.Column('roster_status', sa.String(), nullable=True),
        sa.Column('report_date', sa.DateTime(timezone=True), nullable=True),
        sa.Column('return_date', sa.Date(), nullable=True),
        sa.Column('espn_injury_id', sa.Integer(), nullable=True),
        sa.Column('comment', sa.String(), nullable=True),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('fetched_at', 'espn_athlete_id', name='uq_player_injuries'),
    )
    op.create_index(op.f('ix_player_injuries_fetched_at'), 'player_injuries', ['fetched_at'], unique=False)
    op.create_index(op.f('ix_player_injuries_player_id'), 'player_injuries', ['player_id'], unique=False)


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index(op.f('ix_player_injuries_player_id'), table_name='player_injuries')
    op.drop_index(op.f('ix_player_injuries_fetched_at'), table_name='player_injuries')
    op.drop_table('player_injuries')
