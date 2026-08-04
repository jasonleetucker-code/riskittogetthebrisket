"use client";

/**
 * Consensus Edge — the unified buy/sell board.
 *
 * This page reads the FULL board (`/api/consensus-edge/players`), not
 * the top-20 slice, and that is a correctness requirement rather than a
 * preference. Two things broke when it read the slice:
 *
 * 1. Position leaders were computed over the global top 20, so a
 *    position whose best qualifying buy ranked 25th rendered as "no
 *    qualifying player" — directly contradicting the panel's own copy.
 * 2. `top_movers` filters to Buy/Sell before returning, so Conflicted,
 *    Insufficient Evidence and No Market Price — the refusal states that
 *    are this feature's entire honesty claim — could never reach a user.
 *
 * Everything displayed is computed by the backend. The only derivation
 * here is filtering and grouping rows the backend already labelled, and
 * qualification is read off `row.qualified` rather than re-derived from
 * label strings.
 */

import { useMemo, useState } from "react";
import { SegmentedControl } from "@/components/ds";
import { useConsensusEdge } from "@/components/useConsensusEdge";
import {
  componentLabel,
  componentRows,
  formatConfidence,
  formatPct,
  formatScore,
  formatValue,
  labelTone,
  positionLeaders,
  rankKey,
} from "@/lib/consensus-edge";
import styles from "./consensus-edge.module.css";

// Buy/sell is a FILTER over one list, not a set of tabpanels, so it uses
// the design system's radiogroup-based SegmentedControl. A tab role
// without aria-controls promises a tabpanel that does not exist.
const VIEWS = [
  { value: "buys", label: "Buys" },
  { value: "sells", label: "Sells" },
  { value: "withheld", label: "Withheld" },
];

// No WITHHELD_LABELS set here. It used to be a JS copy of
// service.REFUSAL_LABELS matched by English string, in the one file the
// anti-duplication test does not read — so renaming a label server-side
// would have silently emptied this tab with nothing failing. The backend
// stamps `withheld` per row, the same way it stamps `qualified`.

// How many rows the list renders before it stops. The board is ~1,000
// rows and roughly 1.5 MB; rendering all of it is neither useful nor
// fast. The count is used to SAY how many were hidden — an unannounced
// slice reads as "that is the whole answer".
const RENDER_LIMIT = 50;

// Positions offered by the filter, derived from the board rather than
// listed. The hardcoded list held 7 of the 11 asset classes the board
// actually produces, so K, PICK, T and unpositioned rows — 18% of the
// board — were unreachable by filter and silently absent from the
// leaders panel. Sorted with the familiar offence-then-defence order
// first and anything new appended, so adding a position to the pipeline
// cannot quietly drop it from the UI again.
const POSITION_ORDER = ["QB", "RB", "WR", "TE", "K", "DL", "LB", "DB"];

function positionsOnBoard(rows) {
  const seen = new Set();
  for (const row of rows || []) {
    if (row.position) seen.add(row.position);
  }
  const known = POSITION_ORDER.filter((p) => seen.has(p));
  const extra = [...seen].filter((p) => !POSITION_ORDER.includes(p)).sort();
  return [...known, ...extra];
}

