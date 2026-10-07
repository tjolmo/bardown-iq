"""add skater_game_shares (precomputed per-game deployment shares) and an index on skater_game_logs.player_id

Revision ID: f6a1b2c3d4e5
Revises: e5f6a1b2c3d4
Create Date: 2026-10-07 18:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'f6a1b2c3d4e5'
down_revision: Union[str, Sequence[str], None] = 'e5f6a1b2c3d4'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table(
        'skater_game_shares',
        sa.Column('player_id', sa.Integer(), nullable=False),
        sa.Column('game_id', sa.Integer(), nullable=False),
        sa.Column('pp_share', sa.Float(), nullable=True),
        sa.Column('toi_rank', sa.Float(), nullable=True),
        sa.Column('sog_share', sa.Float(), nullable=True),
        sa.Column('xg_share', sa.Float(), nullable=True),
        sa.Column('computed_at', sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint('player_id', 'game_id'),
    )
    op.create_index('ix_skater_game_shares_game_id', 'skater_game_shares', ['game_id'])
    # if_not_exists: on a busy DB the index may have been built beforehand with CREATE INDEX CONCURRENTLY
    op.create_index('ix_skater_game_logs_player_id', 'skater_game_logs', ['player_id'], if_not_exists=True)


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index('ix_skater_game_logs_player_id', table_name='skater_game_logs')
    op.drop_index('ix_skater_game_shares_game_id', table_name='skater_game_shares')
    op.drop_table('skater_game_shares')
