"use client";

import { useState } from "react";

import {
  playerHeadshotUrl,
  nflTeamLogoUrl,
  positionTint,
  playerInitials,
} from "@/lib/player-images";

// PlayerImage — render a player's Sleeper headshot, with graceful fallbacks.
//
// Layered fallback chain (each step kicks in only if the previous fails):
//   1. Sleeper player headshot ("https://sleepercdn.com/content/nfl/players/{id}.jpg")
//   2. NFL team logo for the player's team
//   3. Position-tinted circle with the player's two-letter initials
//
// Picks (pos === "PICK") skip straight to step 3 with the pick name —
// nothing on the CDN to render for a draft pick.
//
// The component is tiny intentionally: a fixed-size circle, position
// tint behind whatever image lands, alt text always populated for
// screen readers.  Use ``size`` to scale; ``rounded={false}`` for
// square (use that for the Player Popup hero shot).
export default function PlayerImage({
  playerId,
  team,
  position,
  name,
  size = 28,
  rounded = true,
  className = "",
  showTeamFallback = true,
  style,
}) {
  // Stage tracks which fallback the component is currently rendering.
  // We bump it forward on each ``onError`` so we never loop.
  const [stage, setStage] = useState("headshot");
  const isPick = String(position || "").toUpperCase() === "PICK";
  const tint = positionTint(position);
  const initials = playerInitials(name);

  // Picks: skip straight to the initials chip.  Nothing on the CDN.
  if (isPick || !playerId) {
    return (
      <FallbackChip
        initials={initials || "PK"}
        tint={tint}
        size={size}
        rounded={rounded}
        className={className}
        style={style}
        title={name || ""}
      />
    );
  }

  if (stage === "headshot") {
    const src = playerHeadshotUrl(playerId, size > 64 ? "full" : "thumb");
    if (!src) {
      // No URL we could even attempt — go to next fallback.
      setStage(showTeamFallback ? "team" : "initials");
      return null;
    }
    return (
      <img
        src={src}
        alt={name || ""}
        title={name || ""}
        loading="lazy"
        decoding="async"
        width={size}
        height={size}
        onError={() => setStage(showTeamFallback ? "team" : "initials")}
        className={className}
        style={{
          width: size,
          height: size,
          borderRadius: rounded ? "50%" : 4,
          background: tint,
          objectFit: "cover",
          flexShrink: 0,
          ...style,
        }}
      />
    );
  }

  if (stage === "team") {
    const src = nflTeamLogoUrl(team);
    if (!src) {
      // No team to logo — go to initials.
      setStage("initials");
      return null;
    }
    return (
      <img
        src={src}
        alt={team ? `${team} logo` : ""}
        title={name || team || ""}
        loading="lazy"
        decoding="async"
        width={size}
        height={size}
        onError={() => setStage("initials")}
        className={className}
        style={{
          width: size,
          height: size,
          borderRadius: rounded ? "50%" : 4,
          background: tint,
          objectFit: "contain",
          padding: Math.max(2, Math.round(size * 0.12)),
          flexShrink: 0,
          ...style,
        }}
      />
    );
  }

  return (
    <FallbackChip
      initials={initials || "?"}
      tint={tint}
      size={size}
      rounded={rounded}
      className={className}
      style={style}
      title={name || ""}
    />
  );
}

function FallbackChip({ initials, tint, size, rounded, className, style, title }) {
  const fontSize = Math.max(10, Math.round(size * 0.42));
  return (
    <span
      className={className}
      title={title}
      aria-label={title}
      style={{
        display: "inline-flex",
        alignItems: "center",
        justifyContent: "center",
        width: size,
        height: size,
        borderRadius: rounded ? "50%" : 4,
        background: tint,
        color: "var(--text)",
        fontWeight: 700,
        fontSize,
        letterSpacing: "0.02em",
        textTransform: "uppercase",
        flexShrink: 0,
        ...style,
      }}
    >
      {initials}
    </span>
  );
}
