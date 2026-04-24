"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { useLeague } from "@/components/useLeague";

/**
 * LeagueSwitcher — dropdown that picks the active dynasty league.
 *
 * Renders nothing when only one league is configured (the common
 * case today) so it doesn't crowd the nav for single-league
 * deployments.  Once the operator activates a second league in
 * ``config/leagues/registry.json``, the switcher appears in both
 * the desktop top-bar and the mobile action rail.
 *
 * We never ask the user to type a league ID — they pick from the
 * list that the server already validated against the registry.
 *
 * Variants match ``TeamSwitcher`` for visual consistency.
 */
export default function LeagueSwitcher({ variant = "desktop" }) {
  const { leagues, selectedLeague, selectedLeagueKey, setLeague, loading } = useLeague();
  const [open, setOpen] = useState(false);
  const rootRef = useRef(null);

  useEffect(() => {
    if (!open) return undefined;
    function onDocClick(e) {
      if (!rootRef.current) return;
      if (rootRef.current.contains(e.target)) return;
      setOpen(false);
    }
    function onKey(e) {
      if (e.key === "Escape") setOpen(false);
    }
    document.addEventListener("mousedown", onDocClick);
    document.addEventListener("keydown", onKey);
    return () => {
      document.removeEventListener("mousedown", onDocClick);
      document.removeEventListener("keydown", onKey);
    };
  }, [open]);

  const choose = useCallback(
    (key) => {
      if (key && key !== selectedLeagueKey) setLeague(key);
      setOpen(false);
    },
    [setLeague, selectedLeagueKey],
  );

  // Hide when there's nothing to switch between.  Single-league
  // deployments never see the switcher; as soon as a second league
  // is flipped ``active: true`` in the registry the UI updates
  // automatically on the next ``/api/leagues`` refresh.
  if (loading) return null;
  if (!Array.isArray(leagues) || leagues.length < 2) return null;

  const label = selectedLeague?.displayName || "League";
  const classes = [
    "league-switcher",
    `league-switcher--${variant}`,
    open ? "league-switcher--open" : "",
  ]
    .filter(Boolean)
    .join(" ");

  return (
    <div ref={rootRef} className={classes}>
      <button
        type="button"
        className="league-switcher-toggle"
        aria-haspopup="listbox"
        aria-expanded={open}
        onClick={() => setOpen((v) => !v)}
        title={`Active league: ${label}`}
      >
        <span className="league-switcher-label">{label}</span>
        <span className="league-switcher-caret" aria-hidden="true">▾</span>
      </button>
      {open && (
        <ul className="league-switcher-menu" role="listbox">
          {leagues.map((lg) => {
            const active = lg.key === selectedLeagueKey;
            const formatBits = [];
            if (lg.idpEnabled) formatBits.push("IDP");
            const roster = lg.rosterSettings || {};
            if (roster.teamCount) formatBits.push(`${roster.teamCount} teams`);
            return (
              <li key={lg.key}>
                <button
                  type="button"
                  role="option"
                  aria-selected={active}
                  className={`league-switcher-option${active ? " is-active" : ""}`}
                  onClick={() => choose(lg.key)}
                >
                  <span className="league-switcher-option-name">
                    {lg.displayName || lg.key}
                  </span>
                  {formatBits.length > 0 && (
                    <span className="league-switcher-option-meta">
                      {formatBits.join(" · ")}
                    </span>
                  )}
                </button>
              </li>
            );
          })}
        </ul>
      )}
    </div>
  );
}
