"use client";

import Link from "next/link";
import { useEffect, useMemo, useState } from "react";
import { getPlayerEdge } from "@/lib/trade-logic";
import { resolvedRank, RANKING_SOURCES } from "@/lib/dynasty-data";
import { buildTeamByPlayer, normalizeName } from "@/lib/waiver-logic";
import PlayerRankHistoryChart from "@/components/PlayerRankHistoryChart";
import { useApp } from "@/components/AppShell";
import { useLeague } from "@/components/useLeague";
import { useNews } from "@/components/useNews";
import { lookupPlayerDigest, lookupPlayerNews } from "@/lib/player-name-match";
import { buildRosIndex, rosEntryForRow } from "@/lib/ros-index";
import { buildPlayerMetaIndex } from "@/lib/news-filters";
import { timeAgo } from "@/lib/news-service";
import { useTeam } from "@/components/useTeam";
import { useTerminal } from "@/components/useTerminal";
import { useUserState } from "@/components/useUserState";
import { useSettings } from "@/components/useSettings";
import { PlayerImage } from "@/components/ui";
import { Badge, Button, Drawer, Icon, Movement, StatTile } from "@/components/ds";
import styles from "./player-card.module.css";

// ── PLAYER PROFILE DRAWER (Redesign R2) ──────────────────────────────
// The scouting-card experience: identity header, Our Value + source
// breakdown, value chain, rank history, league-mate intel (#534), news
// digest (#540), and the NEW playerctx section (#539 — contracts, snap
// share, depth-chart standing, first UI surface).  Rebuilt on the ds
// Drawer (focus trap, Escape, restore, overlay stack) — every data
// derivation from the pre-R2 popup is preserved verbatim.

// ── ROS context section ──────────────────────────────────────────────
// Read-only contender-layer labels surfaced inside the profile.  Never
// mutates dynasty values; gated by ``settings.showRosTags``.  Caches
// the player-values JSON at module level so opening multiple popups
// doesn't refetch the 500-row payload each time.
const _rosCache = { byName: null, fetchedAt: 0, inflight: null };
const _ROS_TTL_MS = 30 * 60 * 1000;

// Sources whose raw 0-9999 published board is the user-meaningful
// display number (e.g. KTC TE++ at keeptradecut.com).  Read from
// ``row.rawSourceValues`` instead of the Hill-curve
// ``valueContribution`` so the chip matches the source's website.
// Mirrors ``_RAW_VALUE_PREFERRED_KEYS`` in
// ``src/api/source_history.py`` and ``src/api/data_contract.py``.
const RAW_VALUE_PREFERRED_KEYS = new Set(["ktcSfTep"]);

// Sources retired from the blend whose canonical replacement covers
// the same signal (e.g. ``ktc`` standard SF, replaced by
// ``ktcSfTep``).  Still loaded into ``canonicalSiteValues`` for the
// trade-page arbitrage finder + per-source winner row but should not
// appear in the popup chip render — emitting both would render two
// "KTC" chips for every player.  Mirrors
// ``_RETIRED_FROM_CHART_KEYS`` in ``src/api/source_history.py``.
const RETIRED_FROM_CHART_KEYS = new Set(["ktc"]);

async function _loadRosValuesByName() {
  const fresh = _rosCache.byName && Date.now() - _rosCache.fetchedAt < _ROS_TTL_MS;
  if (fresh) return _rosCache.byName;
  if (_rosCache.inflight) return _rosCache.inflight;
  const promise = fetch("/api/ros/player-values?limit=2000")
    .then((r) => (r.ok ? r.json() : null))
    .then((payload) => {
      // Indexed by canonical NAME KEY, not the raw string: the ROS
      // aggregate lowercases and strips apostrophes while board rows
      // carry display names, so the raw join matched 12 of 1075 rows.
      // See lib/ros-index.js.
      const map = buildRosIndex(payload?.players);
      _rosCache.byName = map;
      _rosCache.fetchedAt = Date.now();
      _rosCache.inflight = null;
      return map;
    })
    .catch(() => {
      _rosCache.inflight = null;
      return _rosCache.byName || new Map();
    });
  _rosCache.inflight = promise;
  return promise;
}

const _ROS_TAG_TONE = {
  "Win-now target": "accent",
  "Contender upgrade": "accent",
  "Seller cash-out": "warning",
  "Rebuilder hold": "positive",
  "Avoid unless contending": "negative",
  "Depth spike option": "neutral",
  "Best-ball boost": "accent",
  "IDP contender target": "accent",
  "Injury/bye cover": "neutral",
};
const _VET_AGE = { QB: 32, RB: 26, WR: 29, TE: 30, DL: 30, DE: 30, DT: 30, EDGE: 30, LB: 29, DB: 29, S: 29, CB: 29 };

function _tagsForPlayer({ position, age, rosValue, rosRank, dynastyValue, volatilityFlag }) {
  const tags = [];
  if (rosValue == null || rosValue <= 0) return tags;
  const pos = String(position || "").toUpperCase().split("/")[0];
  const isIdp = ["DL", "DE", "DT", "EDGE", "LB", "DB", "S", "CB"].includes(pos);
  const isStrong = rosValue >= 60;
  const isElite = rosValue >= 80;
  const isStarterCaliber = rosRank != null && rosRank <= 100;
  const isTopIdp = isIdp && rosRank != null && rosRank <= 50;
  const veteran = age != null && _VET_AGE[pos] != null && age >= _VET_AGE[pos];
  const young = age != null && age <= 24;
  if (veteran && isStrong) tags.push("Win-now target");
  if (isElite && isStarterCaliber && !isIdp) tags.push("Contender upgrade");
  if (veteran && isStrong && dynastyValue != null && dynastyValue < rosValue * 0.7) tags.push("Seller cash-out");
  if (young && !isStrong) tags.push("Rebuilder hold");
  if (veteran && isStrong && !isStarterCaliber) tags.push("Avoid unless contending");
  if (!isStarterCaliber && rosValue >= 30 && rosValue < 60) tags.push("Depth spike option");
  if (volatilityFlag && isStarterCaliber) tags.push("Best-ball boost");
  if (isTopIdp) tags.push("IDP contender target");
  if (!isStrong && !young) tags.push("Injury/bye cover");
  return tags;
}

