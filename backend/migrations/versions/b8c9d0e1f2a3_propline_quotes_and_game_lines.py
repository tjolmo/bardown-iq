"""PropLine replaces the Odds API: odds_api_prop_quotes -> prop_quotes (+ provider), props.book, game_line_quotes

Revision ID: b8c9d0e1f2a3
Revises: a7b8c9d0e1f2
Create Date: 2026-10-07 22:30:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'b8c9d0e1f2a3'
down_revision: Union[str, Sequence[str], None] = 'a7b8c9d0e1f2'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.rename_table('odds_api_prop_quotes', 'prop_quotes')
    op.execute('ALTER INDEX ix_odds_api_prop_quotes_player_id RENAME TO ix_prop_quotes_player_id')
    op.execute('ALTER TABLE prop_quotes RENAME CONSTRAINT odds_api_prop_quotes_pkey TO prop_quotes_pkey')
    # rows stored before this migration came from the Odds API
    op.add_column('prop_quotes', sa.Column('provider', sa.String(), nullable=False, server_default='odds_api'))
    op.add_column('props', sa.Column('book', sa.String(), nullable=True))
    op.create_table(
        'game_line_quotes',
        sa.Column('game_id', sa.Integer(), nullable=False),
        sa.Column('market', sa.String(), nullable=False),
        sa.Column('side', sa.String(), nullable=False),
        sa.Column('line', sa.Float(), nullable=False),
        sa.Column('bookmaker', sa.String(), nullable=False),
        sa.Column('odds', sa.Float(), nullable=False),
        sa.Column('first_odds', sa.Float(), nullable=False),
        sa.Column('first_seen', sa.DateTime(timezone=True), nullable=False),
        sa.Column('last_seen', sa.DateTime(timezone=True), nullable=False),
        sa.Column('book_last_update', sa.DateTime(timezone=True), nullable=True),
        sa.Column('event_id', sa.String(), nullable=True),
        sa.PrimaryKeyConstraint('game_id', 'market', 'side', 'line', 'bookmaker'),
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_table('game_line_quotes')
    op.drop_column('props', 'book')
    op.drop_column('prop_quotes', 'provider')
    op.execute('ALTER TABLE prop_quotes RENAME CONSTRAINT prop_quotes_pkey TO odds_api_prop_quotes_pkey')
    op.execute('ALTER INDEX ix_prop_quotes_player_id RENAME TO ix_odds_api_prop_quotes_player_id')
    op.rename_table('prop_quotes', 'odds_api_prop_quotes')
