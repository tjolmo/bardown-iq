"""ESPN athlete id -> NHL player id.

ESPN prop rows only carry ESPN athlete ids. We resolve each athlete once, from its
ESPN bio (name, position) plus the games it had props in:

1. candidates = players whose normalized "first last" equals the ESPN name, with
   goalie/skater agreeing (ESPN position "G");
2. if none, a loose pass: same normalized last name and one first name a prefix of
   the other ("Alex"/"Alexander", "Mitch"/"Mitchell") or the same first initial;
3. each candidate is scored on team evidence over the athlete's prop games:
   (# games he has a game log in, # games where he logged a game for one of the two
   teams that season, # games where his current team is one of the two teams,
   # games where he logged for one of the two teams the season before/after --
   playoff call-ups and depth players who never logged a regular-season game for
   that team that year).
   A last tiebreak is defence vs forward agreeing with ESPN's position (namesakes on
   one team, e.g. Vancouver's two Elias Petterssons). The best candidate wins if it
   has some team evidence and strictly beats the runner-up.

No birth dates on our side, so team-season evidence is what separates namesakes
(e.g. the two Elias Petterssons) and rejects a same-named player who never played
for either team.
"""

from __future__ import annotations

import collections
from dataclasses import dataclass, field
from typing import Iterable

from app.name_matching import normalize_name


@dataclass
class PlayerIndex:
    """Lookup tables built from the players table and game logs."""
    players: dict[int, dict]                       # id -> {first_name, last_name, position, current_team}
    by_name: dict[str, list[int]] = field(default_factory=dict)
    by_last: dict[str, list[int]] = field(default_factory=dict)
    team_seasons: set[tuple[int, int, str]] = field(default_factory=set)   # (player_id, season start year, team)
    game_players: set[tuple[int, int]] = field(default_factory=set)        # (game_id, player_id)


def build_player_index(players: Iterable[dict], team_seasons: Iterable[tuple[int, int, str]] = (),
                       game_players: Iterable[tuple[int, int]] = ()) -> PlayerIndex:
    idx = PlayerIndex(players={})
    by_name, by_last = collections.defaultdict(list), collections.defaultdict(list)
    for p in players:
        idx.players[int(p["id"])] = p
        by_name[normalize_name(f"{p['first_name']} {p['last_name']}")].append(int(p["id"]))
        by_last[normalize_name(p["last_name"])].append(int(p["id"]))
    idx.by_name, idx.by_last = dict(by_name), dict(by_last)
    idx.team_seasons = set(team_seasons)
    idx.game_players = set(game_players)
    return idx


def season_of(game_id: int) -> int:
    """NHL game ids start with the season start year: 2023020846 -> 2023."""
    return int(game_id) // 1_000_000


def _is_goalie(position: str | None) -> bool:
    return (position or "").upper() == "G"


def _first_names_compatible(a: str, b: str) -> bool:
    a, b = normalize_name(a), normalize_name(b)
    return bool(a and b) and (a.startswith(b) or b.startswith(a) or a[0] == b[0])


def name_candidates(idx: PlayerIndex, athlete: dict, goalie: bool | None) -> tuple[list[int], str]:
    """(candidate ids, 'exact' | 'loose')."""
    def keep(ids):
        return [i for i in ids if goalie is None or _is_goalie(idx.players[i].get("position")) == goalie]

    names = {normalize_name(athlete.get("full_name") or ""),
             normalize_name(f"{athlete.get('first_name', '')} {athlete.get('last_name', '')}")}
    exact = keep(sorted({i for n in names if n for i in idx.by_name.get(n, [])}))
    if exact:
        return exact, "exact"
    loose = [i for i in keep(idx.by_last.get(normalize_name(athlete.get("last_name") or ""), []))
             if _first_names_compatible(idx.players[i]["first_name"], athlete.get("first_name") or "")]
    return loose, "loose"


def _is_defence(position: str | None) -> bool:
    return (position or "").upper() == "D"


def evidence(idx: PlayerIndex, player_id: int, games: Iterable[tuple[int, str, str]]) -> tuple[int, int, int, int]:
    """Team evidence for a candidate over (game_id, home, away) contexts."""
    in_game = team_season = current = adjacent = 0
    team_now = idx.players[player_id].get("current_team")
    for game_id, home, away in games:
        season = season_of(game_id)
        in_game += (game_id, player_id) in idx.game_players
        team_season += (player_id, season, home) in idx.team_seasons or (player_id, season, away) in idx.team_seasons
        current += team_now in (home, away)
        adjacent += any((player_id, s, t) in idx.team_seasons for s in (season - 1, season + 1) for t in (home, away))
    return in_game, team_season, current, adjacent


def resolve_athlete(idx: PlayerIndex, athlete: dict, games: list[tuple[int, str, str]],
                    goalie_hint: bool | None = None) -> tuple[int | None, str]:
    """(NHL player id or None, reason). `goalie_hint` comes from the props themselves
    (saves markets are goalie-only) when ESPN's position is missing."""
    goalie = _is_goalie(athlete.get("position")) if athlete.get("position") else goalie_hint
    candidates, how = name_candidates(idx, athlete, goalie)
    if not candidates:
        return None, "name_not_found"
    espn_d = _is_defence(athlete.get("position")) if athlete.get("position") else None
    scored = sorted((((*evidence(idx, c, games),
                       int(espn_d is not None and _is_defence(idx.players[c].get("position")) == espn_d)), c)
                     for c in candidates), reverse=True)
    best_score, best = scored[0]
    if not any(best_score[:4]):
        return None, f"{how}_no_team_evidence"
    if len(scored) > 1 and scored[1][0] == best_score:
        return None, f"{how}_ambiguous"
    return best, how


def resolve_athletes(idx: PlayerIndex, athletes: dict[int, dict],
                     contexts: dict[int, list[tuple[int, str, str]]],
                     goalie_hints: dict[int, bool] | None = None,
                     known: dict[int, int] | None = None) -> tuple[dict[int, int], dict[int, str]]:
    """Maps every athlete in `contexts` (athlete -> [(game_id, home, away)]).
    `known` (e.g. pairs already stored in player_prop_odds) is trusted as is.
    Returns (espn_athlete_id -> player_id, espn_athlete_id -> reason for the unmatched)."""
    mapping, unmatched = dict(known or {}), {}
    for athlete_id, games in contexts.items():
        if athlete_id in mapping:
            continue
        athlete = athletes.get(athlete_id)
        if athlete is None:
            unmatched[athlete_id] = "no_espn_bio"
            continue
        pid, reason = resolve_athlete(idx, athlete, games, (goalie_hints or {}).get(athlete_id))
        if pid is None:
            unmatched[athlete_id] = reason
        else:
            mapping[athlete_id] = pid
    return mapping, unmatched