function RosContextSection({ row }) {
  const { settings } = useSettings();
  const enabled = settings?.showRosTags !== false;
  const [ros, setRos] = useState(null);
  useEffect(() => {
    if (!enabled || !row) return;
    let active = true;
    _loadRosValuesByName().then((map) => {
      if (!active) return;
      setRos(rosEntryForRow(map, row));
    });
    return () => {
      active = false;
    };
  }, [enabled, row?.canonicalName, row?.displayName]);

  if (!enabled || !row) return null;
  if (!ros || !ros.rosValue) {
    return (
      <div className={styles.quietNote} title="No ROS source ranked this player today.">
        ROS · no data yet
      </div>
    );
  }
  const dynastyValue = row.values?.full ?? row.rankDerivedValue ?? null;
  const tags = _tagsForPlayer({
    position: row.pos,
    age: row.age,
    rosValue: ros.rosValue,
    rosRank: ros.rosRank,
    dynastyValue,
    volatilityFlag: ros.volatilityFlag,
  });
  return (
    <div className={styles.section}>
      <p className={styles.sectionLabel}>Short-term context (ROS) · informational only</p>
      <div className={styles.rosRow}>
        <span className="ds-mono">
          ROS value <strong>{Math.round(ros.rosValue)}</strong>
        </span>
        {ros.rosRank != null && (
          <span className={`ds-mono ${styles.quietNote}`}>#{ros.rosRank} overall</span>
        )}
        {ros.tier != null && <span className={styles.quietNote}>Tier {ros.tier}</span>}
        {ros.confidence != null && (
          <span className={styles.quietNote}>
            confidence {Math.round(ros.confidence * 100)}%
          </span>
        )}
      </div>
      {tags.length > 0 && (
        <div className={styles.rosTags}>
          {tags.map((tag) => (
            <Badge key={tag} tone={_ROS_TAG_TONE[tag] || "outline"}>
              {tag}
            </Badge>
          ))}
        </div>
      )}
    </div>
  );
}

// ── League-mate intel section (Insider Trading) ──────────────────────
// Cross-league exposure line: how many league-mates hold this player
// across their other Sleeper leagues, and the recent net add activity.
// Fetches GET /api/intel/player and degrades SILENTLY when intel is
// unavailable — the profile simply omits the section.
//
// Intel is league-scoped, so the cache is keyed on (leagueKey, asset)
// and the active leagueKey rides on every request.
const _intelCache = new Map(); // `${leagueKey}::asset` → {payload|null, fetchedAt}
const _INTEL_TTL_MS = 5 * 60 * 1000;

export async function _loadPlayerIntel(playerId, name, leagueKey = "") {
  const assetKey = playerId ? `id:${playerId}` : `name:${name}`;
  const key = `${leagueKey || ""}::${assetKey}`;
  const cached = _intelCache.get(key);
  if (cached && Date.now() - cached.fetchedAt < _INTEL_TTL_MS) return cached.payload;
  try {
    const params = new URLSearchParams(
      playerId ? { playerId } : { name },
    );
    if (leagueKey) params.set("leagueKey", leagueKey);
    const res = await fetch(`/api/intel/player?${params.toString()}`);
    const payload = res.ok ? await res.json() : null;
    _intelCache.set(key, { payload, fetchedAt: Date.now() });
    return payload;
  } catch {
    _intelCache.set(key, { payload: null, fetchedAt: Date.now() });
    return null;
  }
}

function IntelContextSection({ row }) {
  const [intel, setIntel] = useState(null);
  const { selectedLeagueKey } = useLeague();
  const playerId = String(row?.raw?.playerId || row?.playerId || "").trim();
  const name = String(row?.name || "").trim();

  useEffect(() => {
    if (!playerId && !name) return;
    let active = true;
    setIntel(null);
    _loadPlayerIntel(playerId, name, selectedLeagueKey).then((payload) => {
      if (active) setIntel(payload);
    });
    return () => {
      active = false;
    };
  }, [playerId, name, selectedLeagueKey]);

  if (!intel) return null;
  const holders = Number(intel.holderCount) || 0;
  const heldLeagues = Number(intel.heldLeagueTotal) || 0;
  const net7d = Number(intel.windows?.["7d"]?.net) || 0;
  const buys7d = Number(intel.windows?.["7d"]?.buys) || 0;
  const sells7d = Number(intel.windows?.["7d"]?.sells) || 0;
  if (holders === 0 && buys7d === 0 && sells7d === 0) return null;

  const parts = [];
  if (holders > 0) {
    parts.push(
      `${holders} league-mate${holders === 1 ? "" : "s"} hold${holders === 1 ? "s" : ""} him ` +
        `in ${heldLeagues} league${heldLeagues === 1 ? "" : "s"}`,
    );
  }
  if (buys7d > 0 || sells7d > 0) {
    parts.push(`net ${net7d > 0 ? "+" : ""}${net7d} add${Math.abs(net7d) === 1 ? "" : "s"} this week`);
  }

  return (
    <div className={`${styles.signalBox} ${styles.signalInfo}`}>
      <span className={styles.signalTitle}>League-mate intel</span>
      <span className={styles.signalBody}>{parts.join(" · ")}</span>
    </div>
  );
}

