"use client";

// Schedule Intelligence UI foundation (Milestone A, Lane 6).
//
// Reusable, contract-driven pieces for every surface that shows schedule
// impact: the League Hub table (Luck tab today), the compact team summary
// (team pages, Milestone C) and the methodology disclosure.  They render the
// canonical contract from src/public_league/schedule_impact.py verbatim —
// no metric is computed here (lib/schedule-impact.js only formats).
//
// Hierarchy (owner directive): actual record → expected head-to-head wins
// and schedule impact → one plain-English reading → method on demand.

import { Banner, DataTable, HelpModal } from "@/components/ds";
import {
  excludedNote,
  fmtCredits,
  fmtRate,
  fmtRecord,
  fmtSignedCredits,
  impactDirection,
  interpretation,
  medianRecord,
  officialRecord,
  recordSortValue,
  stateNotice,
  teamLabel,
} from "@/lib/schedule-impact";
import styles from "./ScheduleImpact.module.css";

const GLYPH = { up: "▲", down: "▼", flat: "–", none: "" };

export function ImpactValue({ value }) {
  const dir = impactDirection(value);
  return (
    <span className={`${styles.impact} ${styles[dir] || ""}`} data-direction={dir}>
      {dir !== "none" ? (
        <span aria-hidden="true" className={styles.glyph}>
          {GLYPH[dir]}
        </span>
      ) : null}
      {fmtSignedCredits(value)}
    </span>
  );
}

/** Methodology disclosure — what is fixed, what varies, what it is not. */
export function ScheduleImpactMethod({ contract }) {
  return (
    <HelpModal title="How schedule impact works" label="How this works">
      <p>
        Every team&apos;s weekly score stays exactly as it happened. The only thing that changes is
        who they played. In each finished week, each team that played a head-to-head game is treated
        as an equally likely opponent.
      </p>
      <ul>
        <li>
          <strong>All-play</strong> — the team&apos;s record if it had played every other team that
          week.
        </li>
        <li>
          <strong>Expected wins</strong> — the head-to-head wins those same scores average against an
          equally likely opponent (the sum of the weekly all-play rates). It can be a fraction: it is
          an average, not a record.
        </li>
        <li>
          <strong>Schedule impact</strong> — actual head-to-head wins minus expected wins. Positive
          means the schedule helped; negative means it cost wins.
        </li>
      </ul>
      <p>
        Median (league-average) games are a separate part of the official record. Changing an
        opponent cannot change a median result, so they are never counted as schedule effects.
      </p>
      <p>
        This looks back at finished games; it is not a forecast and says nothing about a
        manager&apos;s skill. It is not a schedule to adopt — no schedule is created or changed.
      </p>
      {contract ? (
        <p className={styles.provenance}>
          Model {contract.model?.id} · exact calculation · weeks {contract.finalizedWeeks?.join(", ") || "—"} ·
          version {contract.algorithmVersion}
        </p>
      ) : null}
    </HelpModal>
  );
}

