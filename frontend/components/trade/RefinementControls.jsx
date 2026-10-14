"use client";

// LOCK / EXCLUDE / Skip controls for generated trades (C3-CON-03).
//
// Pure display: state lives in the page (lib/trade-refinement.js) and every
// change regenerates through the server's one constraint owner.  Buttons carry
// text labels and aria-pressed, never colour alone.

import { refinementState } from "@/lib/trade-refinement";
import styles from "./refinement-controls.module.css";

/** Outgoing asset: LOCK (must stay in the package) or EXCLUDE (keep it out). */
export function OutgoingRefinement({ name, refinement, onLock, onExclude, disabled = false }) {
  if (!name) return null;
  const state = refinementState(refinement, name);
  return (
    <span className={styles.group} role="group" aria-label={`Refine ${name}`}>
      <button
        type="button"
        className={styles.toggle}
        aria-pressed={state === "lock"}
        aria-label={state === "lock" ? `Unlock ${name}` : `Lock ${name} into every package`}
        title="Lock: keep this player in every regenerated package"
        disabled={disabled}
        onClick={() => onLock(name)}
      >
        Lock
      </button>
      <button
        type="button"
        className={styles.toggle}
        aria-pressed={state === "exclude"}
        aria-label={
          state === "exclude" ? `Stop excluding ${name}` : `Exclude ${name} from outgoing packages`
        }
        title="Exclude: keep this player out of regenerated packages (temporary)"
        disabled={disabled}
        onClick={() => onExclude(name)}
      >
        Exclude
      </button>
    </span>
  );
}

/** Incoming asset: a session-only search filter, never a constraint. */
export function IncomingSkip({ name, refinement, onSkip, disabled = false }) {
  if (!name) return null;
  const skipped = refinementState(refinement, name) === "skip";
  return (
    <button
      type="button"
      className={styles.toggle}
      aria-pressed={skipped}
      aria-label={skipped ? `Target ${name} again` : `Don't target ${name} in this scan`}
      title="Skip target: leave this player out of this scan's results"
      disabled={disabled}
      onClick={() => onSkip(name)}
    >
      Skip
    </button>
  );
}

/** Active refinements, each removable, plus a single Clear. */
export function RefinementBar({ refinement, onLock, onExclude, onSkip, onClear, disabled = false }) {
  const groups = [
    // Chip names differ from the card toggles' pressed names so each control
    // is uniquely addressable by assistive technology.
    { label: "Locked", names: refinement?.lock || [], undo: onLock, verb: "Remove lock:" },
    { label: "Excluded", names: refinement?.exclude || [], undo: onExclude, verb: "Remove exclusion:" },
    { label: "Skipped targets", names: refinement?.skip || [], undo: onSkip, verb: "Remove skip:" },
  ].filter((g) => g.names.length);
  if (!groups.length) return null;
  return (
    <div className={styles.bar} aria-label="Active refinements">
      {groups.map((g) => (
        <div key={g.label} className={styles.barGroup}>
          <span className={styles.barLabel}>{g.label}:</span>
          {g.names.map((name) => (
            <button
              key={name}
              type="button"
              className={styles.chip}
              aria-label={`${g.verb} ${name}`}
              disabled={disabled}
              onClick={() => g.undo(name)}
            >
              {name} <span aria-hidden="true">×</span>
            </button>
          ))}
        </div>
      ))}
      <button type="button" className={styles.clear} disabled={disabled} onClick={onClear}>
        Clear refinements
      </button>
    </div>
  );
}
