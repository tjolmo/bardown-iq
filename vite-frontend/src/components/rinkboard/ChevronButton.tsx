import type { FC } from "react";

interface ChevronButtonProps {
  direction: "previous" | "next";
  label: string;
  onClick: () => void;
}

/** A round chevron button. */
export const ChevronButton: FC<ChevronButtonProps> = ({ direction, label, onClick }) => (
  <button type="button" className="bd-icon-btn" aria-label={label} onClick={onClick}>
    <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.4" aria-hidden="true">
      <path d={direction === "previous" ? "M15 5l-7 7 7 7" : "M9 5l7 7-7 7"} />
    </svg>
  </button>
);
