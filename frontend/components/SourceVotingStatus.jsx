"use client";

import { useCallback, useMemo, useState } from "react";
import { DataTable, FailureState, SkeletonTable, StatusIndicator } from "@/components/ds";
import {
  formatWeight,
  votingStatusAvailability,
  votingStatusRows,
  votingStatusSummary,
} from "@/lib/source-voting-status";
import styles from "./SourceVotingStatus.module.css";

/**
 * SourceVotingStatus — is each source voting, at what weight, and why.
 *
 * Owner directive 2026-10-19 §8: Source · Last Updated · Freshness ·
 * Voting Weight · Status, with the owner's plain status labels, a
 * plain-English reason on every row, and the technical detail one click
 * away.
 *
 * Rendering only.  `block` is the backend's voting-status object
 * (src/sources/voting_status.py) — from `/api/sources/weighting`'s
 * `votingStatus` on Source Health, from the contract's `sourceVotingStatus`
 * on Settings.  Every status, percentage, weight, day count and reason is
 * the backend's; lib/source-voting-status.js only labels and formats.
 *
 * Before the backend publishes the block, the component says so — it never
 * fabricates rows and never shows an absent freshness as 0%.
 *
 * Mobile: below 768px the three middle columns fold into a secondary line
 * under the source name, so the page never scrolls sideways and nothing is
 * hidden without a path to it (contract §6).
 */

const SCHEDULE_NOTE =
  "Voting power by days since the publisher's last genuine rankings update: " +
  "0–7 days 100% · 8–14 days 75% · 15–21 days 50% · 22–30 days 25% · " +
  "over 30 days not voting. Downloading unchanged rankings does not reset the clock.";

function capitalize(s) {
  return s ? s.charAt(0) + s.slice(1).toLowerCase() : s;
}

function detailId(key) {
  return `source-voting-detail-${String(key).replace(/[^A-Za-z0-9_-]/g, "-")}`;
}

function SourceCell({ row, open, onToggle }) {
  const meta = [row.coverageLabel, row.provider && row.provider !== row.label ? row.provider : null]
    .filter(Boolean)
    .join(" · ");
  return (
    <div className={styles.sourceCell}>
      <button
        type="button"
        className={styles.toggle}
        aria-expanded={open}
        aria-controls={open ? detailId(row.key) : undefined}
        onClick={() => onToggle(row.key)}
        data-testid={`source-voting-toggle-${row.key}`}
      >
        {/* Thin-ruled caret drawn in CSS: points right when collapsed,
            down when open. */}
        <span className={open ? styles.caretOpen : styles.caret} aria-hidden="true" />
        <span className={styles.sourceName}>{row.label}</span>
      </button>
      {meta ? <span className={styles.sourceMeta}>{meta}</span> : null}
      {/* Below 768px the Last Updated / Freshness / Voting Weight columns are
          hidden; the same three values ride here instead. */}
      <span className={styles.mobileFacts} data-testid={`source-voting-mobile-${row.key}`}>
        Updated {row.lastUpdatedLabel}
        {row.agoLabel ? ` (${row.agoLabel})` : ""} · Freshness {row.freshnessLabel} · Weight{" "}
        {formatWeight(row.effectiveWeight)}
      </span>
    </div>
  );
}

function DetailItem({ term, children }) {
  return (
    <div className={styles.detailItem}>
      <dt>{term}</dt>
      <dd>{children}</dd>
    </div>
  );
}

