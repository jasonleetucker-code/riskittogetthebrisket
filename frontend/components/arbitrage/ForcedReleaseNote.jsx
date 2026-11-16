"use client";

// The roster consequence of one generated trade (Wave B / C3-CAP-01).
//
// Display only: `capacity` is the backend's `rosterCapacity` block
// (src/trade/roster_capacity.py), worded by lib/trade-finder-capacity — the
// one display rule for every generated-trade surface.  A missing or
// unavailable block renders as "not checked", never as silence — absent and
// "fits" must not look the same.
//
// `team` names whose roster it is (a counterparty's); omitted, it is yours.
// `label` is an optional visible lead-in ("Your roster").

import { useId } from "react";
import { forcedReleaseSummary } from "@/lib/trade-finder-capacity";
import styles from "./trade-tool-notes.module.css";

export default function ForcedReleaseNote({ capacity, team = null, label = null, className = "" }) {
  const s = forcedReleaseSummary(capacity, { team });
  const listLabelId = useId();
  const cls = [styles.note, s.tone === "warning" ? styles.warning : "", className]
    .filter(Boolean)
    .join(" ");
  return (
    <div
      className={cls}
      role="note"
      aria-label={label ? `${label} capacity` : "Roster capacity"}
      data-capacity-state={s.state}
    >
      <p className={styles.headline}>
        {label ? <span className={styles.lead}>{`${label}: `}</span> : null}
        {s.headline}
      </p>
      {s.context ? <p className={styles.context}>{s.context}</p> : null}
      {s.drops.length ? (
        <>
          {/* Visible, not only an aria-label: "Worst case" and "Released"
              say different things about the same list. */}
          <p className={styles.dropsLabel} id={listLabelId}>
            {s.dropsLabel || "Forced releases"}
          </p>
          <ul className={styles.drops} aria-labelledby={listLabelId}>
            {s.drops.map((d) => (
              <li key={d.key}>{`${d.label} — ${d.valueText}`}</li>
            ))}
          </ul>
        </>
      ) : null}
    </div>
  );
}
