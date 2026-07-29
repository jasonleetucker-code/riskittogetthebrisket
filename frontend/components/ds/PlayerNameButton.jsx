/**
 * PlayerNameButton — a player's name, clickable, opening the detail popup.
 *
 * On /rankings, /edge, /finder and /news a player's name opens the
 * PlayerPopup.  On /trending, /rosters, /intel and /idptc-rookies the
 * same name was dead text — the pages render raw tables rather than ds
 * <DataTable>, so they never picked up the `colPlayer` cell that wires
 * the popup.  A user who learns "click the name" on one board and finds
 * it inert on the next concludes the site is broken, not that these are
 * different components.
 *
 * This is the shared version of that cell for pages that build their own
 * markup.  It stays a <button>, not a link: the popup is an overlay on
 * the current page, not a navigation, and dressing it as a link would
 * promise a URL that does not exist.
 *
 * Falls back to plain text when no handler is supplied — the popup is
 * unavailable on public routes (AppShell's openPlayerPopup no-ops there),
 * and an inert button that looks clickable is worse than text.
 */
"use client";

import React from "react";

export function PlayerNameButton({
  name,
  row,
  onOpen,
  className = "",
  children,
  ...rest
}) {
  const label = children ?? name;
  if (typeof onOpen !== "function") {
    return <span className={className}>{label}</span>;
  }
  return (
    <button
      type="button"
      className={`ds-player-name ${className}`.trim()}
      onClick={() => onOpen(row ?? name)}
      title={`Open ${name}`}
      {...rest}
    >
      {label}
    </button>
  );
}
