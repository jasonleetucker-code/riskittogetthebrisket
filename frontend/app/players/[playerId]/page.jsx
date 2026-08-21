"use client";

// Universal Player Profile ("Player File") — C8-PSI-02 PR B.
//
// A full private page for one player, reached by clicking a player's
// name anywhere in the app (PlayerPopup's slim quick-view launches into
// this page rather than duplicating it). Reuses PlayerPopup's real data
// plumbing verbatim — computeOwnership/computeSiteDetails/
// computeConsensusText/computeValueChain and the RosContextSection/
// PlayerContextSection/RealizedPointsSection/IntelContextSection/
// PlayerNewsSection components are the SAME functions the popup calls,
// imported from it rather than reimplemented. No frontend valuation or
// ranking engine: every number here traces to a row field the backend
// already stamped.
//
// Not in the naming canon (naming-canon.js): this is a per-entity detail
// route reached only via a player link, the same relationship
// /league/player/[playerId] has to the public nav — dynamic per-entity
// routes are exempt from the static <h1>-equals-canon-string check by
// the SAME precedent (see page-title-canon.test.jsx's
// DATA_DERIVED_TITLE_ROUTES for the one nav-reachable example of this).

import Link from "next/link";
import { useParams } from "next/navigation";
import { useMemo, useState } from "react";
import { useApp } from "@/components/AppShell";
import { useUserState } from "@/components/useUserState";
import { LoadingState, PlayerImage } from "@/components/ui";
import {
  Badge,
  Button,
  EmptyState,
  FailureState,
  Icon,
  Movement,
  Panel,
  PageHeader,
  StatTile,
  Tabs,
  tabId,
  tabPanelId,
} from "@/components/ds";
import PlayerRankHistoryChart from "@/components/PlayerRankHistoryChart";
import {
  RosContextSection,
  PlayerContextSection,
  RealizedPointsSection,
  IntelContextSection,
  PlayerNewsSection,
  computeValueChain,
  computeOwnership,
  computeSiteDetails,
  computeConsensusText,
} from "@/components/PlayerPopup";
import { getPlayerEdge } from "@/lib/trade-logic";
import { resolvedRank } from "@/lib/dynasty-data";
import styles from "./player-file.module.css";

function findRowByPlayerId(rows, rawParam) {
  if (!Array.isArray(rows) || !rawParam) return null;
  const target = decodeURIComponent(String(rawParam)).trim();
  if (!target) return null;
  // Sleeper playerId first — the canonical identity for this route,
  // same priority order PlayerPopup's own sections use.
  const byId = rows.find(
    (r) => String(r?.raw?.playerId || r?.playerId || "").trim() === target,
  );
  if (byId) return byId;
  // Name fallback (case-insensitive exact match) — covers a pick or an
  // identity the join missed, the same fallback /players/compare uses.
  const targetLower = target.toLowerCase();
  return rows.find((r) => String(r?.name || "").toLowerCase() === targetLower) || null;
}

// Position rank against the FULL ranked board — same derivation as
// Rankings' own positionRankByName (app/rankings/page.jsx), computed
// for one player instead of the whole pool since this page only needs
// one row's answer. A display ordinal over backend-stamped
// rankDerivedValue, not a recomputed value or rank.
function computePositionRank(row, allRows) {
  if (!row?.pos || !Array.isArray(allRows)) return null;
  const pos = String(row.pos).toUpperCase().split("/")[0];
  const samePosition = allRows
    .filter((r) => {
      const p = String(r?.pos || "").toUpperCase().split("/")[0];
      if (p !== pos) return false;
      const v = Number(r?.rankDerivedValue);
      return Number.isFinite(v) && v > 0;
    })
    .sort((a, b) => Number(b.rankDerivedValue) - Number(a.rankDerivedValue));
  const idx = samePosition.findIndex(
    (r) => r === row || (r?.name && row?.name && r.name === row.name),
  );
  return idx >= 0 ? idx + 1 : null;
}

const TABS = [
  { id: "overview", label: "Overview" },
  { id: "market", label: "Market" },
  { id: "trades", label: "Trades" },
  { id: "performance", label: "Performance" },
  { id: "intel", label: "Intel" },
];

function TabPanel({ id, active, children }) {
  return (
    <div
      role="tabpanel"
      id={tabPanelId("player-file", id)}
      aria-labelledby={tabId("player-file", id)}
      hidden={active !== id}
    >
      {active === id ? children : null}
    </div>
  );
}

