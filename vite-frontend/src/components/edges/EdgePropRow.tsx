import { useState, type FC } from "react";
import { formatBook, formatPrice, type OddsFormat } from "../../utils/books";
import type { PricedProp } from "../../utils/edgePricing";
import { impliedProb, pct } from "../../utils/playerStats";
import { formatPropType } from "../../utils/propMarkets";
import { OddsMeter } from "../player/ModelTile";
import { edgeChipClass, edgeText, isYes, sideName } from "./edgeFormat";

interface Props {
  prop: PricedProp;
  format: OddsFormat;
  myBooks: ReadonlySet<string>;
  // a side shown for completeness, with no edge at these filters
  quiet?: boolean;
}

/** One prop side: the market, the side and line, the best price at the visitor's books, the model's chance against
 *  the book's, and the edge, with every other book's price a click away. */
export const EdgePropRow: FC<Props> = ({ prop, format, myBooks, quiet }) => {
  const [open, setOpen] = useState(false);
  const yes = isYes(prop.over_under);
  const implied = impliedProb(prop.odds);
  const others = prop.prices.filter((b) => !(b.book === prop.book && b.line === prop.line && b.odds === prop.odds));
  const why = (b: PricedProp["prices"][number]): string | null =>
    b.priced === false ? "line only, no price" : b.pick_app ? "pick app, per-pick payout"
      : myBooks.size > 0 && !myBooks.has(b.book) ? "not one of your books" : !b.consensus ? "not in consensus" : null;

  return (
    <li className={`pl-prop${quiet ? " ed-prop-quiet" : ""}`}>
      <span className="pl-market">{formatPropType(prop.prop_type)}</span>
      <span className="pl-side">
        {sideName(prop.over_under)} {!yes && <b>{prop.line}</b>}
      </span>
      <div className="pl-price">
        <strong>{formatPrice(prop.odds, format)}</strong>
        <span>{formatBook(prop.book)}</span>
        {others.length > 0 && (
          <button type="button" className="pl-books" aria-expanded={open} onClick={() => setOpen(!open)}>
            {open ? "Hide books" : `+${others.length} ${others.length === 1 ? "book" : "books"}`}
          </button>
        )}
      </div>
      <div className="pl-model">
        {prop.model_prob !== null ? (
          <>
            <span><strong>{pct(prop.model_prob)}</strong> model · {pct(implied)} book</span>
            <OddsMeter value={prop.model_prob} mark={implied} gap aria={`Model ${pct(prop.model_prob)}, book ${pct(implied)}`} />
          </>
        ) : (
          <span>{pct(implied)} book · no model yet</span>
        )}
      </div>
      <span className={`${edgeChipClass(prop.edge)} pl-edge`}>{prop.edge !== null ? edgeText(prop.edge) : "—"}</span>
      {open && (
        <ul className="pl-book-list">
          {others.map((b) => {
            const note = why(b);
            return (
              <li key={`${b.book}-${b.line}-${b.odds}`} className={note ? "ed-book-off" : undefined}>
                <span>{formatBook(b.book)}{b.line !== prop.line && !yes ? ` · ${b.line}` : ""}</span>
                <strong>{b.priced === false ? "—" : formatPrice(b.odds, format)}</strong>
                {note && <span>{note}</span>}
              </li>
            );
          })}
        </ul>
      )}
    </li>
  );
};