function SourceDetail({ row }) {
  const f = row.factors;
  const factorParts = [
    f.freshness != null ? `freshness ${formatWeight(f.freshness)}` : null,
    f.health != null ? `data quality ${formatWeight(f.health)}` : null,
    f.coverage != null ? `board size ${formatWeight(f.coverage)}` : null,
  ].filter(Boolean);
  const universes = [
    row.contributing.offense ? `Offense ${row.contributing.offense.toLocaleString()}` : null,
    row.contributing.idp ? `IDP ${row.contributing.idp.toLocaleString()}` : null,
  ].filter(Boolean);
  return (
    <dl className={styles.detail}>
      {row.restoreRequirement ? (
        <DetailItem term="What would change this">{row.restoreRequirement}</DetailItem>
      ) : null}
      <DetailItem term="Last genuine update">
        {row.lastUpdatedLabel}
        {row.agoLabel ? ` (${row.agoLabel})` : ""} — based on {row.basisLabel}.
      </DetailItem>
      <DetailItem term="Freshness">{row.freshnessLabel}</DetailItem>
      <DetailItem term="Voting weight">
        {formatWeight(row.effectiveWeight)} of a {formatWeight(row.baseWeight)} base weight
        {factorParts.length && f.applied !== false ? (
          <span className={styles.detailNote}>
            Base weight × {factorParts.join(" × ")}.
          </span>
        ) : null}
        {f.applied === false ? (
          <span className={styles.detailNote}>
            Freshness weighting is switched off for this board.
          </span>
        ) : null}
      </DetailItem>
      {row.meanAppliedWeight != null ? (
        <DetailItem term="Average weight per player">
          {formatWeight(row.meanAppliedWeight)}
          <span className={styles.detailNote}>
            After sources from the same provider share one provider&apos;s vote.
          </span>
        </DetailItem>
      ) : null}
      <DetailItem term="Players counted">
        {row.playersContributing == null ? "Unknown" : row.playersContributing.toLocaleString()}
        {universes.length ? <span className={styles.detailNote}>{universes.join(" · ")}</span> : null}
      </DetailItem>
      {row.picksContributing || row.picks ? (
        <DetailItem term="Picks counted">
          {row.picksContributing == null ? "Unknown" : row.picksContributing.toLocaleString()}
          {row.picks ? (
            <span className={styles.detailNote}>
              Pick prices last updated {row.picks.lastUpdatedLabel}
              {row.picks.agoLabel ? ` (${row.picks.agoLabel})` : ""} · freshness{" "}
              {row.picks.freshnessLabel} · weight {formatWeight(row.picks.effectiveWeight)}
            </span>
          ) : null}
        </DetailItem>
      ) : null}
      {row.notVotingRows.length ? (
        <DetailItem term="Rows not counted">
          <ul className={styles.reasonList}>
            {row.notVotingRows.map((n) => (
              <li key={n.reason}>
                <span className={styles.num}>{n.count.toLocaleString()}</span> — {n.label}
              </li>
            ))}
          </ul>
        </DetailItem>
      ) : null}
      {row.voteHold ? (
        <DetailItem term="Vote hold">
          {row.voteHold.decision || row.voteHold.reason || "Held from voting"}
          {row.voteHold.rollbackFlag ? (
            <span className={styles.detailNote}>Switch: {row.voteHold.rollbackFlag}</span>
          ) : null}
        </DetailItem>
      ) : null}
      {row.provider || row.family ? (
        <DetailItem term="Provider">
          {row.provider || "Unknown"}
          {row.family ? <span className={styles.detailNote}>Family: {row.family}</span> : null}
        </DetailItem>
      ) : null}
      {row.coverageLabel ? <DetailItem term="Covers">{row.coverageLabel}</DetailItem> : null}
      {row.health ? <DetailItem term="Latest download">{capitalize(row.health)}</DetailItem> : null}
      <DetailItem term="Source key">
        <code className={styles.code}>
          {row.key}
          {row.status ? ` · ${row.status}` : ""}
        </code>
      </DetailItem>
    </dl>
  );
}

function Unavailable({ reason }) {
  const body =
    reason === "malformed"
      ? "The loaded board's voting status could not be read, so this page will not guess which sources are voting."
      : reason === "empty"
        ? "The loaded board lists no sources in its voting status."
        : "The loaded board does not publish per-source voting status yet, so this page will not guess which sources are voting or at what weight.";
  return (
    <div className={styles.unavailable} data-testid="source-voting-unavailable">
      <p className={styles.unavailableTitle}>Voting status not available yet</p>
      <p className={styles.unavailableBody}>{body}</p>
    </div>
  );
}