// ── Player context section (playerctx, #539 — first UI surface) ──────
// Contracts, snap share, and depth-chart standing from the nflverse
// snapshot behind GET /api/playerctx/player.  Sleeper-id keyed (the
// only stable join the frontend holds); every block is optional —
// render what exists, hide what doesn't; the whole section degrades
// silently when the snapshot has nothing for this player.
const _ctxCache = new Map(); // playerId → {payload|null, fetchedAt}
const _CTX_TTL_MS = 30 * 60 * 1000;

export async function _loadPlayerContext(playerId) {
  const key = String(playerId || "").trim();
  if (!key) return null;
  const cached = _ctxCache.get(key);
  if (cached && Date.now() - cached.fetchedAt < _CTX_TTL_MS) return cached.payload;
  try {
    const res = await fetch(`/api/playerctx/player?playerId=${encodeURIComponent(key)}`);
    const payload = res.ok ? await res.json() : null;
    _ctxCache.set(key, { payload, fetchedAt: Date.now() });
    return payload;
  } catch {
    _ctxCache.set(key, { payload: null, fetchedAt: Date.now() });
    return null;
  }
}

function formatMoney(n) {
  const num = Number(n);
  if (!Number.isFinite(num) || num <= 0) return null;
  if (num >= 1_000_000) return `$${(num / 1_000_000).toFixed(1)}M`;
  if (num >= 1_000) return `$${Math.round(num / 1_000)}K`;
  return `$${num}`;
}

export function PlayerContextSection({ row }) {
  const [ctx, setCtx] = useState(null);
  const playerId = String(row?.raw?.playerId || row?.playerId || "").trim();

  useEffect(() => {
    if (!playerId) return;
    let active = true;
    setCtx(null);
    _loadPlayerContext(playerId).then((payload) => {
      if (active) setCtx(payload?.player || null);
    });
    return () => {
      active = false;
    };
  }, [playerId]);

  if (!ctx) return null;
  const { contract, snaps, depth } = ctx;
  if (!contract && !snaps && !depth) return null;

  return (
    <div className={styles.section} data-testid="player-context">
      <p className={styles.sectionLabel}>Player context</p>
      <div className={styles.ctxGrid}>
        {contract && (
          <div className={styles.ctxRow}>
            <span className={styles.ctxKey}>Contract</span>
            <span className={styles.ctxVal}>
              {formatMoney(contract.apy) || "—"}/yr
              {contract.endYear ? ` thru ${contract.endYear}` : ""}
            </span>
            {formatMoney(contract.guaranteed) && (
              <span className={styles.ctxNote}>{formatMoney(contract.guaranteed)} gtd</span>
            )}
            {contract.team && contract.team !== ctx.team && (
              <span
                className={styles.ctxNote}
                title="OTC contracts keep the SIGNING franchise — a traded player's deal still shows its origin team. End year can undershoot for in-contract extensions."
              >
                signed with {contract.team}
              </span>
            )}
          </div>
        )}
        {snaps && Number.isFinite(Number(snaps.pct)) && (
          <div className={styles.ctxRow}>
            <span className={styles.ctxKey}>Snaps</span>
            <span className={styles.ctxVal}>{Number(snaps.pct).toFixed(1)}%</span>
            <span className={styles.ctxNote}>
              {snaps.season} season · {snaps.games} gm ({snaps.side})
            </span>
            {Number.isFinite(Number(snaps.trend)) && Number(snaps.trend) !== 0 && (
              <Movement
                delta={Number(snaps.trend)}
                format={(n) => `${n.toFixed(1)}%`}
                srLabel={`snap share ${Number(snaps.trend) > 0 ? "up" : "down"} ${Math.abs(Number(snaps.trend)).toFixed(1)} percentage points over the last three games`}
              />
            )}
          </div>
        )}
        {depth && depth.rank != null && (
          <div className={styles.ctxRow}>
            <span className={styles.ctxKey}>Depth</span>
            <span className={styles.ctxVal}>
              {depth.position}
              {depth.rank}
            </span>
            {depth.team && <span className={styles.ctxNote}>on {depth.team}</span>}
            {depth.rank === 1 ? (
              <Badge tone="positive">starter</Badge>
            ) : (
              <Badge>backup</Badge>
            )}
          </div>
        )}
      </div>
    </div>
  );
}

// ── News section ─────────────────────────────────────────────────────
// Full news list for this player from ``useNews().byPlayer`` (all
// items, newest first).  The hook is single-flighted at module level.
// Degrades silently: no news, unavailable backend, or loading all
// render nothing.
const _POPUP_NEWS_LIMIT = 5;

// ── Realized fantasy points (Tier 3 stats surface) ──────────────────
// GET /api/player/{sleeperId}/realized scores this player's real weekly
// stat lines under THIS league's scoring settings. The endpoint has
// existed for some time and nothing called it, which is how its row
// filter came to return zero weeks for every player without anyone
// noticing.
//
// Rendered only when there are weeks to show. The endpoint answers 200
// with an empty list and a `reason` for several legitimate states
// (stats not ingested, player unmapped, offseason), and none of those
// are worth a box that says "no data" on every popup.
const _realizedCache = new Map(); // sleeperId → {payload|null, fetchedAt}
const _REALIZED_TTL_MS = 30 * 60 * 1000;

export async function _loadRealized(sleeperId) {
  const key = String(sleeperId || "").trim();
  if (!key) return null;
  const cached = _realizedCache.get(key);
  if (cached && Date.now() - cached.fetchedAt < _REALIZED_TTL_MS) return cached.payload;
  try {
    const res = await fetch(`/api/player/${encodeURIComponent(key)}/realized`);
    // 503 is the feature flag being off; 401 is signed-out. Both are
    // "nothing to show", not errors worth surfacing on a popup.
    const payload = res.ok ? await res.json() : null;
    _realizedCache.set(key, { payload, fetchedAt: Date.now() });
    return payload;
  } catch {
    _realizedCache.set(key, { payload: null, fetchedAt: Date.now() });
    return null;
  }
}

