"use client";

import {
  useMemo,
  useState,
  useCallback,
  useDeferredValue,
  useEffect,
  useRef,
  useTransition,
} from "react";
import dynamic from "next/dynamic";
import { useDynastyData } from "@/components/useDynastyData";
import {
  resolvedRank,
  RANKING_SOURCES,
  siteOverridesAreCustomized,
  valuationBasisLabel,
  valuationBasisOf,
} from "@/lib/dynasty-data";
import { useSettings } from "@/components/useSettings";
import { useApp } from "@/components/AppShell";
import { useTeam } from "@/components/useTeam";
import { useUserState } from "@/components/useUserState";
import {
  tierLabel,
  effectiveTierId,
  valueBand,
  rowChips,
  DEFAULT_ROW_LIMIT,
} from "@/lib/rankings-helpers";
import {
  LENSES,
  SCREENS,
  isScreen,
  getLens,
  applyLens,
  actionLabel,
  cautionLabels,
  computeEdgeSummary,
} from "@/lib/edge-helpers";
import {
  posBadgeClass,
  confBadgeClass as confidenceBadgeClass,
  confBadgeLabel as confidenceBadgeLabel,
  marketEdge,
  marketAction,
  isEligibleForBoard,
} from "@/lib/display-helpers";
import {
  EXPERIENCE_BUCKETS,
  FREE_AGENT_OWNER,
  rowMatches,
  teamOptions,
} from "@/lib/player-filters";
import { buildTeamByPlayer } from "@/lib/waiver-logic";
import { useBdvmEndpoint } from "@/components/useBdvm";
import {
  buildBdvmIndex,
  bdvmEntryForRow,
  bdvmSignalEdgeCss,
  formatBdvmGap,
  formatBdvmValue,
} from "@/lib/bdvm";
import RankChangeGlyph from "@/components/graphs/RankChangeGlyph";
import { PlayerImage } from "@/components/ui";
import {
  Badge,
  Banner,
  Button,
  DataTable,
  EmptyState,
  FailureState,
  HelpModal,
  Icon,
  InfoTip,
  Input,
  Movement,
  PageHeader,
  Panel,
  Select,
  SkeletonTable,
  StatTile,
  Tabs,
  tabId,
  tabPanelId,
} from "@/components/ds";
import { useNews } from "@/components/useNews";
import { lookupPlayerNews } from "@/lib/player-name-match";
import { buildPlayerMetaIndex } from "@/lib/news-filters";
import { formatSourceCell, exportSourceCells } from "./board-utils";
import {
  MethodologySection,
  TopMoversRail,
  EdgeRail,
  MobileSourceStrip,
  SourceAuditPanel,
} from "./board-sections";
import styles from "./board.module.css";

// Methodology charts: rendered only when `showMethodology` is true, and
// that state starts false — so on every page load this was ~18 KB of
// chart code parsed for a panel nobody had opened. Gated at the render
// site already, so `dynamic()` is enough here; no mount-latch needed
// the way /trade's collapsed panel required one.
const HillCurveExplorer = dynamic(
  () => import("@/components/graphs/HillCurveExplorer"),
  { ssr: false },
);
const TierGapWaterfall = dynamic(
  () => import("@/components/graphs/TierGapWaterfall"),
  { ssr: false },
);

// ── UNIFIED RANKINGS PAGE (Redesign R2) ──────────────────────────────
// Trust-forward blended board: offense + IDP sorted by unified rank.
// Rebuilt on the ds primitives (PageHeader / Panel / DataTable / Tabs)
// — ALL board behavior is unchanged from the pre-R2 page: lenses,
// pos/confidence filters, the Phase 3 advanced-filter rail + token
// search, sortable columns (incl. dynamic source columns), tier
// grouping, row expansion with the source-audit panel, watchlist
// toggles, news chips, copy/CSV export, row limit + filter bypass,
// IDP gating, and ?pos= deep-link seeding.  buildRows stays pure;
// backend stamps render verbatim; no ranking math client-side.
//
// Default experience decisions:
//   • Lens: "consensus" (standard rank view)
//   • Sort: by rank ascending (most intentional view)
//   • Rows shown: 200 initially (starters + depth in 12-team)
//   • Tier grouping: ON by default
//   • Edge rail: visible by default (quick-scan signal)
//   • Flagged rows: shown inline (not hidden)
//   • Quarantined rows: shown but dimmed
//
// Performance note.  This used to read "virtualization is not
// warranted; revisit only if the default limit grows past ~500 rows",
// and the row limit was doing the work it credited itself with — but
// only while the user left the limit alone.  "Show all" takes the board
// to ~1,100 rows / ~31k DOM nodes, and there it collapses: measured 6.8
// FPS during a real scroll against a 60.0 FPS control on the same
// hardware, with a p95 frame time of 167 ms.
//
// The cost is TABLE LAYOUT, not paint, and no CSS reaches it (the
// containment spec excludes table-row / table-row-group, so
// `content-visibility` and `contain` both measured as no-ops).  Hence
// `virtualize` below, and hence `freezeColumnWidths` as its
// prerequisite rather than its companion.  Ablation table and method:
// components/ds/useRowWindow.js and docs/performance-optimization.md.
//
// The row limit STAYS.  It is a different control — it bounds the
// initial commit, where windowing bounds the scroll — and the
// useTransition wrapper on `growRows` still exists for the same reason
// it always did.

const CONFIDENCE_FILTERS = [
  { key: "all", label: "Any confidence" },
  { key: "high", label: "High" },
  { key: "medium", label: "Medium" },
  { key: "low", label: "Low" },
];

function posMatchesFilter(pos, assetClass, filter, row) {
  if (filter === "all") return true;
  if (filter === "offense") return assetClass === "offense";
  if (filter === "idp") return assetClass === "idp";
  if (filter === "pick") return assetClass === "pick";
  if (filter === "rookie") return !!row?.rookie;
  if (filter.startsWith("rookie:"))
    return !!row?.rookie && pos === filter.split(":")[1];
  return pos === filter;
}

// Explicit confidence explanation — shared by the Confidence cell and
// the expanded audit panel.
function confidenceExplain(row) {
  return (
    row.confidenceLabel ||
    (row.confidenceBucket === "high"
      ? "2+ sources, tight agreement (spread ≤30)"
      : row.confidenceBucket === "medium"
        ? "2+ sources, moderate spread (30-80)"
        : row.confidenceBucket === "low"
          ? "Single source or wide disagreement (spread >80)"
          : "Unranked")
  );
}

// ── Custom Mix badge ─────────────────────────────────────────────────
// Renders next to the page title when the active rankings payload was
// computed from a user-customized source configuration.  Clicking the
// badge toggles a short description listing disabled sources and any
// weights that differ from the registry defaults.  The data comes from
// ``rawData.rankingsOverride`` which the backend stamps on both the
// full-contract and delta-merged responses.
//
// The derivation logic is factored into ``describeCustomMix`` so unit
// tests can pin the business rules without spinning up a DOM.
export function describeCustomMix(rankingsOverride) {
  if (!rankingsOverride || !rankingsOverride.isCustomized) {
    return { active: false, disabled: [], reweighted: [], summary: "" };
  }
  const received = rankingsOverride.received || {};
  const defaults = rankingsOverride.defaults || {};
  const weights = rankingsOverride.weights || {};

  const disabled = [];
  const reweighted = [];
  for (const src of RANKING_SOURCES) {
    const ov = received[src.key];
    if (ov && ov.include === false) {
      disabled.push(src.columnLabel || src.displayName);
      continue;
    }
    const active = Number(weights[src.key]);
    const def = Number(defaults[src.key] ?? src.weight ?? 1);
    if (Number.isFinite(active) && active !== def) {
      reweighted.push(
        `${src.columnLabel || src.displayName} ${def.toFixed(1)}→${active.toFixed(1)}`,
      );
    }
  }

  const parts = [];
  if (disabled.length) parts.push(`${disabled.length} disabled`);
  if (reweighted.length) parts.push(`${reweighted.length} reweighted`);
  const summary = parts.length ? `(${parts.join(", ")})` : "";

  return { active: true, disabled, reweighted, summary };
}

function CustomMixBadge({ rankingsOverride }) {
  const [open, setOpen] = useState(false);
  const { active, disabled, reweighted, summary } =
    describeCustomMix(rankingsOverride);
  if (!active) return null;

  return (
    <span className={styles.popoverWrap} aria-label="Custom source mix active">
      <button
        type="button"
        className="ds-badge ds-badge--warning custom-mix-badge"
        onClick={() => setOpen((v) => !v)}
        aria-expanded={open}
        title={
          open
            ? "Hide custom mix details"
            : "Click to see which sources are customized"
        }
      >
        Custom Mix {summary}
      </button>
      {open && (
        <div className={styles.popover} role="tooltip">
          <p className={styles.popoverHeader}>Custom source configuration</p>
          {disabled.length > 0 && (
            <p className={styles.popoverHint}>
              <strong>Disabled:</strong> {disabled.join(", ")}
            </p>
          )}
          {reweighted.length > 0 && (
            <p className={styles.popoverHint}>
              <strong>Reweighted:</strong> {reweighted.join(", ")}
            </p>
          )}
          <p className={styles.popoverHint}>
            Change these on the Settings page.
          </p>
        </div>
      )}
    </span>
  );
}