export default function PlayerFilePage() {
  const params = useParams();
  const playerId = params?.playerId;
  const { rows, rawData, loading, error, failure, retry } = useApp();
  const { state: userState, toggleWatchlist, serverBacked: userStateServerBacked } = useUserState();
  const [tab, setTab] = useState("overview");

  const row = useMemo(() => findRowByPlayerId(rows, playerId), [rows, playerId]);

  const rank = row ? resolvedRank(row) : Infinity;
  const positionRank = useMemo(() => computePositionRank(row, rows), [row, rows]);
  const ownership = useMemo(() => computeOwnership(row, rawData, rows), [row, rawData, rows]);
  const edge = useMemo(() => (row ? getPlayerEdge(row) : null), [row]);
  const valueChain = useMemo(() => computeValueChain(row), [row]);
  const siteDetails = useMemo(() => computeSiteDetails(row, []), [row]);
  const consensusText = useMemo(() => computeConsensusText(siteDetails), [siteDetails]);

  // Every return path — including these early ones — renders inside
  // the same .psi-editorial-scoped section. A first version returned
  // these directly, which left the loading/error/not-found states on
  // the OLD dark terminal palette (only the happy path was wrapped) —
  // caught by an actual screenshot of the not-found state, not by
  // inspection.
  if (loading) {
    return (
      <section className={`${styles.page} psi-editorial`}>
        <LoadingState message="Loading player pool…" />
      </section>
    );
  }
  if (failure) {
    return (
      <section className={`${styles.page} psi-editorial`}>
        <FailureState failure={failure} onRetry={retry} context="player profile" variant="block" />
      </section>
    );
  }
  if (error) {
    return (
      <section className={`${styles.page} psi-editorial`}>
        <EmptyState
          title="Couldn't load player data"
          description={error}
          action={retry ? <Button variant="secondary" size="sm" onClick={retry}>Try again</Button> : null}
        />
      </section>
    );
  }
  if (!row) {
    return (
      <section className={`${styles.page} psi-editorial`}>
        <EmptyState
          title="Player not found"
          description="No player on the current board matches this link — it may be misspelled, or the player may not be ranked today."
          action={
            <Button as={Link} href="/rankings" variant="secondary" size="sm">
              Back to Rankings
            </Button>
          }
        />
      </section>
    );
  }

  const value = Number(row.values?.full) > 0 ? Math.round(Number(row.values.full)) : null;
  const watching = (userState?.watchlist || []).some(
    (x) => String(x).toLowerCase() === String(row.name || "").toLowerCase(),
  );

  return (
    <section className={`${styles.page} psi-editorial`}>
      <PageHeader
        className={styles.hero}
        eyebrow={`Player File / ${row.pos}${row.raw?.team ? ` — ${row.raw.team}` : ""}`}
        title={row.name}
        description={
          ownership?.ownerLabel
            ? `Owned by ${ownership.ownerLabel}${ownership.positionLabel ? ` · ${ownership.positionLabel} on roster` : ""}`
            : "Unrostered in your league"
        }
        actions={
          <div className={styles.actions}>
            <Button
              size="sm"
              variant={watching ? "secondary" : "ghost"}
              aria-pressed={watching}
              icon={<Icon name={watching ? "star-filled" : "star"} size={13} />}
              onClick={() => toggleWatchlist(row.name)}
              title={
                watching
                  ? userStateServerBacked
                    ? "Remove from watchlist (synced)"
                    : "Remove from watchlist"
                  : userStateServerBacked
                    ? "Add to watchlist (synced across devices)"
                    : "Add to watchlist (local)"
              }
            >
              {watching ? "Watching" : "Watch"}
            </Button>
            <Button
              as={Link}
              href={`/players/compare?p1=${encodeURIComponent(row.name)}`}
              size="sm"
              variant="ghost"
            >
              Compare
            </Button>
            {/* No route accepts a player-seeding param today (checked
                /trade — nothing reads the query string), so this is a
                plain, honest navigation link, not a claim that the
                trade calculator opens pre-loaded with this player. */}
            <Button as={Link} href="/trade" size="sm" variant="primary">
              Open in Trade Calculator
            </Button>
          </div>
        }
      />

      <div className={styles.identityRow}>
        <PlayerImage
          playerId={row.raw?.playerId}
          team={row.raw?.team || row.team}
          position={row.pos}
          name={row.name}
          size={72}
        />
        <div className={styles.identityMeta}>
          <Badge>{row.pos}</Badge>
          {row.raw?.team && <span>{row.raw.team}</span>}
          {row.age != null && <span>age {row.age}</span>}
          {row.yearsExp != null && (
            <span>{row.yearsExp === 0 ? "rookie year" : `${row.yearsExp} yr exp`}</span>
          )}
          {row.raw?.rookie && <Badge tone="info">ROOKIE</Badge>}
        </div>
      </div>

      <div className={styles.summaryStrip}>
        <StatTile
          size="lg"
          label="Our Value"
          value={value != null ? value.toLocaleString() : "not priced"}
        />
        {rank < Infinity && <StatTile label="Overall rank" value={`#${rank}`} />}
        {positionRank != null && <StatTile label="Position rank" value={`${row.pos}${positionRank}`} />}
        {row.confidenceLabel && <StatTile label="Confidence" value={row.confidenceLabel} />}
        {row.siteCount > 0 && (
          <StatTile
            label="Sources"
            value={String(row.siteCount)}
            meta={row.canonicalTierId ? `Tier ${row.canonicalTierId}` : undefined}
          />
        )}
      </div>

      <Tabs
        idPrefix="player-file"
        label="Player sections"
        tabs={TABS}
        active={tab}
        onChange={setTab}
        className={styles.tabs}
      />

      <TabPanel id="overview" active={tab}>
        <div className={styles.tabStack}>
          {edge?.signal && (
            <Panel
              title={edge.signal === "BUY" ? "Buy Low" : "Sell High"}
              dense
            >
              {edge.signal === "BUY"
                ? `Consensus values this player ${edge.valueGapPct}% above KTC — market is cheap.`
                : `KTC values this player ${edge.valueGapPct}% above consensus — market overvalues.`}
              {edge.edgePct > 0 && ` ~${edge.edgePct}% value gap.`}
            </Panel>
          )}
          {valueChain.length > 0 && (
            <Panel title="Value chain" subtitle="How we arrived at Our Value">
              {valueChain.map((stage, i) => (
                <div key={stage.key} className={styles.chainStage}>
                  <div className={styles.chainIndex}>{i + 1}</div>
                  <div className={styles.chainBody}>
                    <div className={styles.chainLabel}>{stage.label}</div>
                    <div className={styles.chainDescription}>{stage.description}</div>
                  </div>
                  <div className={styles.chainValue}>
                    {stage.value.toLocaleString()}
                    {stage.delta !== null && stage.delta !== 0 && (
                      <div>
                        <Movement delta={stage.delta} />
                      </div>
                    )}
                  </div>
                </div>
              ))}
            </Panel>
          )}
          <Panel title="Rank history" subtitle="180-day trajectory" flush>
            <PlayerRankHistoryChart row={row} />
          </Panel>
        </div>
      </TabPanel>

      <TabPanel id="market" active={tab}>
        <div className={styles.tabStack}>
          {siteDetails.length > 0 ? (
            <Panel title="Source breakdown" subtitle={consensusText || undefined}>
              {siteDetails.map((s) => (
                <div key={s.key} className={styles.sourceRow}>
                  <div className={styles.sourceLabel} title={s.key}>{s.label}</div>
                  <div className={styles.sourceTrack}>
                    <div
                      className={[
                        styles.sourceFill,
                        s.pct >= 90 ? styles.sourceFillHigh : s.pct >= 50 ? styles.sourceFillMid : styles.sourceFillLow,
                      ].join(" ")}
                      style={{ width: `${Math.min(100, s.pct)}%` }}
                    />
                  </div>
                  <div className={styles.sourceValue}>
                    {Math.round(s.value).toLocaleString()}
                    {s.native != null && (
                      <span className={styles.sourceNative}> ({s.native.toLocaleString()})</span>
                    )}
                  </div>
                </div>
              ))}
            </Panel>
          ) : (
            <EmptyState
              title="No source breakdown"
              description="No ranking source has this player priced individually today."
            />
          )}
          {row?.assetClass === "pick" &&
            Number.isFinite(row?.pickProjectedDraftValue) &&
            Number(row?.pickProjectedDraftValueGain) > 0 && (
              <Panel title="Projected at draft" dense>
                ~{Number(row.pickProjectedDraftValue).toLocaleString()} by the {row.pickProjectedDraftYear} draft
                {Number(row.pickProjectedDraftValueGainPct) > 0 && (
                  <>
                    {" · "}
                    <Movement delta={Number(row.pickProjectedDraftValueGainPct)} format={(n) => `${n}%`} />
                    {" gain"}
                  </>
                )}
              </Panel>
            )}
        </div>
      </TabPanel>

      <TabPanel id="trades" active={tab}>
        {/* No canonical per-player trade-history data source exists in
            this codebase today (checked: the trade engines compute
            live suggestions/simulations, none persist a queryable
            per-player trade ledger) — an honest unavailable state
            rather than a fabricated history or a "Trade Desk" button
            for a standalone feature EXECUTION_PLAN.md §6 lists as not
            yet authorized to build. */}
        <EmptyState
          title="Trade history not available"
          description="This build has no per-player trade-history feed yet. Use the trade calculator to evaluate a specific package involving this player."
          action={
            <Button as={Link} href="/trade" variant="secondary" size="sm">
              Open Trade Calculator
            </Button>
          }
        />
      </TabPanel>

      <TabPanel id="performance" active={tab}>
        <div className={styles.tabStack}>
          <RosContextSection row={row} />
          <PlayerContextSection row={row} />
          <RealizedPointsSection row={row} />
        </div>
      </TabPanel>

      <TabPanel id="intel" active={tab}>
        <div className={styles.tabStack}>
          <IntelContextSection row={row} />
          <PlayerNewsSection playerName={row.name} position={row.pos} team={row.raw?.team} />
        </div>
      </TabPanel>
    </section>
  );
}
