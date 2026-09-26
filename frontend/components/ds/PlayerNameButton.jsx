/**
 * PlayerNameButton — THE canonical player-name primitive (#1337).
 *
 * One component answers "what happens when someone clicks a player's
 * name", so no page builds its own `/players/...` URL.  Three outcomes,
 * decided in this order:
 *
 *   1. `playerId` present  → a real link to the Universal Player Profile /
 *      Player File, `/players/[playerId]`.  #1337: "route it to that
 *      player's canonical Universal Player Profile / Player File", and the
 *      destination is that route.  It is a link, not a button, because it
 *      IS a navigation: middle-click, open-in-new-tab, copy-link and deep
 *      links all work, which a click handler cannot give.
 *   2. no id, `onOpen` given → the legacy quick-view button (PlayerPopup).
 *      Kept for callers whose data carries no canonical id yet — the
 *      popup resolves the row itself, so behaviour there is unchanged.
 *   3. neither            → plain text.  An inert control that looks
 *      clickable is worse than text.
 *
 * IDENTITY RULE.  The id must be the canonical one the data already
 * carries (Sleeper playerId — the key `/players/[playerId]` looks up
 * first).  Never pass a display name as `playerId`, and never resolve a
 * name to an id by guessing: two players can share a name, and a missing
 * link is better than a link to the wrong player.  `canonicalPlayerId`
 * reads only id fields, never `name`.
 *
 * NESTING RULE.  This renders an interactive element.  Never place it
 * inside another <a> or <button> (e.g. a whole-row trigger button); a
 * surface built that way has to be restructured, not wrapped.  Inside a
 * ds <DataTable> row with `onRowClick` it is fine: the table ignores
 * activations that originate in links.
 *
 * `prefetch={false}`: a board renders hundreds of these, and prefetching
 * every Player File on viewport entry would cost far more than the one
 * click it speeds up.
 */
"use client";

import React from "react";
import Link from "next/link";

/**
 * The canonical player id carried by a row-like object, or null.
 * Board rows keep it under `raw.playerId` (buildRows) and flat payloads
 * under `playerId`.  Reads ONLY id fields — a name is never an id.
 */
export function canonicalPlayerId(source) {
  if (source == null) return null;
  if (typeof source === "string" || typeof source === "number") {
    const s = String(source).trim();
    return s || null;
  }
  const candidate = source?.raw?.playerId ?? source?.playerId;
  if (candidate == null) return null;
  const s = String(candidate).trim();
  return s || null;
}

/** `/players/[playerId]` for a canonical id, or null without one. */
export function playerProfileHref(playerId) {
  const id = canonicalPlayerId(playerId);
  return id ? `/players/${encodeURIComponent(id)}` : null;
}

export function PlayerNameButton({
  name,
  row,
  playerId,
  onOpen,
  className = "",
  children,
  title,
  ...rest
}) {
  const label = children ?? name;
  const href = playerProfileHref(playerId);
  if (href) {
    return (
      <Link
        href={href}
        prefetch={false}
        className={`ds-player-name ${className}`.trim()}
        title={title ?? (name ? `Open ${name}'s Player File` : undefined)}
        {...rest}
      >
        {label}
      </Link>
    );
  }
  if (typeof onOpen !== "function") {
    return <span className={className || undefined}>{label}</span>;
  }
  return (
    <button
      type="button"
      className={`ds-player-name ${className}`.trim()}
      onClick={() => onOpen(row ?? name)}
      title={title ?? `Open ${name}`}
      {...rest}
    >
      {label}
    </button>
  );
}
