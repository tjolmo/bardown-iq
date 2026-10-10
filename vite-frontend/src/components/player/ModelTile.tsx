import type { FC, ReactNode } from "react";

interface Meter {
  value: number;          // 0..1 along the track: the puck
  mark?: number;          // 0..1: a dashed comparison mark (the book's chance, the season)
  scale?: [string, string, string];
  aria: string;
}

interface ModelTileProps {
  label: string;
  corner: string;
  big: string;
  meter?: Meter;
  children?: ReactNode;
}

const at = (x: number) => `${Math.max(0, Math.min(1, x)) * 100}%`;

/** A small rink-style track: a puck at the value, filled up to it unless a comparison mark is drawn instead. */
export const OddsMeter: FC<Meter> = ({ value, mark, aria }) => (
  <div className="pl-odds" role="img" aria-label={aria}>
    {mark === undefined && <i className="pl-odds-fill" style={{ width: at(value) }} />}
    {mark === undefined && <i className="pl-odds-half" />}
    {mark !== undefined && <i className="pl-odds-mark" style={{ left: at(mark) }} />}
    <i className="pl-odds-puck" style={{ left: at(value) }} />
  </div>
);

/** One stat the model predicts: the headline number, an optional meter, and the lines under it. */
export const ModelTile: FC<ModelTileProps> = ({ label, corner, big, meter, children }) => (
  <article className="pl-tile">
    <div className="pl-tile-top">
      <span className="bd-label" style={{ alignSelf: "auto" }}>{label}</span>
      <span className="pl-sub">{corner}</span>
    </div>
    <span className="pl-big">{big}</span>
    {meter && <OddsMeter {...meter} />}
    {meter?.scale && (
      <div className="pl-odds-scale">
        {meter.scale.map((s) => <span key={s}>{s}</span>)}
      </div>
    )}
    {children}
  </article>
);
