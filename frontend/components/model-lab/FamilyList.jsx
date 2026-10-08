"use client";

/**
 * FamilyList — every model family the Lab reports, one dense row each.
 *
 * Every cell is a backend value or the backend's own state block.  The
 * family name links to its detail view (`?family=<id>`); the row itself is
 * not a second click target, so there is one keyboard path per family.
 */

import React from "react";
import Link from "next/link";
import { DataTable } from "@/components/ds/DataTable";
import { Badge } from "@/components/ds/Badge";
import { familyListRows, isStateBlock } from "@/lib/model-lab";
import { EvidenceValue, StateMark, cell } from "./EvidenceValue";
import styles from "./model-lab.module.css";

export const MODEL_LAB_HREF = "/admin/model-lab";

export function familyHref(id) {
  return `${MODEL_LAB_HREF}?family=${encodeURIComponent(id)}`;
}

function StateCounts({ states }) {
  if (isStateBlock(states)) return <StateMark block={states} />;
  // The list shows the states that hold at least one row; the detail view
  // lists all six (a real 0 included).  Hiding a zero here is brevity, not
  // coercion: the backend's counts are complete over an observed list.
  const shown = states.filter((s) => s.count !== 0);
  if (shown.length === 0) {
    return <span className={styles.num}>0 rows</span>;
  }
  return (
    <ul className={styles.countList}>
      {shown.map((s) => (
        <li key={s.state}>
          <span className={styles.num}>{String(s.count)}</span> {s.label.toLowerCase()}
        </li>
      ))}
    </ul>
  );
}

function Served({ row }) {
  return (
    <div className={styles.cellStack}>
      {row.flags.length ? (
        <ul className={styles.flagList}>
          {row.flags.map((f) => (
            <li key={f.flag}>
              <code className={styles.code}>{f.flag}</code>{" "}
              <Badge tone="outline">{f.word}</Badge>
            </li>
          ))}
        </ul>
      ) : null}
      {row.served !== null ? (
        <span className={styles.clamp}>
          <EvidenceValue value={row.served} />
        </span>
      ) : row.flags.length ? null : (
        <StateMark block={{ state: "unobserved", reason: "the family states no served side" }} />
      )}
    </div>
  );
}

const COLUMNS = [
  {
    key: "name",
    header: "Model family",
    render: cell((row) => (
      <div className={styles.cellStack}>
        <Link href={familyHref(row.id)} className={styles.familyLink}>
          {row.name}
        </Link>
        <code className={styles.code}>{row.id}</code>
      </div>
    )),
  },
  {
    key: "champion",
    header: "Champion",
    render: cell((row) => <EvidenceValue value={row.champion} />),
  },
  {
    key: "states",
    header: "Challenger states",
    hideBelow: "md",
    render: cell((row) => <StateCounts states={row.states} />),
  },
  {
    key: "lastEvaluated",
    header: "Last evaluated",
    hideBelow: "lg",
    render: cell((row) => (
      <div className={styles.cellStack}>
        <EvidenceValue value={row.lastEvaluated.at} />
        {row.lastEvaluated.by ? <span className={styles.muted}>{row.lastEvaluated.by}</span> : null}
      </div>
    )),
  },
  {
    key: "served",
    header: "Served now",
    hideBelow: "md",
    render: cell((row) => <Served row={row} />),
  },
  {
    key: "decision",
    header: "Why",
    render: cell((row) => (
      <span className={styles.clamp}>
        <EvidenceValue value={row.decision} />
      </span>
    )),
  },
];

export function FamilyList({ payload }) {
  const rows = familyListRows(payload);
  return (
    <DataTable
      caption="Model families: champion, challenger states, last evaluation, served side and decision reason"
      columns={COLUMNS}
      rows={rows}
      rowKey="id"
      density="compact"
    />
  );
}
