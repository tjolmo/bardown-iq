import type { FC, ReactNode } from "react";

export interface Cell {
  v: ReactNode;
  pre?: string;     // a small lead-in: "vs", "@"
  exp?: string;     // a small line under the value: what the model expected, "avg"
  cls?: string;
}

export interface TableSpec {
  label: string;
  grid: string;     // grid-template-columns, shared by every row
  minWidth: number;
  cols: { label: string; hl?: boolean }[];
  rows: { key: string | number; cells: Cell[] }[];
  foot?: Cell[];
}

const cellClass = (c: Cell, hl: boolean | undefined) => `pl-c${c.cls ? ` ${c.cls}` : ""}${hl ? " pl-hl" : ""}`;

const CellView: FC<{ c: Cell; hl?: boolean }> = ({ c, hl }) => (
  <span className={cellClass(c, hl)} role="cell">
    {c.pre && <small>{c.pre}</small>}
    {c.v}
    {c.exp && <span className="pl-c-exp">{c.exp}</span>}
  </span>
);

/** A stat table drawn as one grid per row, so a wide table scrolls inside its own box and a column (the picked
 *  stat) can be highlighted top to bottom. `flush` drops the outer padding, for a table inside a panel. */
export const StatTable: FC<{ spec: TableSpec; flush?: boolean }> = ({ spec, flush }) => (
  <div className={`pl-gt${flush ? " pl-flush" : ""}`} role="table" aria-label={spec.label} style={{ minWidth: spec.minWidth }}>
    <div className="pl-tr pl-th" role="row" style={{ gridTemplateColumns: spec.grid }}>
      {spec.cols.map((c, i) => (
        <span key={i} className={`pl-c${c.hl ? " pl-hl" : ""}`} role="columnheader">{c.label}</span>
      ))}
    </div>
    {spec.rows.map((r) => (
      <div className="pl-tr" role="row" key={r.key} style={{ gridTemplateColumns: spec.grid }}>
        {r.cells.map((c, i) => <CellView key={i} c={c} hl={spec.cols[i]?.hl} />)}
      </div>
    ))}
    {spec.foot && (
      <div className="pl-tr pl-tf" role="row" style={{ gridTemplateColumns: spec.grid }}>
        {spec.foot.map((c, i) => <CellView key={i} c={c} hl={spec.cols[i]?.hl} />)}
      </div>
    )}
  </div>
);
