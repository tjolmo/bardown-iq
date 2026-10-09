from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy import delete, select, func
from app.crud.prop_quotes import get_quotes_for_games, latest_fetch
from app.models import PlayerPropOdds, Props
from app.schemas.player import PlayerPropOut, PropBookPriceOut
from external.propline.books import CONSENSUS_BOOKS

PROPS_COLUMNS = {"game_id", "player_id", "prop_type", "over_under", "odds", "line", "book"}


def props_upsert_stmt(props: list[PlayerPropOut]):
    """INSERT ... ON CONFLICT DO UPDATE for the props table. Only the table's columns are dumped: the output-only
    fields of PlayerPropOut (model_prob, edge, source, other_books) would make the insert fail to compile."""
    data = [prop.model_dump(include=PROPS_COLUMNS) for prop in props]
    stmt = insert(Props).values(data)
    return stmt.on_conflict_do_update(
        index_elements=['game_id', 'player_id', 'prop_type', 'over_under'],
        set_={
            "odds": stmt.excluded.odds,
            "line": stmt.excluded.line,
            "book": stmt.excluded.book,
        }
    )


async def upsert_player_props(db: AsyncSession, props: list[PlayerPropOut]):
    """Saves the best-price player props (one row per side, from PropLine's books), replacing what their games had:
    a side a fetch no longer prices (a pulled market, a line that moved to the other side's) must not linger."""
    if not props:
        return
    await db.execute(delete(Props).where(Props.game_id.in_({p.game_id for p in props})))
    await db.execute(props_upsert_stmt(props))
    await db.commit()

# ESPN prop slug (player_prop_odds.prop_type) -> the app market key the props endpoint and prop_probability use.
# ESPN carries markets PropLine doesn't have for NHL (hits: no market on PropLine or the Odds API), so its table fills
# the gaps on the player page. Milestone ladders and first/last goal are left out.
ESPN_PROP_KEYS = {"goals": "player_goals", "assists": "player_assists", "points": "player_points",
                  "shots_on_goal": "player_shots_on_goal", "blocked_shots": "player_blocked_shots",
                  "hits": "player_hits", "saves": "player_total_saves", "pp_points": "player_power_play_points",
                  "anytime_goal": "player_goal_scorer_anytime"}


def espn_prop_rows(markets, covered: set[str]) -> list[PlayerPropOut]:
    """One output row per side of each ESPN market (player_prop_odds rows of one game), skipping market keys the
    PropLine books already priced for that game (`covered`). One-sided anytime goal prices come out as "Yes"."""
    out = []
    for m in markets:
        key = ESPN_PROP_KEYS.get(m.prop_type)
        if key is None or key in covered:
            continue
        sides = [("Yes", m.over_price)] if m.prop_type == "anytime_goal" else [("Over", m.over_price), ("Under", m.under_price)]
        if m.prop_type != "anytime_goal" and (m.over_price is None or m.under_price is None):
            continue  # half a market (unpaired DraftKings row): no fair comparison
        for side, price in sides:
            if price is not None:
                out.append(PlayerPropOut(game_id=m.game_id, player_id=m.player_id, prop_type=key, over_under=side,
                                         odds=price, line=m.line, source="espn", book=m.book))
    return sorted(out, key=lambda p: (p.prop_type, p.line, p.over_under != "Over"))


def other_book_prices(prop: PlayerPropOut, quotes) -> list[PropBookPriceOut]:
    """Every other stored book's price for the same prop and side in the latest fetch, best first: the "+N books"
    list under a prop card. The shown price (its book at its line) is left out."""
    out = [PropBookPriceOut(book=q.bookmaker, odds=q.odds, line=q.line, consensus=q.bookmaker in CONSENSUS_BOOKS)
           for q in quotes
           if q.prop_type == prop.prop_type and q.over_under == prop.over_under
           and not (q.bookmaker == prop.book and q.line == prop.line)]
    return sorted(out, key=lambda b: (b.line != prop.line, b.line, -b.odds))


async def get_player_prop_board(db: AsyncSession, player_id: int) -> list[PlayerPropOut]:
    """The player's props for his latest priced game: PropLine's best-price rows (props) with every other book's
    price, plus ESPN's markets (player_prop_odds) for the market keys PropLine didn't return, hits above all."""
    api_game = (await db.execute(select(func.max(Props.game_id)).where(Props.player_id == player_id))).scalar()
    espn_game = (await db.execute(select(func.max(PlayerPropOdds.game_id))
                                  .where(PlayerPropOdds.player_id == player_id))).scalar()
    games = [g for g in (api_game, espn_game) if g is not None]
    if not games:
        return []
    game_id = max(games)    # game ids increase through a season: the more recent game wins
    api = (await db.execute(select(Props).where(Props.player_id == player_id, Props.game_id == game_id))).scalars().all()
    out = [PlayerPropOut.model_validate(p, from_attributes=True) for p in api]
    if out:
        quotes = latest_fetch(await get_quotes_for_games(db, [game_id], player_id))
        for prop in out:
            prop.other_books = other_book_prices(prop, quotes)
    espn = (await db.execute(select(PlayerPropOdds).where(PlayerPropOdds.player_id == player_id,
                                                          PlayerPropOdds.game_id == game_id))).scalars().all()
    return out + espn_prop_rows(espn, {p.prop_type for p in out})
