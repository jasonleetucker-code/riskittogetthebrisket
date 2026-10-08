"use client";

/**
 * FamilyDetail — one model family: decision, what is served and how it
 * would be rolled back, the champion, every challenger, the evaluation and
 * the evidence behind it.
 *
 * Loaded lazily by ModelLabWorkspace (React.lazy, not next/dynamic — see
 * CLAUDE.md "Perfect Draft": next/dynamic pulls Next's loadable runtime into
 * the shared graph).  The family list is the landing view, so this module
 * stays out of the page's first chunk.
 *
 * DISPLAY ONLY.  There is deliberately no promote / apply / rollback control
 * here: evaluation is not activation, and nothing self-promotes.  The
 * rollback block shows the backend's stated mechanism as text.
 */

import React, { useMemo, useState } from "react";
import Link from "next/link";
import { Panel } from "@/components/ds/Panel";
import { CollapsiblePanel } from "@/components/ds/CollapsiblePanel";
import { DataTable } from "@/components/ds/DataTable";
import { Badge } from "@/components/ds/Badge";
import { Button } from "@/components/ds/Button";
import { Field } from "@/components/ds/Input";
import { Select } from "@/components/ds/Select";
import {
  READ_ONLY_NOTE,
  challengerRows,
  challengerStateCounts,
  championVersion,
  isStateBlock,
  labStateLabel,
  lastEvaluated,
  selectChallengers,
} from "@/lib/model-lab";
import { EvidenceList, EvidenceValue, StateMark, cell } from "./EvidenceValue";
import { MODEL_LAB_HREF } from "./FamilyList";
import styles from "./model-lab.module.css";

/** Challenger rows rendered per page; "Show more" adds another page. */
export const CHALLENGER_PAGE = 25;

function Facts({ items }) {
  return (
    <dl className={styles.facts}>
      {items.map(([label, value]) => (
        <React.Fragment key={label}>
          <dt>{label}</dt>
          <dd>
            <EvidenceValue value={value} />
          </dd>
        </React.Fragment>
      ))}
    </dl>
  );
}

function LabStateBadge({ state }) {
  return <Badge tone={state === "CHAMPION" ? "accent" : "outline"}>{labStateLabel(state)}</Badge>;
}

function StateCountsFull({ counts }) {
  if (isStateBlock(counts)) return <StateMark block={counts} />;
  return (
    <ul className={styles.countList}>
      {counts.map((s) => (
        <li key={s.state}>
          <span className={styles.num}>{String(s.count)}</span> {s.label.toLowerCase()}
        </li>
      ))}
    </ul>
  );
}

function gateResult(gate) {
  if (isStateBlock(gate)) return gate;
  if (!gate || typeof gate !== "object") {
    return { state: "unobserved", reason: "the payload carries no gate block" };
  }
  if (gate.result === undefined) {
    return { state: "unobserved", reason: "the gate block records no result" };
  }
  return gate.result;
}

const CHALLENGER_COLUMNS = [
  {
    key: "version",
    header: "Version",
    render: cell((row) => <EvidenceValue value={row.version} />),
  },
  {
    key: "state",
    header: "Lab state",
    render: cell((row) => <LabStateBadge state={row.state} />),
  },
  {
    key: "nativeStatus",
    header: "Native status",
    hideBelow: "md",
    render: cell((row) => <EvidenceValue value={row.nativeStatus} />),
  },
  {
    key: "al0Verdict",
    header: "AL-0 verdict",
    hideBelow: "lg",
    render: cell((row) => <EvidenceValue value={row.al0Verdict} />),
  },
  {
    key: "createdAt",
    header: "Created",
    hideBelow: "lg",
    render: cell((row) => <EvidenceValue value={row.createdAt} />),
  },
  {
    key: "metrics",
    header: "Metrics",
    hideBelow: "md",
    render: cell((row) => <EvidenceValue value={row.metrics} depth={1} />),
  },
  {
    key: "reason",
    header: "Reason",
    render: cell((row) => <EvidenceValue value={row.reason} />),
  },
];

