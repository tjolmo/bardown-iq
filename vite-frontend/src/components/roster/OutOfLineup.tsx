import type { FC } from "react";
import { Link } from "react-router-dom";
import type { TeamInjury, TeamLineup, TeamScratch } from "../../types/lineup";
import { injuryChipClass, injuryLabel, lastName, playerLink, returnLabel, usefulComment } from "../../utils/lineup";

const POSITION_SHORT: Record<string, string> = { C: "C", L: "LW", R: "RW", D: "D", G: "G", LW: "LW", RW: "RW" };

const InjuryRow: FC<{ injury: TeamInjury; inLineup: boolean }> = ({ injury, inLineup }) => {
  const p = injury.player;
  const name = p?.lastName || injury.name?.split(" ").slice(1).join(" ") || injury.name || "Unknown";
  const position = POSITION_SHORT[p?.position ?? injury.position ?? ""] ?? injury.position ?? "";
  const ret = injury.status === "day_to_day" ? "Game-time call" : returnLabel(injury.returnDate);
  const comment = usefulComment(injury.comment);
  return (
    <div className="rs-row rs-out">
      <span>
        {p ? <Link to={playerLink(p)} className="rs-name">{name}</Link> : <span className="rs-name">{name}</span>}
        <span className="rs-out-pos">{[p?.number != null ? `#${p.number}` : null, position].filter(Boolean).join(" · ")}</span>
      </span>
      <span className={`bd-chip ${injuryChipClass(injury.status)} rs-out-chip`}>{injuryLabel(injury.status)}</span>
      <span className="rs-out-detail">{[injury.injuryType, inLineup ? "in the lineup" : null].filter(Boolean).join(" · ")}</span>
      <span className="rs-out-detail rs-out-detail-end">{ret}</span>
      {comment && <span className="rs-out-comment">{comment}</span>}
    </div>
  );
};

const ScratchRow: FC<{ scratch: TeamScratch }> = ({ scratch }) => {
  const p = scratch.player;
  return (
    <div className="rs-row" style={{ display: "flex", alignItems: "center", justifyContent: "space-between", gap: 12 }}>
      <Link to={playerLink(p)} className="rs-player">
        <span className="rs-disc" aria-hidden="true">{p.number ?? "–"}</span>
        <span className="rs-player-text">
          <span className="rs-name">{lastName(p)}</span>
          <span className="rs-out-detail">{[p.firstName, p.position ? POSITION_SHORT[p.position] : null].filter(Boolean).join(" · ")}</span>
        </span>
      </Link>
      <span style={{ display: "flex", flexDirection: "column", alignItems: "flex-end", gap: 4 }}>
        <span className="bd-chip bd-chip-quiet">{scratch.healthy ? "HEALTHY SCRATCH" : "SCRATCHED"}</span>
        <span className="rs-out-detail">
          {scratch.gamesScratched > 1 ? `${scratch.gamesScratched} straight games` : "Last game"}
        </span>
      </span>
    </div>
  );
};

// out tonight first, then injured reserve, then day-to-day; players on the roster before minor leaguers
const ORDER: Record<string, number> = { out: 0, suspended: 0, ir: 1, ltir: 1, day_to_day: 2 };

/** ESPN's injury report beside the NHL's scratches. */
export const OutOfLineup: FC<{ lineup: TeamLineup; posted: boolean }> = ({ lineup, posted }) => {
  const dressed = new Set([...lineup.forwards, ...lineup.defense].flatMap((u) => u.players.map((p) => p.id)));
  const injuries = [...lineup.injuries].sort((a, b) =>
    (ORDER[a.status] ?? 1) - (ORDER[b.status] ?? 1) || Number(a.player === null) - Number(b.player === null)
    || (a.name ?? "").localeCompare(b.name ?? ""));
  return (
    <div className="rs-grid">
      <div className="rs-card">
        <div className="rs-card-head">
          <h3 className="rs-card-title">Injured <span className="rs-count">{injuries.length}</span></h3>
        </div>
        {injuries.length === 0 && <p className="rs-note rs-row" style={{ margin: 0 }}>Nobody on the injury report.</p>}
        {injuries.map((i, k) => <InjuryRow key={`${i.playerId ?? i.name}-${k}`} injury={i} inLineup={i.playerId !== null && dressed.has(i.playerId)} />)}
      </div>
      <div className="rs-stack">
        <div className="rs-card">
          <div className="rs-card-head">
            <h3 className="rs-card-title">Scratched <span className="rs-count">{lineup.scratches.length}</span></h3>
          </div>
          {lineup.scratches.length === 0 && <p className="rs-note rs-row" style={{ margin: 0 }}>No scratches {posted ? "tonight" : "last game"}.</p>}
          {lineup.scratches.map((s) => <ScratchRow key={s.player.id} scratch={s} />)}
        </div>
        <p className="rs-note" style={{ margin: "0 8px" }}>
          A scratch the injury report doesn't list is a healthy scratch: the coach's call.
          {posted ? " These are tonight's, from the lineup the NHL posted." : " Tonight's replace these once the NHL posts the lineup."}
        </p>
      </div>
    </div>
  );
};