export default function SourceVotingStatus({
  block = null,
  loading = false,
  failure = null,
  onRetry,
  context = "source voting status",
}) {
  const [expanded, setExpanded] = useState(() => new Set());
  const toggle = useCallback((key) => {
    setExpanded((prev) => {
      const next = new Set(prev);
      if (next.has(key)) next.delete(key);
      else next.add(key);
      return next;
    });
  }, []);

  const availability = votingStatusAvailability(block);
  const rows = useMemo(() => votingStatusRows(block), [block]);
  const summary = useMemo(() => votingStatusSummary(block, rows), [block, rows]);

  const columns = useMemo(
    () => [
      {
        key: "label",
        header: "Source",
        sortable: true,
        render: (r) => <SourceCell row={r} open={expanded.has(r.key)} onToggle={toggle} />,
      },
      {
        key: "lastUpdated",
        header: "Last Updated",
        sortable: true,
        hideBelow: "md",
        sortAccessor: (r) => r.daysSinceUpdate,
        firstDirection: "asc",
        headerInfo:
          "When the publisher last genuinely updated its rankings — its own stated date, or the last time we saw the rankings change. Downloading unchanged rankings does not count.",
        render: (r) => (
          <span className={styles.dateCell}>
            {r.lastUpdatedLabel}
            {r.agoLabel ? <span className={styles.subtle}>{r.agoLabel}</span> : null}
          </span>
        ),
      },
      {
        key: "freshness",
        header: "Freshness",
        numeric: true,
        sortable: true,
        hideBelow: "md",
        sortAccessor: (r) => r.freshnessPct,
        headerInfo: "How much of its voting power the source keeps, from the age of its last genuine update.",
        render: (r) =>
          r.freshnessPct == null ? (
            <span className={styles.subtle}>{r.freshnessLabel}</span>
          ) : (
            r.freshnessLabel
          ),
      },
      {
        key: "weight",
        header: "Voting Weight",
        numeric: true,
        sortable: true,
        hideBelow: "md",
        sortAccessor: (r) => r.effectiveWeight,
        headerInfo:
          "The weight this source votes with: its base weight × freshness × data checks. Sources from the same provider then share one provider's vote.",
        render: (r) => (
          <span>
            {formatWeight(r.effectiveWeight)}
            <span className={styles.subtle}> / {formatWeight(r.baseWeight)}</span>
          </span>
        ),
      },
      {
        key: "status",
        header: "Status",
        sortable: true,
        sortAccessor: (r) => r.statusRank,
        render: (r) => (
          <div className={styles.statusCell} data-testid={`source-voting-status-${r.key}`}>
            <StatusIndicator status={r.tone}>{r.statusLabel}</StatusIndicator>
            {r.reason ? <p className={styles.reason}>{r.reason}</p> : null}
          </div>
        ),
      },
    ],
    [expanded, toggle],
  );

  if (failure) {
    return <FailureState failure={failure} onRetry={onRetry} context={context} />;
  }
  if (loading && !block) {
    return <SkeletonTable rows={8} />;
  }
  if (!availability.available) {
    return <Unavailable reason={availability.reason} />;
  }

  return (
    <div className={styles.root}>
      <p className={styles.summary} data-testid="source-voting-summary">
        <strong className={styles.num}>{summary.votingCount}</strong> of{" "}
        <strong className={styles.num}>{summary.registeredCount}</strong> sources voting
        {summary.groups.map((g) => (
          <span key={g.status}>
            {" · "}
            <span className={styles.num}>{g.count}</span> {g.label}
          </span>
        ))}
        {summary.asOfLabel ? <> · board as of {summary.asOfLabel}</> : null}
      </p>
      {summary.freshnessApplied === false ? (
        <p className={styles.notice} role="note">
          <strong>Freshness weighting is switched off.</strong> Every collected source votes at
          its full base weight on this board.
        </p>
      ) : null}
      <DataTable
        columns={columns}
        rows={rows}
        rowKey="id"
        caption="Per-source voting status: last genuine update, freshness, voting weight and status, with the reason"
        density="compact"
        defaultSort={{ key: "status", direction: "asc" }}
        className={styles.table}
        renderAfterRow={(r) =>
          expanded.has(r.key) ? (
            <tr key={`${r.key}-detail`} className={styles.detailRow}>
              <td colSpan={columns.length} id={detailId(r.key)}>
                <SourceDetail row={r} />
              </td>
            </tr>
          ) : null
        }
      />
      {summary.stepSchedule ? <p className={styles.footnote}>{SCHEDULE_NOTE}</p> : null}
    </div>
  );
}
