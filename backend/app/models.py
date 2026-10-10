from .database import Base
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy import ForeignKey, DateTime, ForeignKeyConstraint
import datetime

class Team(Base):
    __tablename__ = "teams"
    tri_code: Mapped[str] = mapped_column(primary_key=True)
    current_name: Mapped[str] = mapped_column(unique=True, nullable=False)
    franchise_id: Mapped[int] = mapped_column(nullable=False)
    current_players: Mapped[list["Player"]] = relationship("Player", back_populates="current_team")
    team_ids: Mapped[list[int]] = relationship("TeamHistory", back_populates="team")
    last_updated: Mapped[datetime.datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=datetime.datetime.now(datetime.timezone.utc), onupdate=datetime.datetime.now(datetime.timezone.utc))
    roster_last_updated: Mapped[datetime.datetime] = mapped_column(DateTime(timezone=True), nullable=True)

class TeamHistory(Base):
    __tablename__ = "team_history"
    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(nullable=False)
    tri_code: Mapped[str] = mapped_column(ForeignKey("teams.tri_code"), nullable=False)
    team: Mapped["Team"] = relationship("Team", back_populates="team_ids")
    last_updated: Mapped[datetime.datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=datetime.datetime.now(datetime.timezone.utc), onupdate=datetime.datetime.now(datetime.timezone.utc))

class Player(Base):
    __tablename__ = "players"

    id: Mapped[int] = mapped_column(primary_key=True)
    headshot: Mapped[str] = mapped_column(nullable=True)
    first_name: Mapped[str] = mapped_column(nullable=False)
    last_name: Mapped[str] = mapped_column(nullable=False)
    current_team_tri_code: Mapped[int] = mapped_column(ForeignKey("teams.tri_code"), nullable=True)
    number: Mapped[int] = mapped_column(nullable=True)
    position: Mapped[str] = mapped_column(nullable=True)
    shoots_catches: Mapped[str] = mapped_column(nullable=True)
    birth_date: Mapped[datetime.date] = mapped_column(nullable=True)
    current_team: Mapped["Team"] = relationship("Team", back_populates="current_players")
    last_updated: Mapped[datetime.datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=datetime.datetime.now(datetime.timezone.utc), onupdate=datetime.datetime.now(datetime.timezone.utc))
    game_logs: Mapped[list["SkaterGameLog"]] = relationship("SkaterGameLog", back_populates="player")
    goalie_game_logs: Mapped[list["GoalieGameLog"]] = relationship("GoalieGameLog", back_populates="player")
    game_log_last_updated: Mapped[datetime.datetime] = mapped_column(DateTime(timezone=True), nullable=True)

class SkaterGameLog(Base):
    __tablename__ = "skater_game_logs"
    # composite primary key of game_id and player_id
    game_id: Mapped[int] = mapped_column(primary_key=True)
    # indexed on its own too: live predictions load one player's history (the primary key only serves game_id lookups)
    player_id: Mapped[int] = mapped_column(ForeignKey("players.id"), primary_key=True, index=True)
    name: Mapped[str] = mapped_column(nullable=False)
    season: Mapped[int] = mapped_column(nullable=False)
    home_away: Mapped[str] = mapped_column(nullable=True)
    player_team_tricode: Mapped[str] = mapped_column(ForeignKey("teams.tri_code"), nullable=False)
    opposing_team_tricode: Mapped[str] = mapped_column(ForeignKey("teams.tri_code"), nullable=False)
    game_date: Mapped[int] = mapped_column(nullable=False)
    goals: Mapped[int] = mapped_column(nullable=False)
    primary_assists: Mapped[int] = mapped_column(nullable=False)
    secondary_assists: Mapped[int] = mapped_column(nullable=False)
    points: Mapped[int] = mapped_column(nullable=False)
    x_goals: Mapped[float] = mapped_column(nullable=False)
    toi: Mapped[float] = mapped_column(nullable=False)
    high_danger_shots: Mapped[int] = mapped_column(nullable=False)
    shot_attempts: Mapped[int] = mapped_column(nullable=False)
    on_ice_x_goals_percentage: Mapped[float] = mapped_column(nullable=False)
    game_score: Mapped[float] = mapped_column(nullable=False)
    shots_on_goal: Mapped[int | None] = mapped_column(nullable=True)
    pp_toi: Mapped[float | None] = mapped_column(nullable=True)  # 5on4 ice time, seconds
    pp_points: Mapped[int | None] = mapped_column(nullable=True)  # 5on4 points
    hits: Mapped[int | None] = mapped_column(nullable=True)
    blocked_shots: Mapped[int | None] = mapped_column(nullable=True)  # shots blocked by the player
    last_updated: Mapped[datetime.datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=datetime.datetime.now(datetime.timezone.utc), onupdate=datetime.datetime.now(datetime.timezone.utc))
    player: Mapped["Player"] = relationship("Player", back_populates="game_logs")

