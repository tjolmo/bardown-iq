import type { CSSProperties, FC } from "react";
import { Link } from "react-router-dom";
import type { LineupGoalie, LineupUnit, TeamLineup } from "../../types/lineup";
import { formatSeconds, lastName, playerLink, togetherLine } from "../../utils/lineup";
import { LineupPlayerLink } from "./LineupPlayerLink";

const GOALIE_STATUS: Record<string, string> = {
  confirmed: "CONFIRMED", probable: "PROBABLE", actual: "STARTED", projected: "PROJECTED",
};

const LineMeta: FC<{ unit: LineupUnit; games: number }> = ({ unit, games }) =>
  unit.secondsLastGame > 0 ? (
    <div className="rs-meta">
      <strong>{formatSeconds(unit.secondsLastGame)}</strong>
      <span>last game{unit.gamesTogether > 0 && ` · ${unit.gamesTogether} of ${games} games`}</span>
    </div>
  ) : (
    <div className="rs-meta">
      <span className="bd-chip bd-chip-quiet">{unit.gamesTogether > 0 ? "REUNITED" : "NEW LINE"}</span>
    </div>
  );

const ForwardsCard: FC<{ units: LineupUnit[]; incoming: Set<number>; games: number }> = ({ units, incoming, games }) => (
  <div className="rs-card">
    <div className="rs-card-head">
      <h3 className="rs-card-title">Forwards</h3>
      <span className="bd-label">Together at 5 on 5</span>
    </div>
    {units.map((u, i) => (
      <div key={u.name} className="rs-row rs-line">
        <span className="rs-line-n"><span className="bd-score">{i + 1}</span><small>LINE</small></span>
        <div className="rs-slots">
          {u.players.map((p) => <LineupPlayerLink key={p.id} player={p} incoming={incoming.has(p.id)} />)}
        </div>
        <LineMeta unit={u} games={games} />
      </div>
    ))}
  </div>
);

const DefenceCard: FC<{ units: LineupUnit[]; incoming: Set<number>; games: number }> = ({ units, incoming, games }) => (
  <div className="rs-card">
    <div className="rs-card-head"><h3 className="rs-card-title">Defence</h3></div>
    {units.map((u, i) => (
      <div key={u.name} className="rs-row">
        <div className="rs-pair-head">
          <span className="bd-label">Pair {i + 1}</span>
          <span>{togetherLine(u.secondsLastGame, u.gamesTogether, games) ?? <span className="bd-chip bd-chip-quiet">NEW PAIR</span>}</span>
        </div>
        <div className="rs-slots" style={{ "--rs-cols": 2 } as CSSProperties}>
          {u.players.map((p) => <LineupPlayerLink key={p.id} player={p} incoming={incoming.has(p.id)} />)}
        </div>
      </div>
    ))}
  </div>
);

const GoaliesCard: FC<{ goalies: LineupGoalie[] }> = ({ goalies }) => {
  const starter = goalies.find((g) => g.role === "starter");
  return (
    <div className="rs-card">
      <div className="rs-card-head"><h3 className="rs-card-title">Goalies</h3></div>
      {goalies.map((g) => (
        <div key={g.player.id} className="rs-goalie">
          <LineupPlayerLink player={g.player} slot={g.role === "starter" ? "Starter" : "Backup"} large={g.role === "starter"} />
          {g.role === "starter" && <span className="bd-chip bd-chip-time">{GOALIE_STATUS[g.status] ?? g.status.toUpperCase()}</span>}
        </div>
      ))}
      {starter?.status === "projected" && (
        <p className="rs-note" style={{ margin: 0 }}>
          {starter.player.lastName} started the last game. ESPN's probable starter shows here once it's posted.
        </p>
      )}
      {goalies.length === 0 && <p className="rs-note" style={{ margin: 0 }}>No goalies in the lineup yet.</p>}
    </div>
  );
};

const SpecialTeamsCard: FC<{ powerPlay: LineupUnit[]; penaltyKill: LineupUnit[]; games: number }> = ({ powerPlay, penaltyKill, games }) => {
  const units = [...powerPlay.map((u) => ({ u, kind: "Power play" })), ...penaltyKill.map((u) => ({ u, kind: "Penalty kill" }))];
  return (
    <div className="rs-card">
      <div className="rs-card-head"><h3 className="rs-card-title">Special teams</h3></div>
      {units.length === 0 && <p className="rs-note rs-row" style={{ margin: 0 }}>No power-play or penalty-kill time in recent games yet.</p>}
      {units.map(({ u, kind }) => (
        <div key={u.name} className="rs-row">
          <div className="rs-unit-head">
            <span className="rs-unit-name"><span className="bd-score">{u.name}</span><span className="bd-label">{kind}</span></span>
            <span className="rs-note">{togetherLine(u.secondsLastGame, u.gamesTogether, games) ?? "New unit"}</span>
          </div>
          <div className="rs-pills">
            {u.players.map((p) => (
              <Link key={p.id} to={playerLink(p)} className={`rs-pill${p.slot === "D" ? " rs-pill-d" : ""}`}>
                <span className="rs-disc" aria-hidden="true">{p.number ?? "–"}</span>
                <span className="rs-name">{lastName(p)}</span>
                {p.slot === "D" && <span className="rs-slot">D</span>}
              </Link>
            ))}
          </div>
        </div>
      ))}
    </div>
  );
};

/** The next game's lines: the forward lines across the board, then defence pairs, goalies and special teams. */
export const LinesBoard: FC<{ lineup: TeamLineup }> = ({ lineup }) => {
  const incoming = new Set(lineup.changes.playersIn.map((p) => p.id));
  const games = Math.max(lineup.basedOn.length, 1);
  return (
    <div className="rs-stack">
      <ForwardsCard units={lineup.forwards} incoming={incoming} games={games} />
      <div className="rs-subgrid">
        <DefenceCard units={lineup.defense} incoming={incoming} games={games} />
        <GoaliesCard goalies={lineup.goalies} />
        <SpecialTeamsCard powerPlay={lineup.powerPlay} penaltyKill={lineup.penaltyKill} games={games} />
      </div>
    </div>
  );
};
