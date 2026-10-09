import type { FC } from "react";
import { formatEdge } from "../../utils/gameStatus";

// an edge of 3 points or more is the strong chip
export const STRONG_EDGE_POINTS = 3;

interface EdgeChipProps {
  tricode: string;
  logoUrl: string;
  points: number;
}

/** How far the model's win probability sits above the no-vig market, for the side the model likes. */
export const EdgeChip: FC<EdgeChipProps> = ({ tricode, logoUrl, points }) => (
  <span className={`bd-edge${points >= STRONG_EDGE_POINTS ? " bd-edge-strong" : ""}`}>
    <span className="bd-edge-logo">
      <img src={logoUrl} alt="" />
    </span>
    Edge {tricode} {formatEdge(points)}
  </span>
);
