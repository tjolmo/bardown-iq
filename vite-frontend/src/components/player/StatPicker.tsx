import type { FC } from "react";

/** The stat the last-five chart shows (and the season tables highlight). */
export const StatPicker: FC<{ options: { key: string; label: string }[]; value: string; onChange: (key: string) => void }> = ({ options, value, onChange }) => (
  <label className="pl-pick">
    <span className="bd-label">Stat</span>
    <select className="pl-select" value={value} onChange={(e) => onChange(e.target.value)}>
      {options.map((o) => <option key={o.key} value={o.key}>{o.label}</option>)}
    </select>
    <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.4" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
      <path d="m6 9 6 6 6-6" />
    </svg>
  </label>
);