class GoalieGameLog(Base):
    __tablename__ = "goalie_game_logs"
    # composite primary key of game_id and player_id
    game_id: Mapped[int] = mapped_column(primary_key=True)
    player_id: Mapped[int] = mapped_column(ForeignKey("players.id"), primary_key=True)
    name: Mapped[str] = mapped_column(nullable=False)
    season: Mapped[int] = mapped_column(nullable=False)
    home_away: Mapped[str] = mapped_column(nullable=True)
    player_team_tricode: Mapped[str] = mapped_column(ForeignKey("teams.tri_code"), nullable=False)
    opposing_team_tricode: Mapped[str] = mapped_column(ForeignKey("teams.tri_code"), nullable=False)
    game_date: Mapped[int] = mapped_column(nullable=False)
    toi: Mapped[float] = mapped_column(nullable=False)
    x_goals_against: Mapped[float] = mapped_column(nullable=False)
    goals_against: Mapped[int] = mapped_column(nullable=False)
    unblocked_shot_attempts: Mapped[int] = mapped_column(nullable=False)
    x_rebounds: Mapped[float] = mapped_column(nullable=False)
    rebounds: Mapped[int] = mapped_column(nullable=False)
    x_freeze: Mapped[float] = mapped_column(nullable=False)
    freeze: Mapped[int] = mapped_column(nullable=False)
    x_sog: Mapped[float] = mapped_column(nullable=False)
    sog: Mapped[int] = mapped_column(nullable=False)
    x_play_stopped: Mapped[float] = mapped_column(nullable=False)
    play_stopped: Mapped[int] = mapped_column(nullable=False)
    x_play_continued_in_zone: Mapped[float] = mapped_column(nullable=False)
    x_play_continued_outside_zone: Mapped[float] = mapped_column(nullable=False)
    flurry_adjusted_x_goals: Mapped[float] = mapped_column(nullable=False)
    low_danger_shots: Mapped[int] = mapped_column(nullable=False)
    medium_danger_shots: Mapped[int] = mapped_column(nullable=False)
    high_danger_shots: Mapped[int] = mapped_column(nullable=False)
    low_danger_x_goals: Mapped[float] = mapped_column(nullable=False)
    medium_danger_x_goals: Mapped[float] = mapped_column(nullable=False)
    high_danger_x_goals: Mapped[float] = mapped_column(nullable=False)
    blocked_shot_attempts: Mapped[int] = mapped_column(nullable=False)
    penality_minutes: Mapped[int] = mapped_column(nullable=False)
    penalties: Mapped[int] = mapped_column(nullable=False)
    last_updated: Mapped[datetime.datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=datetime.datetime.now(datetime.timezone.utc), onupdate=datetime.datetime.now(datetime.timezone.utc))
    player: Mapped["Player"] = relationship("Player", back_populates="goalie_game_logs")

