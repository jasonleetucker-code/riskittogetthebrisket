// Pure helpers for Sleeper-hosted player + NFL team images.
//
// Sleeper publishes per-player headshots and per-NFL-team logos at
// stable CDN URLs.  We use them throughout the UI so player rows in
// rankings, trade trays, popups, league franchises etc. all show the
// same image without us having to host or upload anything.
//
// CDN URL conventions
// ───────────────────
// * Player headshot     https://sleepercdn.com/content/nfl/players/{playerId}.jpg
// * Player thumb        https://sleepercdn.com/content/nfl/players/thumb/{playerId}.jpg
// * NFL team logo       https://sleepercdn.com/images/team_logos/nfl/{abbr_lower}.png
// * Sleeper user avatar https://sleepercdn.com/avatars/thumbs/{avatar_id}
//   (already covered by ``avatarUrlFor`` in app/league/shared-helpers.js)
//
// All helpers are zero-cost when the input is missing — they return
// the empty string so consumers can render a placeholder instead.
// Sleeper returns a default silhouette JPG when the playerId is
// unknown, but we guard the call so we don't fire a CDN miss for
// things like draft picks (no playerId at all).

const SLEEPER_CDN = "https://sleepercdn.com";

/** Map an NFL team abbreviation to Sleeper's logo CDN URL. */
export function nflTeamLogoUrl(team) {
  if (!team || typeof team !== "string") return "";
  const abbr = team.trim().toLowerCase();
  if (!abbr || abbr === "fa" || abbr === "free agent") return "";
  return `${SLEEPER_CDN}/images/team_logos/nfl/${abbr}.png`;
}

/** Sleeper player headshot URL.  ``size`` may be ``"full"`` or ``"thumb"``. */
export function playerHeadshotUrl(playerId, size = "thumb") {
  if (!playerId) return "";
  const id = String(playerId).trim();
  if (!id) return "";
  if (size === "full") {
    return `${SLEEPER_CDN}/content/nfl/players/${id}.jpg`;
  }
  return `${SLEEPER_CDN}/content/nfl/players/thumb/${id}.jpg`;
}

/** Position-tinted background for the placeholder circle.  Mirrors the
 *  position-color tokens used on rankings so a fallback chip feels
 *  visually consistent with the rest of the row. */
export function positionTint(pos) {
  switch (String(pos || "").toUpperCase()) {
    case "QB":
      return "rgba(244, 114, 182, 0.18)"; // pink
    case "RB":
      return "rgba(74, 222, 128, 0.18)"; // green
    case "WR":
      return "rgba(96, 165, 250, 0.18)"; // blue
    case "TE":
      return "rgba(251, 191, 36, 0.18)"; // amber
    case "K":
      return "rgba(168, 162, 158, 0.18)"; // stone
    case "DL":
      return "rgba(248, 113, 113, 0.18)"; // red
    case "LB":
      return "rgba(192, 132, 252, 0.18)"; // purple
    case "DB":
      return "rgba(125, 211, 252, 0.18)"; // sky
    case "PICK":
      return "rgba(148, 163, 184, 0.18)"; // slate — matches rookie pick chips
    default:
      return "rgba(148, 163, 184, 0.18)";
  }
}

/** Two-letter initials from a player display name.  Used for the
 *  text fallback when no image loads.
 *
 *  Skips trailing suffixes (Jr., Sr., II, III) so "Patrick Mahomes II"
 *  becomes "PM" not "PI".
 */
export function playerInitials(name) {
  if (!name) return "";
  const s = String(name).trim();
  if (!s) return "";
  const parts = s.split(/\s+/).filter((p) => {
    if (!p) return false;
    const norm = p.replace(/[.,]/g, "").toLowerCase();
    return !["jr", "sr", "ii", "iii", "iv"].includes(norm);
  });
  if (parts.length === 0) return s.slice(0, 2).toUpperCase();
  if (parts.length === 1) return parts[0].slice(0, 2).toUpperCase();
  return (parts[0][0] + parts[parts.length - 1][0]).toUpperCase();
}
