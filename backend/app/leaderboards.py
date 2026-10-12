"""The top skaters and top goalies boards: every rostered player's season totals, ranked on the stat asked for.

Totals are summed in the database and the rates (points a game, save percentage, GAA, goals saved above expected)
are worked out here, so the ranking is one pass over a few hundred rows whatever the sort."""
import datetime
from dataclasses import dataclass, field

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import GoalieGameLog, Player, SkaterGameLog

SKATER_SORTS = ("points", "goals", "assists", "points_per_game", "x_goals", "pp_points")
GOALIE_SORTS = ("gsax", "save_percentage", "gaa", "shots_faced")
# forwards and defence, as the position filter groups them
POSITION_GROUPS = {"F": ("C", "L", "R"), "D": ("D",)}
# the goalies board's games-played floor while the season is young; the UI can lift or lower it
DEFAULT_GOALIE_MIN_GAMES = 2


@dataclass
class TopSkater:
    player: Player
    games: int
    goals: int
    assists: int
    points: int
    x_goals: float
    shots_on_goal: int
    toi_per_game: float       # minutes
    pp_points: int
    points_by_game: list[int] = field(default_factory=list)

    @property
    def points_per_game(self) -> float:
        return self.points / self.games if self.games else 0.0


@dataclass
class TopGoalie:
    player: Player
    games: int
    shots_faced: int
    goals_against: int
    x_goals_against: float
    toi: float                # seconds
    high_danger_shots: int

    @property
    def save_percentage(self) -> float | None:
        return 1 - self.goals_against / self.shots_faced if self.shots_faced else None

    @property
    def gaa(self) -> float | None:
        return self.goals_against * 3600 / self.toi if self.toi else None

    @property
    def gsax(self) -> float:
        return self.x_goals_against - self.goals_against


def season_through(game_date: int | None) -> datetime.date | None:
    """The calendar day of the latest log, from MoneyPuck's YYYYMMDD."""
    if game_date is None:
        return None
    return datetime.date(game_date // 10000, game_date // 100 % 100, game_date % 100)


async def latest_game_date(db: AsyncSession, season: int) -> int | None:
    return (await db.execute(select(func.max(SkaterGameLog.game_date)).where(SkaterGameLog.season == season))).scalar()


def _skater_sort_key(sort: str):
    # ties go to the player with more points, then more goals, then the fewer games it took
    return lambda s: (-getattr(s, sort), -s.points, -s.goals, s.games)


def _goalie_sort_key(sort: str):
    # a rate that can't be worked out (no shots, no ice time) ranks last; GAA is the one where lower is better
    def key(g: TopGoalie):
        value = getattr(g, sort)
        missing = value is None
        if sort == "gaa":
            return (missing, value if not missing else 0.0, -g.gsax)
        return (missing, -(value if not missing else 0.0), -g.gsax, -g.shots_faced)
    return key


async def top_skaters(db: AsyncSession, season: int, n: int, sort: str = "points", position: str = "all") -> list[TopSkater]:
    """The n rostered skaters with the most of `sort` this season, forwards or defence only when asked."""
    if sort not in SKATER_SORTS:
        raise ValueError(f"Unknown skater sort {sort!r}")
    assists = SkaterGameLog.primary_assists + SkaterGameLog.secondary_assists
    where = [Player.position != "G", Player.current_team_tri_code.is_not(None), SkaterGameLog.season == season]
    if position in POSITION_GROUPS:
        where.append(Player.position.in_(POSITION_GROUPS[position]))
    result = await db.execute(
        select(
            Player,
            func.count(SkaterGameLog.game_id),
            func.coalesce(func.sum(SkaterGameLog.goals), 0),
            func.coalesce(func.sum(assists), 0),
            func.coalesce(func.sum(SkaterGameLog.points), 0),
            func.coalesce(func.sum(SkaterGameLog.x_goals), 0.0),
            func.coalesce(func.sum(SkaterGameLog.shots_on_goal), 0),
            func.coalesce(func.sum(SkaterGameLog.toi), 0.0),
            func.coalesce(func.sum(SkaterGameLog.pp_points), 0),
        )
        .join(SkaterGameLog, SkaterGameLog.player_id == Player.id)
        .where(*where)
        .group_by(Player.id)
    )
    rows = [
        TopSkater(player=p, games=gp, goals=g, assists=a, points=pts, x_goals=float(xg), shots_on_goal=sog,
                  toi_per_game=float(toi) / gp / 60 if gp else 0.0, pp_points=ppp)
        for p, gp, g, a, pts, xg, sog, toi, ppp in result.all()
    ]
    rows.sort(key=_skater_sort_key(sort))
    rows = rows[:n]
    if rows:
        logs = await db.execute(
            select(SkaterGameLog.player_id, SkaterGameLog.points)
            .where(SkaterGameLog.season == season, SkaterGameLog.player_id.in_([s.player.id for s in rows]))
            .order_by(SkaterGameLog.game_date, SkaterGameLog.game_id)
        )
        by_player: dict[int, list[int]] = {}
        for pid, pts in logs.all():
            by_player.setdefault(pid, []).append(pts)
        for s in rows:
            s.points_by_game = by_player.get(s.player.id, [])
    return rows


async def top_goalies(db: AsyncSession, season: int, n: int, sort: str = "gsax",
                      min_games: int = DEFAULT_GOALIE_MIN_GAMES) -> list[TopGoalie]:
    """The n rostered goalies best on `sort` this season, among those with at least min_games games."""
    if sort not in GOALIE_SORTS:
        raise ValueError(f"Unknown goalie sort {sort!r}")
    result = await db.execute(
        select(
            Player,
            func.count(GoalieGameLog.game_id),
            func.coalesce(func.sum(GoalieGameLog.sog), 0),
            func.coalesce(func.sum(GoalieGameLog.goals_against), 0),
            func.coalesce(func.sum(GoalieGameLog.x_goals_against), 0.0),
            func.coalesce(func.sum(GoalieGameLog.toi), 0.0),
            func.coalesce(func.sum(GoalieGameLog.high_danger_shots), 0),
        )
        .join(GoalieGameLog, GoalieGameLog.player_id == Player.id)
        .where(Player.position == "G", Player.current_team_tri_code.is_not(None), GoalieGameLog.season == season)
        .group_by(Player.id)
        .having(func.count(GoalieGameLog.game_id) >= max(1, min_games))
    )
    rows = [
        TopGoalie(player=p, games=gp, shots_faced=sa, goals_against=ga, x_goals_against=float(xga), toi=float(toi),
                  high_danger_shots=hd)
        for p, gp, sa, ga, xga, toi, hd in result.all()
    ]
    rows.sort(key=_goalie_sort_key(sort))
    return rows[:n]
