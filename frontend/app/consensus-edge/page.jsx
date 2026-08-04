"use client";

/**
 * Consensus Edge — the unified buy/sell board.
 *
 * Two things this page is careful about, because they are the ways a
 * buy/sell screen misleads:
 *
 * 1. It never renders a number without its standing. Every score sits
 *    next to a confidence, and the component breakdown marks which
 *    components have been validated against an outcome and which have
 *    not. Today that is one of three.
 * 2. Conflicted and Insufficient Evidence are rendered as their own
 *    states, not as a mild Neutral. A player whose evidence strongly
 *    disagrees is the single most misleading thing a composite can
 *    average to zero, so it gets its own tone and its own explanation.
 */

import { useMemo, useState } from "react";
import { SegmentedControl } from "@/components/ds";
import { useConsensusEdge } from "@/components/useConsensusEdge";
import {
  componentRows,
  formatConfidence,
  formatPct,
  formatScore,
  formatValue,
  labelTone,
  positionLeaders,
} from "@/lib/consensus-edge";
import styles from "./consensus-edge.module.css";

// Buy/sell is a FILTER over one list, not a set of tabpanels, so it uses
// the design system's radiogroup-based SegmentedControl. A tab role
// without aria-controls promises a tabpanel that does not exist — the
// repo has an a11y guard for exactly that, and it caught this.
const DIRECTIONS = [
  { value: "buys", label: "Buys" },
  { value: "sells", label: "Sells" },
];

function FailureState({ failure }) {
  if (failure.kind === "disabled") {
    return (
      <div className={styles.notice}>
        <h2>Consensus Edge is switched off</h2>
        <p>
          Only one of its three components has been validated against an
          outcome, so it ships behind a feature flag. Enable{" "}
          <code>consensus_edge</code> to view the board.
        </p>
      </div>
    );
  }
  if (failure.kind === "not_ready") {
    return (
      <div className={styles.notice}>
        <h2>No board yet</h2>
        <p>{failure.message || "The first scrape may still be running."}</p>
      </div>
    );
  }
  if (failure.kind === "auth") {
    return (
      <div className={styles.notice}>
        <h2>Sign in required</h2>
        <p>{failure.message}</p>
      </div>
    );
  }
  return (
    <div className={styles.notice}>
      <h2>Consensus Edge unavailable</h2>
      <p>{failure.message}</p>
    </div>
  );
}

function ComponentBar({ component }) {
  if (component.absent) {
    return (
      <div className={styles.component} title={component.note}>
        <span className={styles.componentLabel}>{component.label}</span>
        <span className={styles.componentAbsent}>not assessed</span>
      </div>
    );
  }
  const pct = Math.min(100, Math.abs(component.value) * 100);
  return (
    <div className={styles.component} title={component.note}>
      <span className={styles.componentLabel}>
        {component.label}
        {!component.validated && (
          <span className={styles.unvalidated} title={component.note}>
            {" "}
            unvalidated
          </span>
        )}
      </span>
      <span className={styles.componentTrack}>
        <span
          className={component.value >= 0 ? styles.barPos : styles.barNeg}
          style={{ width: `${pct}%` }}
        />
      </span>
      <span className={styles.componentValue}>
        {component.value >= 0 ? "+" : ""}
        {component.value.toFixed(2)}
      </span>
    </div>
  );
}

