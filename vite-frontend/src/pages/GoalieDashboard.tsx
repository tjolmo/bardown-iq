import { useState } from "react";
import { Outlet, useParams } from "react-router-dom";
import { GOALIE_STATS, DEFAULT_GOALIE_STAT, goalieSeasonLine } from "../components/goalie/goalieStats";
import { PlayerHero } from "../components/player/PlayerHero";
import { PlayerTabs } from "../components/player/PlayerTabs";
import type { PlayerPageContext } from "../components/player/pageContext";
import { useGoalie } from "../hooks/useGoalie";
import type { GoalieData, GoalieGame } from "../types/goalie";
import { signed, total } from "../utils/playerStats";

const capitalize = (s: string) => s.charAt(0).toUpperCase() + s.slice(1);

/** A goalie's page: the rink hero, then one tab per view (next game, props, last five, season). */
export default function GoalieDashboard() {
  const { id } = useParams();
  const { data, loading, error } = useGoalie(Number(id));
  const [statKey, setStat] = useState(DEFAULT_GOALIE_STAT);

  if (loading || error || !data) {
    return (
      <div className="bd-page">
        <main className="bd-main">
          <div className="bd-empty">{loading ? "Loading the board…" : "Couldn't load this goalie. Try again in a minute."}</div>
        </main>
      </div>
    );
  }

  const stat = GOALIE_STATS.find((d) => d.key === statKey) ?? GOALIE_STATS[0];
  const { season, recent, predictions, props, upcomingGame } = data;
  const opp = upcomingGame?.opposing_team_tricode;
  const best = props.reduce<number | null>((m, p) => (p.edge !== null && (m === null || p.edge > m) ? p.edge : m), null);
  const recentTotal = total(recent, stat.value);
  const context: PlayerPageContext<GoalieData, GoalieGame> = { data, stat, setStat };

  return (
    <div className="bd-page">
      <main className="bd-main" style={{ gap: 20 }}>
        <PlayerHero player={data} teams={data.teams} upcomingGame={upcomingGame} seasonLine={goalieSeasonLine(season)} />
        <PlayerTabs tabs={[
          { to: "predictions", num: predictions ? predictions.saves.toFixed(1) : "—", label: "Next game",
            sub: opp ? `Saves expected ${upcomingGame!.home_away === "AWAY" ? "@" : "vs"} ${opp}` : "No game scheduled" },
          { to: "props", num: String(props.length), label: "Props", sub: best !== null ? `Best edge ${signed(best * 100, 1)}` : "No lines yet" },
          { to: "recent", num: recentTotal !== null ? String(recentTotal) : "—", label: "Last five",
            sub: `${capitalize(stat.many)} in ${recent.length} ${recent.length === 1 ? "start" : "starts"}` },
          { to: "season", num: String(season.length), label: "Season", sub: "Every start, every stat" },
        ]} />
        <Outlet context={context} />
      </main>
    </div>
  );
}
