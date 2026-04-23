"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { useTeam } from "@/components/useTeam";

/**
 * TeamSwitcher — dropdown that binds the signed-in user's "my team"
 * identity to the global useTeam state.
 *
 * Renders nothing on public-only routes or before sleeper.teams has
 * hydrated.  Auth-gating is the caller's responsibility (we expect
 * ``authenticated`` to already be true where this is mounted).
 *
 * Variants:
 *   - "desktop" (default): inline pill, fits into the topbar nav row
 *   - "mobile": compact, fits into the mobile top bar action slot
 */
export default function TeamSwitcher({ variant = "desktop" }) {
  const {
    availableTeams,
    selectedTeam,
    setSelectedTeam,
    needsSelection,
    privateDataEnabled,
  } = useTeam();
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
    (name) => {
      setSelectedTeam(name);
      setOpen(false);
    },
    [setSelectedTeam],
  );

  if (!privateDataEnabled) return null;
  if (!Array.isArray(availableTeams) || availableTeams.length === 0) return null;

  const label = selectedTeam?.name || (needsSelection ? "Pick your team" : "Team");
  const classes = [
    "team-switcher",
    `team-switcher--${variant}`,
    needsSelection ? "team-switcher--needs" : "",
    open ? "team-switcher--open" : "",
  ]
    .filter(Boolean)
    .join(" ");

  return (
    <div ref={rootRef} className={classes}>
      <button
        type="button"
        className="team-switcher-toggle"
        aria-haspopup="listbox"
        aria-expanded={open}
        onClick={() => setOpen((v) => !v)}
        title={selectedTeam?.name || "Select your team"}
      >
        <span className="team-switcher-label">{label}</span>
        <span className="team-switcher-caret" aria-hidden="true">▾</span>
      </button>
      {open && (
        <ul className="team-switcher-menu" role="listbox">
          {availableTeams.map((t) => {
            const name = t?.name || "";
            const active = selectedTeam?.name === name;
            const playerCount = Array.isArray(t?.players) ? t.players.length : 0;
            const pickCount = Array.isArray(t?.picks) ? t.picks.length : 0;
            return (
              <li key={name || t?.ownerId || Math.random()}>
                <button
                  type="button"
                  role="option"
                  aria-selected={active}
                  className={`team-switcher-option${active ? " is-active" : ""}`}
                  onClick={() => choose(name)}
                >
                  <span className="team-switcher-option-name">{name || "Unnamed"}</span>
                  <span className="team-switcher-option-meta">
                    {playerCount}p · {pickCount}pk
                  </span>
                </button>
              </li>
            );
          })}
        </ul>
      )}
    </div>
  );
}
