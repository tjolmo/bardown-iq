"""add team_game_stats and game_odds

Revision ID: a7d3e1f09b21
Revises: c0a51cae31d8
Create Date: 2026-10-06 18:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'a7d3e1f09b21'
down_revision: Union[str, Sequence[str], None] = 'c0a51cae31d8'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table('team_game_stats',
        sa.Column('game_id', sa.Integer(), nullable=False),
        sa.Column('team_tri_code', sa.String(), nullable=False),
        sa.Column('opposing_team_tri_code', sa.String(), nullable=False),
        sa.Column('season', sa.Integer(), nullable=False),
        sa.Column('game_date', sa.Integer(), nullable=False),
        sa.Column('home_away', sa.String(), nullable=False),
        sa.Column('playoff', sa.Boolean(), nullable=False),
        sa.Column('goals_for', sa.Integer(), nullable=False),
        sa.Column('goals_against', sa.Integer(), nullable=False),
        sa.Column('x_goals_for', sa.Float(), nullable=False),
        sa.Column('x_goals_against', sa.Float(), nullable=False),
        sa.Column('shot_attempts_for', sa.Integer(), nullable=False),
        sa.Column('shot_attempts_against', sa.Integer(), nullable=False),
        sa.Column('x_goals_for_5v5', sa.Float(), nullable=True),
        sa.Column('x_goals_against_5v5', sa.Float(), nullable=True),
        sa.Column('shot_attempts_for_5v5', sa.Float(), nullable=True),
        sa.Column('shot_attempts_against_5v5', sa.Float(), nullable=True),
        sa.Column('goals_for_5v5', sa.Integer(), nullable=True),
        sa.Column('goals_against_5v5', sa.Integer(), nullable=True),
        sa.Column('pp_x_goals_for', sa.Float(), nullable=True),
        sa.Column('pp_toi', sa.Float(), nullable=True),
        sa.Column('pk_x_goals_against', sa.Float(), nullable=True),
        sa.Column('pk_toi', sa.Float(), nullable=True),
        sa.Column('last_updated', sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint('game_id', 'team_tri_code')
    )
    op.create_table('game_odds',
        sa.Column('game_id', sa.Integer(), nullable=False),
        sa.Column('date', sa.Integer(), nullable=False),
        sa.Column('home_team_tri_code', sa.String(), nullable=False),
        sa.Column('away_team_tri_code', sa.String(), nullable=False),
        sa.Column('home_moneyline', sa.Float(), nullable=True),
        sa.Column('away_moneyline', sa.Float(), nullable=True),
        sa.Column('home_prob_novig', sa.Float(), nullable=True),
        sa.Column('open_home_prob_novig', sa.Float(), nullable=True),
        sa.Column('total_line', sa.Float(), nullable=True),
        sa.Column('n_books', sa.Integer(), nullable=False),
        sa.Column('books', sa.String(), nullable=True),
        sa.Column('espn_event_id', sa.Integer(), nullable=True),
        sa.Column('last_updated', sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint('game_id')
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_table('game_odds')
    op.drop_table('team_game_stats')
