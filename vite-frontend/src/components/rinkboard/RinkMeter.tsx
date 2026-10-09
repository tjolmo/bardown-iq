import type { FC } from "react";

interface RinkMeterProps {
  // the away side's win probability, 0-1
  away: number;
  label: string;
}

/** A small rink: away's share of the ice on the left, home's on the right, the puck at the away win %. */
export const RinkMeter: FC<RinkMeterProps> = ({ away, label }) => {
  const awayPct = Math.round(away * 100);
  const homePct = 100 - awayPct;
  return (
    <div>
      <div
        className="bd-meter-track"
        role="img"
        aria-label={`${label}: away ${awayPct}%, home ${homePct}%`}
      >
        <i className="bd-meter-away" style={{ width: `${awayPct}%` }} />
        <i className="bd-meter-home" style={{ width: `${homePct}%` }} />
        <i className="bd-meter-blue" style={{ left: "33%" }} />
        <i className="bd-meter-red" />
        <i className="bd-meter-blue" style={{ left: "67%" }} />
        <i className="bd-meter-puck" style={{ left: `${awayPct}%` }} />
      </div>
      <div className="bd-meter-labels" aria-hidden="true">
        <span className="bd-away">{awayPct}%</span>
        <span className="bd-label">{label}</span>
        <span className="bd-home">{homePct}%</span>
      </div>
    </div>
  );
};