function Challengers({ family, labStates }) {
  const rows = challengerRows(family);
  const counts = challengerStateCounts(family, labStates);
  const [state, setState] = useState("ALL");
  const [limit, setLimit] = useState(CHALLENGER_PAGE);
  const selected = useMemo(
    () => (Array.isArray(rows) ? selectChallengers(rows, state) : []),
    [rows, state],
  );

  if (isStateBlock(rows)) {
    return (
      <Panel title="Challengers" headingLevel={3}>
        <StateMark block={rows} />
      </Panel>
    );
  }

  const options = [
    { value: "ALL", label: `All states (${rows.length})` },
    ...(Array.isArray(counts)
      ? counts.map((c) => ({ value: c.state, label: `${c.label} (${String(c.count)})` }))
      : []),
  ];
  const visible = selected.slice(0, limit);
  const remaining = selected.length - visible.length;

  return (
    <Panel
      title="Champion and challengers"
      subtitle="Every version the family has recorded, newest first. Rejected challengers are kept as evidence."
      headingLevel={3}
      actions={
        <Field label="Lab state">
          <Select
            value={state}
            onChange={(e) => {
              setState(e.target.value);
              setLimit(CHALLENGER_PAGE);
            }}
            options={options}
          />
        </Field>
      }
      flush
    >
      <DataTable
        caption="Challenger versions with lab state, native status, AL-0 verdict, metrics and reason"
        columns={CHALLENGER_COLUMNS}
        rows={visible}
        rowKey={(row, i) => `${isStateBlock(row.version) ? "v" : String(row.version)}:${i}`}
        density="compact"
        emptyState={
          <p className={styles.panelNote}>No challenger in the {labStateLabel(state).toLowerCase()} state.</p>
        }
      />
      <div className={styles.tableFooter}>
        <span className={styles.muted}>
          Showing <span className={styles.num}>{visible.length}</span> of{" "}
          <span className={styles.num}>{selected.length}</span>
        </span>
        {remaining > 0 ? (
          <Button size="sm" variant="secondary" onClick={() => setLimit((n) => n + CHALLENGER_PAGE)}>
            Show {Math.min(CHALLENGER_PAGE, remaining)} more
          </Button>
        ) : null}
      </div>
    </Panel>
  );
}

export default function FamilyDetail({ family, labStates }) {
  const evaluated = lastEvaluated(family.lastEvaluation);
  const name = typeof family.name === "string" && family.name ? family.name : family.family;

  return (
    <div className={styles.detail}>
      <nav aria-label="Model Lab" className={styles.crumbs}>
        <Link href={MODEL_LAB_HREF}>All model families</Link>
      </nav>

      <Panel title={name} subtitle={<code className={styles.code}>{family.family}</code>} headingLevel={2}>
        <div className={styles.decision}>
          <p className={styles.eyebrow}>Why</p>
          <div className={styles.lead}>
            <EvidenceValue value={family.decisionReason} />
          </div>
        </div>
        <Facts
          items={[
            ["Domain", family.domain],
            ["Champion", championVersion(family.champion)],
            ["Last evaluated", evaluated.at],
            [
              "Evaluated by",
              evaluated.by ??
                (isStateBlock(family.lastEvaluation)
                  ? family.lastEvaluation
                  : { state: "unobserved", reason: "the evaluation names no evaluator" }),
            ],
            ["Gate result", gateResult(family.gate)],
          ]}
        />
        <div className={styles.subBlock}>
          <p className={styles.eyebrow}>Lab states</p>
          <StateCountsFull counts={challengerStateCounts(family, labStates)} />
        </div>
      </Panel>

      <Panel title="Served now and rollback" headingLevel={3}>
        <p className={styles.panelNote} data-testid="read-only-note">
          {READ_ONLY_NOTE}
        </p>
        <Facts
          items={[
            ["Served now", family.productionState],
            ["How to roll back", family.rollback],
            ["Promotion authority", family.promotionAuthority],
          ]}
        />
      </Panel>

      <Panel title="Champion" subtitle="Training and evaluation windows, sample sizes, target and metrics" headingLevel={3}>
        <EvidenceValue value={family.champion} />
      </Panel>

      <Challengers family={family} labStates={labStates} />

      <Panel title="Evaluation" headingLevel={3}>
        <Facts
          items={[
            ["Last evaluation", family.lastEvaluation],
            ["Gate", family.gate],
            ["Calibration", family.calibration],
            ["Drift", family.drift],
          ]}
        />
      </Panel>

      <CollapsiblePanel title="Data quality and provenance" headingLevel={3} defaultCollapsed>
        <EvidenceList
          value={family}
          keys={["dataQuality", "receipts", "owners", "artifacts"]}
        />
      </CollapsiblePanel>
    </div>
  );
}
