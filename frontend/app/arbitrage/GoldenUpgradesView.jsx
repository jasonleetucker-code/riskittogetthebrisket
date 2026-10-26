"use client";

// Golden Upgrades (C7-GOLD-01) — same-position 1-for-1 inversions.
//
// Display only: the six criteria, thresholds and ordering live in
// src/trade/golden_upgrades.py; every number here comes from
// POST /api/trade/golden-upgrades.  Recommendation only — there is no send
// action; "Open in Trade Calculator" hands the swap to /trade.
//
// Discovery (owner directive 2026-10-18): the page's shared Target Quality /
// Players to target / Sort travel as ``discovery`` and are applied by the
// server during candidate generation.  An empty filtered result says so and
// offers one-click expansion to a broader Target Quality — never padded.

import { useEffect, useRef, useState } from "react";
import Link from "next/link";
import {
  Badge,
  Banner,
  Button,
  EmptyState,
  SegmentedControl,
  SkeletonTable,
} from "@/components/ds";
import { withValuationMode } from "@/lib/valuation-mode";
import { buildShareUrl } from "@/lib/trade-share";
import { deskBodyFromOffer } from "@/lib/trade-desk";
import SaveToDeskButton from "@/components/trade/SaveToDeskButton";
import { goldenRows, noResultText } from "@/lib/golden-upgrades";
import {
  broaderQualityOptions,
  discoveryRequest,
  discoverySummary,
} from "@/lib/trade-discovery";
import {
  emptyRefinement,
  loadRefinement,
  refinementKey,
  saveRefinement,
  toRequest,
  toggleExclude,
  toggleLock,
} from "@/lib/trade-refinement";
import {
  OutgoingRefinement,
  RefinementBar,
} from "@/components/trade/RefinementControls";
import styles from "./golden-upgrades.module.css";

const CONTEXT_OPTIONS = [
  { value: "team", label: "Team context" },
  { value: "asset", label: "Asset only" },
];

function calcUrl(myTeam, row) {
  try {
    return buildShareUrl({
      sides: [
        { name: myTeam || "You", players: [row.owned.name] },
        { name: row.opponent, players: [row.target.name] },
      ],
    });
  } catch {
    return null;
  }
}