export function RealizedPointsSection({ row }) {
  const [data, setData] = useState(null);
  const sleeperId = String(row?.raw?.playerId || row?.playerId || "").trim();

  useEffect(() => {
    if (!sleeperId) return;
    let active = true;
    setData(null);
    _loadRealized(sleeperId).then((payload) => {
      if (active) setData(payload);
    });
    return () => {
      active = false;
    };
  }, [sleeperId]);

  const weeks = Array.isArray(data?.weeks) ? data.weeks : [];
  if (!weeks.length) return null;

  const best = data?.bestWeek || null;
  const worst = data?.worstWeek || null;

  return (
    <div className={styles.section} data-testid="realized-points">
      <p className={styles.sectionLabel}>
        Realized points{" "}
        <span className={styles.ctxNote}>scored on your league&apos;s settings</span>
      </p>
      <div className={styles.ctxGrid}>
        <div className={styles.ctxRow}>
          <span className={styles.ctxKey}>Total</span>
          <span className={styles.ctxVal}>
            {Number(data.totalPoints || 0).toFixed(1)} pts
          </span>
          <span className={styles.ctxNote}>
            {data.weekCount} {data.weekCount === 1 ? "week" : "weeks"} ·{" "}
            {Number(data.averagePoints || 0).toFixed(1)}/wk
          </span>
        </div>
        {best && (
          <div className={styles.ctxRow}>
            <span className={styles.ctxKey}>Best</span>
            <span className={styles.ctxVal}>
              {Number(best.fantasyPoints || 0).toFixed(1)} pts
            </span>
            <span className={styles.ctxNote}>
              {best.season} wk {best.week}
            </span>
          </div>
        )}
        {worst && (
          <div className={styles.ctxRow}>
            <span className={styles.ctxKey}>Worst</span>
            <span className={styles.ctxVal}>
              {Number(worst.fantasyPoints || 0).toFixed(1)} pts
            </span>
            <span className={styles.ctxNote}>
              {worst.season} wk {worst.week}
            </span>
          </div>
        )}
      </div>
    </div>
  );
}


function PlayerNewsSection({ playerName, position, team }) {
  const { byPlayer, digestByPlayer } = useNews();
  const { rows: liveRows } = useApp();
  // Live-pool meta index: name-only items for a name that is
  // AMBIGUOUS in the pool (CJ Allen LB vs C.J. Allen WR) are
  // suppressed here rather than shown on the wrong player's profile;
  // mentions carrying backend-stamped position/team resolve to the
  // right identity instead.
  const newsPlayerMeta = useMemo(() => buildPlayerMetaIndex(liveRows), [liveRows]);
  const items = useMemo(
    () =>
      lookupPlayerNews(byPlayer, playerName, {
        position,
        team,
        playerMeta: newsPlayerMeta,
      }),
    [byPlayer, playerName, position, team, newsPlayerMeta],
  );
  // Backend per-player digest — ONE combined entry when the player
  // has multiple recent stories.  Rendered above the raw list.
  const digest = useMemo(
    () => lookupPlayerDigest(digestByPlayer, playerName, { position }),
    [digestByPlayer, playerName, position],
  );
  if (!items.length) return null;
  return (
    <div className={styles.section}>
      <p className={styles.sectionLabel}>News ({items.length})</p>
      {digest && (
        <div className={styles.newsDigest}>
          <div className={styles.newsDigestHeadline}>{digest.headline}</div>
          <div className={styles.newsDigestSummary}>{digest.summary}</div>
          {Array.isArray(digest.sources) && digest.sources.length > 0 && (
            <div className={styles.quietNote} style={{ marginTop: 4 }}>
              Sources: {digest.sources.join(" · ")}
            </div>
          )}
        </div>
      )}
      {items.slice(0, _POPUP_NEWS_LIMIT).map((item) => (
        <div key={item.id || `${item.ts}-${item.headline}`} className={styles.newsItem}>
          <div className={styles.newsMeta}>
            <span>{timeAgo(item.ts)}</span>
            <span>{item.providerLabel || item.provider || "—"}</span>
            {item.severity && (
              <span
                className={styles.newsSeverity}
                style={{
                  color:
                    item.severity === "alert"
                      ? "var(--negative-text)"
                      : item.severity === "watch"
                        ? "var(--warning-text)"
                        : "var(--text-tertiary)",
                }}
              >
                {item.severity}
              </span>
            )}
          </div>
          <div style={{ marginTop: 2 }}>
            {item.url ? (
              <a href={item.url} target="_blank" rel="noopener noreferrer" className={styles.newsLink}>
                {item.headline}
              </a>
            ) : (
              item.headline
            )}
          </div>
        </div>
      ))}
    </div>
  );
}

/**
 * Build the ordered value-chain stages from a player row.
 *
 * Pipeline order (Final Framework live chain,
 * src/api/data_contract.py Phase 3):
 *   1. Anchor value — IDPTC's percentile-Hill value for this player,
 *      or the subgroup-only fallback when IDPTC doesn't rank them.
 *   2. Subgroup adjustment — trimmed mean-median of non-anchor source
 *      values, shrunk by α into the anchor baseline: center =
 *      anchor + α·(subgroup − anchor).  Only emitted when both
 *      anchor and subgroup contribute.
 *   3. Combined output → ``rankDerivedValue``.
 *
 * (The λ·MAD volatility penalty and the IDP calibration post-pass were
 * both retired — ``sourceSpread`` renders as a pure diagnostic.)
 */
