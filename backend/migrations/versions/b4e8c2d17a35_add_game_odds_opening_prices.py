"""add opening prices to game_odds

Revision ID: b4e8c2d17a35
Revises: a7d3e1f09b21
Create Date: 2026-10-06 21:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'b4e8c2d17a35'
down_revision: Union[str, Sequence[str], None] = 'a7d3e1f09b21'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column('game_odds', sa.Column('open_home_moneyline', sa.Float(), nullable=True))
    op.add_column('game_odds', sa.Column('open_away_moneyline', sa.Float(), nullable=True))
    op.add_column('game_odds', sa.Column('open_total_line', sa.Float(), nullable=True))


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_column('game_odds', 'open_total_line')
    op.drop_column('game_odds', 'open_away_moneyline')
    op.drop_column('game_odds', 'open_home_moneyline')
