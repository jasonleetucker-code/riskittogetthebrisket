"use client";

// Schedule Multiverse (Schedule Intelligence Milestone B, read-only).
//
// Renders the timing_only_v1 block of the canonical schedule contract
// (src/public_league/schedule_timing.py via schedule_impact.season_contract):
// every score and every actual weekly pairing is kept, and only which week
// each pairing falls in changes.  Exact distributions come from the backend;
// nothing here computes one (lib/schedule-impact.js only formats).
//
// Separate from the equal-opponent table on purpose: a different model id,
// a different question, never blended into its numbers.

import { Banner, DataTable, HelpModal } from "@/components/ds";
import {
  fmtCount,
  fmtCredits,
  fmtExactCredits,
  fmtRecord,
  fmtShare,
  teamLabel,
  timingNotice,
} from "@/lib/schedule-impact";
import { ImpactValue } from "./ScheduleImpact";
import styles from "./ScheduleImpact.module.css";

/** Inline distribution: one bar per possible win total, the actual one marked. */
export function WinDistribution({ distribution, actual }) {
  if (!Array.isArray(distribution) || distribution.length === 0) return null;
  const barW = 6;
  const gap = 1;
  const h = 22;
  const max = Math.max(...distribution.map(([, p]) => p));
  const width = distribution.length * (barW + gap);
  const label = distribution
    .filter(([, p]) => p >= 0.005)
    .map(([x, p]) => `${x} wins ${fmtShare(p)}`)
    .join(", ");
  return (
    <svg
      className={styles.dist}
      width={width}
      height={h + 6}
      viewBox={`0 0 ${width} ${h + 6}`}
      role="img"
      aria-label={`Share of week orders by head-to-head wins: ${label}. Actual: ${actual}.`}
    >
      {distribution.map(([x, p], i) => {
        const bh = max > 0 ? Math.max(1, (p / max) * h) : 0;
        const isActual = Math.abs(x - actual) < 1e-9;
        return (
          <g key={x}>
            <rect
              x={i * (barW + gap)}
              y={h - bh}
              width={barW}
              height={bh}
              className={isActual ? styles.distActual : styles.distBar}
            />
            {isActual ? (
              <rect x={i * (barW + gap)} y={h + 2} width={barW} height={3} className={styles.distActual} />
            ) : null}
          </g>
        );
      })}
    </svg>
  );
}

export function ScheduleMultiverseMethod({ contract }) {
  const t = contract?.timingOnly;
  return (
    <HelpModal title="How the week-order view works" label="How this works">
      <p>
        Every team&apos;s weekly score stays exactly as it happened, and so does every matchup that
        was actually played. The only thing that changes is <em>which week</em> each set of matchups
        falls in. Each team keeps exactly the opponents it really had — including divisions and
        repeat opponents — just in a different order.
      </p>
      <ul>
        <li>
          Every ordering of the finished weeks is counted once and treated as equally likely
          {t?.totalCalendars ? ` (${fmtCount(t.totalCalendars)} orderings this season)` : ""}. The
          numbers are exact, not simulated.
        </li>
        <li>
          <strong>Average</strong> — the head-to-head wins those scores average across all
          orderings. <strong>More / fewer</strong> — the share of orderings that would have given
          more or fewer wins than actually happened.
        </li>
        <li>
          Median (league-average) games are not affected by opponent order and are left out.
        </li>
      </ul>
      <p>
        No week is treated as fixed in place, because the league does not publish one (for example a
        rivalry week). This looks back at finished games only; it is not a forecast, not a
        judgement of the manager, and not a schedule to adopt.
      </p>
      {t ? (
        <p className={styles.provenance}>
          Model {t.model?.id} · exact · weeks {t.permutedWeeks?.join(", ") || "—"} · version{" "}
          {t.algorithmVersion}
        </p>
      ) : null}
    </HelpModal>
  );
}

function timing(r) {
  return r?.timingOnly && r.timingOnly.state === "complete" ? r.timingOnly : null;
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
          {r.timingOnly && r.timingOnly.state !== "complete" ? (
            <span className={`${styles.muted} ${styles.note}`}>
              Not comparable: a bye changes this team&apos;s game count between week orders.
            </span>
          ) : null}
        </span>
      ),
    },
    {
      key: "actual",
      header: "H2H",
      accessor: (r) => r.actualH2HCredits,
      sortable: true,
      numeric: true,
      headerInfo: "Actual head-to-head record (median games excluded).",
      render: (r) => fmtRecord(r.h2hWins, r.h2hLosses, r.h2hTies),
    },
    {
      key: "shift",
      header: "Order",
      accessor: (r) => timing(r)?.impact ?? null,
      sortable: true,
      numeric: true,
      headerInfo: "Actual head-to-head wins minus the average across every week order.",
      render: (r) => (timing(r) ? <ImpactValue value={timing(r).impact} /> : "—"),
    },
    {
      key: "avg",
      header: (
        <span className={styles.stackedHead}>
          Avg wins<span className={styles.headSub}>all orders</span>
        </span>
      ),
      headerInfoLabel: "Average head-to-head wins across every week order",
      accessor: (r) => timing(r)?.expectedCredits ?? null,
      sortable: true,
      numeric: true,
      hideBelow: "sm",
      headerInfo: "Head-to-head wins the same scores and opponents average across every week order.",
      render: (r) => (timing(r) ? fmtCredits(timing(r).expectedCredits) : "—"),
    },
    {
      key: "dist",
      header: "Spread",
      accessor: (r) => timing(r)?.maxCredits ?? null,
      hideBelow: "md",
      headerInfo: "How often each win total occurs across week orders; the marked bar is what happened.",
      render: (r) =>
        timing(r) ? (
          <span className={styles.distCell}>
            <WinDistribution distribution={timing(r).distribution} actual={r.actualH2HCredits} />
            <span className={styles.muted}>
              {fmtExactCredits(timing(r).minCredits)}–{fmtExactCredits(timing(r).maxCredits)}
            </span>
          </span>
        ) : (
          "—"
        ),
    },
    {
      key: "more",
      header: "More / fewer",
      accessor: (r) => timing(r)?.probAboveActual ?? null,
      sortable: true,
      numeric: true,
      hideBelow: "lg",
      headerInfo: "Share of week orders giving more / fewer head-to-head wins than actually happened.",
      render: (r) =>
        timing(r) ? `${fmtShare(timing(r).probAboveActual)} / ${fmtShare(timing(r).probBelowActual)}` : "—",
    },
  ];
}

/** League-wide read-only week-order table. */
export function ScheduleMultiverseTable({ contract }) {
  const t = contract?.timingOnly;
  const notice = timingNotice(t);
  const rows = t?.state === "complete" ? contract?.teams || [] : [];
  return (
    <section className={styles.block} data-testid="schedule-multiverse" data-state={t?.state || "none"}>
      <header className={styles.head}>
        <h3 className={styles.title}>
          Same opponents, different weeks{contract?.season ? ` — ${contract.season}` : ""}
        </h3>
        <ScheduleMultiverseMethod contract={contract} />
      </header>
      <p className={styles.lede}>
        Keep every score and every matchup, and change only the week each matchup was played: how
        much did the order alone move each team&apos;s head-to-head wins?
      </p>
      {notice ? <Banner tone={notice.tone}>{notice.text}</Banner> : null}
      {rows.length ? (
        <DataTable
          columns={columns()}
          rows={rows}
          rowKey={(r) => r.teamKey}
          caption="Head-to-head wins across every week order"
          density="compact"
          defaultSort={{ key: "shift", direction: "desc" }}
        />
      ) : null}
    </section>
  );
}

