"use client";

/**
 * EvidenceValue — renders ONE Model Lab field exactly as the backend wrote it.
 *
 * The Lab payload is heterogeneous by design: each family's owner states
 * its own evidence (a Hill holdout's per-board RMSE, a Consensus Edge ship
 * gate's bar, a flag record), so the renderer is structural rather than
 * per-field:
 *
 *   state block   -> its label ("Unobserved" / "Not applicable" /
 *                    "Unmeasured") + the backend's reason.  NEVER 0, "—"
 *                    or an empty cell: MISSING IS NEVER ZERO.
 *   instant       -> `<time>` in UTC, raw ISO kept in `dateTime`
 *   number        -> verbatim (no rounding, no arithmetic), tabular
 *   boolean       -> yes / no
 *   null          -> "none recorded" (the backend recorded null — e.g. a
 *                    point estimate with no interval — which is data, not
 *                    a missing field)
 *   string        -> text
 *   array         -> inline list for primitives, stacked blocks for objects
 *   object        -> a definition list, recursively
 *
 * Display only: nothing here computes a value.
 */

import React from "react";
import { Badge } from "@/components/ds/Badge";
import {
  formatInstant,
  humanizeKey,
  isInstantString,
  isStateBlock,
  stateBlockExtras,
  stateBlockLabel,
} from "@/lib/model-lab";
import styles from "./model-lab.module.css";

/** Arrays longer than this fold behind a native disclosure. */
const FOLD_AFTER = 12;

/**
 * DataTable cell wrapper: the legacy global `td { white-space: nowrap }`
 * (app/globals.css) would otherwise stretch a table to one line per reason.
 */
export function cell(render) {
  return function ModelLabCell(row, i) {
    return <div className={styles.cell}>{render(row, i)}</div>;
  };
}

export function StateMark({ block }) {
  return (
    <span className={styles.stateMark} data-testid="state-block" data-state={block.state}>
      <Badge tone="outline">{stateBlockLabel(block)}</Badge>
      <span className={styles.stateReason}>{String(block.reason)}</span>
    </span>
  );
}

function Primitive({ value }) {
  if (value === null || value === undefined) {
    return <span className={styles.muted}>none recorded</span>;
  }
  if (typeof value === "boolean") {
    return <span>{value ? "yes" : "no"}</span>;
  }
  if (typeof value === "number") {
    return <span className={styles.num}>{String(value)}</span>;
  }
  const text = String(value);
  if (isInstantString(text)) {
    const shown = formatInstant(text);
    if (shown) {
      return (
        <time className={styles.num} dateTime={text} title={text}>
          {shown}
        </time>
      );
    }
  }
  return <span className={styles.text}>{text}</span>;
}

function isPrimitive(v) {
  return v === null || v === undefined || typeof v !== "object";
}

function ArrayValue({ value, depth }) {
  if (value.length === 0) {
    return <span className={styles.muted}>empty list</span>;
  }
  const allPrimitive = value.every(isPrimitive);
  const body = allPrimitive ? (
    <ul className={styles.inlineList}>
      {value.map((v, i) => (
        <li key={i}>
          <Primitive value={v} />
        </li>
      ))}
    </ul>
  ) : (
    <ol className={styles.blockList}>
      {value.map((v, i) => (
        <li key={i}>
          <EvidenceValue value={v} depth={depth + 1} />
        </li>
      ))}
    </ol>
  );
  if (value.length <= FOLD_AFTER) return body;
  return (
    <details className={styles.fold}>
      <summary>{value.length} items</summary>
      {body}
    </details>
  );
}

export function EvidenceList({ value, depth = 0, keys }) {
  const entries = (keys || Object.keys(value)).filter((k) =>
    Object.prototype.hasOwnProperty.call(value, k),
  );
  if (entries.length === 0) {
    return <span className={styles.muted}>empty record</span>;
  }
  return (
    <dl className={depth > 0 ? `${styles.facts} ${styles.factsNested}` : styles.facts}>
      {entries.map((k) => (
        <React.Fragment key={k}>
          <dt>{humanizeKey(k)}</dt>
          <dd>
            <EvidenceValue value={value[k]} depth={depth + 1} />
          </dd>
        </React.Fragment>
      ))}
    </dl>
  );
}

export function EvidenceValue({ value, depth = 0 }) {
  if (isStateBlock(value)) {
    // A state block with siblings (the backend spreads `_flag_state()` into
    // productionState) is a state PLUS evidence: badge + reason, then the
    // remaining fields — never the badge alone.
    const extras = stateBlockExtras(value);
    if (!extras) return <StateMark block={value} />;
    return (
      <div className={styles.cellStack}>
        <StateMark block={value} />
        <EvidenceList value={extras} depth={depth} />
      </div>
    );
  }
  if (Array.isArray(value)) return <ArrayValue value={value} depth={depth} />;
  if (value && typeof value === "object") return <EvidenceList value={value} depth={depth} />;
  return <Primitive value={value} />;
}
