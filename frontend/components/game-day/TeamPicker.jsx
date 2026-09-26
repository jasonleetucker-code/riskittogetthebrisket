"use client";

/**
 * TeamPicker — whose side Game Day is showing (owner directive 2026-09-25).
 *
 * Game Day answers for ANY roster in the selected league, not only the
 * viewer's own. This control chooses the perspective; it computes nothing.
 * The list is the backend's `leagueTeams` — the rosters of the very league
 * render the page was served from — so it cannot offer another league's
 * team, and choosing one is a `?team=<ownerId>` URL change the panel turns
 * into one request against the same league.
 *
 * It deliberately does NOT write the global "my team" (`useUserState`
 * selectedTeam): looking at a rival's matchup must not re-point /rosters,
 * /trade or the terminal at that rival.
 *
 * A native select (ds `Select`): keyboard, screen readers and phone pickers
 * work as the platform does. It stays mounted across a switch, so focus
 * stays on it while the next team's answer loads.
 */

import { useId } from "react";
import { Button, Select } from "@/components/ds";
import { teamOptionLabel } from "@/lib/game-day-view";
import styles from "./game-day.module.css";

export default function TeamPicker({ teams, value, myOwnerId = "", opponentOwnerId = "", onSelect }) {
  const selectId = useId();
  const hintId = useId();
  const current = teams.find((t) => t.ownerId && t.ownerId === value) || null;
  const mineListed = Boolean(myOwnerId) && teams.some((t) => t.ownerId === myOwnerId);
  const options = [
    ...(current ? [] : [{ value: "", label: "Choose a team", disabled: true }]),
    ...teams.map((t) => ({
      // An unmanaged roster is listed but cannot be addressed by owner.
      value: t.ownerId || `roster:${t.rosterId}`,
      label: teamOptionLabel(t, { myOwnerId, opponentOwnerId }),
      disabled: !t.ownerId,
    })),
  ];

  return (
    <div className={styles.teamPicker} data-game-day-team-picker="true">
      <label className={styles.teamPickerLabel} htmlFor={selectId}>
        Viewing team
      </label>
      <div className={styles.teamPickerControl}>
        <Select
          id={selectId}
          className={styles.teamPickerSelect}
          value={current ? current.ownerId : ""}
          aria-describedby={hintId}
          onChange={(e) => {
            const next = e.target.value;
            if (next && next !== value && !next.startsWith("roster:")) onSelect(next);
          }}
          options={options}
        />
      </div>
      {mineListed && value && value !== myOwnerId ? (
        <Button size="sm" variant="ghost" onClick={() => onSelect(myOwnerId)}>
          Back to my team
        </Button>
      ) : null}
      <p id={hintId} className={styles.teamPickerHint}>
        Any team in this league. Score, forecast and games switch to that side.
      </p>
    </div>
  );
}
