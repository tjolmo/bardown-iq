import type { FC } from "react";

const DEFAULT_HEADSHOT = "https://assets.nhle.com/mugs/nhl/default-player.png";

/** The player's headshot in a ringed disc, the league's blank one when it's missing or fails to load. */
export const Headshot: FC<{ player: { headshot: string | null }; size: number; className?: string }> = ({ player, size, className }) => (
  <span className={`lb-face${className ? ` ${className}` : ""}`} style={{ width: size, height: size }}>
    <img
      src={player.headshot ?? DEFAULT_HEADSHOT}
      alt=""
      loading="lazy"
      onError={(e) => {
        const img = e.currentTarget;
        if (img.src !== DEFAULT_HEADSHOT) img.src = DEFAULT_HEADSHOT;
      }}
    />
  </span>
);