class Games(Base):
    __tablename__ = "games"
    id: Mapped[int] = mapped_column(primary_key=True)
    home_team_tri_code: Mapped[str] = mapped_column(ForeignKey("teams.tri_code"), nullable=False)
    away_team_tri_code: Mapped[str] = mapped_column(ForeignKey("teams.tri_code"), nullable=False)
    season: Mapped[int] = mapped_column(nullable=False)
    date: Mapped[int] = mapped_column(nullable=False)
    venue: Mapped[str] = mapped_column(nullable=False)
    start_time: Mapped[datetime.datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    home_team_logo: Mapped[str] = mapped_column(nullable=True)
    away_team_logo: Mapped[str] = mapped_column(nullable=True)
    home_score: Mapped[int] = mapped_column(nullable=True)
    away_score: Mapped[int] = mapped_column(nullable=True)
    game_state: Mapped[str] = mapped_column(nullable=False)
    last_updated: Mapped[datetime.datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=datetime.datetime.now(datetime.timezone.utc), onupdate=datetime.datetime.now(datetime.timezone.utc))

class SkaterGameFeatures(Base):
    __tablename__ = "skater_game_features"
    game_id: Mapped[int] = mapped_column(primary_key=True)
    player_id: Mapped[int] = mapped_column(primary_key=True)
    rolling_x_goals: Mapped[float] = mapped_column(nullable=False)
    rolling_toi: Mapped[float] = mapped_column(nullable=False)
    rolling_game_score: Mapped[float] = mapped_column(nullable=False)
    rolling_shot_attempts: Mapped[float] = mapped_column(nullable=False)
    rolling_high_danger_shots: Mapped[float] = mapped_column(nullable=False)
    rolling_on_ice_x_goals_percentage: Mapped[float] = mapped_column(nullable=False)
    rolling_primary_assists: Mapped[float] = mapped_column(nullable=False)
    rolling_goals: Mapped[float] = mapped_column(nullable=False)
    rolling_points: Mapped[float] = mapped_column(nullable=False)
    last_updated: Mapped[datetime.datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=datetime.datetime.now(datetime.timezone.utc), onupdate=datetime.datetime.now(datetime.timezone.utc))
    ForeignKeyConstraint(["game_id", "player_id"], ["skater_game_logs.game_id", "skater_game_logs.player_id"]),

class GoalieGameFeatures(Base):
    __tablename__ = "goalie_game_features"
    game_id: Mapped[int] = mapped_column(primary_key=True)
    player_id: Mapped[int] = mapped_column(primary_key=True)
    rolling_x_goals_against: Mapped[float] = mapped_column(nullable=False)
    rolling_goals_against: Mapped[float] = mapped_column(nullable=False)
    rolling_sog: Mapped[float] = mapped_column(nullable=False)
    rolling_flurry_adjusted_x_goals: Mapped[float] = mapped_column(nullable=False)
    rolling_high_danger_x_goals: Mapped[float] = mapped_column(nullable=False)
    rolling_x_sog: Mapped[float] = mapped_column(nullable=False)
    rolling_high_danger_shots: Mapped[float] = mapped_column(nullable=False)
    rolling_rebounds: Mapped[float] = mapped_column(nullable=False)
    rolling_x_rebounds: Mapped[float] = mapped_column(nullable=False)
    rolling_freeze: Mapped[float] = mapped_column(nullable=False)
    rolling_x_freeze: Mapped[float] = mapped_column(nullable=False)
    last_updated: Mapped[datetime.datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=datetime.datetime.now(datetime.timezone.utc), onupdate=datetime.datetime.now(datetime.timezone.utc))
    ForeignKeyConstraint(["game_id", "player_id"], ["goalie_game_logs.game_id", "goalie_game_logs.player_id"]),

class TeamGameLog(Base):
    __tablename__ = "team_game_logs"
    game_id: Mapped[int] = mapped_column(primary_key=True)
    team_tri_code: Mapped[str] = mapped_column(ForeignKey("teams.tri_code"), primary_key=True)
    opposing_team_tri_code: Mapped[str] = mapped_column(ForeignKey("teams.tri_code"), nullable=False)
    season: Mapped[int] = mapped_column(nullable=False)
    game_date: Mapped[int] = mapped_column(nullable=False)
    home_away: Mapped[str] = mapped_column(nullable=False)
    goals: Mapped[int] = mapped_column(nullable=False)
    x_goals: Mapped[float] = mapped_column(nullable=False)
    shot_attempts: Mapped[int] = mapped_column(nullable=False)
    high_danger_shots: Mapped[int] = mapped_column(nullable=False)
    points: Mapped[int] = mapped_column(nullable=False)
    primary_assists: Mapped[int] = mapped_column(nullable=False)
    avg_on_ice_x_goals_percentage: Mapped[float] = mapped_column(nullable=False)
    avg_game_score: Mapped[float] = mapped_column(nullable=False)
    goals_against: Mapped[int] = mapped_column(nullable=False)
    x_goals_against: Mapped[float] = mapped_column(nullable=False)
    sog_against: Mapped[int] = mapped_column(nullable=False)
    high_danger_shots_against: Mapped[int] = mapped_column(nullable=False)
    high_danger_x_goals_against: Mapped[float] = mapped_column(nullable=False)
    flurry_adjusted_x_goals_against: Mapped[float] = mapped_column(nullable=False)
    last_updated: Mapped[datetime.datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=datetime.datetime.now(datetime.timezone.utc), onupdate=datetime.datetime.now(datetime.timezone.utc))

class TeamGameFeatures(Base):
    __tablename__ = "team_game_features"
    game_id: Mapped[int] = mapped_column(primary_key=True)
    team_tri_code: Mapped[str] = mapped_column(primary_key=True)
    rolling_goals_5g: Mapped[float | None] = mapped_column(nullable=True)
    rolling_x_goals_5g: Mapped[float | None] = mapped_column(nullable=True)
    rolling_shot_attempts_5g: Mapped[float | None] = mapped_column(nullable=True)
    rolling_high_danger_shots_5g: Mapped[float | None] = mapped_column(nullable=True)
    rolling_points_5g: Mapped[float | None] = mapped_column(nullable=True)
    rolling_primary_assists_5g: Mapped[float | None] = mapped_column(nullable=True)
    rolling_avg_on_ice_x_goals_percentage_5g: Mapped[float | None] = mapped_column(nullable=True)
    rolling_avg_game_score_5g: Mapped[float | None] = mapped_column(nullable=True)
    rolling_goals_against_5g: Mapped[float | None] = mapped_column(nullable=True)
    rolling_x_goals_against_5g: Mapped[float | None] = mapped_column(nullable=True)
    rolling_sog_against_5g: Mapped[float | None] = mapped_column(nullable=True)
    rolling_high_danger_shots_against_5g: Mapped[float | None] = mapped_column(nullable=True)
    rolling_high_danger_x_goals_against_5g: Mapped[float | None] = mapped_column(nullable=True)
    rolling_flurry_adjusted_x_goals_against_5g: Mapped[float | None] = mapped_column(nullable=True)
    last_updated: Mapped[datetime.datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=datetime.datetime.now(datetime.timezone.utc), onupdate=datetime.datetime.now(datetime.timezone.utc))
    ForeignKeyConstraint(["game_id", "team_tri_code"], ["team_game_logs.game_id", "team_game_logs.team_tri_code"]),

class Props(Base):
    __tablename__ = "props"
    game_id: Mapped[int] = mapped_column(primary_key=True)
    player_id: Mapped[int] = mapped_column(primary_key=True)
    prop_type: Mapped[str] = mapped_column(primary_key=True)
    over_under: Mapped[str] = mapped_column(primary_key=True)
    odds: Mapped[float] = mapped_column(nullable=False)
    line: Mapped[float] = mapped_column(nullable=False)
    book: Mapped[str | None] = mapped_column(nullable=True)    # the book with the best price (PropLine key)

class TeamGameStats(Base):
    """One team's totals for one game from MoneyPuck, split by situation (all / 5v5 / power play / penalty kill)."""
    __tablename__ = "team_game_stats"
    game_id: Mapped[int] = mapped_column(primary_key=True)
    team_tri_code: Mapped[str] = mapped_column(primary_key=True)
    opposing_team_tri_code: Mapped[str] = mapped_column(nullable=False)
    season: Mapped[int] = mapped_column(nullable=False)
    game_date: Mapped[int] = mapped_column(nullable=False)
    home_away: Mapped[str] = mapped_column(nullable=False)
    playoff: Mapped[bool] = mapped_column(nullable=False)
    goals_for: Mapped[int] = mapped_column(nullable=False)
    goals_against: Mapped[int] = mapped_column(nullable=False)
    x_goals_for: Mapped[float] = mapped_column(nullable=False)
    x_goals_against: Mapped[float] = mapped_column(nullable=False)
    shot_attempts_for: Mapped[int] = mapped_column(nullable=False)
    shot_attempts_against: Mapped[int] = mapped_column(nullable=False)
    # 5 on 5, score- and venue-adjusted
    x_goals_for_5v5: Mapped[float | None] = mapped_column(nullable=True)
    x_goals_against_5v5: Mapped[float | None] = mapped_column(nullable=True)
    shot_attempts_for_5v5: Mapped[float | None] = mapped_column(nullable=True)
    shot_attempts_against_5v5: Mapped[float | None] = mapped_column(nullable=True)
    goals_for_5v5: Mapped[int | None] = mapped_column(nullable=True)
    goals_against_5v5: Mapped[int | None] = mapped_column(nullable=True)
    pp_x_goals_for: Mapped[float | None] = mapped_column(nullable=True)
    pp_toi: Mapped[float | None] = mapped_column(nullable=True)
    pk_x_goals_against: Mapped[float | None] = mapped_column(nullable=True)
    pk_toi: Mapped[float | None] = mapped_column(nullable=True)
    last_updated: Mapped[datetime.datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=datetime.datetime.now(datetime.timezone.utc), onupdate=datetime.datetime.now(datetime.timezone.utc))

class GameOdds(Base):
    """Closing moneyline/total consensus for a game (median across books, vig removed), from ESPN."""
    __tablename__ = "game_odds"
    game_id: Mapped[int] = mapped_column(primary_key=True)
    date: Mapped[int] = mapped_column(nullable=False)
    home_team_tri_code: Mapped[str] = mapped_column(nullable=False)
    away_team_tri_code: Mapped[str] = mapped_column(nullable=False)
    home_moneyline: Mapped[float | None] = mapped_column(nullable=True)
    away_moneyline: Mapped[float | None] = mapped_column(nullable=True)
    home_prob_novig: Mapped[float | None] = mapped_column(nullable=True)
    open_home_prob_novig: Mapped[float | None] = mapped_column(nullable=True)
    open_home_moneyline: Mapped[float | None] = mapped_column(nullable=True)
    open_away_moneyline: Mapped[float | None] = mapped_column(nullable=True)
    total_line: Mapped[float | None] = mapped_column(nullable=True)
    open_total_line: Mapped[float | None] = mapped_column(nullable=True)
    n_books: Mapped[int] = mapped_column(nullable=False, default=0)
    books: Mapped[str | None] = mapped_column(nullable=True)
    espn_event_id: Mapped[int | None] = mapped_column(nullable=True)
    last_updated: Mapped[datetime.datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=datetime.datetime.now(datetime.timezone.utc), onupdate=datetime.datetime.now(datetime.timezone.utc))

class PlayerPropOdds(Base):
    """One player prop market (one book, one line) for a game, from ESPN's core API (Feb 2024 onward).

    over_price / under_price are American odds of the latest pre-game snapshot (frozen at puck drop for finished
    games); one-sided markets (anytime/first goal, "N+" milestones) only have over_price. open_* is the book's
    opening market, which can be a different line than `line` (open_line); `sides_inferred` marks DraftKings rows,
    whose over/under labels are inferred from row order (see external/espn/props.py)."""
    __tablename__ = "player_prop_odds"
    game_id: Mapped[int] = mapped_column(primary_key=True)
    player_id: Mapped[int] = mapped_column(ForeignKey("players.id"), primary_key=True, index=True)
    prop_type: Mapped[str] = mapped_column(primary_key=True)
    line: Mapped[float] = mapped_column(primary_key=True)
    book: Mapped[str] = mapped_column(primary_key=True)
    espn_athlete_id: Mapped[int] = mapped_column(nullable=False, index=True)
    espn_event_id: Mapped[int | None] = mapped_column(nullable=True)
    over_price: Mapped[float | None] = mapped_column(nullable=True)
    under_price: Mapped[float | None] = mapped_column(nullable=True)
    open_line: Mapped[float | None] = mapped_column(nullable=True)
    open_over_price: Mapped[float | None] = mapped_column(nullable=True)
    open_under_price: Mapped[float | None] = mapped_column(nullable=True)
    sides_inferred: Mapped[bool] = mapped_column(nullable=False, default=False)
    espn_last_updated: Mapped[datetime.datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_updated: Mapped[datetime.datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=datetime.datetime.now(datetime.timezone.utc), onupdate=datetime.datetime.now(datetime.timezone.utc))

class PropQuote(Base):
    """Every player prop quote a multi-book feed returns: one bookmaker, one side, one line (fetched going forward).
    PropLine since Oct 2026; earlier rows came from the Odds API (`provider`).

    `props` keeps only the consensus-line best price; this table keeps each book's price so line shopping and
    consensus fair probabilities can be backtested later. Each run overwrites `odds`/`last_seen`/`book_last_update`;
    `first_odds`/`first_seen` keep the price from the first fetch that saw this quote (an opening-ish price)."""
    __tablename__ = "prop_quotes"
    game_id: Mapped[int] = mapped_column(primary_key=True)
    player_id: Mapped[int] = mapped_column(ForeignKey("players.id"), primary_key=True, index=True)
    prop_type: Mapped[str] = mapped_column(primary_key=True)      # app market key (Odds API style), e.g. player_points
    over_under: Mapped[str] = mapped_column(primary_key=True)     # "Over" / "Under" (or "Yes" for one-sided markets)
    line: Mapped[float] = mapped_column(primary_key=True)
    bookmaker: Mapped[str] = mapped_column(primary_key=True)      # bookmaker key, e.g. draftkings
    odds: Mapped[float] = mapped_column(nullable=False)           # American odds at the latest fetch
    first_odds: Mapped[float] = mapped_column(nullable=False)
    first_seen: Mapped[datetime.datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    last_seen: Mapped[datetime.datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    book_last_update: Mapped[datetime.datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    event_id: Mapped[str | None] = mapped_column(nullable=True)
    provider: Mapped[str] = mapped_column(nullable=False, default="propline", server_default="odds_api")

class GameLineQuote(Base):
    """Every book's main game line from PropLine: moneyline (h2h), puck line (spreads) and total, one side each.
    Upserted like prop_quotes (latest price plus the first one seen). The site's live moneyline is the median of the
    consensus books here; game_odds (ESPN) stays the closing-line history the models and backtests use."""
    __tablename__ = "game_line_quotes"
    game_id: Mapped[int] = mapped_column(primary_key=True)
    market: Mapped[str] = mapped_column(primary_key=True)         # "h2h" / "spreads" / "totals"
    side: Mapped[str] = mapped_column(primary_key=True)           # "home" / "away" / "over" / "under"
    line: Mapped[float] = mapped_column(primary_key=True)         # spread for the side, the total, 0 for h2h
    bookmaker: Mapped[str] = mapped_column(primary_key=True)
    odds: Mapped[float] = mapped_column(nullable=False)
    first_odds: Mapped[float] = mapped_column(nullable=False)
    first_seen: Mapped[datetime.datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    last_seen: Mapped[datetime.datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    book_last_update: Mapped[datetime.datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    event_id: Mapped[str | None] = mapped_column(nullable=True)

# ---------- price path, prediction log and forward scoring (see predictions/prediction_log.py) ----------
from sqlalchemy import Index, UniqueConstraint  # noqa: E402

class GameOddsSnapshot(Base):
    """Append-only game price path: one row per game per ESPN fetch, never overwritten.

    Rows are only written before puck drop (captured_at < games.start_time), except one `is_closing` row per game
    written by the first fetch after the game is final, holding ESPN's price frozen at puck drop (the close)."""
    __tablename__ = "game_odds_snapshots"
    __table_args__ = (UniqueConstraint("game_id", "source", "captured_at", name="uq_game_odds_snapshots"),)
    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    game_id: Mapped[int] = mapped_column(nullable=False, index=True)
    captured_at: Mapped[datetime.datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    source: Mapped[str] = mapped_column(nullable=False)            # "espn" (median consensus across books)
    is_closing: Mapped[bool] = mapped_column(nullable=False, default=False)
    home_moneyline: Mapped[float | None] = mapped_column(nullable=True)
    away_moneyline: Mapped[float | None] = mapped_column(nullable=True)
    home_prob_novig: Mapped[float | None] = mapped_column(nullable=True)
    total_line: Mapped[float | None] = mapped_column(nullable=True)
    over_price: Mapped[float | None] = mapped_column(nullable=True)
    under_price: Mapped[float | None] = mapped_column(nullable=True)
    n_books: Mapped[int | None] = mapped_column(nullable=True)
    books: Mapped[str | None] = mapped_column(nullable=True)

class PlayerPropSnapshot(Base):
    """Append-only player prop price path (one book, one line per row), same pre-game / closing rules as above."""
    __tablename__ = "player_prop_snapshots"
    __table_args__ = (
        UniqueConstraint("game_id", "player_id", "prop_type", "line", "book", "captured_at", name="uq_player_prop_snapshots"),
        Index("ix_player_prop_snapshots_game_captured", "game_id", "captured_at"),
    )
    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    game_id: Mapped[int] = mapped_column(nullable=False)
    player_id: Mapped[int] = mapped_column(nullable=False, index=True)
    prop_type: Mapped[str] = mapped_column(nullable=False)
    line: Mapped[float] = mapped_column(nullable=False)
    book: Mapped[str] = mapped_column(nullable=False)
    captured_at: Mapped[datetime.datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    is_closing: Mapped[bool] = mapped_column(nullable=False, default=False)
    over_price: Mapped[float | None] = mapped_column(nullable=True)
    under_price: Mapped[float | None] = mapped_column(nullable=True)
    sides_inferred: Mapped[bool] = mapped_column(nullable=False, default=False)
    espn_last_updated: Mapped[datetime.datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

class PredictionLog(Base):
    """Frozen pre-game team win probability plus the market price at that moment. Insert-only."""
    __tablename__ = "prediction_log"
    __table_args__ = (UniqueConstraint("game_id", "model_version", "run_id", name="uq_prediction_log"),)
    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    run_id: Mapped[str] = mapped_column(nullable=False, index=True)
    model_version: Mapped[str] = mapped_column(nullable=False)
    logged_at: Mapped[datetime.datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    game_id: Mapped[int] = mapped_column(nullable=False, index=True)
    game_date: Mapped[int] = mapped_column(nullable=False)
    start_time: Mapped[datetime.datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    home_team_tri_code: Mapped[str] = mapped_column(nullable=False)
    away_team_tri_code: Mapped[str] = mapped_column(nullable=False)
    home_win_prob: Mapped[float] = mapped_column(nullable=False)
    market_captured_at: Mapped[datetime.datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    market_home_prob_novig: Mapped[float | None] = mapped_column(nullable=True)
    market_home_moneyline: Mapped[float | None] = mapped_column(nullable=True)
    market_away_moneyline: Mapped[float | None] = mapped_column(nullable=True)

class PlayerPredictionLog(Base):
    """Frozen pre-game expected count for one player and stat, plus the market's main line at that moment. Insert-only."""
    __tablename__ = "player_prediction_log"
    __table_args__ = (
        UniqueConstraint("game_id", "player_id", "stat", "model_version", "run_id", name="uq_player_prediction_log"),
    )
    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    run_id: Mapped[str] = mapped_column(nullable=False, index=True)
    model_version: Mapped[str] = mapped_column(nullable=False)
    logged_at: Mapped[datetime.datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    game_id: Mapped[int] = mapped_column(nullable=False, index=True)
    game_date: Mapped[int] = mapped_column(nullable=False)
    player_id: Mapped[int] = mapped_column(nullable=False)
    team_tri_code: Mapped[str] = mapped_column(nullable=False)
    role: Mapped[str] = mapped_column(nullable=False)              # "skater" / "goalie"
    stat: Mapped[str] = mapped_column(nullable=False)              # model target, e.g. shots_on_goal, saves
    expected: Mapped[float] = mapped_column(nullable=False)
    market_captured_at: Mapped[datetime.datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    market_line: Mapped[float | None] = mapped_column(nullable=True)
    market_over_price: Mapped[float | None] = mapped_column(nullable=True)
    market_under_price: Mapped[float | None] = mapped_column(nullable=True)
    market_over_prob_novig: Mapped[float | None] = mapped_column(nullable=True)
    market_n_books: Mapped[int | None] = mapped_column(nullable=True)
    # "espn" (player_prop_snapshots), or "propline" / "odds_api" (prop_quotes consensus of that provider's rows, the
    # fallback when ESPN has no two-sided line); NULL when neither had one. The scorer reads the closing line from the same feed.
    market_source: Mapped[str | None] = mapped_column(nullable=True)

class PredictionScore(Base):
    """Realized score of one logged prediction (kind "team" -> prediction_log.id, "player" -> player_prediction_log.id),
    against results and the closing snapshot. Written once by the nightly scorer."""
    __tablename__ = "prediction_scores"
    __table_args__ = (UniqueConstraint("kind", "log_id", name="uq_prediction_scores"),)
    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    kind: Mapped[str] = mapped_column(nullable=False)
    log_id: Mapped[int] = mapped_column(nullable=False)
    run_id: Mapped[str] = mapped_column(nullable=False)
    model_version: Mapped[str] = mapped_column(nullable=False, index=True)
    game_id: Mapped[int] = mapped_column(nullable=False)
    game_date: Mapped[int] = mapped_column(nullable=False, index=True)
    player_id: Mapped[int | None] = mapped_column(nullable=True)
    stat: Mapped[str] = mapped_column(nullable=False)              # "home_win" for team rows
    status: Mapped[str] = mapped_column(nullable=False)            # scored / push / no_line / dnp
    scored_at: Mapped[datetime.datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    expected: Mapped[float | None] = mapped_column(nullable=True)  # player expected count
    actual: Mapped[float | None] = mapped_column(nullable=True)    # player count, or 1/0 home win
    poisson_deviance: Mapped[float | None] = mapped_column(nullable=True)
    line: Mapped[float | None] = mapped_column(nullable=True)
    model_prob: Mapped[float | None] = mapped_column(nullable=True)  # P(home win) / P(over line)
    outcome: Mapped[int | None] = mapped_column(nullable=True)       # 1 home win / over hit, 0 otherwise
    log_loss: Mapped[float | None] = mapped_column(nullable=True)
    market_prob_logged: Mapped[float | None] = mapped_column(nullable=True)  # vig-free, same event, at log time
    market_prob_close: Mapped[float | None] = mapped_column(nullable=True)
    market_log_loss_logged: Mapped[float | None] = mapped_column(nullable=True)
    market_log_loss_close: Mapped[float | None] = mapped_column(nullable=True)
    clv_prob: Mapped[float | None] = mapped_column(nullable=True)    # close - logged vig-free prob, signed toward the model's side
    bet_side: Mapped[str | None] = mapped_column(nullable=True)      # home/away/over/under when edge >= threshold
    bet_edge: Mapped[float | None] = mapped_column(nullable=True)
    bet_price_logged: Mapped[float | None] = mapped_column(nullable=True)  # American
    bet_price_close: Mapped[float | None] = mapped_column(nullable=True)
    clv_price: Mapped[float | None] = mapped_column(nullable=True)   # decimal(logged) / decimal(close) - 1
    bet_profit: Mapped[float | None] = mapped_column(nullable=True)  # 1-unit flat stake at the logged price

class GameStarter(Base):
    """Each team's starting goalie for a game, one row per (game, team, source) so the pre-game pick and the
    actual starter are both kept: source "espn" rows are "confirmed" (announced) or "probable" (ESPN's expected
    starter) and the latest fetch wins; source "nhl" rows are "actual" (who started: the goalie in net for the first
    shot the team faced, from the NHL play-by-play, with the boxscore's starter flag as fallback), back to 2008.
    No FK on player_id: a same-day call-up may not be in players yet."""
    __tablename__ = "game_starters"
    game_id: Mapped[int] = mapped_column(primary_key=True)
    team: Mapped[str] = mapped_column(primary_key=True)
    source: Mapped[str] = mapped_column(primary_key=True)
    player_id: Mapped[int] = mapped_column(nullable=False)
    status: Mapped[str] = mapped_column(nullable=False)
    fetched_at: Mapped[datetime.datetime] = mapped_column(DateTime(timezone=True), nullable=False)

class PlayerInjury(Base):
    """ESPN's league-wide injury report, one snapshot per fetch (append-only): every listed player with the fetch
    time, so the report known before any game can be rebuilt later (ESPN keeps no history). status is normalized
    (external.espn.injuries.normalize_status): out / ir / ltir / suspended keep a player out of expected lineups,
    day_to_day doesn't. No FK on player_id (None when the ESPN athlete isn't matched, e.g. minor leaguers)."""
    __tablename__ = "player_injuries"
    __table_args__ = (UniqueConstraint("fetched_at", "espn_athlete_id", name="uq_player_injuries"),)
    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    fetched_at: Mapped[datetime.datetime] = mapped_column(DateTime(timezone=True), nullable=False, index=True)
    espn_athlete_id: Mapped[int] = mapped_column(nullable=False)
    player_id: Mapped[int | None] = mapped_column(nullable=True, index=True)
    team: Mapped[str | None] = mapped_column(nullable=True)
    full_name: Mapped[str | None] = mapped_column(nullable=True)
    position: Mapped[str | None] = mapped_column(nullable=True)
    status: Mapped[str] = mapped_column(nullable=False)
    espn_status: Mapped[str | None] = mapped_column(nullable=True)
    fantasy_status: Mapped[str | None] = mapped_column(nullable=True)
    injury_type: Mapped[str | None] = mapped_column(nullable=True)
    roster_status: Mapped[str | None] = mapped_column(nullable=True)
    report_date: Mapped[datetime.datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    return_date: Mapped[datetime.date | None] = mapped_column(nullable=True)
    espn_injury_id: Mapped[int | None] = mapped_column(nullable=True)
    comment: Mapped[str | None] = mapped_column(nullable=True)


class SkaterGameShare(Base):
    """Each skater's deployment shares in a game, as `predictions.features.skater_shares` computes them from every
    skater's log of that game: PP time share, ice-time rank among his team's forwards or defensemen, shot and xG
    shares. Rebuilt nightly after the log scrape (predictions/shares.py), so a live prediction reads the player's own
    rows instead of every teammate's log of every past game. Per-game values only; the pre-game summaries are
    still built at serve time. No FK: rows mirror skater_game_logs and are replaced with it."""
    __tablename__ = "skater_game_shares"
    # player first: the live lookup is by player; the refresh replaces whole games through the game_id index
    player_id: Mapped[int] = mapped_column(primary_key=True)
    game_id: Mapped[int] = mapped_column(primary_key=True, index=True)
    pp_share: Mapped[float | None] = mapped_column(nullable=True)
    toi_rank: Mapped[float | None] = mapped_column(nullable=True)
    sog_share: Mapped[float | None] = mapped_column(nullable=True)
    xg_share: Mapped[float | None] = mapped_column(nullable=True)
    computed_at: Mapped[datetime.datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class GameLineup(Base):
    """Who dressed for each team in a game and who it scratched (NHL play-by-play rosterSpots and right-rail
    scratches), with each dressed player's ice time by strength once the shift chart is in (app/deployment.py).
    Stored when lineups are posted before puck drop and again, with ice time, once the game is over. The NHL scratch
    list includes injured players; a healthy scratch is one the injury report doesn't list. Names and numbers are
    kept here because a same-day call-up may not be in players yet (no FK on player_id)."""
    __tablename__ = "game_lineups"
    __table_args__ = (Index("ix_game_lineups_team_game", "team", "game_id"),)
    game_id: Mapped[int] = mapped_column(primary_key=True)
    team: Mapped[str] = mapped_column(primary_key=True)
    player_id: Mapped[int] = mapped_column(primary_key=True)
    status: Mapped[str] = mapped_column(nullable=False)            # "dressed" / "scratched"
    position: Mapped[str | None] = mapped_column(nullable=True)    # C / L / R / D / G (dressed players)
    sweater_number: Mapped[int | None] = mapped_column(nullable=True)
    first_name: Mapped[str | None] = mapped_column(nullable=True)
    last_name: Mapped[str | None] = mapped_column(nullable=True)
    # seconds; NULL until the shift chart is in (ev = 5 on 5, pp / pk = power play / penalty kill)
    toi: Mapped[int | None] = mapped_column(nullable=True)
    toi_ev: Mapped[int | None] = mapped_column(nullable=True)
    toi_pp: Mapped[int | None] = mapped_column(nullable=True)
    toi_pk: Mapped[int | None] = mapped_column(nullable=True)
    faceoffs: Mapped[int | None] = mapped_column(nullable=True)    # taken, won or lost
    fetched_at: Mapped[datetime.datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class GameUnit(Base):
    """Seconds each group of teammates spent on the ice together in a game, from the shift chart: forward trios
    (ev_f) and defense pairs (ev_d) at 5 on 5, power-play (pp) and penalty-kill (pk) groups. `unit` is the sorted
    player ids joined with "-". Line projections (app/line_projection.py) are built from these."""
    __tablename__ = "game_units"
    __table_args__ = (Index("ix_game_units_team_game", "team", "game_id"),)
    game_id: Mapped[int] = mapped_column(primary_key=True)
    team: Mapped[str] = mapped_column(primary_key=True)
    situation: Mapped[str] = mapped_column(primary_key=True)
    unit: Mapped[str] = mapped_column(primary_key=True)
    seconds: Mapped[int] = mapped_column(nullable=False)
