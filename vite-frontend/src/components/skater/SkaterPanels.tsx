import { Link, useOutletContext } from "react-router-dom";
import type { SkaterData, SkaterGame } from "../../types/skater";
import { splitTeamName } from "../../utils/gameStatus";
import { pct, perGame, signed, teamOf } from "../../utils/playerStats";
import { LastFive } from "../player/LastFive";
import { ModelTile } from "../player/ModelTile";
import type { PlayerPageContext } from "../player/pageContext";
import { SeasonLog } from "../player/SeasonLog";
import { StatPicker } from "../player/StatPicker";
import { chanceAtLine, SKATER_STATS, skaterExpected, skaterSeasonViews } from "./skaterStats";

type Ctx = PlayerPageContext<SkaterData, SkaterGame>;

/** Next game: a tile for every stat the model predicts, with its chance at the book's line. */
export const SkaterNextGame = () => {
  const { data } = useOutletContext<Ctx>();
  const { predictions, upcomingGame, props, season, teams } = data;
  const opp = upcomingGame?.opposing_team_tricode ? teamOf(teams, upcomingGame.opposing_team_tricode) : null;
  const best = props.reduce<number | null>((m, p) => (p.edge !== null && (m === null || p.edge > m) ? p.edge : m), null);

  return (
    <section className="bd-section" aria-labelledby="model-h">
      <div className="bd-section-head">
        <h2 className="bd-heading" id="model-h">
          {opp ? `The model ${upcomingGame!.home_away === "AWAY" ? "@" : "vs"} ${splitTeamName(opp.name).nickname}` : "The model"}
        </h2>
        <span className="bd-muted">Every stat the model predicts, with its chance at the book's line</span>
      </div>
      {!predictions ? (
        <div className="bd-empty">The model has no numbers for the next game yet.</div>
      ) : (
        <div className="pl-tiles">
          {SKATER_STATS.map((d) => {
            const exp = skaterExpected(predictions, d.key);
            const chance = chanceAtLine(d, props, predictions);
            const avg = perGame(season, d.value);
            return (
              <ModelTile key={d.key} label={d.label} corner={chance?.label ?? "Expected"}
                big={chance ? pct(chance.p) : exp !== null ? exp.toFixed(2) : "—"}
                meter={chance ? { value: chance.p, aria: `${pct(chance.p)}, ${chance.label.toLowerCase()}` } : undefined}>
                <div className="pl-sub">
                  {exp !== null && <><strong>{exp.toFixed(2)}</strong> expected</>}
                  {exp !== null && avg !== null && <> · season <strong>{avg.toFixed(2)}</strong> a game <span className="pl-c-dim">({signed(exp - avg, 2)})</span></>}
                </div>
                {d.propTypes.length === 0 && (
                  <div className="pl-sub">No prop: the model counts 5-on-4 points only, books settle on every power play.</div>
                )}
              </ModelTile>
            );
          })}
          {props.length > 0 && (
            <Link to="../props" replace className="pl-tile pl-tile-link">
              <span className="bd-label" style={{ alignSelf: "auto" }}>Props</span>
              <span className="pl-market">See the {props.length} {props.length === 1 ? "line" : "lines"} on the board</span>
              {best !== null && <span className="pl-sub">Best edge <strong>{signed(best * 100, 1)}</strong></span>}
            </Link>
          )}
        </div>
      )}
    </section>
  );
};

/** Last five: the picked stat as bars against the model's next number, beside the five games' log. */
export const SkaterLastFive = () => {
  const { data, stat, setStat } = useOutletContext<Ctx>();
  const { recent, predictions, upcomingGame, teams } = data;
  if (!recent.length) return <div className="bd-empty">No games logged yet.</div>;
  return (
    <LastFive games={recent} defs={SKATER_STATS} stat={stat} teams={teams}
      picker={<StatPicker options={SKATER_STATS} value={stat.key} onChange={setStat} />}
      expectedNext={skaterExpected(predictions, stat.key)}
      next={upcomingGame?.opposing_team_tricode
        ? { tricode: upcomingGame.opposing_team_tricode, home: upcomingGame.home_away !== "AWAY", time: upcomingGame.time } : null} />
  );
};

/** The season: every game, seen as a box score, shot quality, the model against the result, or splits. */
export const SkaterSeason = () => {
  const { data, stat } = useOutletContext<Ctx>();
  return <SeasonLog games={data.season} views={skaterSeasonViews(stat.key)} noun={["game", "games"]} />;
};
