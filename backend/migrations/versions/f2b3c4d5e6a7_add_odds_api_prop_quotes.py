"""add odds_api_prop_quotes (every bookmaker's Odds API player prop quote)

Revision ID: f2b3c4d5e6a7
Revises: e1a2b3c4d5f6
Create Date: 2026-10-06 23:30:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'f2b3c4d5e6a7'
down_revision: Union[str, Sequence[str], None] = 'e1a2b3c4d5f6'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table(
        'odds_api_prop_quotes',
        sa.Column('game_id', sa.Integer(), nullable=False),
        sa.Column('player_id', sa.Integer(), nullable=False),
        sa.Column('prop_type', sa.String(), nullable=False),
        sa.Column('over_under', sa.String(), nullable=False),
        sa.Column('line', sa.Float(), nullable=False),
        sa.Column('bookmaker', sa.String(), nullable=False),
        sa.Column('odds', sa.Float(), nullable=False),
        sa.Column('first_odds', sa.Float(), nullable=False),
        sa.Column('first_seen', sa.DateTime(timezone=True), nullable=False),
        sa.Column('last_seen', sa.DateTime(timezone=True), nullable=False),
        sa.Column('book_last_update', sa.DateTime(timezone=True), nullable=True),
        sa.Column('event_id', sa.String(), nullable=True),
        sa.ForeignKeyConstraint(['player_id'], ['players.id']),
        sa.PrimaryKeyConstraint('game_id', 'player_id', 'prop_type', 'over_under', 'line', 'bookmaker'),
    )
    op.create_index('ix_odds_api_prop_quotes_player_id', 'odds_api_prop_quotes', ['player_id'])


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index('ix_odds_api_prop_quotes_player_id', table_name='odds_api_prop_quotes')
    op.drop_table('odds_api_prop_quotes')
