"""add player_prop_odds (ESPN player prop markets)

Revision ID: d6b2e4f8a012
Revises: c5a1d3e7f901
Create Date: 2026-10-06 23:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'd6b2e4f8a012'
down_revision: Union[str, Sequence[str], None] = 'c5a1d3e7f901'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table(
        'player_prop_odds',
        sa.Column('game_id', sa.Integer(), nullable=False),
        sa.Column('player_id', sa.Integer(), nullable=False),
        sa.Column('prop_type', sa.String(), nullable=False),
        sa.Column('line', sa.Float(), nullable=False),
        sa.Column('book', sa.String(), nullable=False),
        sa.Column('espn_athlete_id', sa.Integer(), nullable=False),
        sa.Column('espn_event_id', sa.Integer(), nullable=True),
        sa.Column('over_price', sa.Float(), nullable=True),
        sa.Column('under_price', sa.Float(), nullable=True),
        sa.Column('open_line', sa.Float(), nullable=True),
        sa.Column('open_over_price', sa.Float(), nullable=True),
        sa.Column('open_under_price', sa.Float(), nullable=True),
        sa.Column('sides_inferred', sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column('espn_last_updated', sa.DateTime(timezone=True), nullable=True),
        sa.Column('last_updated', sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(['player_id'], ['players.id']),
        sa.PrimaryKeyConstraint('game_id', 'player_id', 'prop_type', 'line', 'book'),
    )
    op.create_index('ix_player_prop_odds_player_id', 'player_prop_odds', ['player_id'])
    op.create_index('ix_player_prop_odds_espn_athlete_id', 'player_prop_odds', ['espn_athlete_id'])


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index('ix_player_prop_odds_espn_athlete_id', table_name='player_prop_odds')
    op.drop_index('ix_player_prop_odds_player_id', table_name='player_prop_odds')
    op.drop_table('player_prop_odds')
