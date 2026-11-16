"use client";

// The roster consequence of one generated trade (Wave B / C3-CAP-01).
//
// Display only: `capacity` is the backend's `rosterCapacity` block
// (src/trade/roster_capacity.py), worded by lib/trade-finder-capacity.  A
// missing or unavailable block renders as "not checked", never as silence —
// absent and "fits" must not look the same.

import { forcedReleaseSummary } from "@/lib/trade-finder-capacity";
import styles from "./trade-tool-notes.module.css";

export default function ForcedReleaseNote({ capacity, className = "" }) {
  const s = forcedReleaseSummary(capacity);
  const cls = [styles.note, s.tone === "warning" ? styles.warning : "", className]
    .filter(Boolean)
    .join(" ");
  return (
    <div className={cls} role="note" aria-label="Roster capacity" data-capacity-state={s.state}>
      <p className={styles.headline}>{s.headline}</p>
      {s.drops.length ? (
        <ul className={styles.drops} aria-label={s.dropsLabel || "Forced releases"}>
          {s.drops.map((d) => (
            <li key={d.key}>{`${d.label} — ${d.valueText}`}</li>
          ))}
        </ul>
      ) : null}
    </div>
  );
}
