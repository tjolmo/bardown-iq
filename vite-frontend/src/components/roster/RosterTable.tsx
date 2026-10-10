import type { FC } from "react";
import { Link } from "react-router-dom";
import type { PlayerFullData } from "../../types/player";
import type { TonightRole } from "../../utils/lineup";

const GROUPS = [
  { title: "Forwards", positions: ["C", "L", "R"], hand: "Shoots" },
  { title: "Defence", positions: ["D"], hand: "Shoots" },
  { title: "Goalies", positions: ["G"], hand: "Catches" },
  { title: "Unlisted", positions: ["U"], hand: "Shoots" },
];
const POSITION_SHORT: Record<string, string> = { C: "C", L: "LW", R: "RW", D: "D", G: "G", U: "–" };
const SIDE: Record<string, string> = { L: "Left", R: "Right" };

/** The whole roster by position, sweater numbers in order, with each player's place tonight. */
export const RosterTable: FC<{ players: PlayerFullData[]; roles: Map<number, TonightRole> | null }> = ({ players, roles }) => (
  <div className="rs-stack" style={{ gap: 32 }}>
    {GROUPS.map((group) => {
      const rows = players.filter((p) => group.positions.includes(p.position))
        .sort((a, b) => (a.number ?? 999) - (b.number ?? 999) || a.last_name.localeCompare(b.last_name));
      if (rows.length === 0) return null;
      return (
        <section key={group.title} className="bd-section" aria-label={group.title}>
          <h2 className="bd-heading">{group.title} <span className="rs-count">{rows.length}</span></h2>
          <div className="rs-table-wrap">
            <table className="rs-table">
              <thead>
                <tr>
                  <th scope="col">No.</th>
                  <th scope="col">Player</th>
                  <th scope="col">Position</th>
                  <th scope="col">{group.hand}</th>
                  {roles && <th scope="col">Next game</th>}
                </tr>
              </thead>
              <tbody>
                {rows.map((p) => {
                  const role = roles?.get(p.id);
                  return (
                    <tr key={p.id}>
                      <td><span className="bd-score">{p.number ?? "–"}</span></td>
                      <td>
                        <Link to={p.position === "G" ? `/goalie/${p.id}` : `/player/${p.id}`}>
                          <span className="rs-first">{p.first_name}</span> <span className="rs-name">{p.last_name}</span>
                        </Link>
                      </td>
                      <td style={{ fontWeight: 700 }}>{POSITION_SHORT[p.position] ?? p.position}</td>
                      <td className="bd-muted">{SIDE[p.shoots_catches] ?? "–"}</td>
                      {roles && (
                        <td>
                          <span className={`bd-chip ${role?.chip ?? "bd-chip-quiet"}`}>{role?.label ?? "NOT IN LINEUP"}</span>
                        </td>
                      )}
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        </section>
      );
    })}
  </div>
);
