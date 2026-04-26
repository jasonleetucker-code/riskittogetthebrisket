"use client";

import { useState } from "react";

import { nflTeamLogoUrl } from "@/lib/player-images";

// NflTeamLogo — small standalone NFL-team-logo chip.  Falls back to a
// muted text badge with the team abbreviation when Sleeper has no
// logo (free agent / unknown team).  Used next to player names in
// rankings, trade trays, and player cards.
export default function NflTeamLogo({
  team,
  size = 16,
  className = "",
  style,
  showAbbr = false,
}) {
  const [errored, setErrored] = useState(false);
  const abbr = String(team || "").trim().toUpperCase();
  const url = errored ? "" : nflTeamLogoUrl(team);

  if (!url) {
    if (!abbr || abbr === "FA") return null;
    return (
      <span
        className={className}
        title={abbr}
        aria-label={abbr}
        style={{
          display: "inline-flex",
          alignItems: "center",
          justifyContent: "center",
          minWidth: size,
          height: size,
          padding: "0 4px",
          borderRadius: 4,
          background: "rgba(148, 163, 184, 0.16)",
          fontFamily: "var(--mono)",
          fontSize: Math.max(9, Math.round(size * 0.6)),
          fontWeight: 700,
          color: "var(--subtext)",
          flexShrink: 0,
          ...style,
        }}
      >
        {abbr}
      </span>
    );
  }

  if (showAbbr) {
    return (
      <span
        className={className}
        style={{
          display: "inline-flex",
          alignItems: "center",
          gap: 4,
          flexShrink: 0,
          ...style,
        }}
      >
        <img
          src={url}
          alt={`${abbr} logo`}
          title={abbr}
          loading="lazy"
          decoding="async"
          width={size}
          height={size}
          onError={() => setErrored(true)}
          style={{ width: size, height: size, objectFit: "contain" }}
        />
        <span style={{ fontFamily: "var(--mono)", fontSize: Math.max(9, size - 2), color: "var(--subtext)" }}>
          {abbr}
        </span>
      </span>
    );
  }

  return (
    <img
      src={url}
      alt={`${abbr} logo`}
      title={abbr}
      loading="lazy"
      decoding="async"
      width={size}
      height={size}
      onError={() => setErrored(true)}
      className={className}
      style={{
        width: size,
        height: size,
        objectFit: "contain",
        flexShrink: 0,
        ...style,
      }}
    />
  );
}
