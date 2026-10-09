"""add odds price-path snapshots, prediction log and prediction scores

Revision ID: a1b2c3d4e5f6
Revises: f2b3c4d5e6a7
Create Date: 2026-10-06 23:45:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = 'a1b2c3d4e5f6'
down_revision: Union[str, Sequence[str], None] = 'f2b3c4d5e6a7'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

TZ = sa.DateTime(timezone=True)


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table(
        'game_odds_snapshots',
        sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
        sa.Column('game_id', sa.Integer(), nullable=False),
        sa.Column('captured_at', TZ, nullable=False),
        sa.Column('source', sa.String(), nullable=False),
        sa.Column('is_closing', sa.Boolean(), nullable=False),
        sa.Column('home_moneyline', sa.Float(), nullable=True),
        sa.Column('away_moneyline', sa.Float(), nullable=True),
        sa.Column('home_prob_novig', sa.Float(), nullable=True),
        sa.Column('total_line', sa.Float(), nullable=True),
        sa.Column('over_price', sa.Float(), nullable=True),
        sa.Column('under_price', sa.Float(), nullable=True),
        sa.Column('n_books', sa.Integer(), nullable=True),
        sa.Column('books', sa.String(), nullable=True),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('game_id', 'source', 'captured_at', name='uq_game_odds_snapshots'),
    )
    op.create_index('ix_game_odds_snapshots_game_id', 'game_odds_snapshots', ['game_id'])

    op.create_table(
        'player_prop_snapshots',
        sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
        sa.Column('game_id', sa.Integer(), nullable=False),
        sa.Column('player_id', sa.Integer(), nullable=False),
        sa.Column('prop_type', sa.String(), nullable=False),
        sa.Column('line', sa.Float(), nullable=False),
        sa.Column('book', sa.String(), nullable=False),
        sa.Column('captured_at', TZ, nullable=False),
        sa.Column('is_closing', sa.Boolean(), nullable=False),
        sa.Column('over_price', sa.Float(), nullable=True),
        sa.Column('under_price', sa.Float(), nullable=True),
        sa.Column('sides_inferred', sa.Boolean(), nullable=False),
        sa.Column('espn_last_updated', TZ, nullable=True),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('game_id', 'player_id', 'prop_type', 'line', 'book', 'captured_at', name='uq_player_prop_snapshots'),
    )
    op.create_index('ix_player_prop_snapshots_player_id', 'player_prop_snapshots', ['player_id'])
    op.create_index('ix_player_prop_snapshots_game_captured', 'player_prop_snapshots', ['game_id', 'captured_at'])

    op.create_table(
        'prediction_log',
        sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
        sa.Column('run_id', sa.String(), nullable=False),
        sa.Column('model_version', sa.String(), nullable=False),
        sa.Column('logged_at', TZ, nullable=False),
        sa.Column('game_id', sa.Integer(), nullable=False),
        sa.Column('game_date', sa.Integer(), nullable=False),
        sa.Column('start_time', TZ, nullable=False),
        sa.Column('home_team_tri_code', sa.String(), nullable=False),
        sa.Column('away_team_tri_code', sa.String(), nullable=False),
        sa.Column('home_win_prob', sa.Float(), nullable=False),
        sa.Column('market_captured_at', TZ, nullable=True),
        sa.Column('market_home_prob_novig', sa.Float(), nullable=True),
        sa.Column('market_home_moneyline', sa.Float(), nullable=True),
        sa.Column('market_away_moneyline', sa.Float(), nullable=True),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('game_id', 'model_version', 'run_id', name='uq_prediction_log'),
    )
    op.create_index('ix_prediction_log_run_id', 'prediction_log', ['run_id'])
    op.create_index('ix_prediction_log_game_id', 'prediction_log', ['game_id'])

    op.create_table(
        'player_prediction_log',
        sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
        sa.Column('run_id', sa.String(), nullable=False),
        sa.Column('model_version', sa.String(), nullable=False),
        sa.Column('logged_at', TZ, nullable=False),
        sa.Column('game_id', sa.Integer(), nullable=False),
        sa.Column('game_date', sa.Integer(), nullable=False),
        sa.Column('player_id', sa.Integer(), nullable=False),
        sa.Column('team_tri_code', sa.String(), nullable=False),
        sa.Column('role', sa.String(), nullable=False),
        sa.Column('stat', sa.String(), nullable=False),
        sa.Column('expected', sa.Float(), nullable=False),
        sa.Column('market_captured_at', TZ, nullable=True),
        sa.Column('market_line', sa.Float(), nullable=True),
        sa.Column('market_over_price', sa.Float(), nullable=True),
        sa.Column('market_under_price', sa.Float(), nullable=True),
        sa.Column('market_over_prob_novig', sa.Float(), nullable=True),
        sa.Column('market_n_books', sa.Integer(), nullable=True),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('game_id', 'player_id', 'stat', 'model_version', 'run_id', name='uq_player_prediction_log'),
    )
    op.create_index('ix_player_prediction_log_run_id', 'player_prediction_log', ['run_id'])
    op.create_index('ix_player_prediction_log_game_id', 'player_prediction_log', ['game_id'])

    op.create_table(
        'prediction_scores',
        sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
        sa.Column('kind', sa.String(), nullable=False),
        sa.Column('log_id', sa.Integer(), nullable=False),
        sa.Column('run_id', sa.String(), nullable=False),
        sa.Column('model_version', sa.String(), nullable=False),
        sa.Column('game_id', sa.Integer(), nullable=False),
        sa.Column('game_date', sa.Integer(), nullable=False),
        sa.Column('player_id', sa.Integer(), nullable=True),
        sa.Column('stat', sa.String(), nullable=False),
        sa.Column('status', sa.String(), nullable=False),
        sa.Column('scored_at', TZ, nullable=False),
        sa.Column('expected', sa.Float(), nullable=True),
        sa.Column('actual', sa.Float(), nullable=True),
        sa.Column('poisson_deviance', sa.Float(), nullable=True),
        sa.Column('line', sa.Float(), nullable=True),
        sa.Column('model_prob', sa.Float(), nullable=True),
        sa.Column('outcome', sa.Integer(), nullable=True),
        sa.Column('log_loss', sa.Float(), nullable=True),
        sa.Column('market_prob_logged', sa.Float(), nullable=True),
        sa.Column('market_prob_close', sa.Float(), nullable=True),
        sa.Column('market_log_loss_logged', sa.Float(), nullable=True),
        sa.Column('market_log_loss_close', sa.Float(), nullable=True),
        sa.Column('clv_prob', sa.Float(), nullable=True),
        sa.Column('bet_side', sa.String(), nullable=True),
        sa.Column('bet_edge', sa.Float(), nullable=True),
        sa.Column('bet_price_logged', sa.Float(), nullable=True),
        sa.Column('bet_price_close', sa.Float(), nullable=True),
        sa.Column('clv_price', sa.Float(), nullable=True),
        sa.Column('bet_profit', sa.Float(), nullable=True),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('kind', 'log_id', name='uq_prediction_scores'),
    )
    op.create_index('ix_prediction_scores_model_version', 'prediction_scores', ['model_version'])
    op.create_index('ix_prediction_scores_game_date', 'prediction_scores', ['game_date'])


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index('ix_prediction_scores_game_date', table_name='prediction_scores')
    op.drop_index('ix_prediction_scores_model_version', table_name='prediction_scores')
    op.drop_table('prediction_scores')
    op.drop_index('ix_player_prediction_log_game_id', table_name='player_prediction_log')
    op.drop_index('ix_player_prediction_log_run_id', table_name='player_prediction_log')
    op.drop_table('player_prediction_log')
    op.drop_index('ix_prediction_log_game_id', table_name='prediction_log')
    op.drop_index('ix_prediction_log_run_id', table_name='prediction_log')
    op.drop_table('prediction_log')
    op.drop_index('ix_player_prop_snapshots_game_captured', table_name='player_prop_snapshots')
    op.drop_index('ix_player_prop_snapshots_player_id', table_name='player_prop_snapshots')
    op.drop_table('player_prop_snapshots')
    op.drop_index('ix_game_odds_snapshots_game_id', table_name='game_odds_snapshots')
    op.drop_table('game_odds_snapshots')
