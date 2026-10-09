import type { FC, ReactNode } from "react";

interface RinkHeroProps {
  left: ReactNode;
  right: ReactNode;
  labelledBy?: string;
}

/** The page opener drawn as a rink, with a zone on each side of centre ice. One per page, first under the nav. */
export const RinkHero: FC<RinkHeroProps> = ({ left, right, labelledBy }) => (
  <section className="bd-rink" aria-labelledby={labelledBy}>
    <div className="bd-rink-marks" aria-hidden="true">
      <i className="bd-rink-goal-l" />
      <i className="bd-rink-goal-r" />
      <i className="bd-rink-blue-l" />
      <i className="bd-rink-blue-r" />
      <i className="bd-rink-center" />
      <i className="bd-rink-circle" />
      <i className="bd-rink-dot" />
      <i className="bd-rink-crease-l" />
      <i className="bd-rink-crease-r" />
    </div>
    <div className="bd-rink-content">
      <div className="bd-rink-zone">{left}</div>
      <div className="bd-rink-zone" style={{ textAlign: "right", gap: 6 }}>
        {right}
      </div>
    </div>
  </section>
);
