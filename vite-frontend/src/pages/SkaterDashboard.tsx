import { useState } from "react";
import { Outlet, useParams } from "react-router-dom";
import { PlayerHero } from "../components/player/PlayerHero";
import { PlayerTabs } from "../components/player/PlayerTabs";
import type { PlayerPageContext } from "../components/player/pageContext";
import { DEFAULT_SKATER_STAT, SKATER_STATS } from "../components/skater/skaterStats";
import { useSkater } from "../hooks/useSkater";
import type { SkaterData, SkaterGame } from "../types/skater";
import { pct, signed, total } from "../utils/playerStats";

const capitalize = (s: string) => s.charAt(0).toUpperCase() + s.slice(1);

/** A skater's page: the rink hero, then one tab per view (next game, props, last five, season). */
export default function SkaterDashboard() {
  const { id } = useParams();
  const { data, loading, error } = useSkater(Number(id));
  const [statKey, setStat] = useState(DEFAULT_SKATER_STAT);

  if (loading || error || !data) {
    return (
      <div className="bd-page">
        <main className="bd-main">
          <div className="bd-empty">{loading ? "Loading the board…" : "Couldn't load this player. Try again in a minute."}</div>
        </main>
      </div>
    );
  }

  const stat = SKATER_STATS.find((d) => d.key === statKey) ?? SKATER_STATS[2];
  const { season, recent, predictions, props, upcomingGame } = data;
  const opp = upcomingGame?.opposing_team_tricode;
  const best = props.reduce<number | null>((m, p) => (p.edge !== null && (m === null || p.edge > m) ? p.edge : m), null);
  const recentTotal = total(recent, stat.value);
  const context: PlayerPageContext<SkaterData, SkaterGame> = { data, stat, setStat };

  return (
    <div className="bd-page">
      <main className="bd-main" style={{ gap: 20 }}>
        <PlayerHero player={data} teams={data.teams} upcomingGame={upcomingGame}
          seasonLine={[
            { label: "GP", value: String(season.length) },
            { label: "Goals", value: String(total(season, (g) => g.goals) ?? 0) },
            { label: "Assists", value: String(total(season, (g) => g.assists) ?? 0) },
            { label: "Points", value: String(total(season, (g) => g.points) ?? 0) },
          ]} />
        <PlayerTabs tabs={[
          { to: "predictions", num: predictions?.prob_point != null ? pct(predictions.prob_point) : "—", label: "Next game",
            sub: opp ? `Point chance ${upcomingGame!.home_away === "AWAY" ? "@" : "vs"} ${opp}` : "No game scheduled" },
          { to: "props", num: String(props.length), label: "Props", sub: best !== null ? `Best edge ${signed(best * 100, 1)}` : "No lines yet" },
          { to: "recent", num: recentTotal !== null ? String(recentTotal) : "—", label: "Last five",
            sub: `${capitalize(stat.many)} in ${recent.length} ${recent.length === 1 ? "game" : "games"}` },
          { to: "season", num: String(season.length), label: "Season", sub: "Every game, every stat" },
        ]} />
        <Outlet context={context} />
      </main>
    </div>
  );
}