function FailureState({ failure }) {
  if (failure.kind === "disabled") {
    return (
      <div className={styles.notice}>
        <h2>Consensus Edge is switched off</h2>
        <p>
          Its top-20 buy list did not beat a random draw from the same priced
          universe in any measured fold, so it ships behind a feature flag that
          defaults off. Enable <code>consensus_edge</code> to view the board
          anyway — everything works; what is missing is evidence that it helps.
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

/**
 * States what the board could actually see. A component that is dark
 * because its data source is empty is indistinguishable, from the
 * outside, from one nobody wired up — and the difference silently
 * governs whether Strong labels can appear at all.
 */
function AvailabilityBanner({ board }) {
  const availability = board.componentAvailability || {};
  const live = Object.entries(availability).filter(([, v]) => v.available);
  // A component is dark for two very different reasons, and lumping
  // them under "has no data" was wrong for one of them: opportunity
  // measures hundreds of rows and carries zero weight because its
  // backtest returned a null.
  const noData = Object.entries(availability).filter(
    ([, v]) => !v.available && v.unavailableReason !== "zero_weight",
  );
  const rejected = Object.entries(availability).filter(
    ([, v]) => v.unavailableReason === "zero_weight",
  );
  const hours = board.inputs?.hoursStale;
  // Read from the payload rather than hardcoded. A literal here is the
  // same backend/frontend drift this file's own comments warn against —
  // change the threshold server-side and the sentence starts lying.
  const threshold = board.strongLabelThreshold;
  const diverged = board.validationScope?.matchesMeasured === false;

  return (
    <div className={styles.experimental}>
      <p>
        <strong>Experimental.</strong> {live.length} of{" "}
        {Object.keys(availability).length} components are live
        {noData.length > 0 && (
          <>
            {" "}
            — {joinLabels(noData)} {noData.length === 1 ? "has" : "have"} no
            data
          </>
        )}
        {rejected.length > 0 && (
          <>
            {" "}
            — {joinLabels(rejected)} {rejected.length === 1 ? "was" : "were"}{" "}
            measured and carries no weight
          </>
        )}
        . Validated against market movement, not fantasy production.
      </p>
      {diverged && (
        <p className={styles.ceilingNote}>
          <strong>Note:</strong> this board is not running the configuration the
          published measurement was produced under
          {board.validationScope.differences?.length > 0 && (
            <> — {board.validationScope.differences.join("; ")}</>
          )}
          .
        </p>
      )}
      {board.strongLabelsReachable === false && (
        <p className={styles.ceilingNote}>
          Strong Buy and Strong Sell cannot appear: with {live.length} live
          component{live.length === 1 ? "" : "s"} the confidence ceiling is{" "}
          {Math.round(board.confidenceCeiling)}
          {typeof threshold === "number" && (
            <>, below the threshold of {threshold}</>
          )}
          . This is the model declining to make a strong call on partial
          evidence, not an absence of candidates.
        </p>
      )}
      {typeof hours === "number" && (
        <p className={styles.ceilingNote}>
          Market data is {hours < 1 ? "under an hour" : `${Math.round(hours)}h`}{" "}
          old (oldest market anchor); confidence is discounted accordingly.
        </p>
      )}
      {/* When the DATA was gathered, not when this board was assembled.
          The payload only ever carried `generatedAt` — build time — which
          refreshes on every cache miss and so reads as fresh beside
          day-old prices. */}
      {board.contractScrapedAt && (
        <p className={styles.ceilingNote}>
          Prices scraped {new Date(board.contractScrapedAt).toLocaleString()}.
        </p>
      )}
    </div>
  );
}

function joinLabels(entries) {
  return entries.map(([key]) => componentLabel(key)).join(", ");
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
  // A zero-weight component is shown because the evidence is real, and
  // muted because it does not move the score. Drawing it identically to
  // a contributing component would leave a reader unable to tell which
  // number the model actually used.
  const barClass = component.zeroWeight
    ? styles.barInert
    : component.value >= 0
      ? styles.barPos
      : styles.barNeg;
  return (
    <div className={styles.component} title={component.note}>
      <span className={styles.componentLabel}>
        {component.label}
        {component.zeroWeight ? (
          <span className={styles.notCounted} title={component.note}>
            {" "}
            not counted
          </span>
        ) : (
          !component.validated && (
            <span className={styles.unvalidated} title={component.note}>
              {" "}
              unvalidated
            </span>
          )
        )}
        {component.partial && (
          <span
            className={styles.partial}
            title={`No evidence for: ${component.absentAxes.join(", ")}`}
          >
            {" "}
            partial evidence
          </span>
        )}
      </span>
      <span className={styles.componentTrack}>
        <span className={barClass} style={{ width: `${pct}%` }} />
      </span>
      <span
        className={
          component.zeroWeight
            ? `${styles.componentValue} ${styles.componentValueInert}`
            : styles.componentValue
        }
      >
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
            {/* Market value on the collapsed row, because the measured
                edge is concentrated in cheap assets — 91% of the top-20
                sits under 2000 — and a user deciding whether a call is
                worth acting on needs to see what the player is worth
                without opening the card. */}
            {typeof row.marketValue === "number" && (
              <> · {formatValue(row.marketValue)}</>
            )}
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
          {row.labelReason && (
            <p className={styles.reason}>{row.labelReason}</p>
          )}

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

          {row.unpricedReason && (
            <p className={styles.footnote}>
              Not priced: {row.unpricedReason.replace(/_/g, " ")}.
            </p>
          )}

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
  const [view, setView] = useState("buys");
  const [position, setPosition] = useState("");
  const [minConfidence, setMinConfidence] = useState(0);
  const [openKey, setOpenKey] = useState(null);

  const { loading, data, failure } = useConsensusEdge(
    "/api/consensus-edge/players",
  );
  const methodology = useConsensusEdge("/api/consensus-edge/methodology");
  const validation = methodology.data?.components || {};

  const allRows = useMemo(() => data?.players || [], [data]);
  const positions = useMemo(() => positionsOnBoard(allRows), [allRows]);

  const rows = useMemo(() => {
    let out = allRows;
    if (view === "withheld") {
      // `withheld` is stamped by the backend. Note it is NOT the
      // complement of `qualified` — a Neutral row is neither, because
      // "the evidence points nowhere" is a finding and not a refusal.
      out = out.filter((r) => r.withheld);
    } else {
      const wantPositive = view === "buys";
      out = out.filter(
        (r) => r.qualified && (wantPositive ? r.score > 0 : r.score < 0),
      );
    }
    if (position) out = out.filter((r) => r.position === position);
    if (minConfidence > 0) {
      out = out.filter((r) => (r.confidence ?? 0) >= minConfidence);
    }
    // Buys arrive in conviction order from the backend, so they are left
    // alone. Sells are the same list read from the other end, and the
    // reverse has to use the SAME key — sorting them by raw score gave
    // the sells view an ordering no measurement describes.
    return view === "sells"
      ? [...out].sort((a, b) => rankKey(a) - rankKey(b))
      : out;
  }, [allRows, view, position, minConfidence]);

  // Position leaders read the FULL board, never the displayed slice.
  const leaders = useMemo(
    () =>
      positionLeaders(allRows, {
        direction: view === "sells" ? "sell" : "buy",
      }),
    [allRows, view],
  );

  return (
    <section className={styles.page}>
      <header className={styles.header}>
        <h1>Consensus Edge</h1>
        <p className={styles.sub}>
          Where our anchor-free fair value disagrees with the market.
        </p>
        {data && <AvailabilityBanner board={data} />}
      </header>

      {loading && <div className={styles.loading}>Building the board…</div>}
      {failure && !loading && <FailureState failure={failure} />}

      {data && !loading && (
        <>
          <div className={styles.controls}>
            <SegmentedControl
              options={VIEWS}
              value={view}
              onChange={setView}
              label="Show buys, sells, or withheld players"
            />
            <label className={styles.filter}>
              <span>Position</span>
              <select
                value={position}
                onChange={(e) => setPosition(e.target.value)}
              >
                <option value="">All</option>
                {positions.map((p) => (
                  <option key={p} value={p}>
                    {p}
                  </option>
                ))}
              </select>
            </label>
            <label className={styles.filter}>
              <span>Min confidence</span>
              <select
                value={minConfidence}
                onChange={(e) => setMinConfidence(Number(e.target.value))}
              >
                <option value={0}>Any</option>
                <option value={40}>40+</option>
                <option value={50}>50+</option>
                <option value={60}>60+</option>
              </select>
            </label>
          </div>

          {view === "withheld" && (
            <p className={styles.leadersNote}>
              Players the model declined to call, and why. Conflicted means
              strong evidence pointing both ways — deliberately not shown as
              Neutral, because that would read as "nothing is happening".
            </p>
          )}

          {/* Buys and sells are not equally grounded. The sell side was
              measured over 22 folds and carries no edge, so it must not
              render as the buy list's peer just because the UI happens
              to give them the same control. */}
          {view === "sells" && data.sellSideValidation?.validated === false && (
            <p className={styles.sellWarning}>
              <strong>These are not validated.</strong>{" "}
              {data.sellSideValidation.note}
            </p>
          )}

          {rows.length === 0 ? (
            <p className={styles.empty}>
              No players match. When the board declines rather than promoting
              the least-bad candidate, that is a result, not an error.
            </p>
          ) : (
            <ul className={styles.list}>
              {rows.slice(0, RENDER_LIMIT).map((row) => (
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

          {rows.length > RENDER_LIMIT && (
            <p className={styles.truncation}>
              Showing {RENDER_LIMIT} of {rows.length.toLocaleString()} matching
              players. Narrow by position or confidence to see further down.
            </p>
          )}

          {view !== "withheld" && (
            <section className={styles.leaders}>
              <h2>Position leaders</h2>
              <p className={styles.leadersNote}>
                Best qualifying player per position, computed over the whole
                board. Positions with nothing above the threshold are listed as
                having no qualifying player rather than being filled from
                further down.
              </p>
              <ul className={styles.leaderList}>
                {positions.map((pos) => {
                  const found = leaders.find((l) => l.position === pos);
                  return (
                    <li key={pos}>
                      <span className={styles.leaderPos}>{pos}</span>
                      <span>
                        {found ? (
                          found.row.displayName
                        ) : (
                          <em className={styles.componentAbsent}>
                            No qualifying {view === "sells" ? "sell" : "buy"}
                          </em>
                        )}
                      </span>
                      <span className={styles.score}>
                        {found ? formatScore(found.row.score) : ""}
                      </span>
                    </li>
                  );
                })}
              </ul>
            </section>
          )}

          <p className={styles.footnote}>
            Model {data.modelVersion} · params {data.paramSetId} · generated{" "}
            {data.generatedAt}
          </p>
        </>
      )}
    </section>
  );
}