function computeValueChain(row) {
  if (!row) return [];

  const stages = [];

  // Stage 1 — anchor baseline.  IDPTC's percentile-Hill value.
  const anchor = Number(row.anchorValue) || null;
  const subgroupBlend = Number(row.subgroupBlendValue) || null;
  const subgroupDelta =
    typeof row.subgroupDelta === "number" ? row.subgroupDelta : null;
  const alpha =
    typeof row.alphaShrinkage === "number" ? row.alphaShrinkage : null;

  if (anchor !== null && anchor > 0) {
    stages.push({
      key: "anchor",
      label: "Anchor value",
      description:
        "IDPTC percentile-Hill — the universal offense+IDP baseline",
      value: Math.round(anchor),
      delta: null,
    });
  } else if (subgroupBlend !== null && subgroupBlend > 0) {
    // Player only has subgroup coverage (no anchor) — surface the
    // subgroup blend as the effective baseline.
    stages.push({
      key: "subgroup-only",
      label: "Subgroup baseline",
      description:
        "No anchor coverage — trimmed mean-median of subgroup sources",
      value: Math.round(subgroupBlend),
      delta: null,
    });
  }

  // Stage 2 — α-shrunk subgroup adjustment (only when both anchor and
  // subgroup are present and the adjustment is non-zero).
  if (
    anchor !== null &&
    anchor > 0 &&
    subgroupBlend !== null &&
    subgroupDelta !== null &&
    alpha !== null &&
    Math.round(alpha * subgroupDelta) !== 0
  ) {
    const adjusted = Math.round(anchor + alpha * subgroupDelta);
    const prior = stages.length ? stages[stages.length - 1].value : null;
    stages.push({
      key: "subgroup",
      label: `Subgroup adjustment ×${alpha.toFixed(2)}`,
      description:
        `Subgroup blend ${Math.round(subgroupBlend)} − anchor ` +
        `${Math.round(anchor)} = Δ${subgroupDelta >= 0 ? "+" : ""}` +
        `${Math.round(subgroupDelta)}; shrunk by α=${alpha.toFixed(2)}`,
      value: adjusted,
      delta: prior !== null ? adjusted - prior : null,
    });
  }

  const blended = Number(row.rankDerivedValue) || null;
  if (blended !== null && blended > 0 && stages.length === 0) {
    // Offense rows (no anchor/subgroup stamps) — surface the final
    // blended value as a single "Blended value" chain row.
    stages.push({
      key: "blend",
      label: "Blended value",
      description:
        "Count-aware mean-median over every source that ranked this " +
        "player (value-based sources vote with their raw values; " +
        "rank-only sources go through the Hill curve).",
      value: Math.round(blended),
      delta: null,
    });
  }

  return stages;
}

/**
 * Player profile drawer — multi-source breakdown, value diagnostics,
 * edge signal, intel, news, and player context.  Triggered by clicking
 * a player name anywhere in the app.
 *
 * Props:
 *   row       — Player row object from buildRows() (null to hide)
 *   siteKeys  — Array of site key strings from dynasty data
 *   onClose   — Callback to close
 *   onAddToTrade — Optional callback to add player to trade builder
 */