function PlayerCard({ row, validation, expanded, onToggle }) {
  const tone = labelTone(row.label);
  return (
    <li className={styles.card}>
      <button className={styles.cardHead} onClick={onToggle} type="button">
        <span className={styles.name}>
          {row.displayName}
          <span className={styles.meta}>
            {row.position}
            {row.assetClass === "idp" ? " · IDP" : ""}
          </span>
        </span>
        <span className={`${styles.label} ${styles[tone]}`}>{row.label}</span>
        <span className={styles.score}>{formatScore(row.score)}</span>
        <span className={styles.confidence}>
          conf {formatConfidence(row.confidence)}
        </span>
      </button>

      {expanded && (
        <div className={styles.cardBody}>
          {row.labelReason && <p className={styles.reason}>{row.labelReason}</p>}

          <ul className={styles.explanation}>
            {(row.explanation || []).map((line, i) => (
              <li key={i}>{line}</li>
            ))}
          </ul>

          <div className={styles.values}>
            <div>
              <dt>Fair value</dt>
              <dd>{formatValue(row.fairValue)}</dd>
            </div>
            <div>
              <dt>Market</dt>
              <dd>{formatValue(row.marketValue)}</dd>
            </div>
            <div>
              <dt>Gap</dt>
              <dd>{formatPct(row.mispricing?.pctGap)}</dd>
            </div>
            <div>
              <dt>Market source</dt>
              <dd>{row.anchorKey || "—"}</dd>
            </div>
          </div>

          <div className={styles.components}>
            {componentRows(row, validation).map((component) => (
              <ComponentBar key={component.key} component={component} />
            ))}
          </div>

          {row.excludedSources?.length > 0 && (
            <p className={styles.footnote}>
              Fair value excludes {row.excludedSources.join(", ")} so it is
              independent of the price it is compared against.
            </p>
          )}
        </div>
      )}
    </li>
  );
}

export default function ConsensusEdgePage() {
  const [direction, setDirection] = useState("buys");
  const [openKey, setOpenKey] = useState(null);

  const params = useMemo(() => ({ limit: 20 }), []);
  const { loading, data, failure } = useConsensusEdge("/api/consensus-edge/top", {
    params,
  });
  const methodology = useConsensusEdge("/api/consensus-edge/methodology");

  const validation = methodology.data?.components || {};
  const rows = data?.[direction] || [];
  const leaders = useMemo(
    () =>
      positionLeaders(rows, {
        direction: direction === "buys" ? "buy" : "sell",
      }),
    [rows, direction],
  );

  return (
    <section className={styles.page}>
      <header className={styles.header}>
        <h1>Consensus Edge</h1>
        <p className={styles.sub}>
          Where our anchor-free fair value disagrees with the market.
        </p>
        <p className={styles.experimental}>
          Experimental. One of three components has been validated against an
          outcome; the composite weights are declared priors, not fitted. Tested
          against market movement, not fantasy production.
        </p>
      </header>

      {loading && <div className={styles.loading}>Building the board…</div>}
      {failure && !loading && <FailureState failure={failure} />}

      {data && !loading && (
        <>
          <SegmentedControl
            options={DIRECTIONS}
            value={direction}
            onChange={setDirection}
            label="Show buys or sells"
            className={styles.tabs}
          />

          {rows.length === 0 ? (
            <p className={styles.empty}>
              No players currently qualify on score and confidence. That is a
              result, not an error — the board declines rather than promoting
              the least-bad candidate.
            </p>
          ) : (
            <ul className={styles.list}>
              {rows.map((row) => (
                <PlayerCard
                  key={row.playerKey}
                  row={row}
                  validation={validation}
                  expanded={openKey === row.playerKey}
                  onToggle={() =>
                    setOpenKey(openKey === row.playerKey ? null : row.playerKey)
                  }
                />
              ))}
            </ul>
          )}

          <section className={styles.leaders}>
            <h2>Position leaders</h2>
            <p className={styles.leadersNote}>
              Best qualifying player per position. Positions with nothing above
              the threshold are listed as having no qualifying player rather
              than being filled from further down the board.
            </p>
            <ul className={styles.leaderList}>
              {leaders.map(({ position, row }) => (
                <li key={position}>
                  <span className={styles.leaderPos}>{position}</span>
                  <span>{row.displayName}</span>
                  <span className={styles.score}>{formatScore(row.score)}</span>
                </li>
              ))}
              {leaders.length === 0 && (
                <li className={styles.empty}>No qualifying player at any position.</li>
              )}
            </ul>
          </section>

          {data.sharpFlowStatus === "no_ledger" && (
            <p className={styles.footnote}>
              Sharp flow is unavailable in this environment, so it is omitted
              from the composite rather than counted as neutral.
            </p>
          )}
        </>
      )}
    </section>
  );
}