export default function GoldenUpgradesView({
  myTeam,
  leagueKey,
  ownerKey,
  discovery = null,
  onDiscoveryChange,
}) {
  const [result, setResult] = useState(null);
  const [running, setRunning] = useState(false);
  const [error, setError] = useState("");
  const [useTeamContext, setUseTeamContext] = useState(true);
  const storageKey = refinementKey({
    owner: ownerKey,
    leagueKey,
    surface: "golden-upgrades",
    context: myTeam,
  });
  const [refinement, setRefinement] = useState(emptyRefinement);
  const seq = useRef(0);

  useEffect(() => {
    seq.current += 1; // drop any response for the previous team or league
    setResult(null);
    setRunning(false);
    setRefinement(loadRefinement(storageKey));
  }, [storageKey]);

  // A filter change re-runs an existing result: the server applies the new
  // filters during generation, so a stale list is never shown under them.
  const discoveryKey = JSON.stringify(discovery ? discoveryRequest(discovery) : null);
  const lastDiscoveryKey = useRef(discoveryKey);
  useEffect(() => {
    if (lastDiscoveryKey.current === discoveryKey) return;
    lastDiscoveryKey.current = discoveryKey;
    if (result) void run();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [discoveryKey]);

  async function run(
    nextRefinement = refinement,
    teamContext = useTeamContext,
  ) {
    if (!myTeam) return;
    const mine = ++seq.current;
    setRunning(true);
    setError("");
    try {
      const res = await fetch("/api/trade/golden-upgrades", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        cache: "no-store",
        body: JSON.stringify(
          withValuationMode({
            myTeam,
            leagueKey: leagueKey || undefined,
            useTeamContext: teamContext !== false,
            refinement: toRequest(nextRefinement),
            ...(discovery ? { discovery: discoveryRequest(discovery) } : {}),
          }),
        ),
      });
      const data = await res.json().catch(() => ({}));
      if (!res.ok)
        throw new Error(data?.error || `Request failed (${res.status})`);
      if (mine === seq.current) setResult(data);
    } catch (err) {
      if (mine === seq.current) setError(err?.message || "Request failed");
    } finally {
      if (mine === seq.current) setRunning(false);
    }
  }

  function applyRefinement(next) {
    setRefinement(next);
    saveRefinement(storageKey, next);
    if (result) void run(next);
  }

  const rows = goldenRows(result);
  const refine = {
    refinement,
    onLock: (name) => applyRefinement(toggleLock(refinement, name)),
    onExclude: (name) => applyRefinement(toggleExclude(refinement, name)),
    onClear: () => applyRefinement(emptyRefinement()),
    disabled: running,
  };

  return (
    <section
      className={`${styles.view} psi-editorial`}
      aria-label="Golden Upgrades"
    >
      <p className={styles.lede}>
        Same-position swaps where our board prefers their player while that
        position&apos;s own market (KTC for offense, IDP Trade Calculator for
        IDP) prefers yours. Recommendations only — nothing is sent.
      </p>
      <div className={styles.controls}>
        <SegmentedControl
          label="Analysis mode"
          options={CONTEXT_OPTIONS}
          value={useTeamContext ? "team" : "asset"}
          onChange={(v) => {
            const next = v === "team";
            setUseTeamContext(next);
            if (result) void run(refinement, next);
          }}
        />
        <Button onClick={() => run()} disabled={running || !myTeam}>
          {running ? "Checking every roster…" : "Find Golden Upgrades"}
        </Button>
      </div>
      <RefinementBar
        refinement={refinement}
        onLock={refine.onLock}
        onExclude={refine.onExclude}
        onClear={refine.onClear}
        disabled={running}
      />
      {result?.criteria ? (
        <p className={styles.muted}>
          Minimums: {result.criteria.boardPrefersTarget};{" "}
          {result.criteria.marketPrefersOwned} ({result.criteria.status}).
        </p>
      ) : null}
      {error ? <Banner tone="negative">{error}</Banner> : null}
      {running ? <SkeletonTable rows={4} /> : null}
      {!running && result ? (
        <p className={styles.count} role="status">
          {rows.length} Golden Upgrade{rows.length === 1 ? "" : "s"} found
          {discovery ? ` (${discoverySummary(discovery)})` : ""}.
        </p>
      ) : null}
      {!running && result && !rows.length ? (
        <EmptyState
          title={result.noResultLabel || "No Golden Upgrade found"}
          description={noResultText(result) || "No swap met every criterion."}
        />
      ) : null}
      {!running && result && !rows.length && discovery && onDiscoveryChange ? (
        <BroadenQuality
          current={discovery.targetQuality}
          availability={result?.discovery?.broaderAvailability}
          onBroaden={(level) =>
            onDiscoveryChange({ ...discovery, targetQuality: level })
          }
        />
      ) : null}
      {!running && rows.length ? (
        <ol className={styles.list}>
          {rows.map((row) => {
            const url = calcUrl(myTeam, row);
            return (
              <li key={row.key} className={styles.row}>
                <div className={styles.pair}>
                  <div>
                    <span className={styles.label}>You send</span>
                    <span className={styles.name}>{row.owned.name}</span>
                    <Badge tone="neutral">{row.owned.position}</Badge>
                    <OutgoingRefinement
                      name={row.owned.name}
                      refinement={refinement}
                      onLock={refine.onLock}
                      onExclude={refine.onExclude}
                      disabled={running}
                      context={`the upgrade to ${row.target.name}`}
                    />
                    <span className={styles.sub}>{row.ownedLine}</span>
                  </div>
                  <div>
                    <span className={styles.label}>
                      You receive from {row.opponent}
                    </span>
                    <span className={styles.name}>{row.target.name}</span>
                    <Badge tone="neutral">{row.target.position}</Badge>
                    <span className={styles.sub}>{row.targetLine}</span>
                  </div>
                </div>
                {row.targetRank || row.ownedRank ? (
                  <p className={styles.sub}>
                    Canonical rank: you send {row.ownedRank || "—"}, you
                    receive {row.targetRank || "—"}
                  </p>
                ) : null}
                <dl className={styles.metrics}>
                  {row.absoluteGain ? (
                    <div>
                      <dt>Value gain</dt>
                      <dd>{row.absoluteGain}</dd>
                    </div>
                  ) : null}
                  <div>
                    <dt>Board gain</dt>
                    <dd>{row.boardGain}</dd>
                  </div>
                  <div>
                    <dt>{row.market} prefers yours by</dt>
                    <dd>{row.marketInversion}</dd>
                  </div>
                </dl>
                {row.whyItMatters ? (
                  <p className={styles.why}>
                    <strong>Why it matters:</strong> {row.whyItMatters}
                  </p>
                ) : null}
                <p className={styles.why}>{row.why}</p>
                {row.exploitRisk ? (
                  <p className={styles.caution}>
                    Large inversion: the two boards disagree sharply about these
                    players, so it ranks lower — check both values before
                    offering.
                  </p>
                ) : null}
                {row.lineupText ? (
                  <p className={styles.sub}>{row.lineupText}</p>
                ) : null}
                <SaveToDeskButton
                  body={deskBodyFromOffer(
                    { send: [row.owned], receive: [row.target] },
                    {
                      leagueKey,
                      myTeam,
                      opponent: row.opponent,
                      source: "golden_upgrades",
                    },
                  )}
                  disabled={!leagueKey}
                />
                {url ? (
                  <Button as={Link} href={url} size="sm" variant="secondary">
                    Open in Trade Calculator
                  </Button>
                ) : null}
              </li>
            );
          })}
        </ol>
      ) : null}
      {!result && !running ? (
        <EmptyState
          title="Golden Upgrades ready"
          description="Scan every roster for a better player at the same position that the market rates below one of yours."
        />
      ) : null}
    </section>
  );
}

/** One-click expansion from an empty filtered result (never a padded list). */
function BroadenQuality({ current, availability, onBroaden }) {
  const options = broaderQualityOptions(current);
  if (!options.length) return null;
  return (
    <div className={styles.controls} role="group" aria-label="Broaden Target Quality">
      {options.map((o) => {
        const n = availability ? availability[o.value] : undefined;
        return (
          <Button
            key={o.value}
            size="sm"
            variant="secondary"
            onClick={() => onBroaden(o.value)}
          >
            Search {o.label}
            {Number.isFinite(n) ? ` (${n} found)` : ""}
          </Button>
        );
      })}
    </div>
  );
}
