import { Link, useOutletContext } from "react-router-dom";
import type { GoalieData, GoalieGame } from "../../types/goalie";
import { splitTeamName } from "../../utils/gameStatus";
import { gaa, pct, perGame, savePct, signed, teamOf, total } from "../../utils/playerStats";
import { LastFive } from "../player/LastFive";
import { ModelTile } from "../player/ModelTile";
import type { PlayerPageContext } from "../player/pageContext";
import { SeasonLog } from "../player/SeasonLog";
import { StatPicker } from "../player/StatPicker";
import { GOALIE_STATS, goalieExpected, goalieSeasonViews } from "./goalieStats";

type Ctx = PlayerPageContext<GoalieData, GoalieGame>;

// the save-percentage meter's range
const SV_LOW = 0.88;
const SV_HIGH = 0.94;
const onSvScale = (x: number) => (x - SV_LOW) / (SV_HIGH - SV_LOW);

/** "season 27.86 a game (−0.46)" */
const versusSeason = (exp: number, avg: number | null) =>
  avg === null ? null : <> · season <strong>{avg.toFixed(2)}</strong> a game <span className="pl-c-dim">({signed(exp - avg, 2)})</span></>;

/** Next game: saves, shots against and goals against as the model expects them, assuming the start. */
export const GoalieNextGame = () => {
  const { data } = useOutletContext<Ctx>();
  const { predictions: p, upcomingGame, props, season, teams } = data;
  const opp = upcomingGame?.opposing_team_tricode ? teamOf(teams, upcomingGame.opposing_team_tricode) : null;
  const savesProp = props
    .filter((x) => x.prop_type === "player_total_saves" && x.over_under.toUpperCase() === "OVER" && x.model_prob !== null)
    .sort((a, b) => a.line - b.line)[0];
  const seasonSv = total(season, (g) => g.shots_against) ? (total(season, (g) => g.saves) ?? 0) / (total(season, (g) => g.shots_against) ?? 1) : null;
  const best = props.reduce<number | null>((m, x) => (x.edge !== null && (m === null || x.edge > m) ? x.edge : m), null);
  const starter = p?.starter_status ? `Starter: ${p.starter_status}` : null;

  return (
    <section className="bd-section" aria-labelledby="model-h">
      <div className="bd-section-head">
        <h2 className="bd-heading" id="model-h">
          {opp ? `The model ${upcomingGame!.home_away === "AWAY" ? "@" : "vs"} ${splitTeamName(opp.name).nickname}` : "The model"}
        </h2>
        <span className="bd-muted">
          Every stat the model predicts in net, assuming the start{starter ? `. ${starter}` : ""}
        </span>
      </div>
      {p?.starting === false && (
        <div className="bd-empty" style={{ padding: "16px 24px", textAlign: "left" }}>
          Not the expected starter for this game. These numbers are what the model expects if the start comes anyway.
        </div>
      )}
      {!p ? (
        <div className="bd-empty">The model has no numbers for the next game yet.</div>
      ) : (
        <div className="pl-tiles">
          <ModelTile label="Saves" corner="Expected" big={p.saves.toFixed(1)}
            meter={savesProp ? { value: savesProp.model_prob!, aria: `${pct(savesProp.model_prob!)} chance of more than ${savesProp.line} saves` } : undefined}>
            <div className="pl-sub">
              {savesProp && <><strong>{pct(savesProp.model_prob!)}</strong> over {savesProp.line}</>}
              {savesProp ? versusSeason(p.saves, perGame(season, (g) => g.saves)) : <>Season <strong>{(perGame(season, (g) => g.saves) ?? 0).toFixed(2)}</strong> a game</>}
            </div>
          </ModelTile>
          {p.shots_against != null && (
            <ModelTile label="Shots against" corner="Expected" big={p.shots_against.toFixed(1)}>
              <div className="pl-sub">
                <strong>{p.shots_against.toFixed(1)}</strong> expected{versusSeason(p.shots_against, perGame(season, (g) => g.shots_against))}
              </div>
            </ModelTile>
          )}
          <ModelTile label="Goals against" corner="Expected" big={p.goals_against.toFixed(1)}>
            <div className="pl-sub">
              <strong>{p.goals_against.toFixed(2)}</strong> expected{versusSeason(p.goals_against, perGame(season, (g) => g.goals_against))}
            </div>
            {season.length > 0 && <div className="pl-sub">Season GAA <strong>{(gaa(season) ?? 0).toFixed(2)}</strong></div>}
          </ModelTile>
          {p.save_percentage != null && (
            <ModelTile label="Save percentage" corner="From the above" big={savePct(p.save_percentage, 1)}
              meter={{
                value: onSvScale(p.save_percentage), mark: seasonSv !== null ? onSvScale(seasonSv) : undefined,
                scale: [".880", ".910", ".940"],
                aria: `Projected save percentage ${savePct(p.save_percentage, 1)}` + (seasonSv !== null ? ` against a season ${savePct(seasonSv, 1)}` : ""),
              }}>
              {seasonSv !== null && <div className="pl-sub">Puck is the projection, dash the season's <strong>{savePct(seasonSv, 1)}</strong></div>}
            </ModelTile>
          )}
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

export const GoalieLastFive = () => {
  const { data, stat, setStat } = useOutletContext<Ctx>();
  const { recent, predictions, upcomingGame, teams } = data;
  if (!recent.length) return <div className="bd-empty">No starts logged yet.</div>;
  return (
    <LastFive games={recent} defs={GOALIE_STATS} stat={stat} teams={teams}
      picker={<StatPicker options={GOALIE_STATS} value={stat.key} onChange={setStat} />}
      expectedNext={goalieExpected(predictions, stat.key)}
      next={upcomingGame?.opposing_team_tricode
        ? { tricode: upcomingGame.opposing_team_tricode, home: upcomingGame.home_away !== "AWAY", time: upcomingGame.time } : null}
      extraCols={[{ label: "SV%", value: (g) => savePct(g.saves, g.shots_against), foot: (gs) => savePct(total(gs, (g) => g.saves) ?? 0, total(gs, (g) => g.shots_against) ?? 0) }]} />
  );
};

export const GoalieSeason = () => {
  const { data, stat } = useOutletContext<Ctx>();
  return <SeasonLog games={data.season} views={goalieSeasonViews(stat.key)} noun={["start", "starts"]} />;
};
