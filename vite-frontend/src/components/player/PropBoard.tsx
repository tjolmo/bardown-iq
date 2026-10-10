import { useState, type FC } from "react";
import type { PlayerPropData } from "../../types/player";
import { formatBook } from "../../utils/books";
import { americanOdds, impliedProb, pct, signed } from "../../utils/playerStats";
import { STRONG_EDGE_POINTS } from "../rinkboard/EdgeChip";
import { formatPropType } from "./PlayerPropCard";
import { OddsMeter } from "./ModelTile";

const sideName = (side: string) => {
  const s = side.toUpperCase();
  return s === "YES" ? "Yes" : s === "UNDER" ? "Under" : "Over";
};

const propKey = (p: PlayerPropData) => `${p.prop_type}-${p.over_under}-${p.line}-${p.source}`;

/** Best edge first; sides the model hasn't priced last. */
const sortProps = (props: PlayerPropData[]): PlayerPropData[] =>
  [...props].sort((a, b) => (b.edge ?? -Infinity) - (a.edge ?? -Infinity));

/** Every prop side for the player's next game on one board: the best price, the model's chance against the book's,
 *  and the edge, with the other books' prices a click away. */
export const PropBoard: FC<{ props: PlayerPropData[] }> = ({ props }) => {
  const [open, setOpen] = useState<string | null>(null);
  return (
    <ul className="pl-props">
      <li className="pl-prop pl-prop-head" aria-hidden="true">
        <span className="bd-label">Market</span>
        <span className="bd-label">Side</span>
        <span className="bd-label">Best price</span>
        <span className="bd-label">Model vs book</span>
        <span className="bd-label">Edge</span>
      </li>
      {sortProps(props).map((p) => {
        const key = propKey(p);
        const books = p.other_books ?? [];
        const isOpen = open === key;
        const implied = impliedProb(p.odds);
        const edgePts = p.edge !== null ? p.edge * 100 : null;
        const yes = p.over_under.toUpperCase() === "YES";
        return (
          <li className="pl-prop" key={key}>
            <div style={{ display: "flex", flexDirection: "column", gap: 4, alignItems: "flex-start" }}>
              <span className="pl-market">{formatPropType(p.prop_type)}</span>
              {books.length > 0 && (
                <button type="button" className="pl-books" aria-expanded={isOpen} onClick={() => setOpen(isOpen ? null : key)}>
                  {isOpen ? "Hide books" : `+${books.length} ${books.length === 1 ? "book" : "books"}`}
                </button>
              )}
            </div>
            <span className="pl-side">
              {sideName(p.over_under)} {!yes && <b>{p.line}</b>}
            </span>
            <div className="pl-price">
              <strong>{americanOdds(p.odds)}</strong>
              <span>{p.source === "espn" ? p.book ?? "ESPN" : formatBook(p.book)}</span>
            </div>
            <div className="pl-model">
              {p.model_prob !== null ? (
                <>
                  <span><strong>{pct(p.model_prob)}</strong> model · {pct(implied)} book</span>
                  <OddsMeter value={p.model_prob} mark={implied}
                    aria={`Model ${pct(p.model_prob)}, book ${pct(implied)}`} />
                </>
              ) : (
                <span>{pct(implied)} book · no model yet</span>
              )}
            </div>
            <span className={`bd-edge pl-edge${edgePts !== null && edgePts >= STRONG_EDGE_POINTS ? " bd-edge-strong" : ""}`}>
              {edgePts !== null ? signed(edgePts, 1) : "—"}
            </span>
            {isOpen && (
              <ul className="pl-book-list">
                {books.map((b) => (
                  <li key={`${b.book}-${b.line}`} title={b.consensus ? undefined : "Not part of the consensus price"}>
                    <span>{formatBook(b.book)}{b.line !== p.line && !yes ? ` · ${b.line}` : ""}</span>
                    <strong>{americanOdds(b.odds)}</strong>
                    {!b.consensus && <span>not in consensus</span>}
                  </li>
                ))}
              </ul>
            )}
          </li>
        );
      })}
    </ul>
  );
};
