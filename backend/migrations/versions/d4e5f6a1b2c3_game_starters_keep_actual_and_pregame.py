"""game_starters: key on (game_id, team, source) so the actual starter (NHL) and the pre-game pick (ESPN) coexist

Revision ID: d4e5f6a1b2c3
Revises: c3d4e5f6a1b2
Create Date: 2026-10-07 18:00:00.000000

"""
from typing import Sequence, Union

from alembic import op


# revision identifiers, used by Alembic.
revision: str = 'd4e5f6a1b2c3'
down_revision: Union[str, Sequence[str], None] = 'c3d4e5f6a1b2'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    # play-by-play rows written once a game had started are the actual starter
    op.execute("UPDATE game_starters SET source = 'nhl', status = 'actual' WHERE source = 'nhl_pbp'")
    op.drop_constraint('game_starters_pkey', 'game_starters', type_='primary')
    op.create_primary_key('game_starters_pkey', 'game_starters', ['game_id', 'team', 'source'])


def downgrade() -> None:
    """Downgrade schema."""
    # one row per (game, team) again: the actual starter wins
    op.execute("DELETE FROM game_starters s USING game_starters n "
               "WHERE s.source <> 'nhl' AND n.source = 'nhl' AND s.game_id = n.game_id AND s.team = n.team")
    op.execute("UPDATE game_starters SET source = 'nhl_pbp', status = 'confirmed' WHERE source = 'nhl'")
    op.drop_constraint('game_starters_pkey', 'game_starters', type_='primary')
    op.create_primary_key('game_starters_pkey', 'game_starters', ['game_id', 'team'])
