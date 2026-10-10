"""add game_lineups and game_units (dressed players, scratches and shift-chart deployment)

Revision ID: c9d0e1f2a3b4
Revises: b8c9d0e1f2a3
Create Date: 2026-10-10 04:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'c9d0e1f2a3b4'
down_revision: Union[str, Sequence[str], None] = 'b8c9d0e1f2a3'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table(
        'game_lineups',
        sa.Column('game_id', sa.Integer(), nullable=False),
        sa.Column('team', sa.String(), nullable=False),
        sa.Column('player_id', sa.Integer(), nullable=False),
        sa.Column('status', sa.String(), nullable=False),
        sa.Column('position', sa.String(), nullable=True),
        sa.Column('sweater_number', sa.Integer(), nullable=True),
        sa.Column('first_name', sa.String(), nullable=True),
        sa.Column('last_name', sa.String(), nullable=True),
        sa.Column('toi', sa.Integer(), nullable=True),
        sa.Column('toi_ev', sa.Integer(), nullable=True),
        sa.Column('toi_pp', sa.Integer(), nullable=True),
        sa.Column('toi_pk', sa.Integer(), nullable=True),
        sa.Column('faceoffs', sa.Integer(), nullable=True),
        sa.Column('fetched_at', sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint('game_id', 'team', 'player_id'),
    )
    op.create_index('ix_game_lineups_team_game', 'game_lineups', ['team', 'game_id'], unique=False)
    op.create_table(
        'game_units',
        sa.Column('game_id', sa.Integer(), nullable=False),
        sa.Column('team', sa.String(), nullable=False),
        sa.Column('situation', sa.String(), nullable=False),
        sa.Column('unit', sa.String(), nullable=False),
        sa.Column('seconds', sa.Integer(), nullable=False),
        sa.PrimaryKeyConstraint('game_id', 'team', 'situation', 'unit'),
    )
    op.create_index('ix_game_units_team_game', 'game_units', ['team', 'game_id'], unique=False)


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index('ix_game_units_team_game', table_name='game_units')
    op.drop_table('game_units')
    op.drop_index('ix_game_lineups_team_game', table_name='game_lineups')
    op.drop_table('game_lineups')