export default function PlayerPopup({ row, siteKeys = [], onClose, onAddToTrade }) {
  const [chainOpen, setChainOpen] = useState(false);

  // Reset the chain panel when switching players — the new row's
  // transforms are different, so starting collapsed keeps the
  // profile compact for casual lookups.
  useEffect(() => {
    setChainOpen(false);
  }, [row?.name]);

  const edge = useMemo(() => (row ? getPlayerEdge(row) : null), [row]);
  const valueChain = useMemo(() => computeValueChain(row), [row]);

  // ── Ownership: which team holds this player + their depth-chart slot.
  // ``rawData.sleeper.teams[].name`` is already the owner's first name
  // (resolved server-side via ``src/utils/owner_names.py``).  Position
  // rank walks the team's roster restricted to the player's position,
  // by Sleeper playerId first (avoids the offense/IDP cross-universe
  // name-collision case), falling back to normalized name.
  const { rows: allRows, rawData } = useApp();
  const ownership = useMemo(() => {
    if (!row) return null;
    const sleeperTeams = rawData?.sleeper?.teams;
    if (!Array.isArray(sleeperTeams) || sleeperTeams.length === 0) return null;
    const { byId, byName } = buildTeamByPlayer(sleeperTeams);
    const playerId = String(row.raw?.playerId || row.playerId || "").trim();
    let team = playerId ? byId.get(playerId) : null;
    if (!team) team = byName.get(normalizeName(row.name));
    if (!team) return null;

    const pos = String(row.pos || "").toUpperCase().split("/")[0];
    let positionLabel = "";
    if (pos && Array.isArray(allRows) && allRows.length > 0) {
      // Build both id and name indexes over the row pool so position
      // rank uses the same identity disambiguation as the team lookup.
      const rowsById = new Map();
      const rowsByName = new Map();
      for (const r of allRows) {
        const rid = String(r?.raw?.playerId || r?.playerId || "").trim();
        if (rid && !rowsById.has(rid)) rowsById.set(rid, r);
        const rname = normalizeName(r?.name);
        if (rname && !rowsByName.has(rname)) rowsByName.set(rname, r);
      }
      const teamPlayerIds = Array.isArray(team.playerIds) ? team.playerIds : [];
      const teamPlayerNames = Array.isArray(team.players) ? team.players : [];
      const resolved = [];
      // Prefer the id list when the team has one (newer contract); fall
      // back to names when only the name list is present.
      const idsToUse = teamPlayerIds.length > 0 ? teamPlayerIds : null;
      if (idsToUse) {
        for (const id of idsToUse) {
          const r = rowsById.get(String(id || "").trim());
          if (r) resolved.push(r);
        }
      } else {
        for (const n of teamPlayerNames) {
          const r = rowsByName.get(normalizeName(n));
          if (r) resolved.push(r);
        }
      }
      const samePositionRanks = resolved
        .filter((r) => {
          const p = String(r.pos || "").toUpperCase().split("/")[0];
          if (p !== pos) return false;
          const v = Number(r.rankDerivedValue);
          return Number.isFinite(v) && v > 0;
        })
        .sort(
          (a, b) =>
            Number(b.rankDerivedValue) - Number(a.rankDerivedValue),
        );
      const matchesRow = (r) => {
        if (playerId) {
          const rid = String(r?.raw?.playerId || r?.playerId || "").trim();
          if (rid && rid === playerId) return true;
        }
        return normalizeName(r.name) === normalizeName(row.name);
      };
      const idx = samePositionRanks.findIndex(matchesRow);
      if (idx >= 0) positionLabel = `${pos}${idx + 1}`;
    }

    return {
      ownerId: String(team.ownerId || ""),
      ownerLabel: String(team.name || "").trim(),
      positionLabel,
    };
  }, [row, rawData, allRows]);

  // Injury impact lookup from the server-side signals block.
  // Only populated for roster players today — non-roster players
  // won't have impact data, and the chip simply doesn't render.
  const { selectedTeam, loading: teamLoading } = useTeam();
  const { signals: serverSignals } = useTerminal({
    // Hold the fetch until team identity resolves from the contract
    // (prevents the discarded ownerId:"" duplicate call).
    skip: teamLoading,
    ownerId: String(selectedTeam?.ownerId || ""),
    teamName: selectedTeam?.name || "",
    windowDays: 30,
  });
  const injury = useMemo(() => {
    const name = String(row?.name || "").toLowerCase();
    if (!name) return null;
    const hit = (serverSignals || []).find(
      (s) => s?.name && String(s.name).toLowerCase() === name,
    );
    if (!hit?.injuryImpact) return null;
    return { impact: hit.injuryImpact, adjustedValue: hit.injuryAdjustedValue };
  }, [serverSignals, row?.name]);

  // Watchlist toggle — wires the star button in the header to
  // useUserState.toggleWatchlist.  ``serverBacked`` drives the
  // tooltip so users know whether the state syncs across devices.
  const { state: userState, toggleWatchlist, serverBacked: userStateServerBacked } = useUserState();
  const onWatchlist = useMemo(() => {
    const name = String(row?.name || "").toLowerCase();
    if (!name) return false;
    const list = userState?.watchlist || [];
    return list.some((x) => String(x).toLowerCase() === name);
  }, [userState?.watchlist, row?.name]);

  const siteDetails = useMemo(() => {
    if (!row) return [];
    // Prefer the backend's 9,999-scale ``valueContribution`` stamp —
    // the same normalized vote each source casts into the blend, and
    // the same number rendered in the rankings row chips.  Reading
    // ``canonicalSites`` here (the previous behaviour) mixed value
    // sources' raw native scale with rank-signal sources' synthetic
    // rank encoding, so IDP expert boards were either dwarfed to
    // invisible bars or dropped entirely.  Using
    // ``sourceRankMeta[key].valueContribution`` keeps the profile in
    // lockstep with the rankings table.
    //
    // Two exceptions to the contribution-first rule:
    //   * ``RAW_VALUE_PREFERRED_KEYS`` — sources whose published
    //     0-9999 board is the user-meaningful display number (e.g.
    //     KTC TE++).  Read raw scrape from ``row.rawSourceValues``
    //     so users can cross-check against keeptradecut.com.
    //   * ``RETIRED_FROM_CHART_KEYS`` — sources retired from the
    //     blend whose canonical replacement covers the same signal.
    const meta = row.sourceRankMeta || {};
    const canonicalSites = row.canonicalSites || {};
    const rawSourceValues = row.rawSourceValues || {};
    const sourceByKey = Object.fromEntries(
      RANKING_SOURCES.map((s) => [s.key, s]),
    );
    const candidateKeys = Array.from(
      new Set([
        ...(siteKeys.length > 0 ? siteKeys : []),
        ...Object.keys(meta),
        ...Object.keys(canonicalSites),
        ...Object.keys(rawSourceValues),
      ]),
    );
    const rows = candidateKeys
      .map((key) => {
        if (RETIRED_FROM_CHART_KEYS.has(key)) return null;
        const src = sourceByKey[key];
        const label = src?.columnLabel || src?.displayName || key;
        // Raw-preferred sources: read from rawSourceValues first so
        // the chip matches the source's published board.
        if (RAW_VALUE_PREFERRED_KEYS.has(key)) {
          const raw = Number(rawSourceValues[key]);
          if (Number.isFinite(raw) && raw > 0) {
            return { key, label, value: raw };
          }
          // Fall through to contribution / canonicalSites if the raw
          // stamp is missing (legacy payload, partial scrape).
        }
        // Vendor-native value for rank-signal sources (FC crowd value,
        // OTC 0-100, PFK 0-9999, ...).  Display-only annotation — the
        // bar/value stays on the normalized 9,999 contribution scale.
        const nativeRaw = Number(row.sourceNativeValues?.[key]);
        const native = Number.isFinite(nativeRaw) && nativeRaw > 0 ? nativeRaw : null;
        const contribution = Number(meta[key]?.valueContribution);
        if (Number.isFinite(contribution) && contribution > 0) {
          return { key, label, value: contribution, native };
        }
        // Legacy payloads may not carry ``valueContribution`` yet.
        // Fall back to ``canonicalSites`` only for value-based sources
        // — their raw slot is a monotonic value scale.  Rank-signal
        // sources skip this path because their canonicalSites entry is
        // a synthetic rank encoding, not a renderable value.
        if (src?.isRankSignal) return null;
        const raw = Number(canonicalSites[key]);
        if (Number.isFinite(raw) && raw > 0) {
          return { key, label, value: raw };
        }
        return null;
      })
      .filter(Boolean);
    const maxVal = Math.max(1, ...rows.map((r) => r.value));
    return rows
      .map((r) => ({ ...r, pct: (r.value / maxVal) * 100 }))
      .sort((a, b) => b.value - a.value);
  }, [row, siteKeys]);

  // Consensus narrative based on coefficient of variation
  const consensusText = useMemo(() => {
    if (siteDetails.length <= 1) return siteDetails.length === 1 ? "Only 1 source — speculative" : "";
    const vals = siteDetails.map((s) => s.value);
    const mean = vals.reduce((a, b) => a + b, 0) / vals.length;
    const variance = vals.reduce((a, v) => a + Math.pow(v - mean, 2), 0) / vals.length;
    const cv = mean > 0 ? Math.sqrt(variance) / mean : 0;
    if (cv < 0.15) return `Strong consensus (CV ${(cv * 100).toFixed(0)}%) — sources agree closely`;
    if (cv < 0.30) return `Moderate agreement (CV ${(cv * 100).toFixed(0)}%) — some spread between sources`;
    return `Sources disagree significantly (CV ${(cv * 100).toFixed(0)}%) — high volatility player`;
  }, [siteDetails]);

  const rank = row ? resolvedRank(row) : Infinity;
  const values = row?.values || {};

  return (
    <Drawer
      open={Boolean(row)}
      onClose={onClose}
      title={row ? row.name : ""}
      closeLabel="Close player details"
      className={styles.wideDrawer}
    >
      {row && (
        <>
          {/* ── Identity header ── */}
          <div className={styles.identity}>
            <PlayerImage
              playerId={row.raw?.playerId}
              team={row.raw?.team || row.team}
              position={row.pos}
              name={row.name}
              size={44}
            />
            <div style={{ minWidth: 0, flex: 1 }}>
              <div className={styles.identityMeta}>
                <Badge>{row.pos}</Badge>
                {row.raw?.team && <span>{row.raw.team}</span>}
                {row.age != null && <span>age {row.age}</span>}
                {row.yearsExp != null && (
                  <span>
                    {row.yearsExp === 0 ? "rookie year" : `${row.yearsExp} yr exp`}
                  </span>
                )}
                {row.raw?.rookie && <Badge tone="info">ROOKIE</Badge>}
                {rank < Infinity && <span className="ds-mono">Rank #{rank}</span>}
              </div>
              {ownership && ownership.ownerLabel && (
                <div className={styles.ownership} style={{ marginTop: 4 }}>
                  <span>Owned by</span>
                  {ownership.ownerId ? (
                    <Link
                      href={`/league/franchise/${encodeURIComponent(ownership.ownerId)}`}
                      onClick={() => onClose?.()}
                      className={styles.ownerLink}
                    >
                      {ownership.ownerLabel}
                    </Link>
                  ) : (
                    <strong>{ownership.ownerLabel}</strong>
                  )}
                  {ownership.positionLabel && (
                    <span>· {ownership.positionLabel} on roster</span>
                  )}
                </div>
              )}
            </div>
          </div>

          <div className={styles.identityActions}>
            <Button
              size="sm"
              variant={onWatchlist ? "secondary" : "ghost"}
              aria-pressed={onWatchlist}
              icon={<Icon name={onWatchlist ? "star-filled" : "star"} size={13} />}
              onClick={() => toggleWatchlist(row.name)}
              title={
                onWatchlist
                  ? userStateServerBacked
                    ? "Remove from watchlist (synced)"
                    : "Remove from watchlist"
                  : userStateServerBacked
                  ? "Add to watchlist (synced across devices)"
                  : "Add to watchlist (local)"
              }
            >
              {onWatchlist ? "Watching" : "Watch"}
            </Button>
            {/* The comparison page is URL-driven (?p1=&p2=) but nothing
                in the product linked to it — it was reachable only from
                the command palette, so you had to already know it
                existed.  The popup is where someone is already looking
                at one player and wondering how he stacks up. */}
            <Button
              as={Link}
              href={`/players/compare?p1=${encodeURIComponent(row.name)}`}
              size="sm"
              variant="ghost"
              onClick={() => onClose?.()}
              aria-label={`Compare ${row.name} with another player`}
            >
              Compare
            </Button>
            {onAddToTrade && (
              <Button
                size="sm"
                variant="primary"
                onClick={() => { onAddToTrade(row); onClose?.(); }}
                aria-label={`Add ${row.name} to trade`}
              >
                Add to Trade
              </Button>
            )}
          </div>

          {/* ── Primary value — the live blended rankDerivedValue with
              no post-blend adjustments. ── */}
          <div className={styles.valueRow}>
            <StatTile bare label="Our Value" value={Math.round(values.full || 0).toLocaleString()} />
            {injury && injury.impact?.appliedDiscountPct > 0 && (
              <StatTile
                bare
                label={`Adjusted (injury −${Number(injury.impact.appliedDiscountPct).toFixed(
                  injury.impact.appliedDiscountPct < 1 ? 2 : 1,
                )}%)`}
                value={
                  Number.isFinite(Number(injury.adjustedValue))
                    ? Number(injury.adjustedValue).toLocaleString()
                    : "—"
                }
                meta={<Badge tone="negative">injury</Badge>}
              />
            )}
            {injury && injury.impact?.offseasonSuppressed && (
              <span
                className={styles.quietNote}
                title={`Headline: ${injury.impact.headline}`}
              >
                Injury news · offseason (value unchanged)
              </span>
            )}
          </div>

          {/* ── Short-term context (ROS) — read-only labels, never
              mutates the dynasty value.  Gated by settings.showRosTags. ── */}
          <RosContextSection row={row} />

          {/* ── Player context (contracts / snaps / depth) ── */}
          <PlayerContextSection row={row} />
          <RealizedPointsSection row={row} />

          {/* Value chain — how we arrived at Our Value */}
          {valueChain.length > 0 && (
            <div className={styles.section}>
              <button
                type="button"
                className={styles.chainToggle}
                onClick={() => setChainOpen((v) => !v)}
                aria-expanded={chainOpen}
                title={
                  chainOpen
                    ? "Hide the stage-by-stage value derivation"
                    : "See how the blend produced the final number"
                }
              >
                <Icon name={chainOpen ? "chevron-down" : "chevron-right"} size={10} />
                Value chain — how we got {Math.round(values.full || 0).toLocaleString()}
                {!chainOpen && (
                  <span className={styles.quietNote}>
                    {valueChain.length} stage{valueChain.length !== 1 ? "s" : ""}
                  </span>
                )}
              </button>
              {chainOpen && (
                <div className={styles.chainBody}>
                  {valueChain.map((stage, i) => (
                    <div key={stage.key} className={styles.chainStage}>
                      <div className={styles.chainIndex}>{i + 1}</div>
                      <div style={{ flex: 1 }}>
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
                </div>
              )}
            </div>
          )}

          {/* League-mate intel (Insider Trading) — silently absent when
              the intel snapshot has nothing for this asset */}
          <IntelContextSection row={row} />

          {/* Edge signal */}
          {edge?.signal && (
            <div
              className={`${styles.signalBox} ${edge.signal === "BUY" ? styles.signalBuy : styles.signalSell}`}
            >
              <span className={styles.signalTitle}>
                {edge.signal === "BUY" ? "Buy Low" : "Sell High"}
              </span>
              <span className={styles.signalBody}>
                {edge.signal === "BUY"
                  ? `Consensus values this player ${edge.valueGapPct}% above KTC — market is cheap`
                  : `KTC values this player ${edge.valueGapPct}% above consensus — market overvalues`}
                {edge.edgePct > 0 && <> · ~{edge.edgePct}% value gap</>}
              </span>
            </div>
          )}

          {/* Pick value projection — package-now-or-wait context for
              future picks.  ``pickProjectedDraftValue`` is stamped on
              every valued pick row; render only on a positive gain. */}
          {row?.assetClass === "pick"
            && Number.isFinite(row?.pickProjectedDraftValue)
            && Number(row?.pickProjectedDraftValueGain) > 0 && (
              <div className={`${styles.signalBox} ${styles.signalInfo}`}>
                <span className={styles.signalTitle}>Projected at draft</span>
                <span className={styles.signalBody}>
                  ~{Number(row.pickProjectedDraftValue).toLocaleString()} by the {row.pickProjectedDraftYear} draft
                  {Number(row.pickProjectedDraftValueGainPct) > 0 && (
                    <>
                      {" · "}
                      <Movement
                        delta={Number(row.pickProjectedDraftValueGainPct)}
                        format={(n) => `${n}%`}
                      />
                      {" gain"}
                    </>
                  )}
                </span>
              </div>
            )}

          {/* 180-day rank-history mini-chart */}
          <div className={styles.section}>
            <PlayerRankHistoryChart row={row} />
          </div>

          {/* Recent news for this player — renders nothing when the
              player has no items or the feed is unavailable. */}
          <PlayerNewsSection
            playerName={row.name}
            position={row.pos}
            team={row.raw?.team}
          />

          {/* Source breakdown bars */}
          {siteDetails.length > 0 && (
            <div className={styles.section}>
              <p className={styles.sectionLabel}>Source Breakdown</p>
              {siteDetails.map((s) => (
                <div key={s.key} className={styles.sourceRow}>
                  <div className={styles.sourceLabel} title={s.key}>
                    {s.label}
                  </div>
                  {/* Bar tone encodes MAGNITUDE relative to the
                      player's top source (>=90% / >=50% / below) —
                      information, not decoration: it shows at a glance
                      which sources are carrying the blend and which
                      are dragging it. Ported from the pre-R2 popup
                      onto semantic tokens. */}
                  <div className={styles.sourceTrack}>
                    <div
                      className={[
                        styles.sourceFill,
                        s.pct >= 90
                          ? styles.sourceFillHigh
                          : s.pct >= 50
                            ? styles.sourceFillMid
                            : styles.sourceFillLow,
                      ].join(" ")}
                      style={{ width: `${Math.min(100, s.pct)}%` }}
                    />
                  </div>
                  <div
                    className={styles.sourceValue}
                    title={s.native != null
                      ? `Normalized contribution ${Math.round(s.value).toLocaleString()} — vendor's native value ${s.native.toLocaleString()}`
                      : undefined}
                  >
                    {Math.round(s.value).toLocaleString()}
                    {s.native != null && (
                      <span className={styles.sourceNative}>
                        {" "}({s.native.toLocaleString()})
                      </span>
                    )}
                  </div>
                </div>
              ))}
            </div>
          )}

          {/* Consensus narrative */}
          {consensusText && (
            <p className={styles.quietNote} style={{ marginTop: 10, fontStyle: "italic" }}>
              {consensusText}
            </p>
          )}

          {/* Source count + tier footer */}
          <div className={styles.footer}>
            {row.siteCount > 0 && <span>{row.siteCount} source{row.siteCount !== 1 ? "s" : ""} contributing</span>}
            {row.canonicalTierId && <span> · Tier {row.canonicalTierId}</span>}
          </div>
        </>
      )}
    </Drawer>
  );
}