function columns() {
  return [
    {
      key: "team",
      header: "Team",
      accessor: (r) => teamLabel(r),
      sortable: true,
      render: (r) => (
        <span>
          <span className={styles.team}>{teamLabel(r)}</span>
          {excludedNote(r) ? <span className={`${styles.muted} ${styles.note}`}>{excludedNote(r)}</span> : null}
        </span>
      ),
    },
    {
      key: "official",
      header: "Record",
      accessor: (r) => officialRecord(r),
      sortAccessor: (r) => recordSortValue(r),
      sortable: true,
      numeric: true,
      headerInfo: "The official league record, including any median games.",
      render: (r) => officialRecord(r),
    },
    {
      key: "h2h",
      header: "H2H",
      accessor: (r) => r.actualH2HCredits,
      sortable: true,
      numeric: true,
      hideBelow: "sm",
      headerInfo: "Head-to-head games only (median games excluded).",
      render: (r) => fmtRecord(r.h2hWins, r.h2hLosses, r.h2hTies),
    },
    {
      key: "allPlay",
      header: "All-play",
      accessor: (r) => r.allPlayRate,
      sortable: true,
      numeric: true,
      hideBelow: "md",
      headerInfo: "Record if the team had played every other team each week.",
      render: (r) => (
        <span>
          {fmtRecord(r.allPlayWins, r.allPlayLosses, r.allPlayTies)}{" "}
          <span className={styles.muted}>{fmtRate(r.allPlayRate)}</span>
        </span>
      ),
    },
    {
      key: "expected",
      header: "Exp. wins (equal opp.)",
      accessor: (r) => r.equalOpponentExpectedH2HCredits,
      sortable: true,
      numeric: true,
      headerInfo:
        "Head-to-head wins the same scores average against an equally likely opponent each week.",
      render: (r) => fmtCredits(r.equalOpponentExpectedH2HCredits),
    },
    {
      key: "impact",
      header: "Schedule",
      accessor: (r) => r.scheduleImpact,
      sortable: true,
      numeric: true,
      headerInfo: "Actual head-to-head wins minus expected wins.",
      render: (r) => <ImpactValue value={r.scheduleImpact} />,
    },
    {
      key: "opp",
      header: "Opp. strength",
      accessor: (r) => r.avgOpponentScorePercentile,
      sortable: true,
      numeric: true,
      hideBelow: "lg",
      headerInfo:
        "How the opponents actually faced scored that week compared with the other possible opponents (50% is average).",
      render: (r) => fmtRate(r.avgOpponentScorePercentile),
    },
  ];
}

/** League-wide sortable table — every team, one row each. */
export function ScheduleImpactTable({ contract, caption }) {
  const notice = stateNotice(contract);
  const rows = contract?.teams || [];
  return (
    <section className={styles.block} data-testid="schedule-impact" data-state={contract?.state || "none"}>
      <header className={styles.head}>
        <h3 className={styles.title}>Schedule impact{contract?.season ? ` — ${contract.season}` : ""}</h3>
        <ScheduleImpactMethod contract={contract} />
      </header>
      <p className={styles.lede}>
        Same weekly scores, different opponents: how many head-to-head wins each team&apos;s scores
        would average against an equally likely opponent, and how far the actual schedule moved them.
      </p>
      {notice ? <Banner tone={notice.tone}>{notice.text}</Banner> : null}
      {rows.length ? (
        <DataTable
          columns={columns()}
          rows={rows}
          rowKey={(r) => r.teamKey}
          caption={caption || "Schedule impact by team"}
          density="compact"
          defaultSort={{ key: "impact", direction: "desc" }}
        />
      ) : null}
    </section>
  );
}

/** Compact team block (team pages; Milestone C wiring). */
export function ScheduleImpactSummary({ row, contract }) {
  if (!row) {
    const notice = stateNotice(contract) || { text: "No schedule impact for this team yet." };
    return (
      <section className={styles.summary} data-testid="schedule-impact-summary" data-state="unavailable">
        <p className={styles.muted}>{notice.text}</p>
      </section>
    );
  }
  const median = medianRecord(row);
  return (
    <section className={styles.summary} data-testid="schedule-impact-summary" data-state={contract?.state}>
      <dl className={styles.figures}>
        <div>
          <dt>Record</dt>
          <dd>
            {officialRecord(row)}
            {median ? <span className={styles.muted}> (median {median})</span> : null}
          </dd>
        </div>
        <div>
          <dt>Expected H2H wins (equal-opponent)</dt>
          <dd>{fmtCredits(row.equalOpponentExpectedH2HCredits)}</dd>
        </div>
        <div>
          <dt>Schedule impact</dt>
          <dd>
            <ImpactValue value={row.scheduleImpact} />
          </dd>
        </div>
      </dl>
      <p className={styles.reading}>{interpretation(row)}</p>
    </section>
  );
}