// ── Main component ───────────────────────────────────────────────────

export default function RankingsPage() {
  const { loading, error, failure, rows, rawData, retry } = useDynastyData();
  const {
    settings,
    update: updateSetting,
    updateSiteWeight,
    resetSiteWeights,
  } = useSettings();
  const [colsMenuOpen, setColsMenuOpen] = useState(false);
  const [sourcesMenuOpen, setSourcesMenuOpen] = useState(false);
  // Per-source blend inclusion.  ``siteWeights[key].include === false``
  // removes a source from the average; anything else keeps it in.
  // useDynastyData already observes ``settings.siteWeights`` and
  // re-fetches through POST /api/rankings/overrides, which filters
  // disabled sources in _compute_unified_rankings — so flipping a
  // checkbox here transparently rebuilds the blend with no extra
  // wiring and no parallel ranking path.
  const siteWeights = settings.siteWeights || {};
  const includedSourceKeys = useMemo(
    () =>
      RANKING_SOURCES.filter((s) => siteWeights[s.key]?.include !== false).map(
        (s) => s.key,
      ),
    [siteWeights],
  );
  const excludedSourceCount =
    RANKING_SOURCES.length - includedSourceKeys.length;
  // Reset clears BOTH exclusions and custom weights, so its enabled
  // state must track any override — not just excluded sources — or a
  // weights-only customization (set on /settings) can't be cleared
  // here even though the tooltip promises it (Codex PR #438 P2).
  const hasSourceOverrides = useMemo(
    () => siteOverridesAreCustomized(siteWeights),
    [siteWeights],
  );
  const toggleSourceIncluded = useCallback(
    (key, included) => {
      updateSiteWeight(key, "include", included);
    },
    [updateSiteWeight],
  );
  const hiddenSiteCols = settings.hiddenSiteCols || {};
  const visibleSources = useMemo(
    () => RANKING_SOURCES.filter((s) => !hiddenSiteCols[s.key]),
    [hiddenSiteCols],
  );
  const hiddenCount = RANKING_SOURCES.length - visibleSources.length;
  const toggleSiteCol = useCallback(
    (key) => {
      const next = { ...(settings.hiddenSiteCols || {}) };
      if (next[key]) delete next[key];
      else next[key] = true;
      updateSetting("hiddenSiteCols", next);
    },
    [settings.hiddenSiteCols, updateSetting],
  );
  const showAllSiteCols = useCallback(() => {
    updateSetting("hiddenSiteCols", {});
  }, [updateSetting]);
  const { openPlayerPopup } = useApp();
  // IDP gating — when the active league has ``idpEnabled: false``
  // we strip IDP filter tabs from the pos-filter dropdown and drop
  // IDP rows from the list.  The underlying blended board still lives
  // on the backend; we just don't surface it here.
  const { idpEnabled } = useTeam();
  const {
    state: userState,
    toggleWatchlist,
    serverBacked: watchlistServerBacked,
  } = useUserState();
  const watchlistLower = useMemo(
    () =>
      new Set((userState?.watchlist || []).map((n) => String(n).toLowerCase())),
    [userState?.watchlist],
  );
  // Recent news → per-row news chip (lookupPlayerNews is O(1); the
  // news hook is single-flighted at module level).
  const { byPlayer: newsByPlayer } = useNews();

  // BDVM fundamental gap — optional flag-gated enrichment. Non-blocking:
  // the board renders without it; the column appears only when the
  // endpoint answers ok (bdvm_engine on + a projection snapshot exists)
  // and vanishes silently on any 503/failure. League-config-scoped data
  // joined onto rows at render time — never stamped into the contract.
  const { data: bdvmData, failure: bdvmFailure } = useBdvmEndpoint("/api/bdvm/values");
  const bdvmIndex = useMemo(
    () => (!bdvmFailure && bdvmData?.status === "ok" ? buildBdvmIndex(bdvmData) : null),
    [bdvmData, bdvmFailure],
  );
  const newsPlayerMeta = useMemo(() => buildPlayerMetaIndex(rows), [rows]);
  const [query, setQuery] = useState("");
  const [posFilter, setPosFilter] = useState("all");
  const [confFilter, setConfFilter] = useState("all");
  const [activeLens, setActiveLens] = useState("consensus");
  const [showTiers, setShowTiers] = useState(true);
  const [showEdgeRail, setShowEdgeRail] = useState(true);
  const [rowLimit, setRowLimit] = useState(DEFAULT_ROW_LIMIT);
  // Growing the board is a NON-URGENT update.  "Show all" takes the
  // rendered rows from 200 to ~1,095 (36 DOM nodes each), and committing
  // that synchronously froze the page for a measured 6.9s on an
  // unthrottled CPU and 20.9s at 6x throttle — the tab accepted no
  // input for the whole window, which reads as a crash rather than a
  // slow load.  Marking it a transition lets React keep the current
  // board interactive and paint while the larger one is prepared, and
  // gives us a real pending flag for the button instead of a dead
  // control.  It does NOT reduce the final row count — see
  // docs/performance-optimization.md for why virtualizing this table
  // needs its column widths pinned first.
  const [rowGrowthPending, startRowGrowth] = useTransition();
  const growRows = useCallback(
    (next) => {
      startRowGrowth(() => {
        setRowLimit(next);
      });
    },
    [startRowGrowth],
  );
  const [sortCol, setSortCol] = useState("rank");
  const [sortAsc, setSortAsc] = useState(true);
  const [copyStatus, setCopyStatus] = useState("");
  const [showMethodology, setShowMethodology] = useState(false);
  const [expandedRow, setExpandedRow] = useState(null);
  // Advanced filter rail (Phase 3).  ``adv`` holds raw control values
  // (strings from inputs); the criteria object handed to rowMatches is
  // derived in ``advCriteria`` below.
  const [advOpen, setAdvOpen] = useState(false);
  const [adv, setAdv] = useState({});
  const setAdvField = useCallback((key, value) => {
    setAdv((prev) => {
      const next = { ...prev };
      if (value === "" || value === false || value == null) delete next[key];
      else next[key] = value;
      return next;
    });
  }, []);
  const clearAdv = useCallback(() => setAdv({}), []);

  // If the user is viewing an IDP-only filter and then switches to
  // a league that disables IDP, snap back to "all" so the board
  // doesn't render empty.
  useEffect(() => {
    if (
      !idpEnabled &&
      (posFilter === "idp" ||
        posFilter === "DL" ||
        posFilter === "LB" ||
        posFilter === "DB")
    ) {
      setPosFilter("all");
    }
  }, [idpEnabled, posFilter]);

  // Seed ``posFilter`` from the URL query string on first load.  Lets
  // the per-position drill-down routes (e.g. /rankings/qb) deep-link
  // into a pre-filtered view.  Recognised values mirror the dropdown
  // options: all / offense / idp / pick / rookie / rookie:QB / QB /
  // RB / WR / TE / DL / LB / DB.
  useEffect(() => {
    if (typeof window === "undefined") return;
    const params = new URLSearchParams(window.location.search);
    const requested = (params.get("pos") || "").trim();
    if (!requested) return;
    const normalized = ["all", "offense", "idp", "pick", "rookie"].includes(
      requested.toLowerCase(),
    )
      ? requested.toLowerCase()
      : requested.toUpperCase();
    setPosFilter(normalized);
    // Run once on mount only — subsequent filter changes go through
    // the dropdown.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  // Seed the board view from ``?screen=`` / ``?lens=``.  The retired
  // /finder route redirects here with its workflow key, so old links
  // and bookmarks land on the same question they always did.
  useEffect(() => {
    if (typeof window === "undefined") return;
    const params = new URLSearchParams(window.location.search);
    const requested = (params.get("screen") || params.get("lens") || "").trim();
    if (!requested) return;
    // Unknown keys fall through to the default board rather than
    // wedging it on a view that resolves to nothing.
    if (getLens(requested).key !== requested) return;
    handleLensChange(requested);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  // Switch lens: reset sort to default, expand row limit
  const handleLensChange = useCallback((key) => {
    setActiveLens(key);
    const lens = getLens(key);
    if (lens.sort) {
      // Non-consensus lenses have their own sort — disable manual sort
      setSortCol("lens");
      setSortAsc(true);
    } else {
      setSortCol("rank");
      setSortAsc(true);
    }
    // Expand limit for filtered lenses since they show fewer rows
    if (key !== "consensus") {
      setRowLimit(Infinity);
    } else {
      setRowLimit(DEFAULT_ROW_LIMIT);
    }
  }, []);

  // ── Base eligible list ──────────────────────────────────────────
  const eligible = useMemo(() => {
    // 2026 rookie draft has passed — hide current-year slot picks from
    // the board.  Rows stay in buildRows so value resolution still
    // works for trade history; we filter only at display time.
    let filtered = rows
      .filter(isEligibleForBoard)
      .filter((r) => !(r.assetClass === "pick" && /^2026\b/.test(r.name)));
    if (!idpEnabled) {
      return filtered.filter((r) => r?.assetClass !== "idp");
    }
    return filtered;
  }, [rows, idpEnabled]);

  // ── Trust summary stats (single pass) ───────────────────────────
  const trustStats = useMemo(() => {
    let high = 0;
    let medium = 0;
    let low = 0;
    let quarantined = 0;
    let multiSource = 0;
    for (const r of eligible) {
      const bucket = r.confidenceBucket;
      if (bucket === "high") high++;
      else if (bucket === "medium") medium++;
      else if (bucket === "low" || bucket === "none") low++;
      if (r.quarantined) quarantined++;
      if ((r.sourceCount || 0) >= 2) multiSource++;
    }
    return {
      total: eligible.length,
      high,
      medium,
      low,
      quarantined,
      multiSource,
    };
  }, [eligible]);

  // ── Edge summary ─────────────────────────────────────────────────
  const edgeSummary = useMemo(() => computeEdgeSummary(eligible), [eligible]);

  // (Top movers are derived AFTER the filtered list below — the rail
  // reflects the current lens/filter view, matching pre-R2 behavior.)

  // ── Advanced filters (Phase 3) ──────────────────────────────────
  // Ownership is league-scoped while rows are scoring-profile-scoped
  // (the CLAUDE.md split), so the owner join happens here at render
  // time via buildTeamByPlayer — never stamped into the contract.
  const teamByPlayer = useMemo(
    () => buildTeamByPlayer(rawData?.sleeper?.teams || []),
    [rawData?.sleeper?.teams],
  );
  const ownerOptions = useMemo(
    () =>
      (rawData?.sleeper?.teams || [])
        .map((t) => String(t?.name || "").trim())
        .filter(Boolean)
        .sort((a, b) => a.localeCompare(b)),
    [rawData?.sleeper?.teams],
  );
  const nflTeamOptions = useMemo(() => teamOptions(eligible), [eligible]);
  const advCriteria = useMemo(() => {
    const c = {};
    const numOrNull = (v) => {
      if (v === "" || v == null) return null;
      const n = Number(v);
      return Number.isFinite(n) ? n : null;
    };
    if (numOrNull(adv.ageMin) != null) c.ageMin = numOrNull(adv.ageMin);
    if (numOrNull(adv.ageMax) != null) c.ageMax = numOrNull(adv.ageMax);
    if (adv.experience) c.experience = adv.experience;
    if (adv.nflTeam) c.nflTeam = adv.nflTeam;
    if (adv.ownerTeam) c.ownerTeam = adv.ownerTeam;
    if (numOrNull(adv.rankMin) != null) c.rankMin = numOrNull(adv.rankMin);
    if (numOrNull(adv.rankMax) != null) c.rankMax = numOrNull(adv.rankMax);
    if (numOrNull(adv.valueMin) != null) c.valueMin = numOrNull(adv.valueMin);
    if (numOrNull(adv.valueMax) != null) c.valueMax = numOrNull(adv.valueMax);
    if (adv.edge) c.edge = adv.edge;
    if (adv.rookieOnly) c.rookieOnly = true;
    if (adv.watchlistOnly) c.watchlist = watchlistLower;
    return c;
  }, [adv, watchlistLower]);
  const advActiveCount = Object.keys(advCriteria).length;

  // ── Filtered + sorted list (unchanged pipeline) ─────────────────
  const ranked = useMemo(() => {
    const q = query.trim();

    // Start with lens-filtered list
    let list = applyLens(eligible, activeLens);

    // Additional filters layer on top of lens
    if (posFilter !== "all") {
      list = list.filter((r) =>
        posMatchesFilter(r.pos, r.assetClass, posFilter, r),
      );
    }
    if (confFilter !== "all") {
      list = list.filter((r) => {
        if (confFilter === "low")
          return r.confidenceBucket === "low" || r.confidenceBucket === "none";
        return r.confidenceBucket === confFilter;
      });
    }
    // Token search (name / NFL team / pos / owner, with owner:/team:/
    // pos: prefixes) + the advanced criteria, one predicate pass.
    if (q || advActiveCount > 0) {
      const criteria = q ? { ...advCriteria, query: q } : advCriteria;
      list = list.filter((r) => rowMatches(r, criteria, { teamByPlayer }));
    }

    // If lens provides its own sort and user hasn't overridden, use it
    const lens = getLens(activeLens);
    if (sortCol === "lens" && lens.sort) {
      return list; // already sorted by applyLens
    }

    // Manual sort
    const sorted = [...list];
    const dir = sortAsc ? 1 : -1;
    sorted.sort((a, b) => {
      let va, vb;
      switch (sortCol) {
        case "rank":
          va = resolvedRank(a);
          vb = resolvedRank(b);
          return (va - vb) * dir;
        case "name":
          return a.name.localeCompare(b.name) * dir;
        case "pos":
          return (
            a.pos.localeCompare(b.pos) * dir ||
            resolvedRank(a) - resolvedRank(b)
          );
        case "score":
          va = a.blendedSourceRank ?? Infinity;
          vb = b.blendedSourceRank ?? Infinity;
          return (va - vb) * dir;
        case "value":
          va = a.rankDerivedValue || a.values?.full || 0;
          vb = b.rankDerivedValue || b.values?.full || 0;
          return (va - vb) * dir;
        case "confidence": {
          const order = { high: 0, medium: 1, low: 2, none: 3 };
          va = order[a.confidenceBucket] ?? 3;
          vb = order[b.confidenceBucket] ?? 3;
          return (va - vb) * dir;
        }
        case "gap": {
          // BDVM fundamental gap. Unpriced/no-market rows sink to the
          // bottom regardless of direction, then keep rank order.
          const ga = bdvmEntryForRow(bdvmIndex, a)?.gap;
          const gb = bdvmEntryForRow(bdvmIndex, b)?.gap;
          if (ga == null && gb == null) return resolvedRank(a) - resolvedRank(b);
          if (ga == null) return 1;
          if (gb == null) return -1;
          return (ga - gb) * dir;
        }
        default: {
          // Dynamic source-column sort: col === `src:${sourceKey}`.
          // Sort by the same 9,999-scale ``valueContribution`` the cell
          // renders, so the column order always matches the displayed
          // numbers.  Fall back to ``canonicalSites`` only for
          // value-based sources on legacy payloads (their raw slot is
          // a monotonic value scale); rank-signal sources never fall
          // back — their raw slot is a synthetic rank encoding whose
          // visible cells are all "—".
          if (typeof sortCol === "string" && sortCol.startsWith("src:")) {
            const key = sortCol.slice(4);
            const src = RANKING_SOURCES.find((s) => s.key === key);
            const aMeta = Number(a.sourceRankMeta?.[key]?.valueContribution);
            const bMeta = Number(b.sourceRankMeta?.[key]?.valueContribution);
            const allowRawFallback = !src?.isRankSignal;
            va = Number.isFinite(aMeta)
              ? aMeta
              : allowRawFallback
                ? Number(a.canonicalSites?.[key]) || 0
                : 0;
            vb = Number.isFinite(bMeta)
              ? bMeta
              : allowRawFallback
                ? Number(b.canonicalSites?.[key]) || 0
                : 0;
            return (va - vb) * dir;
          }
          return resolvedRank(a) - resolvedRank(b);
        }
      }
    });
    return sorted;
  }, [
    eligible,
    activeLens,
    posFilter,
    confFilter,
    query,
    sortCol,
    sortAsc,
    advCriteria,
    advActiveCount,
    teamByPlayer,
    bdvmIndex,
  ]);

  // ── Top movers (from the current filtered view — pre-R2 behavior) ──
  const movers = useMemo(() => {
    const withChange = ranked.filter(
      (r) =>
        typeof r?.rankChange === "number" &&
        r.rankChange !== 0 &&
        r.rank != null,
    );
    const byDelta = [...withChange].sort(
      (a, b) => Math.abs(b.rankChange) - Math.abs(a.rankChange),
    );
    return {
      risers: byDelta.filter((r) => r.rankChange > 0).slice(0, 5),
      fallers: byDelta.filter((r) => r.rankChange < 0).slice(0, 5),
    };
  }, [ranked]);

  // Apply the row limit — to FILTERED results too, which is the change.
  // Memoized: this slice runs on every render of a 1,800-line page, and
  // a fresh array identity per render forced the whole table to
  // reconcile even when nothing changed.
  //
  // A filter used to bypass the cap entirely, so picking "Position:
  // offense" rendered every one of ~500 matches in one commit and a
  // broad search rendered ~1.1k rows. That is the DOM size behind the
  // board's interaction latency: measured at 4x CPU throttle, sorting a
  // column was 384ms and opening a player 488ms, against Google's 200ms
  // "good" bar for INP.
  //
  // #652 rejected capping on the grounds that "516 shown" has to keep
  // meaning all 516. That objection is answered by `hasMore` below
  // rather than by rendering everything: the count line reads "200 of
  // 516 shown", and the remaining rows are one click away — exactly how
  // the UNFILTERED board has always behaved. Nothing claims to show
  // more than it does, and nothing is unreachable.
  const hasActiveFilter = Boolean(
    query ||
      posFilter !== "all" ||
      confFilter !== "all" ||
      activeLens !== "consensus" ||
      advActiveCount > 0,
  );
  const displayRows = useMemo(
    () => ranked.slice(0, rowLimit),
    [ranked, rowLimit],
  );
  // Must NOT exclude the filtered case any more, or a filtered board
  // would cap silently with no way to reach the rest.
  const hasMore = ranked.length > rowLimit;

  // Changing the filter resets the cap. Without this, one "Show all"
  // click would raise `rowLimit` to Infinity for the rest of the
  // session and every subsequent filter would render uncapped again —
  // the cap above would look right and do nothing.
  //
  // Keyed on the plain filters only. `activeLens` is deliberately
  // absent: the lens handler sets `rowLimit` itself (Infinity for the
  // curated non-consensus lenses, DEFAULT for consensus), and including
  // it here would immediately overwrite that.
  //
  // The ref guard keeps this from firing on mount, where it would clash
  // with the `?pos=` / `?screen=` URL seeding that runs in its own
  // effect and legitimately arrives with a filter already set.
  const filterSignature = `${query}|${posFilter}|${confFilter}|${advActiveCount}`;
  const lastFilterSignature = useRef(filterSignature);
  useEffect(() => {
    if (lastFilterSignature.current === filterSignature) return;
    lastFilterSignature.current = filterSignature;
    setRowLimit(DEFAULT_ROW_LIMIT);
  }, [filterSignature]);

  // A filter deliberately bypasses ``rowLimit`` (above), so a broad one
  // renders the FULL ~1.1k-row board — the same synchronous commit that
  // froze the tab on "Show all" before it was made a transition.
  //
  // Deferring the ROWS rather than wrapping the filter setters in
  // ``startTransition`` is the deliberate choice: the search box's own
  // value has to stay urgent or the text lags a frame behind the
  // keystrokes, which is worse than the freeze it fixes.  Filtering
  // 1,076 rows is microseconds; RENDERING a thousand of them at ~36 DOM
  // nodes each is the expensive half, and that is exactly what this
  // defers.  Counts, movers and the lens chips all stay urgent.
  //
  // While the transition is in flight React keeps serving the previous
  // array, so the table briefly shows pre-filter rows.  That must be
  // visible or it reads as "the filter didn't work" — hence
  // ``rowsPending`` and the affordance on the count line.
  const renderedRows = useDeferredValue(displayRows);
  const rowsPending = renderedRows !== displayRows;

  // Per-position ranks (QB3, RB5, LB2…) — computed from the eligible
  // board sorted by rank ASC, independent of the user's sort/filter.
  const positionRankByName = useMemo(() => {
    const counts = new Map();
    const byName = new Map();
    const sorted = [...eligible].sort(
      (a, b) => (a?.rank ?? Infinity) - (b?.rank ?? Infinity),
    );
    for (const row of sorted) {
      const pos = String(row?.pos || "").toUpperCase();
      if (!pos || !row?.name) continue;
      const next = (counts.get(pos) || 0) + 1;
      counts.set(pos, next);
      byName.set(row.name, next);
    }
    return byName;
  }, [eligible]);

  // ── Copy/Export (unchanged columns + format) ────────────────────
  const buildExportLines = useCallback(
    (joiner, escape = (c) => c) => {
      const sourceHeaders = RANKING_SOURCES.flatMap((src) => [
        src.columnLabel,
        `${src.columnLabel} Rank`,
      ]);
      const headers = [
        "Rank",
        "Player",
        "Pos",
        "Team",
        "Tier",
        "Value",
        "Value Band",
        "Confidence",
        "Action",
        "Sources",
        ...sourceHeaders,
      ];
      // Stamp the value basis as a column on every row, not as a
      // preamble line. An export outlives the app: once these numbers
      // are in a spreadsheet, a league-adjusted board and a market
      // board are indistinguishable, and the two answer different
      // questions about the same player. A header line would be lost
      // the first time someone sorts or pastes a subset; a column
      // travels with the row it describes.
      headers.push("Value Basis");
      const basisCell = valuationBasisLabel(rawData);
      const lines = [headers.map(escape).join(joiner)];
      displayRows.forEach((row) => {
        const val = Math.round(row.rankDerivedValue || row.values?.full || 0);
        const band = valueBand(val);
        const action = actionLabel(row);
        const cautions = cautionLabels(row);
        const actionStr = [action?.label, ...cautions.map((c) => c.label)]
          .filter(Boolean)
          .join("; ");
        const sourceCells = RANKING_SOURCES.flatMap((src) =>
          exportSourceCells(row, src),
        );
        lines.push(
          [
            row.rank,
            row.name,
            row.pos,
            row.team || "",
            tierLabel(row),
            val,
            band.label,
            row.confidenceBucket || "",
            actionStr,
            row.sourceCount || 0,
            ...sourceCells,
            basisCell,
          ]
            .map(escape)
            .join(joiner),
        );
      });
      return lines;
    },
    [displayRows, rawData],
  );

  async function copyValues() {
    const lines = buildExportLines("\t");
    try {
      await navigator.clipboard.writeText(lines.join("\n"));
      setCopyStatus(`Copied ${displayRows.length.toLocaleString()} rows`);
      setTimeout(() => setCopyStatus(""), 1800);
    } catch {
      setCopyStatus("Copy failed");
      setTimeout(() => setCopyStatus(""), 1800);
    }
  }

  function exportCsv() {
    const escape = (cell) => {
      const s = cell == null ? "" : String(cell);
      if (/[",\n\r]/.test(s)) {
        return `"${s.replace(/"/g, '""')}"`;
      }
      return s;
    };
    const lines = buildExportLines(",", escape);
    const csv = lines.join("\n");
    const blob = new Blob([csv], { type: "text/csv;charset=utf-8;" });
    const url = URL.createObjectURL(blob);
    const iso = new Date().toISOString().replace(/[:.]/g, "-").slice(0, 19);
    const a = document.createElement("a");
    a.href = url;
    a.download = `chaseupside-rankings-${iso}.csv`;
    document.body.appendChild(a);
    a.click();
    document.body.removeChild(a);
    URL.revokeObjectURL(url);
    setCopyStatus(`Exported ${displayRows.length.toLocaleString()} rows`);
    setTimeout(() => setCopyStatus(""), 1800);
  }

  // ── Freshness timestamp ─────────────────────────────────────────
  const freshness = rawData?.dataFreshness;
  const timestamp = freshness?.generatedAt || rawData?.date || null;
  const relativeUpdated = useMemo(() => {
    if (!timestamp) return null;
    try {
      const then = new Date(timestamp);
      const now = new Date();
      const secs = Math.round((now.getTime() - then.getTime()) / 1000);
      if (!Number.isFinite(secs)) return null;
      if (secs < 60) return `${secs}s ago`;
      if (secs < 3600) return `${Math.round(secs / 60)}m ago`;
      if (secs < 86_400) return `${Math.round(secs / 3600)}h ago`;
      const days = Math.round(secs / 86_400);
      return `${days}d ago`;
    } catch {
      return null;
    }
  }, [timestamp]);

  // ── Tier separator logic ────────────────────────────────────────
  const tierGroupingActive =
    showTiers &&
    sortCol === "rank" &&
    sortAsc &&
    activeLens === "consensus" &&
    !query;
  const currentLens = getLens(activeLens);

  // ── DataTable wiring ────────────────────────────────────────────
  // Sorting stays in the page's memo above (the lens system + dynamic
  // source columns are page semantics); DataTable renders presorted
  // rows and owns only the header state machine + aria-sort stamps.
  const tableSort =
    sortCol === "lens"
      ? null
      : { key: sortCol, direction: sortAsc ? "asc" : "desc" };
  const handleTableSort = useCallback((next) => {
    if (!next) return;
    setSortCol(next.key);
    setSortAsc(next.direction === "asc");
  }, []);

  const columns = useMemo(() => {
    const cols = [
      {
        key: "rank",
        header: "#",
        sortable: true,
        firstDirection: "asc",
        align: "center",
        width: 56,
        render: (row) => (
          <span className={styles.rankCell}>
            {row.rank || "—"}
            {row.rankChange != null && row.rankChange !== 0 && (
              <Movement
                delta={row.rankChange}
                srLabel={`moved ${row.rankChange > 0 ? "up" : "down"} ${Math.abs(row.rankChange)} since the previous scrape`}
              />
            )}
          </span>
        ),
      },
      {
        key: "tier",
        header: "Tier",
        hideBelow: "md",
        width: 90,
        render: (row) => {
          const tierId = effectiveTierId(row);
          return (
            <span
              className={`rankings-tier-badge ${tierId != null ? `tier-${tierId}` : "tier-unknown"}`}
            >
              {tierLabel(row)}
            </span>
          );
        },
      },
      {
        key: "name",
        header: "Player",
        sortable: true,
        render: (row) => {
          const newsItem = lookupPlayerNews(newsByPlayer, row.name, {
            position: row.pos,
            team: row.raw?.team,
            playerMeta: newsPlayerMeta,
          })[0];
          const chips = rowChips(row, { newsItem });
          const onWatch = watchlistLower.has(
            String(row.name || "").toLowerCase(),
          );
          return (
            <div className={styles.playerCell}>
              <PlayerImage
                playerId={row.raw?.playerId}
                team={row.team}
                position={row.pos}
                name={row.name}
                size={28}
              />
              <button
                type="button"
                className={`${styles.resetButton} ${styles.playerName}`}
                onClick={() => openPlayerPopup?.(row)}
                title={`Open ${row.name}'s profile`}
              >
                {row.name}
              </button>
              <button
                type="button"
                className={`${styles.resetButton} ${styles.watchStar}${onWatch ? ` ${styles.watchStarActive}` : ""}`}
                aria-pressed={onWatch}
                aria-label={
                  onWatch
                    ? `Remove ${row.name} from watchlist`
                    : `Add ${row.name} to watchlist`
                }
                title={
                  onWatch
                    ? `Remove from watchlist${watchlistServerBacked ? " (synced)" : ""}`
                    : `Add to watchlist${watchlistServerBacked ? " (synced)" : " (local)"}`
                }
                onClick={() => toggleWatchlist(row.name)}
              >
                <Icon name={onWatch ? "star-filled" : "star"} size={13} />
              </button>
              {(row.team || row.age) && (
                <span className={styles.playerMeta}>
                  {[row.team, row.age].filter(Boolean).join(" · ")}
                </span>
              )}
              <RankChangeGlyph
                history={row.rankHistory}
                change={row.rankChange}
              />
              {chips.length > 0 && (
                <span className={styles.chips}>
                  {chips.map((c) =>
                    c.url ? (
                      <a
                        key={c.label}
                        href={c.url}
                        target="_blank"
                        rel="noopener noreferrer"
                        className={`badge ${c.css} rankings-chip`}
                        title={`${c.title} — click to read`}
                      >
                        {c.label}
                      </a>
                    ) : (
                      <span
                        key={c.label}
                        className={`badge ${c.css} rankings-chip`}
                        title={c.title}
                      >
                        {c.label}
                      </span>
                    ),
                  )}
                </span>
              )}
            </div>
          );
        },
      },
      {
        key: "pos",
        header: "Pos",
        sortable: true,
        width: 64,
        render: (row) => (
          <span className={posBadgeClass(row)}>
            {row.pos}
            {positionRankByName.get(row.name) != null && (
              <span
                className={styles.posRank}
                title={`${row.pos}${positionRankByName.get(row.name)} — position rank within the full ranked board`}
              >
                {positionRankByName.get(row.name)}
              </span>
            )}
          </span>
        ),
      },
      {
        key: "score",
        header: "Consensus",
        sortable: true,
        numeric: true,
        width: 88,
        headerInfo:
          "Consensus: decimal mean of each source's effective rank. Orthogonal to #. When Consensus and # disagree, the blend penalized source disagreement. Lower = better.",
        render: (row) => (
          <span
            className={styles.consensusCell}
            title={
              row.blendedSourceRank != null
                ? `Mean source rank ${row.blendedSourceRank.toFixed(2)}. Final rank is ${row.rank ? `#${row.rank}` : "— (unranked)"}. Gap = blend penalty/bonus for source disagreement.`
                : "No sources ranked this player"
            }
          >
            {row.blendedSourceRank != null
              ? row.blendedSourceRank.toFixed(1)
              : "—"}
          </span>
        ),
      },
      {
        key: "value",
        header: "Value",
        sortable: true,
        numeric: true,
        render: (row) => {
          const val = Math.round(row.rankDerivedValue || row.values?.full || 0);
          const band = valueBand(val);
          return (
            <span className={styles.valueCell}>
              <button
                type="button"
                className={`${styles.resetButton} ${styles.valueButton}`}
                onClick={() => openPlayerPopup?.(row)}
                title={`Hill-curve value ${val.toLocaleString()} (scale 1–9,999) — click for the per-source breakdown`}
              >
                {val.toLocaleString()}
              </button>
              <span
                className={`rankings-value-band ${band.css}`}
                title={band.title || "Value band"}
              >
                {band.label}
              </span>
            </span>
          );
        },
      },
    ];

    if (settings.showSiteCols) {
      for (const src of visibleSources) {
        cols.push({
          key: `src:${src.key}`,
          header: src.columnLabel,
          sortable: true,
          numeric: true,
          hideBelow: "md",
          width: 96,
          headerInfo: `${src.displayName} — cell shows the source's 1–9,999 scale value (${
            src.isRankSignal
              ? "Hill curve from this source's ordinal rank"
              : "linear rescale of this source's native trade value"
          }) with its effective rank on the shared board in parentheses.`,
          render: (row) => {
            const cell = formatSourceCell(row, src);
            return (
              <span className={styles.srcCell} title={cell.title}>
                {cell.hasVal ? (
                  <>
                    {cell.primary}
                    <span className={styles.srcRank}> ({cell.rankLabel})</span>
                  </>
                ) : (
                  <span className={styles.muted}>—</span>
                )}
              </span>
            );
          },
        });
      }
    }

    cols.push(
      {
        key: "sources",
        header: "Sources",
        hideBelow: "md",
        align: "center",
        width: 72,
        headerInfo:
          "Sources that matched this player / sources structurally eligible to cover the player's position.",
        render: (row) => {
          const srcCount =
            row.sourceCount ?? Object.keys(row.sourceRanks || {}).length;
          const eligibleCount =
            RANKING_SOURCES.filter((s) => {
              const pos = (row.pos || "").toUpperCase();
              if (s.scope === "overall_offense")
                return ["QB", "RB", "WR", "TE", "PICK"].includes(pos);
              if (s.scope === "overall_idp")
                return ["DL", "LB", "DB"].includes(pos);
              return false;
            }).length || RANKING_SOURCES.length;
          return (
            <span
              className={
                srcCount >= 2 ? styles.srcCountMulti : styles.srcCountSingle
              }
            >
              {srcCount}/{eligibleCount}
            </span>
          );
        },
      },
      {
        key: "confidence",
        header: "Confidence",
        sortable: true,
        firstDirection: "desc",
        hideBelow: "md",
        align: "center",
        headerInfo:
          "High / Medium / Low confidence based on how many sources matched and how tightly they agree.",
        render: (row) => (
          <span
            className={confidenceBadgeClass(row.confidenceBucket)}
            title={confidenceExplain(row)}
          >
            {confidenceBadgeLabel(row.confidenceBucket)}
          </span>
        ),
      },
      {
        key: "edge",
        header: "Edge",
        hideBelow: "md",
        align: "center",
        width: 120,
        headerInfo:
          "Market edge: retail (KTC) vs expert consensus. Always rendered with an explicit state — never an ambiguous dash.",
        render: (row) => {
          const action_ = marketAction(row);
          return (
            <span className={`edge-label ${action_.css}`} title={action_.title}>
              {action_.label}
            </span>
          );
        },
      },
    );

    // BDVM fundamental gap — present only while the flag-gated endpoint
    // serves an ok payload (see the bdvmIndex memo). Display-only join;
    // ranks and the # column stay backend-stamped.
    if (bdvmIndex) {
      cols.push({
        key: "gap",
        header: "Fund gap",
        numeric: true,
        sortable: true,
        hideBelow: "md",
        width: 110,
        headerInfo:
          "BDVM fundamental value (balanced) minus market anchor — " +
          "positive means the market underprices the player. " +
          "A trailing * marks a proxy-backed fundamental: no real " +
          "projection source covers that player, so the value is last " +
          "season's realized scoring and the gap is not a clean " +
          "fundamental-vs-market read. " +
          "Visible only while the BDVM engine is enabled.",
        render: (row) => {
          const entry = bdvmEntryForRow(bdvmIndex, row);
          if (!entry) return <span className={styles.muted}>—</span>;
          if (entry.gap == null) {
            return (
              <span
                className={styles.muted}
                title={entry.signalReason || "no market anchor for this asset"}
              >
                —
              </span>
            );
          }
          const css = bdvmSignalEdgeCss(entry.signal);
          // Disclose a proxy-backed fundamental (audit finding B-8).  The
          // /bdvm page badges this; this column used to render the gap
          // with no indication that the fundamental side may be last
          // season's realized PPG rather than a projection.
          const proxyNote = entry.anyProxy
            ? " — PROXY: fundamental is the reconstructed baseline (last " +
              "season's realized scoring), not a real projection, so this " +
              "gap partly reflects information the market has and it does not"
            : "";
          const title =
            `${entry.signal}: ${entry.signalReason} — fundamental ` +
            `${formatBdvmValue(entry.fundamental)} vs market ` +
            `${formatBdvmValue(entry.marketValue)}${proxyNote}`;
          const shown = entry.anyProxy
            ? `${formatBdvmGap(entry.gap)}*`
            : formatBdvmGap(entry.gap);
          return css ? (
            <span className={`edge-label ${css}`} title={title}>
              {shown}
            </span>
          ) : (
            <span title={title}>{shown}</span>
          );
        },
      });
    }

    cols.push({
      key: "signal",
      header: "Signal",
      hideBelow: "md",
      width: 170,
      render: (row) => {
        const action = actionLabel(row);
        const cautions = cautionLabels(row);
        return (
          <>
            {action && (
              <span
                className={`action-label ${action.css}`}
                title={action.title}
              >
                {action.label}
              </span>
            )}
            {cautions.map((c) => (
              <span
                key={c.label}
                className={`action-label ${c.css}`}
                title={c.title}
              >
                {c.label}
              </span>
            ))}
            {!action && cautions.length === 0 && (
              <span className={styles.muted}>—</span>
            )}
          </>
        );
      },
    });

    return cols;
  }, [
    settings.showSiteCols,
    visibleSources,
    newsByPlayer,
    newsPlayerMeta,
    watchlistLower,
    watchlistServerBacked,
    positionRankByName,
    openPlayerPopup,
    toggleWatchlist,
    bdvmIndex,
  ]);

  const totalCols = columns.length;

  // ── Render ──────────────────────────────────────────────────────
  return (
    <section className={`${styles.page} psi-editorial`}>
      <PageHeader
        className={styles.hero}
        eyebrow={
          relativeUpdated
            ? `Chase Upside Consensus / Updated ${relativeUpdated}`
            : "Chase Upside Consensus"
        }
        title="Rankings"
        description="The Dynasty Board — unified dynasty rankings, offense + IDP blended by consensus rank."
        actions={
          <>
            {/*
              The "Value basis" Market / My league control was REMOVED on
              2026-08-14. There is one canonical methodology, so there is
              nothing to choose between, and a control that selects a
              methodology is exactly how one player came to have two
              values: the setting lived in localStorage, never synced, and
              the lens overwrote the canonical field — so phone and
              desktop disagreed with nothing on screen saying which was
              which. Its own comment admitted the highlight was "the only
              thing telling the user which board the numbers came from".

              Removed rather than disabled: a greyed-out control implies
              the choice still exists. See
              docs/valuation/LEAGUE_AWARE_METHODOLOGY_REJECTION.md.
            */}
            <CustomMixBadge rankingsOverride={rawData?.rankingsOverride} />
            {copyStatus && (
              <span className={styles.resultCount}>{copyStatus}</span>
            )}
            <Button
              size="sm"
              variant={showEdgeRail ? "secondary" : "ghost"}
              aria-pressed={showEdgeRail}
              onClick={() => setShowEdgeRail((v) => !v)}
            >
              {showEdgeRail ? "Hide edge" : "Show edge"}
            </Button>
            {/* The nine-step prose lives in a modal now; this toggle
                owns only the two charts, which are genuinely
                page-sized and worth a deliberate reveal. */}
            <HelpModal title="How rankings work" label="How rankings work">
              {/* Formula + confidence rule come from the contract, not
                  from a duplicated constant — see MethodologySection. */}
              <MethodologySection methodology={rawData?.methodology} />
            </HelpModal>
            <Button
              size="sm"
              variant={showMethodology ? "secondary" : "ghost"}
              aria-pressed={showMethodology}
              onClick={() => setShowMethodology((v) => !v)}
            >
              {showMethodology ? "Hide charts" : "Methodology charts"}
            </Button>
            <Button
              size="sm"
              variant="secondary"
              onClick={copyValues}
              title="Copy the current rows as TSV for pasting into a spreadsheet"
            >
              Copy
            </Button>
            <Button
              size="sm"
              variant="secondary"
              onClick={exportCsv}
              title="Download the current rows as a CSV file"
            >
              Export CSV
            </Button>
            {/* Sources popover — blend membership (math). Distinct from
                Columns, which only controls column VISIBILITY. */}
            <span className={styles.popoverWrap}>
              <Button
                size="sm"
                variant="secondary"
                aria-expanded={sourcesMenuOpen}
                onClick={() => setSourcesMenuOpen((v) => !v)}
                title="Choose which sources are factored into the blended rankings"
              >
                Sources
                {excludedSourceCount > 0 ? ` (${excludedSourceCount} off)` : ""}
              </Button>
              {sourcesMenuOpen && (
                <div className={styles.popover}>
                  <div className={styles.popoverHeader}>
                    <span>Sources in blend</span>
                    <Button
                      size="sm"
                      variant="ghost"
                      onClick={resetSiteWeights}
                      title="Re-include every source and clear custom weights"
                      disabled={!hasSourceOverrides}
                    >
                      Reset
                    </Button>
                  </div>
                  <p className={styles.popoverHint}>
                    Unchecking a source removes it from the blended average.
                  </p>
                  {RANKING_SOURCES.map((src) => {
                    const included = siteWeights[src.key]?.include !== false;
                    // Never let the user disable the last source — the
                    // blend needs at least one.
                    const isLastIncluded =
                      included && includedSourceKeys.length === 1;
                    return (
                      <label
                        key={src.key}
                        className={`${styles.popoverRow}${isLastIncluded ? ` ${styles.popoverRowDisabled}` : ""}`}
                        title={
                          isLastIncluded
                            ? "At least one source must stay in the blend"
                            : undefined
                        }
                      >
                        <input
                          type="checkbox"
                          checked={included}
                          disabled={isLastIncluded}
                          onChange={(e) =>
                            toggleSourceIncluded(src.key, e.target.checked)
                          }
                        />
                        <span>{src.columnLabel}</span>
                        <span className={styles.popoverRowMeta}>
                          {src.displayName}
                        </span>
                      </label>
                    );
                  })}
                </div>
              )}
            </span>
            {/* Columns popover — per-source column visibility. */}
            <span className={styles.popoverWrap}>
              <Button
                size="sm"
                variant="secondary"
                aria-expanded={colsMenuOpen}
                onClick={() => setColsMenuOpen((v) => !v)}
                title="Show/hide per-source columns"
              >
                Columns
                {!settings.showSiteCols
                  ? " (off)"
                  : hiddenCount > 0
                    ? ` (${hiddenCount} hidden)`
                    : ""}
              </Button>
              {colsMenuOpen && (
                <div className={styles.popover}>
                  <div className={styles.popoverHeader}>
                    <span>Source columns</span>
                    <Button
                      size="sm"
                      variant="ghost"
                      onClick={showAllSiteCols}
                      title="Restore all source columns"
                      disabled={!settings.showSiteCols}
                    >
                      Show all
                    </Button>
                  </div>
                  <label
                    className={`${styles.popoverRow} ${styles.popoverRowMaster}`}
                  >
                    <input
                      type="checkbox"
                      checked={Boolean(settings.showSiteCols)}
                      onChange={(e) =>
                        updateSetting("showSiteCols", e.target.checked)
                      }
                    />
                    <span>Show source columns</span>
                  </label>
                  {RANKING_SOURCES.map((src) => {
                    const hidden = Boolean(hiddenSiteCols[src.key]);
                    const rowDisabled = !settings.showSiteCols;
                    return (
                      <label
                        key={src.key}
                        className={`${styles.popoverRow}${rowDisabled ? ` ${styles.popoverRowDisabled}` : ""}`}
                      >
                        <input
                          type="checkbox"
                          checked={!hidden}
                          onChange={() => toggleSiteCol(src.key)}
                          disabled={rowDisabled}
                        />
                        <span>{src.columnLabel}</span>
                        <span className={styles.popoverRowMeta}>
                          {src.displayName}
                        </span>
                      </label>
                    );
                  })}
                </div>
              )}
            </span>
          </>
        }
      />

      {/* ── Trust strip ── */}
      {!loading && !error && rows.length > 0 && (
        <div className={styles.trustStrip}>
          <StatTile label="Players" value={trustStats.total.toLocaleString()} />
          <StatTile
            label="High conf"
            value={trustStats.high.toLocaleString()}
            meta={<Badge tone="positive">2+ src, tight</Badge>}
          />
          <StatTile label="Medium" value={trustStats.medium.toLocaleString()} />
          <StatTile label="Low" value={trustStats.low.toLocaleString()} />
          <StatTile
            label="Multi-source"
            value={trustStats.multiSource.toLocaleString()}
          />
          <StatTile
            label="Quarantined"
            value={trustStats.quarantined.toLocaleString()}
            meta={
              trustStats.quarantined > 0 ? (
                <Badge tone="negative">check audit</Badge>
              ) : undefined
            }
          />
          {timestamp && (
            <span
              className={styles.trustFootnote}
              title={`Data generated at ${timestamp}`}
            >
              Last scraped {relativeUpdated || timestamp}
            </span>
          )}
        </div>
      )}

      {/* ── Methodology charts (expandable) ── */}
      {showMethodology && (
        <>
          <Panel
            dense
            title={
              <>
                Hill curve
                <InfoTip label="the Hill curve">
                  <p>
                    Percentile → value mapping with the live board overlaid as
                    dots.
                  </p>
                  <p>
                    The curve is the canonical rank-to-value shape; each dot is
                    where a player actually lands after per-source aggregation.
                  </p>
                </InfoTip>
              </>
            }
          >
            <HillCurveExplorer
              rows={rows}
              curves={rawData?.hillCurves}
              onPointClick={openPlayerPopup}
            />
          </Panel>
          <Panel
            dense
            title={
              <>
                Tier gap waterfall
                <InfoTip label="the tier gap waterfall">
                  <p>
                    Top-120 descending value curve with the gap between adjacent
                    rows drawn as bars.
                  </p>
                  <p>
                    Tall bars mark tier cliffs — the natural boundaries the
                    engine detects by rolling-median gap analysis.
                  </p>
                </InfoTip>
              </>
            }
          >
            <TierGapWaterfall rows={rows} topN={120} />
          </Panel>
        </>
      )}

      {/* ── Signal rails ── */}
      {!loading && !error && rows.length > 0 && (
        <TopMoversRail
          risers={movers.risers}
          fallers={movers.fallers}
          onPlayerClick={openPlayerPopup}
        />
      )}
      {!loading && !error && showEdgeRail && rows.length > 0 && (
        <EdgeRail summary={edgeSummary} onPlayerClick={openPlayerPopup} />
      )}

      {/* ── Loading / error / empty states ── */}
      {loading && (
        <Panel flush title="Value board">
          <SkeletonTable rows={12} columns={7} />
        </Panel>
      )}
      {/* One banner, but the RIGHT one.  This used to be
          `tone="negative" title="Rankings unavailable"` for every
          failure, so a backend that was up and declining for a stated
          reason (a scoring-identity mismatch, a contract still loading)
          read exactly like an outage — and a board that was simply
          empty because the pipeline had not finished its first scrape
          read like a fault.  `failure.kind` decides tone, title and
          whether a retry is even offered; a 403 gets no retry button
          because retrying cannot change the answer. */}
      {failure ? (
        <FailureState failure={failure} onRetry={retry} context="rankings" />
      ) : null}
      {!loading && !error && rows.length === 0 && (
        <EmptyState
          title="No player data available"
          description="The backend may still be initializing."
        />
      )}

      {/* ── Board ── */}
      {!loading && !error && rows.length > 0 && (
        <Panel flush>
          <div className={styles.boardControls}>
            {/* Lens tabs */}
            <div className={styles.lensRow}>
              <Tabs
                idPrefix="lens"
                label="Board lenses"
                active={isScreen(activeLens) ? null : activeLens}
                onChange={handleLensChange}
                tabs={LENSES.map((lens) => ({ id: lens.key, label: lens.label }))}
              />
              {/* Screens — the five saved questions that used to be the
                  /finder page.  A dropdown rather than five more tabs:
                  lenses answer "how do I read the whole board", screens
                  answer "show me this specific question", and ten tabs
                  would just be the old clutter in a new place. */}
              <Select
                aria-label="Screen"
                value={isScreen(activeLens) ? activeLens : ""}
                onChange={(e) =>
                  handleLensChange(e.target.value || "consensus")
                }
              >
                <option value="">Screens…</option>
                {SCREENS.map((sc) => (
                  <option key={sc.key} value={sc.key}>
                    {sc.label}
                  </option>
                ))}
              </Select>
            </div>
            {activeLens !== "consensus" && (
              <p className={styles.lensDescription}>
                {currentLens.description}
              </p>
            )}

            {/* Filters — the "rankings-controls" literal class is the
                E2E selector hook (tests/e2e/helpers/journey.js SEL). */}
            <div
              className={`rankings-controls ${styles.controls}`}
              style={{ marginTop: "var(--space-3)" }}
            >
              <span className={styles.controlsSearch}>
                <Input
                  placeholder="Search — name, team, pos, owner: team: pos:"
                  value={query}
                  onChange={(e) => setQuery(e.target.value)}
                  aria-label="Search the board"
                />
              </span>
              <span className={styles.controlsSelect}>
                <Select
                  value={posFilter}
                  onChange={(e) => setPosFilter(e.target.value)}
                  aria-label="Position filter"
                >
                  <option value="all">All</option>
                  <option value="offense">OFF</option>
                  {idpEnabled && <option value="idp">IDP</option>}
                  <option value="pick">Picks</option>
                  <optgroup label="Rookies">
                    <option value="rookie">All Rookies</option>
                    <option value="rookie:QB">R · QB</option>
                    <option value="rookie:RB">R · RB</option>
                    <option value="rookie:WR">R · WR</option>
                    <option value="rookie:TE">R · TE</option>
                  </optgroup>
                  <optgroup label="Position">
                    <option value="QB">QB</option>
                    <option value="RB">RB</option>
                    <option value="WR">WR</option>
                    <option value="TE">TE</option>
                    {idpEnabled && <option value="DL">DL</option>}
                    {idpEnabled && <option value="LB">LB</option>}
                    {idpEnabled && <option value="DB">DB</option>}
                  </optgroup>
                </Select>
              </span>
              <span className={styles.controlsSelect}>
                <Select
                  value={confFilter}
                  onChange={(e) => setConfFilter(e.target.value)}
                  aria-label="Confidence filter"
                >
                  {CONFIDENCE_FILTERS.map((f) => (
                    <option key={f.key} value={f.key}>
                      {f.label}
                    </option>
                  ))}
                </Select>
              </span>
              <Button
                size="sm"
                variant={showTiers ? "secondary" : "ghost"}
                aria-pressed={showTiers}
                onClick={() => setShowTiers((v) => !v)}
                title="Toggle tier grouping"
              >
                Tiers
              </Button>
              <Button
                size="sm"
                variant={advActiveCount > 0 ? "secondary" : "ghost"}
                onClick={() => setAdvOpen((v) => !v)}
                title="Advanced filters: age, experience, NFL team, owner, rank/value range, edge, watchlist"
                aria-expanded={advOpen}
              >
                Filters{advActiveCount > 0 ? ` (${advActiveCount})` : ""}
              </Button>
            </div>

            {/* Advanced filter rail (Phase 3) — every criterion routes
                through lib/player-filters.js rowMatches; owner filtering
                joins league rosters at render time via buildTeamByPlayer
                (rows are scoring-profile-scoped; owners are league-scoped). */}
            {advOpen && (
              <div
                className={styles.advRail}
                style={{ marginTop: "var(--space-2)" }}
              >
                <label className={styles.advField}>
                  Age
                  <Input
                    type="number"
                    min="18"
                    max="45"
                    placeholder="min"
                    value={adv.ageMin ?? ""}
                    onChange={(e) => setAdvField("ageMin", e.target.value)}
                    className={styles.advNum}
                  />
                  –
                  <Input
                    type="number"
                    min="18"
                    max="45"
                    placeholder="max"
                    value={adv.ageMax ?? ""}
                    onChange={(e) => setAdvField("ageMax", e.target.value)}
                    className={styles.advNum}
                  />
                </label>
                <Select
                  value={adv.experience ?? ""}
                  onChange={(e) => setAdvField("experience", e.target.value)}
                  aria-label="Experience"
                >
                  <option value="">Any experience</option>
                  {EXPERIENCE_BUCKETS.map((b) => (
                    <option key={b.key} value={b.key}>
                      {b.label}
                    </option>
                  ))}
                </Select>
                <Select
                  value={adv.nflTeam ?? ""}
                  onChange={(e) => setAdvField("nflTeam", e.target.value)}
                  aria-label="NFL team"
                >
                  <option value="">Any NFL team</option>
                  {nflTeamOptions.map((t) => (
                    <option key={t} value={t}>
                      {t === "FA" ? "Free agent (NFL)" : t}
                    </option>
                  ))}
                </Select>
                {ownerOptions.length > 0 && (
                  <Select
                    value={adv.ownerTeam ?? ""}
                    onChange={(e) => setAdvField("ownerTeam", e.target.value)}
                    aria-label="Fantasy owner"
                  >
                    <option value="">Any owner</option>
                    <option value={FREE_AGENT_OWNER}>Unrostered</option>
                    {ownerOptions.map((t) => (
                      <option key={t} value={t}>
                        {t}
                      </option>
                    ))}
                  </Select>
                )}
                <label className={styles.advField}>
                  Rank
                  <Input
                    type="number"
                    min="1"
                    placeholder="min"
                    value={adv.rankMin ?? ""}
                    onChange={(e) => setAdvField("rankMin", e.target.value)}
                    className={styles.advNum}
                  />
                  –
                  <Input
                    type="number"
                    min="1"
                    placeholder="max"
                    value={adv.rankMax ?? ""}
                    onChange={(e) => setAdvField("rankMax", e.target.value)}
                    className={styles.advNum}
                  />
                </label>
                <label className={styles.advField}>
                  Value
                  <Input
                    type="number"
                    min="0"
                    placeholder="min"
                    value={adv.valueMin ?? ""}
                    onChange={(e) => setAdvField("valueMin", e.target.value)}
                    className={styles.advNum}
                  />
                  –
                  <Input
                    type="number"
                    min="0"
                    placeholder="max"
                    value={adv.valueMax ?? ""}
                    onChange={(e) => setAdvField("valueMax", e.target.value)}
                    className={styles.advNum}
                  />
                </label>
                <Select
                  value={adv.edge ?? ""}
                  onChange={(e) => setAdvField("edge", e.target.value)}
                  aria-label="Market edge direction"
                >
                  <option value="">Any edge</option>
                  <option value="buy">Buy edge</option>
                  <option value="sell">Sell edge</option>
                </Select>
                <label className={styles.advCheck}>
                  <input
                    type="checkbox"
                    checked={!!adv.rookieOnly}
                    onChange={(e) =>
                      setAdvField("rookieOnly", e.target.checked)
                    }
                  />
                  Rookies
                </label>
                <label className={styles.advCheck}>
                  <input
                    type="checkbox"
                    checked={!!adv.watchlistOnly}
                    onChange={(e) =>
                      setAdvField("watchlistOnly", e.target.checked)
                    }
                  />
                  Watchlist
                </label>
                {advActiveCount > 0 && (
                  <Button
                    size="sm"
                    variant="ghost"
                    onClick={clearAdv}
                    title="Clear advanced filters"
                  >
                    Clear
                  </Button>
                )}
              </div>
            )}

            {/* ``aria-live`` so the count is announced when it settles,
                and ``aria-busy`` while the deferred rows catch up — a
                screen-reader user otherwise gets the stale count read
                out as if it were the answer. */}
            <p
              className={styles.resultCount}
              style={{ margin: "var(--space-2) 0 0" }}
              aria-live="polite"
              aria-busy={rowsPending || undefined}
            >
              {renderedRows.length.toLocaleString()}
              {hasMore ? ` of ${ranked.length.toLocaleString()}` : ""} shown
              {activeLens !== "consensus" && ` · ${currentLens.label} lens`}
              {confFilter !== "all" && ` · ${confFilter} confidence`}
              {tierGroupingActive && " · grouped by tier"}
              {rowsPending && " · filtering…"}
            </p>
          </div>

          {/* ── Table ── */}
          <div
            role="tabpanel"
            id={tabPanelId("lens", activeLens)}
            aria-labelledby={tabId("lens", activeLens)}
            // Dim the stale rows while the deferred list catches up.  No
            // transition on the property: a fade would itself cost paint
            // on the very commit this is trying to keep cheap, and the
            // whole point is that the rows below are the OLD ones.
            style={rowsPending ? { opacity: 0.55 } : undefined}
          >
            <DataTable
              caption="Unified dynasty value board: rank, tier, player, position, consensus, value, per-source values, confidence, and market signals"
              columns={columns}
              rows={renderedRows}
              rowKey={(row) => row.name}
              presorted
              // Prerequisite for windowing the rows: under auto layout a
              // column is as wide as its widest CELL, so rendering only a
              // visible slice would make columns jump while scrolling.
              // DataTable measures the widths the browser already settled
              // on and freezes exactly those, so the geometry is
              // unchanged at every breakpoint.  See DataTable.jsx.
              freezeColumnWidths
              // Mount only the rows near the viewport. This is what makes
              // "Show all" usable: the full board is ~1,100 rows at ~32 DOM
              // nodes each, and the cost is TABLE LAYOUT — no containment
              // property reaches table internals, so no CSS avoids it. See
              // components/ds/useRowWindow.js for the ablation table.
              virtualize
              density="compact"
              // DataTable renders emptyState INSTEAD of the table when
              // rows are empty — without one, a filter that matches
              // nothing renders no table at all (not even headers) and
              // the user is left staring at a blank panel.
              emptyState={
                <EmptyState
                  title="No players match these filters"
                  description={
                    advActiveCount > 0 || query
                      ? "Clear the search or advanced filters to widen the board."
                      : "Try a different lens, position, or confidence filter."
                  }
                  action={
                    hasActiveFilter ? (
                      <Button
                        size="sm"
                        variant="secondary"
                        onClick={() => {
                          setQuery("");
                          setPosFilter("all");
                          setConfFilter("all");
                          clearAdv();
                          handleLensChange("consensus");
                        }}
                      >
                        Reset filters
                      </Button>
                    ) : undefined
                  }
                />
              }
              sort={tableSort}
              onSortChange={handleTableSort}
              onRowClick={(row) =>
                setExpandedRow(expandedRow === row.name ? null : row.name)
              }
              rowClassName={(row) =>
                [
                  "rankings-row-clickable",
                  row.quarantined ? styles.quarantinedRow : "",
                  expandedRow === row.name ? styles.expandedRow : "",
                ]
                  .filter(Boolean)
                  .join(" ")
              }
              renderBeforeRow={(row, i) => {
                if (!tierGroupingActive || i === 0) return null;
                const tierId = effectiveTierId(row);
                const prevTierId = effectiveTierId(renderedRows[i - 1]);
                if (tierId === prevTierId || tierId == null) return null;
                return (
                  <tr className={styles.tierSeparator}>
                    <td colSpan={totalCols}>
                      <span className={styles.tierSeparatorLabel}>
                        {tierLabel(row)}
                      </span>
                    </td>
                  </tr>
                );
              }}
              renderAfterRow={(row) => {
                if (expandedRow !== row.name) return null;
                const val = Math.round(
                  row.rankDerivedValue || row.values?.full || 0,
                );
                return (
                  <>
                    <tr className="rankings-mobile-source-row">
                      <td colSpan={totalCols}>
                        <MobileSourceStrip
                          row={row}
                          formatSourceCell={formatSourceCell}
                        />
                      </td>
                    </tr>
                    {/* rankings-audit-row carries the panel's
                        padding:0 + dark inset from globals.css — the
                        expansion reads as an inset drawer, not another
                        table row. */}
                    <tr className="rankings-audit-row">
                      <td colSpan={totalCols}>
                        <SourceAuditPanel
                          row={row}
                          val={val}
                          edge={marketEdge(row)}
                          confExplain={confidenceExplain(row)}
                        />
                      </td>
                    </tr>
                  </>
                );
              }}
            />
          </div>

          {/* ── Show more / show all ── */}
          {hasMore && (
            <div
              className={styles.showMore}
              style={{ paddingBottom: "var(--space-4)" }}
            >
              <Button
                variant="secondary"
                disabled={rowGrowthPending}
                onClick={() => growRows(rowLimit + 200)}
              >
                {rowGrowthPending
                  ? "Adding rows…"
                  : `Show more (${(ranked.length - rowLimit).toLocaleString()} remaining)`}
              </Button>
              <Button
                variant="ghost"
                disabled={rowGrowthPending}
                onClick={() => growRows(Infinity)}
              >
                Show all
              </Button>
            </div>
          )}
        </Panel>
      )}
    </section>
  );
}
