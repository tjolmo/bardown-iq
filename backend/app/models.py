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
    current_team: Mapped["Team"] = relationship("Team", back_populates="current_players")
    last_updated: Mapped[datetime.datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=datetime.datetime.now(datetime.timezone.utc), onupdate=datetime.datetime.now(datetime.timezone.utc))
    game_logs: Mapped[list["SkaterGameLog"]] = relationship("SkaterGameLog", back_populates="player")
    goalie_game_logs: Mapped[list["GoalieGameLog"]] = relationship("GoalieGameLog", back_populates="player")
    game_log_last_updated: Mapped[datetime.datetime] = mapped_column(DateTime(timezone=True), nullable=True)

class SkaterGameLog(Base):
    __tablename__ = "skater_game_logs"
    # composite primary key of game_id and player_id
    game_id: Mapped[int] = mapped_column(primary_key=True)
    player_id: Mapped[int] = mapped_column(ForeignKey("players.id"), primary_key=True)
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
