import type { FC } from "react";
import type { StatusChipInfo } from "../../utils/gameStatus";

const CLASS = { time: "bd-chip-time", live: "bd-chip-live", final: "bd-chip-final" } as const;

/** Game state: puck-drop time (outlined), LIVE with the period and clock (goal red), or FINAL (ink). */
export const StatusChip: FC<{ status: StatusChipInfo }> = ({ status }) => (
  <span className={`bd-chip ${CLASS[status.kind]}`} title={status.title}>
    {status.text}
  </span>
);
