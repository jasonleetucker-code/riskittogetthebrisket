"use client";

import {
  Suspense,
  lazy,
  useCallback,
  useDeferredValue,
  useEffect,
  useMemo,
  useRef,
  useState,
} from "react";
import { useDynastyData } from "@/components/useDynastyData";
import { isFairGap } from "@/lib/fairness-bands";
import {
  ACTIVE_PACKAGE_MODEL_ID,
  PACKAGE_MODELS,
  TRADE_VALUE_MODE,
  STORAGE_KEY,
  meterVerdict,
  colorFromGap,
  verdictBarPosition,
  adjustedSideTotals,
  multiAdjustedSideTotals,
  sideTotal,
  simulationSignature,
  tradeEvaluationState,
  TRADE_EVAL_STATE,
  applyImportedSides,
  defaultDestination,
  findBalancers,
  isTradeableBoardRow,
  parsePickToken,
  reanchorSuppressedPickEntries,
  resolvePickRow,
  searchCalculatorAssets,
  createSide,
  serializeWorkspaceMulti,
  tradeWorkspaceToCSV,
  tradeWorkspaceToJSON,
  deserializeWorkspaceMulti,
  computeSideFlows,
  computeSideFlowAssets,
  SIDE_LABELS,
  MAX_SIDES,
  MIN_SIDES,
  computeStackAdjustments,
  multiTeamNetSummary,
  tradeSignature,
} from "@/lib/trade-logic";
import { valuationBasisLabel } from "@/lib/dynasty-data";
import { useSettings } from "@/components/useSettings";
import { useApp } from "@/components/AppShell";
import {
  buildShareUrl,
  describeShareModelChange,
  describeShareTruncation,
  parseShareParam,
  shareLinkLimits,
} from "@/lib/trade-share";
import {
  resolveTeamSide,
  tradeRequestForTeam,
  warRoomValueSummaryFor,
} from "@/lib/trade-war-room";
import { historyOriginFor, sharePayloadOf } from "@/lib/trade-history-origin";
import {
  PICK_OWNERSHIP_UNAVAILABLE_LABEL,
  describePickOwnershipReason,
  pickOwnershipUnavailableReason,
} from "@/lib/pick-ownership";
import {
  canAddEntry,
  countEntries,
  heldAssetKeysInTrade,
  removeOneEntry,
  teamPickEntries,
  teamPickLabels,
  tradeEntryKey,
  unusedTeamPickEntries,
} from "@/lib/trade-assets";
import { useTradeSimulator } from "@/components/useTradeSimulator";
import { useTeam } from "@/components/useTeam";
import SharedTradeMeter from "@/components/trade/TradeMeter";
import TradeFairnessExplanation from "@/components/trade/TradeFairnessExplanation";
import { TradeVerdictHelp } from "@/components/help/TradeHelp";
import {
  Banner,
  Button,
  CollapsiblePanel,
  Icon,
  Panel,
  PageHeader,
  SkeletonTable,
  ValueBasisNote,
} from "@/components/ds";
import {
  PickTeamSelectors,
  ProactiveSuggestionsRail,
  SuggestionsRailPlaceholder,
  SideCard,
  SUGG_TYPES,
} from "./trade-sections";
import { withValuationMode } from "@/lib/valuation-mode";
import { buildKtcNameIndex, resolveKtcEntries } from "@/lib/ktc-import";
import ResilientSection from "@/components/ResilientSection";
import { draftCapitalBudgetsUnavailableReason } from "@/lib/draft-capital-budgets";
import {
  DecisionSummary,
  ImmediateResultTable,
  MultiTeamSummaryBar,
  SUMMARY_STATE_TEXT,
  TradeIntelTabs,
  TradeSectionNav,
  TradeVerdictAnnouncer,
  useNarrowViewport,
} from "./trade-layout";
import styles from "./trade.module.css";

// ── /trade — the trading terminal ─────────────────────────────────────
//
// Multi-team trade calculator: give/get ledgers per side, a live
// fairness verdict, per-source breakdown, draft-capital stack effects,
// Monte Carlo simulation, and the roster-aware suggestion desk.
//
// R4 decomposed the render into ./trade-sections.jsx; this file keeps
// all state and orchestration.  Every value, gap, adjustment and
// verdict still comes from lib/trade-logic or the /api/trade/*
// responses — no trade math was moved, added, or reimplemented here.

const ROSTER_KEY = "next_trade_roster_v1";
// The balancer answer while the deferred search is catching up (TC-E).
const NO_BALANCERS = Object.freeze({ list: [], teamName: null });
const TEAM_KEY = "next_trade_team_v1";

// TradeMeter + TradeSourceBreakdown live as shared components under
// frontend/components/trade/ so /waivers can reuse the same fairness bar
// and per-source breakdown for its add/drop calculator.
const TradeMeter = SharedTradeMeter;
// The "Second opinions" block — every component below — lives inside a
// `defaultCollapsed` CollapsiblePanel, so none of it is on screen until
// the user asks for it. ~44 KB of charts. Paired with
// `mountCollapsedChildren={false}` on that panel: `hidden` still MOUNTS
// children, so without it these dynamic imports would fetch on page load
// and the split would buy nothing.
//
// React.lazy, not next/dynamic — the same choice and the same measured
// reason as the Perfect Draft panel on /draft (CLAUDE.md): next/dynamic
// pulls Next's loadable runtime (~1.6 KB) into THIS page's chunk, and
// /trade has no headroom for it.  These still mount client-side only,
// when "Second opinions" is opened (the panel starts collapsed and does
// not mount collapsed children, so SSR never reaches them), each inside
// its OWN Suspense boundary with a null fallback — exactly next/dynamic's
// per-component behaviour, so a panel that mounts later (e.g. the
// multi-team flow when a third side is added) never blanks the others.
//
// Each section also gets its OWN error boundary.  Without one, a failed
// chunk load falls through to app/error.jsx and replaces the whole page —
// and the realistic failure is a deploy: deploy.sh swaps `.next` and
// deletes the old build, so a /trade tab opened before it 404s on its old
// chunk hashes the first time it opens one of these.  React.lazy caches the
// rejected import, so a remount would re-throw; `recovery="reload"` offers a
// page reload instead.
// `loadingText` (TC-E): a panel that is the WHOLE content of a drilldown tab
// says it is loading while its chunk arrives, instead of leaving the tab
// blank.  Every other section keeps the null fallback (no layout shift), each
// still inside its own boundary.
const dyn = (loader, name, loadingText = null) => {
  const LazyPanel = lazy(loader);
  if (loadingText) {
    return function OnDemandTabPanel(props) {
      return (
        <ResilientSection name={name} recovery="reload">
          <Suspense
            fallback={
              <p className={styles.intelLead} aria-busy="true" data-testid="trade-panel-loading">
                {loadingText}
              </p>
            }
          >
            <LazyPanel {...props} />
          </Suspense>
        </ResilientSection>
      );
    };
  }
  return function OnDemandSection(props) {
    return (
      <ResilientSection name={name} recovery="reload">
        <Suspense fallback={null}>
          <LazyPanel {...props} />
        </Suspense>
      </ResilientSection>
    );
  };
};
const TradeSourceBreakdown = dyn(
  () => import("@/components/trade/TradeSourceBreakdown"),
  "Per-source breakdown",
);
const RosTradeFitPanel = dyn(
  () => import("@/components/RosTradeFitPanel"),
  "Rest-of-season fit",
  "Loading rest-of-season fit…",
);
const BdvmTradePanel = dyn(() => import("@/components/BdvmTradePanel"), "Fundamentals check");
// TC-B2 / TCM-M01, M02, M04, M05: how each package is built (stacked value
// bars, Quick Trade Facts, concentration) -- the Value tab's first panel.  It
// supersedes the two-bar value split chart, which repeated the meter's totals
// (UX audit §7.1 "removed or merged outright").
const TradePackageBreakdown = dyn(
  () => import("@/components/trade/TradePackageBreakdown"),
  "Package breakdown",
  "Loading the package breakdown…",
);
// TC-D2: the Reasoning tab -- the decision's own coverage record and "what
// would change it", rendered only when that tab is open.
const TradeDecisionReasoning = dyn(
  () => import("@/components/trade/TradeDecisionReasoning"),
  "Decision reasoning",
  "Loading the decision reasoning…",
);
const MultiTradeFlow = dyn(() => import("@/components/graphs/MultiTradeFlow"), "Multi-team flow");
// TC-07 / TC-10: recorded real trades that moved an asset on the calculator.
// Reference evidence only — it never touches the totals or verdict.  Inside
// its own collapsed panel, so the chunk and the request wait for the user.
const RecentRealTrades = dyn(
  () => import("@/components/trade/RecentRealTrades"),
  "Recent real trades",
  "Loading recorded real trades…",
);
// TC-B / TCM-K03: the immediate Second Opinions tally beside the meter.  On
// screen whenever two sides hold assets, but lazy: the opinion machinery is
// its own chunk, requested after first paint, never in the page's first load.
const TradeOpinionTally = dyn(
  () => import("@/components/trade/TradeOpinionTally"),
  "Second opinions tally",
);
// TC-B / TCM-O11, O12, O13: next steps into the existing engines, partner
// evidence and Save to Trade Desk.  Below the fold, so lazy too.
const TradeNextActions = dyn(
  () => import("@/components/trade/TradeNextActions"),
  "Next steps",
);

// TC-D: the Trade War Room — the page's Final Decision — is its own chunk
// (~20 KB, the largest single module the page carried).  It renders nothing
// useful before its first `POST /api/trade/analyze` answers, which waits for a
// 700 ms debounce after two filled sides, so the chunk is prefetched on mount
// (next to the player-pool fetch the whole builder waits on) and is loaded long
// before it has anything to show.
const loadWarRoom = () => import("@/components/trade/TradeWarRoom");
const TradeWarRoom = dyn(loadWarRoom, "Trade War Room");

// On-demand page sections — the same React.lazy + per-section Suspense
// pattern, for code that cannot be on screen at first render:
//
// * SimulationPanel — renders only once "Simulate impact" has answered;
//   its chunk is requested on the click, in parallel with the request.
// * KtcImportPanel — renders only after "Import KTC" is pressed.
// * SuggestionsDesk — the foot of the page, below the builder, the
//   verdict and Second opinions.  Always rendered, so its chunk is
//   requested on mount, in parallel with the player-pool fetch the whole
//   builder waits on; by the time the page body renders it is loaded.
//
// Measured 2026-10-08: together ~18 KB out of the /trade page chunk,
// which sat at 92.8 KB against a 93 KB budget.  Their modules must stay
// out of ./trade-sections — a static import or re-export from there puts
// them straight back into this page's chunk.
const loadSimulationPanel = () => import("./trade-simulation-panel");
const loadKtcImportPanel = () => import("./trade-ktc-import");
// C3-IMPORT-IMAGE: the screenshot-import dialog renders only after the user
// chooses Import trade -> From screenshot.
const loadScreenshotImport = () => import("./trade-screenshot-import");
const loadSuggestionsDesk = () => import("./trade-suggestions-desk");
// TC-D2: the phone builder's bottom sheet -- rendered only after a tap.
const loadAssetSheet = () => import("./trade-asset-sheet");
// A prefetch failure is not handled here: the lazy render below retries
// the import and surfaces any real failure the same way it always would.
const prefetch = (loader) => {
  loader().catch(() => {});
};
const SimulationPanel = dyn(
  () => loadSimulationPanel().then((m) => ({ default: m.SimulationPanel })),
  "Simulation result",
);
const KtcImportPanel = dyn(
  () => loadKtcImportPanel().then((m) => ({ default: m.KtcImportPanel })),
  "KTC import",
);
const SuggestionsDesk = dyn(
  () => loadSuggestionsDesk().then((m) => ({ default: m.SuggestionsDesk })),
  "Trade suggestions",
);
const TradeAssetSheet = dyn(
  () => loadAssetSheet().then((m) => ({ default: m.TradeAssetSheet })),
  "Add to side",
);
const ScreenshotImportDialog = dyn(
  () =>
    loadScreenshotImport().then((m) => ({ default: m.ScreenshotImportDialog })),
  "Screenshot import",
);

export default function TradePage() {
  const { loading, error, rows, rawData } = useDynastyData();
  const { settings } = useSettings();
  const { openPlayerPopup, registerAddToTrade } = useApp();
  // Trade math is canonical, always (TC-A P0-4): the retired "Raw" mode read
  // the legacy scraper composite.  Kept as a name so every call site states
  // the basis it computes on.
  const valueMode = TRADE_VALUE_MODE;

  // Multi-team state: array of { id, label, assets }
  const [sides, setSides] = useState([createSide(0), createSide(1)]);
  // The trade on screen, for request sequencing (TC-E): an async answer
  // compares the trade it was asked about with this before it may land.
  const sidesSignature = useMemo(() => tradeSignature(sides), [sides]);
  const sidesSignatureRef = useRef(sidesSignature);
  useEffect(() => {
    sidesSignatureRef.current = sidesSignature;
  }, [sidesSignature]);
  const ktcImportSeqRef = useRef(0);
  const ktcExportSeqRef = useRef(0);
  const [activeSide, setActiveSide] = useState(0); // index into sides
  // TC-D2: the open Supporting-intelligence drilldown (only it is mounted).
  const [intelTab, setIntelTab] = useState("value");
  // TC-D2: phones build through one bottom sheet per side (null = closed).
  const narrow = useNarrowViewport();
  const [sheetSideIdx, setSheetSideIdx] = useState(null);
  // TC-D2: CSV / JSON / Copy KTC URL live in the toolbar's "More" group.
  const [moreMenuOpen, setMoreMenuOpen] = useState(false);
  // Toolbar disclosures (Import trade, More) return focus to their trigger
  // when they close (Escape or a chosen action), so a keyboard user is never
  // dropped onto <body> when the focused option unmounts (TC-E).
  const moreMenuButtonRef = useRef(null);
  const importMenuButtonRef = useRef(null);
  const closeToolbarGroup = useCallback((setOpen, triggerRef) => {
    setOpen(false);
    requestAnimationFrame(() => triggerRef.current?.focus?.({ preventScroll: true }));
  }, []);
  // TC-D: the War Room's decision, reported up (onDecision) for the sticky
  // desktop echo and the mobile verdict bar.  The War Room owns the request.
  const [decisionSummary, setDecisionSummary] = useState({ status: "idle", decision: null });
  // Per-side inline search: each side renders its own search input, so
  // adding a player is one tap away — no overlay, no "+ Add" button.
  // ``sideQueries[i]`` holds side i's current input string;
  // ``focusedSideIdx`` controls which side's dropdown is visible.
  const [sideQueries, setSideQueries] = useState({});
  const [focusedSideIdx, setFocusedSideIdx] = useState(null);
  const sideInputRefs = useRef({});
  const [hydrated, setHydrated] = useState(false);
  // The suggestions desk is always rendered once the pool loads; fetch its
  // chunk now, alongside the pool, so it never pops in late.
  useEffect(() => {
    prefetch(loadSuggestionsDesk);
    prefetch(loadWarRoom);
  }, []);

  // The phone sheet belongs to the phone layout: it closes if the viewport widens.
  useEffect(() => {
    if (!narrow) setSheetSideIdx(null);
  }, [narrow]);

  // Per-player value overrides for this trade only.
  // Keyed by player name → number (the final effective value to use in trade math).
  // Cleared when the trade is cleared or a player is removed.
  const [valueOverrides, setValueOverrides] = useState({});

  // Suggestions state
  const [rosterInput, setRosterInput] = useState("");
  const [suggestions, setSuggestions] = useState(null);
  const [suggestionsLoading, setSuggestionsLoading] = useState(false);
  const [suggestionsError, setSuggestionsError] = useState(null);
  // True from the moment we KNOW a proactive-suggestions fetch is
  // coming until it resolves.  Distinct from ``suggestionsLoading``,
  // which only flips inside ``fetchSuggestions`` — i.e. AFTER the 500ms
  // debounce below.  The rail's reserved slot has to cover that
  // debounce window too, otherwise the page renders without it and the
  // rail still lands late (the 229px shove this exists to prevent).
  // Defaults TRUE: effects run AFTER the commit, so initialising this
  // false meant the first !loading paint had no reserved slot and the
  // placeholder itself became the shift.  Starting reserved and letting
  // the effect clear it (roster < 3, error, league mismatch) is the
  // only ordering with no un-reserved frame.
  const [suggestionsPending, setSuggestionsPending] = useState(true);
  const [suggestionTab, setSuggestionTab] = useState("sellHigh");

  // Sleeper team selection state
  const [selectedTeamIdx, setSelectedTeamIdx] = useState(-1);
  const [leagueRosters, setLeagueRosters] = useState(null);

  // KTC import panel state — toggles an inline url-paste row above
  // the trade sides.  ``ktcImportStatus`` holds the post-submit
  // summary message (success count + any unresolved ids).
  const [ktcImportOpen, setKtcImportOpen] = useState(false);
  const [ktcImportUrl, setKtcImportUrl] = useState("");
  const [ktcImportBusy, setKtcImportBusy] = useState(false);
  const [ktcImportError, setKtcImportError] = useState("");
  const [ktcImportStatus, setKtcImportStatus] = useState("");
  // "Import trade" control: a disclosure offering the KTC URL row and the
  // screenshot dialog.  The screenshot feature's status is fetched on the
  // FIRST open of the control — never on page load — and "From screenshot"
  // is hidden unless the backend says the feature is enabled.
  const [importMenuOpen, setImportMenuOpen] = useState(false);
  const [screenshotStatus, setScreenshotStatus] = useState(null); // null | "loading" | object
  const [screenshotImportOpen, setScreenshotImportOpen] = useState(false);
  const [screenshotImportNote, setScreenshotImportNote] = useState("");
  const [exportStatus, setExportStatus] = useState("");

  // Share + simulator state.
  // ``{ text, tone }`` or null.  ``tone: "warning"`` whenever a share link
  // lost anything — on load (decoder bounds) or on copy (encoder/decoder
  // bounds) — so a truncated trade never reads as a clean success.
  const [shareStatus, setShareStatus] = useState(null);
  // TC-B2 / TCM-N03: a completed trade opened from Trade History.  The page
  // stays in LIVE mode (no as-of replay exists) and says so until dismissed
  // or the trade is cleared.  ``{ tradedAt }`` or null.
  const [historyOrigin, setHistoryOrigin] = useState(null);
  const [shareHydrated, setShareHydrated] = useState(false);
  // Use Team Context (#842): default ON.  A share link can carry Asset-Only.
  const [useTeamContext, setUseTeamContext] = useState(true);
  const {
    simulate: simulateTrade,
    result: simResult,
    loading: simLoading,
    error: simError,
    reset: resetSim,
    signature: simResultSignature,
  } = useTradeSimulator();
  // useTeam is already league-aware: ``selectedTeam`` resolves
  // against the active league, ``idpEnabled`` comes from the
  // league config, ``leagueMismatch`` flags the data-not-ready
  // state.  We use all three below to render the right picker
  // options, auto-attach the right league to trade suggestions,
  // and show a clear "data not ready" banner when needed.
  const {
    selectedTeam,
    setSelectedTeam,
    idpEnabled,
    leagueMismatch,
    selectedLeagueKey,
    leagueLoading,
    // ``useTeam`` resolves the team AFTER the contract lands, so
    // ``loading`` here outlives ``useDynastyData().loading``.  The
    // suggestions slot needs both: see the effect below.
    loading: teamLoading,
  } = useTeam();

  // Extract Sleeper teams from dynasty data
  const sleeperTeams = useMemo(() => {
    const teams = rawData?.sleeper?.teams;
    return Array.isArray(teams) && teams.length > 0 ? teams : null;
  }, [rawData]);

  const rowByName = useMemo(() => {
    const m = new Map();
    rows.forEach((r) => m.set(r.name, r));
    return m;
  }, [rows]);


  // Lowercased-name → row map for the Sleeper pick resolver; matches
  // the shape ``resolvePickRow`` expects.  Built alongside rowByName
  // so both are available when we need to translate a Sleeper roster
  // string like "2026 1.12 (own)" back into a rankings row.
  const rowByLowerName = useMemo(() => {
    const m = new Map();
    rows.forEach((r) => m.set(r.name.toLowerCase(), r));
    return m;
  }, [rows]);
  const pickAliases = rawData?.pickAliases || null;

  /**
   * Resolve a Sleeper team's roster into a Set of rankings-row NAMES.
   * Players are looked up verbatim (same display-name space); picks
   * route through ``resolvePickRow`` so Sleeper's "2026 1.12 (own)"
   * ends up pointing at the rankings "2026 Pick 1.12" row.  Only
   * assets the rankings actually know about land in the set, which
   * is exactly what the balancer filter needs (unknown names would
   * filter nothing useful).
   */
  const teamRosterNames = useCallback(
    (team) => {
      const names = new Set();
      if (!team) return names;
      for (const p of team.players || []) {
        if (!p) continue;
        if (rowByName.has(p)) names.add(p);
      }
      // Unknown pick ownership (null) contributes no pick names -- and is
      // disclosed by the banner below, never read as "owns no picks".
      for (const pickLabel of teamPickLabels(team) || []) {
        const row = resolvePickRow(pickLabel, rowByLowerName, pickAliases);
        if (row) names.add(row.name);
      }
      return names;
    },
    [rowByName, rowByLowerName, pickAliases],
  );

  /**
   * Figure out which Sleeper team most likely owns a given side's
   * assets pre-trade.  Scores each team by count of matched assets
   * (players + picks, resolved through ``teamRosterNames``); returns
   * the team with the most matches, or null if no team matches any.
   *
   * Used to filter balancer suggestions so "add these to balance"
   * only shows players ALREADY on the team sitting on that side of
   * the trade.  A mixed side (assets spanning multiple rosters)
   * still resolves to the best single-team match, which is usually
   * the right answer in practice — trades happen against one
   * partner, not a pool.
   */
  const inferTeamForSide = useCallback(
    (side) => {
      if (!sleeperTeams || !side?.assets?.length) return null;
      const assetNames = new Set(side.assets.map((a) => a.name));
      let bestTeam = null;
      let bestCount = 0;
      for (const team of sleeperTeams) {
        const roster = teamRosterNames(team);
        let count = 0;
        for (const n of assetNames) {
          if (roster.has(n)) count += 1;
        }
        if (count > bestCount) {
          bestCount = count;
          bestTeam = team;
        }
      }
      return bestCount > 0 ? bestTeam : null;
    },
    [sleeperTeams, teamRosterNames],
  );

  // Every team's picks as trade entries (lib/trade-assets): an owned pick
  // carries the canonical ``assetId`` the backend stamps on
  // ``pickDetails`` so two picks that both read "2027 Mid 1st" stay two
  // separate lines.  Ownership is displayed, not enforced: the calculator
  // may carry any number of copies (owner decision 2026-10-03); only the
  // equalizer reads these as real inventory (``unusedTeamPickEntries``).
  const pickEntriesByTeam = useMemo(() => {
    const m = new Map();
    const resolve = (label) => resolvePickRow(label, rowByLowerName, pickAliases);
    for (const team of sleeperTeams || []) {
      if (team?.name) m.set(team.name, teamPickEntries(team, resolve));
    }
    return m;
  }, [sleeperTeams, rowByLowerName, pickAliases]);

  // assetId → today's ownership label, so an owned pick restored from a
  // share link shows who holds it rather than a bare tier label.
  const ownedPickLabelById = useMemo(() => {
    const m = new Map();
    for (const entries of pickEntriesByTeam.values()) {
      for (const e of entries) if (e.assetId) m.set(e.assetId, e.assetLabel);
    }
    return m;
  }, [pickEntriesByTeam]);

  // ── Draft-capital stack effect (WITHDRAWN from the verdict) ─────────
  // A pick's worth depends on the receiving team's existing draft
  // capital.  We pull the league's draft-capital ($1200) board, value
  // every pick in the trade (tier picks = slot-average — see
  // lib/pick-stack) and recompute zero-sum effective auction power
  // before/after the routed swap.
  //
  // Owner decision 2026-09-29: the result is shown as a labelled,
  // not-calibrated NOTE and is NOT folded into side totals, the verdict,
  // side flows or balancer suggestions.  The #1527 audit measured it
  // dominating whole packages (a side at -963; a 5,487 package to 317)
  // through data seams -- 2027 picks counted twice, synthesized
  // future-pick dollars, picks "sent" by teams that do not hold them --
  // not through the trade.  It returns to the totals only through an
  // owner-approved methodology meeting issue #1529's prerequisites.  Picks
  // still need a resolved team on every side they touch for the note.
  const [draftCapital, setDraftCapital] = useState(null);
  // A failed draft-capital read is stated, never a silently missing note (TC-E).
  const [draftCapitalFailed, setDraftCapitalFailed] = useState(false);
  useEffect(() => {
    // Wait for the league key to resolve: fetching while it is still ""
    // and again once it lands requested /api/draft-capital twice on every
    // load, the first time for the wrong (default) scope (TC-A).
    if (leagueLoading) return undefined;
    let alive = true;
    // Scope to the page's own league so the stack math never mixes a
    // switched active league's teams/picks with another league's
    // draft-capital board (matches how useDynastyData scopes its
    // contract fetch).
    const qs = selectedLeagueKey
      ? `?leagueKey=${encodeURIComponent(selectedLeagueKey)}`
      : "";
    setDraftCapital(null);
    setDraftCapitalFailed(false);
    fetch(`/api/draft-capital${qs}`)
      .then((r) => (r.ok ? r.json() : null))
      .then((d) => {
        if (!alive) return;
        if (d && Array.isArray(d.picks)) setDraftCapital(d);
        else setDraftCapitalFailed(true);
      })
      .catch(() => {
        if (alive) setDraftCapitalFailed(true);
      });
    return () => {
      alive = false;
    };
  }, [selectedLeagueKey, leagueLoading]);

  const boardValueByName = useCallback(
    (name) => Number(rowByName.get(name)?.values?.full) || 0,
    [rowByName],
  );

  // Per-side resolved league team (name).  An AUTO-inferred team must
  // track the side's current assets (so swapping / clearing /
  // importing a different team's package re-infers instead of keeping
  // a stale roster); an explicit user selection is locked and
  // preserved.  Choosing the blank option unlocks → back to auto.
  const [sideTeamNames, setSideTeamNames] = useState([]);
  const [sideTeamLocked, setSideTeamLocked] = useState([]);
  useEffect(() => {
    setSideTeamNames((prev) =>
      sides.map((s, i) =>
        sideTeamLocked[i]
          ? (prev[i] ?? null)
          : (inferTeamForSide(s)?.name ?? null),
      ),
    );
  }, [sides, inferTeamForSide, sideTeamLocked]);

  // Teams in this trade's context whose pick ownership is UNKNOWN (a failed
  // /traded_picks fetch): their owned picks cannot be listed, searched or
  // suggested, and the page says so instead of rendering "no picks" (TC-A;
  // the frontend's one reader is lib/pick-ownership.js).
  const pickOwnershipUnknown = useMemo(() => {
    const relevant = new Set([selectedTeam?.name, ...sideTeamNames].filter(Boolean));
    const out = [];
    for (const team of sleeperTeams || []) {
      if (!relevant.has(team?.name)) continue;
      const reason = pickOwnershipUnavailableReason(team);
      if (reason) out.push({ name: team.name, reason });
    }
    return out;
  }, [sleeperTeams, selectedTeam, sideTeamNames]);

  const tradeHasPicks = useMemo(
    () =>
      sides.some((s) => (s.assets || []).some((a) => a.assetClass === "pick")),
    [sides],
  );
  // Gate: every side a pick is traded FROM *or* TO needs a resolved
  // team — the stack effect needs both the sender's and the
  // receiver's stack, so checking only pick-holding sides would let a
  // missing destination team silently fall back to board value.
  const stackGateUnmet = useMemo(() => {
    if (!tradeHasPicks) return false;
    const n = sides.length;
    const involved = new Set();
    sides.forEach((s, i) => {
      for (const a of s.assets || []) {
        if (a.assetClass !== "pick") continue;
        involved.add(i);
        let to;
        if (n === 2) {
          to = 1 - i;
        } else {
          const dest = s.destinations?.[tradeEntryKey(a)];
          to = Number.isInteger(dest) ? dest : defaultDestination(i, n);
        }
        if (to != null && to >= 0 && to < n) involved.add(to);
      }
    });
    return [...involved].some((i) => sideTeamNames[i] == null);
  }, [sides, sideTeamNames, tradeHasPicks]);

  // Hydrate roster input and team selection from localStorage.
  // The localStorage path is a fallback for bootstrap before
  // ``useTeam`` resolves; the effect below this one keeps the
  // trade-page selection in lockstep with the topbar's
  // ``useTeam().selectedTeam`` so the user has ONE source of truth
  // for "which team's roster drives this page's suggestions."
  useEffect(() => {
    try {
      const saved = localStorage.getItem(ROSTER_KEY);
      if (saved) setRosterInput(saved);
    } catch {
      /* ignore */
    }
    try {
      const savedTeam = localStorage.getItem(TEAM_KEY);
      if (savedTeam !== null) setSelectedTeamIdx(Number(savedTeam));
    } catch {
      /* ignore */
    }
  }, []);

  // Sync trade-page team picker with the topbar's ``useTeam`` state.
  // When the user picks "Karma Cowboy" in the topbar TeamSwitcher,
  // the trade page's local ``selectedTeamIdx`` previously stayed
  // pinned to whatever was in localStorage from a prior session
  // (often -1 / "Use roster from another team").  That meant the
  // proactive "Recommended right now" rail showed suggestions for
  // either the wrong team or no team at all, depending on prior
  // state.  This effect resolves the topbar's selectedTeam against
  // the live ``sleeperTeams`` array (matching by ownerId first, name
  // second) and snaps the local picker — which in turn populates
  // ``rosterInput`` and triggers the suggestions auto-fetch.
  //
  // The resolution itself is a derived value rather than effect-local,
  // because two things need the answer: this effect, which SNAPS the
  // picker, and the suggestions effect, which needs to know whether a
  // roster is still on its way.  ``null`` means "not answerable yet"
  // (no sleeper teams loaded); ``-1`` means "answered: no match".
  // Without that three-way distinction the suggestions effect read the
  // not-yet-synced ``rosterInput``, saw fewer than 3 players, and
  // collapsed the rail slot one commit before the roster arrived.
  const topbarTeamIdx = useMemo(() => {
    if (!sleeperTeams || sleeperTeams.length === 0) return null;
    if (!selectedTeam) return -1;
    // Owner-id is stable; name is fallback for legacy contracts that
    // don't stamp ownerId.
    const ownerId = String(selectedTeam.ownerId || "");
    const name = String(selectedTeam.name || "")
      .trim()
      .toLowerCase();
    let idx = -1;
    if (ownerId) {
      idx = sleeperTeams.findIndex((t) => String(t?.ownerId || "") === ownerId);
    }
    if (idx < 0 && name) {
      idx = sleeperTeams.findIndex(
        (t) =>
          String(t?.name || "")
            .trim()
            .toLowerCase() === name,
      );
    }
    return idx;
  }, [selectedTeam, sleeperTeams]);

  useEffect(() => {
    if (topbarTeamIdx == null || topbarTeamIdx < 0) return;
    if (topbarTeamIdx === selectedTeamIdx) return;
    // ``selectTeam`` writes localStorage + populates rosterInput +
    // builds the leagueRosters opponent map.  That's exactly the
    // state we need for the suggestions fetch to fire with the
    // right roster.
    selectTeam(topbarTeamIdx);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [topbarTeamIdx]);

  // Hydrate trade workspace from localStorage (with migration)
  useEffect(() => {
    if (!rows.length || hydrated) return;
    try {
      const raw = localStorage.getItem(STORAGE_KEY);
      if (raw) {
        const parsed = JSON.parse(raw);
        const restored = deserializeWorkspaceMulti(parsed, rowByName);
        if (restored) {
          setActiveSide(restored.activeSide);
          setSides(restored.sides);
          setValueOverrides({});
        }
      }
    } catch {
      /* ignore */
    } finally {
      setHydrated(true);
    }
  }, [rows, hydrated, rowByName]);

  // Re-anchor suppressed tier-pick aliases ("2027 Mid 1st" once 2027 is the
  // current class) to the slot row the board prices them on.  One pass for
  // every path that turns a name into a row — saved workspace, share link,
  // KTC import, history import — and for a board refresh that rolls the
  // class while the page is open.  ``reanchorSuppressedPickEntries``
  // returns the same array when nothing changed, so this cannot loop.
  useEffect(() => {
    setSides((prev) => reanchorSuppressedPickEntries(prev, rowByLowerName, pickAliases));
  }, [sides, rowByLowerName, pickAliases]);

  // Persist trade workspace to localStorage
  useEffect(() => {
    if (!hydrated) return;
    const payload = serializeWorkspaceMulti(sides, valueMode, activeSide);
    localStorage.setItem(STORAGE_KEY, JSON.stringify(payload));
  }, [hydrated, valueMode, activeSide, sides]);

  // ── Share-URL decoder ──────────────────────────────────────────────
  // When the page loads with ``?share=<base64url>`` in the URL, decode
  // the payload and replace the first N sides with its contents.  We
  // wait for rows to load + localStorage hydration to finish so the
  // decoded trade doesn't flash-then-disappear when the later effect
  // commits the stored workspace.  Running once per page load is
  // enforced via ``shareHydrated`` — the user can still /clear or edit
  // the trade after, and we won't re-override from the URL.
  useEffect(() => {
    if (!hydrated || shareHydrated) return;
    if (!rows.length) return;
    if (typeof window === "undefined") return;
    const state = parseShareParam(window.location.search);
    if (!state || !state.sides?.length) {
      setShareHydrated(true);
      return;
    }
    setHistoryOrigin(historyOriginFor(sharePayloadOf(window.location.search)));
    // Per-asset degrade (TC-B2 / TCM-C04): a name the board cannot resolve is
    // left out AND named, never silently dropped.
    const unresolved = [];
    try {
      const neededSides = Math.max(2, state.sides.length);
      const ensureSides = (prev) => {
        let next = prev;
        while (next.length < neededSides)
          next = [...next, createSide(next.length)];
        return next;
      };
      // Resolved OUTSIDE the state updater (which React may run later, or
      // twice), so the unresolved names are known before the status is set.
      const resolvedDests = state.sides.map(() => []);
      const resolvedBySide = state.sides.map((incoming, i) => {
        if (!incoming) return [];
        const resolved = [];
        const ids = incoming.assetIds || [];
        const dests = incoming.destinations || [];
        (incoming.players || []).forEach((name, j) => {
          // Direct rowByName lookup catches every player and any
          // pick that happens to be in canonical form
          // ("2026 Pick 1.04").
          let row = rowByName.get(name);
          if (!row) {
            // Pick fallback: trade history items round-trip through
            // share URLs using the SLEEPER format ("2026 1.04 (from
            // Team X)" or "2027 Mid 1st (own)"), which doesn't
            // match the canonical rowByName key.  Re-use the same
            // ``resolvePickRow`` walker league-analysis uses so
            // imported trades from /trades correctly hydrate picks.
            if (parsePickToken(name)) {
              row = resolvePickRow(name, rowByLowerName, pickAliases);
            }
          }
          if (!row) {
            if (!unresolved.includes(name)) unresolved.push(name);
            return;
          }
          // An owned pick keeps its canonical id; everything else is
          // the board row.  Repeated names are copies and ALL load, for
          // every kind of asset (owner decision 2026-10-03).
          const assetId = ids[j];
          resolvedDests[i].push(dests[j] ?? null);
          resolved.push(
            assetId
              ? {
                  ...row,
                  assetId,
                  assetLabel: ownedPickLabelById.get(assetId) || row.name,
                }
              : row,
          );
        });
        return resolved;
      });
      setSides((prev) => {
        const base = ensureSides(prev);
        return base.map((side, i) => {
          if (!state.sides[i]) return { ...side, assets: [], destinations: {} };
          const resolved = resolvedBySide[i] || [];
          const nextDestinations = {};
          if (base.length > 2) {
            // The link's own routing when it carries one (TC-A); otherwise
            // the default.  A destination off the trade, or onto the side
            // itself, falls back to the default.
            resolved.forEach((row, j) => {
              const key = tradeEntryKey(row);
              if (nextDestinations[key] != null) return;
              const d = resolvedDests[i]?.[j];
              nextDestinations[key] =
                Number.isInteger(d) && d >= 0 && d < base.length && d !== i
                  ? d
                  : defaultDestination(i, base.length);
            });
          }
          return { ...side, assets: resolved, destinations: nextDestinations };
        });
      });
      setValueOverrides({});
      if (state.teamContext === false) setUseTeamContext(false);
      const modelNote = describeShareModelChange(
        state.packageModel,
        ACTIVE_PACKAGE_MODEL_ID,
        PACKAGE_MODELS,
      );
      const notes = [
        unresolved.length
          ? `Not on today's board, so left out: ${unresolved.join(", ")}.`
          : "",
        modelNote || "",
      ]
        .filter(Boolean)
        .join(" ");
      const lossy = state.truncated || unresolved.length > 0;
      setShareStatus(
        state.truncated
          ? {
              tone: "warning",
              text: `Loaded only part of the shared trade: the link had ${describeShareTruncation(
                state.truncationReasons,
              )}, beyond what a share link may carry.${notes ? ` ${notes}` : ""}`,
            }
          : lossy
            ? { tone: "warning", text: `Loaded part of the shared trade. ${notes}` }
            : modelNote
              ? { tone: "warning", text: `Loaded shared trade from link. ${modelNote}` }
              : { tone: "positive", text: "Loaded shared trade from link." },
      );
    } catch {
      setShareStatus({ tone: "warning", text: "Share link was malformed — ignored." });
    } finally {
      setShareHydrated(true);
    }
  }, [hydrated, shareHydrated, rows, rowByName, ownedPickLabelById]);

  // Apply per-player value overrides to the sides for all value calculations.
  // Only modifies the asset rows that have an override; everything else passes through.
  const sidesWithOverrides = useMemo(() => {
    if (!Object.keys(valueOverrides).length) return sides;
    return sides.map((s) => ({
      ...s,
      // Keyed by side-line identity (lib/trade-assets): one override per
      // line, applied to every copy of a repeated generic pick, and never
      // leaking between two owned picks that share a label.
      assets: s.assets.map((r) => {
        const ov = valueOverrides[tradeEntryKey(r)];
        if (ov == null) return r;
        return { ...r, customValue: ov };
      }),
    }));
  }, [sides, valueOverrides]);

  // STACK-NOTE-ONLY:BEGIN -- the informational stack model.  Nothing in
  // this region may feed a total, the verdict, flows or balancers
  // (owner directive 2026-09-29; __tests__/trade-stack-withdrawn.test.js).
  // League stacks + routed pick-$ moves for the effective-power lens.
  // null whenever the lens can't / shouldn't apply (no draft data, no
  // picks, or the team gate is unmet) → no note is shown.  The verdict
  // never reads this in any case.
  // The stack model is loaded ON DEMAND -- only once a pick trade meets a
  // loaded draft-capital board -- so this informational note costs the
  // /trade first load nothing (Wave A grew the model past the page budget).
  const [stackLib, setStackLib] = useState(null);
  // A failed chunk load is a stated "unavailable", never a silently missing note.
  const [stackLibFailed, setStackLibFailed] = useState(false);
  const stackLibWanted = Boolean(draftCapital && tradeHasPicks);
  useEffect(() => {
    if (!stackLibWanted || stackLib || stackLibFailed) return undefined;
    let alive = true;
    import("@/lib/pick-stack")
      .then((m) => {
        if (alive) setStackLib(m);
      })
      .catch((err) => {
        console.warn("[trade] draft-capital note model failed to load", err);
        if (alive) setStackLibFailed(true);
      });
    return () => {
      alive = false;
    };
  }, [stackLibWanted, stackLib, stackLibFailed]);
  // The league's auction budgets (draft-capital ``teamTotals``) can be
  // UNAVAILABLE; the stack note then stays off and says why — never stacks
  // built from $0 budgets (MISSING IS NEVER ZERO).
  const stackBudgetsUnavailable = useMemo(
    () => draftCapitalBudgetsUnavailableReason(draftCapital),
    [draftCapital],
  );
  const stackContext = useMemo(() => {
    if (
      !stackLib ||
      !draftCapital ||
      !sleeperTeams ||
      !tradeHasPicks ||
      stackGateUnmet ||
      stackBudgetsUnavailable
    ) {
      return null;
    }
    const {
      buildLeagueStacks,
      buildSlotDollarGrid,
      ownedPickStackInventory,
      pickAuctionDollars,
      pickOwnerKeyByAssetId,
      pickStackAnchorYear,
      poolBoardPerDollar,
      stackPickMoves,
      teamStackKey,
    } = stackLib;
    // Year-keyed slot-$ grid (handles the Sleeper-derived payload's two
    // seasons with colliding round/slot pairs — see buildSlotDollarGrid).
    const slotGrid = buildSlotDollarGrid(draftCapital);
    const teamsPerRound = Number(draftCapital.numTeams) || 12;
    const ctx = {
      slotGrid,
      teamsPerRound,
      // THIS LEAGUE's upcoming draft -- the league-scoped ``upcomingDraftYear``
      // on the draft-capital payload (Wave A) -- never the board's year.
      currentDraftYear: pickStackAnchorYear(rawData, draftCapital),
      boardValueByName,
    };
    // Every real pick the draft-capital totals do not already count, per
    // STABLE team key, each exactly once (Wave A): a season in
    // ``coveredPickYears`` or an assetId already on a draft-capital row is in
    // teamTotals; a duplicate assetId is not counted twice.  Name-keyed joins
    // split a team in two (Sleeper team name vs owner first name), and a
    // missing ``coveredPickYears`` used to re-add the upcoming class.
    const inventory = ownedPickStackInventory(sleeperTeams, draftCapital, (label) =>
      resolvePickRow(label, rowByLowerName, pickAliases),
    );
    const leagueStacks = buildLeagueStacks(draftCapital, inventory.byTeam, ctx);

    // Side -> stable team key, and assetId -> the team that actually holds it.
    const keyByName = new Map(sleeperTeams.map((t) => [t?.name, teamStackKey(t)]));
    const sideTeamKeys = sideTeamNames.map((nm) => (nm == null ? null : (keyByName.get(nm) ?? null)));
    const n = sidesWithOverrides.length;
    // Team-attributed: only an owned pick (assetId) its sending team holds
    // moves a stack; a generic pick never debits real inventory, and a pick
    // the side's team does not hold is reported, not moved.
    const { moves, notOwned } = stackPickMoves(sidesWithOverrides, {
      sideTeamKeys,
      ownerKeyByAssetId: pickOwnerKeyByAssetId(sleeperTeams),
      destinationOf: (i, a) => {
        if (n === 2) return 1 - i;
        const dest = sidesWithOverrides[i].destinations?.[tradeEntryKey(a)];
        const to = Number.isInteger(dest) ? dest : defaultDestination(i, n);
        return to == null || to < 0 || to >= n ? null : to;
      },
      dollarsOf: (a) => pickAuctionDollars(a.name, ctx),
    });
    if (moves.length === 0) return notOwned.length ? { notOwned } : null;
    const boardPerDollar = poolBoardPerDollar(draftCapital, boardValueByName, teamsPerRound);
    return { sideTeams: sideTeamKeys, leagueStacks, moves, boardPerDollar, notOwned };
  }, [
    stackLib,
    rawData,
    draftCapital,
    sleeperTeams,
    tradeHasPicks,
    stackGateUnmet,
    stackBudgetsUnavailable,
    boardValueByName,
    rowByLowerName,
    pickAliases,
    sidesWithOverrides,
    sideTeamNames,
  ]);

  // The withdrawn stack effect, per side, for the labelled note only.
  const stackNote = useMemo(
    () =>
      stackContext?.moves ? computeStackAdjustments(sidesWithOverrides.length, stackContext) : null,
    [stackContext, sidesWithOverrides.length],
  );
  // Owned picks a side's team does not hold: named, never moved (Wave A).
  const stackNotOwned = stackContext?.notOwned?.length ? stackContext.notOwned : null;
  // STACK-NOTE-ONLY:END

  // ── Computed totals for all sides ────────────────────────────────────
  // Both 2-team and N-team trades use the ACTIVE package Value Adjustment
  // (packageAdjustPair — the geometric model, q = 0.78, since 2026-10-17).
  // For N ≥ 3, each side's VA is computed against the merged opposition
  // (every other side's assets flattened) — see
  // ``computeMultiSideAdjustments`` in trade-logic.js.  The draft-capital
  // stack effect is deliberately NOT passed (withdrawn from the verdict,
  // see above): every total here is raw + Value Adjustment.
  const sideTotals = useMemo(() => {
    if (sidesWithOverrides.length === 2) {
      const [a, b] = adjustedSideTotals(
        sidesWithOverrides[0].assets,
        sidesWithOverrides[1].assets,
        valueMode,
        settings,
      );
      return [a, b];
    }
    if (sidesWithOverrides.length > 2) {
      return multiAdjustedSideTotals(
        sidesWithOverrides.map((s) => s.assets),
        valueMode,
        settings,
      );
    }
    return sidesWithOverrides.map((s) => {
      const raw = sideTotal(s.assets, valueMode, settings);
      return { raw, adjustment: 0, adjusted: raw };
    });
  }, [sidesWithOverrides, valueMode, settings]);

  // Per-side flow totals: given / received / net.  In 2-team trades
  // the destinations map is ignored (assets implicitly go to the other
  // side).  In 3+-team trades each asset's destination drives the NET
  // flow, which is what the multi-team fairness bar renders.
  const sideFlows = useMemo(
    () => computeSideFlows(sidesWithOverrides, valueMode, settings),
    [sidesWithOverrides, valueMode, settings],
  );

  // Per-side incoming / outgoing asset lists.  This is the
  // "who's getting what" view — for each side we know exactly which
  // assets (and from whom) are arriving.  Rendered as a "Receiving"
  // section in 3+-team mode so the user doesn't have to mentally
  // reverse-lookup destinations across three separate side cards.
  const sideFlowAssets = useMemo(() => computeSideFlowAssets(sides), [sides]);

  // Which side is the user's own roster?  Derived by counting how
  // many of each side's current assets match the user's selected
  // Sleeper team.  Falls back to ``-1`` when there's no team
  // selected, no matches on either side, or the data isn't ready.
  // Used to label the matching side card with a "Your team" pill so
  // the user always knows which side is "I'm giving" vs. "I'm
  // receiving" — fixes the audit's U-2-style "team affordance
  // disappears once the tray scrolls" finding.
  // The user's explicit "I'm Side A / B" answer, for trades whose roster
  // evidence does not decide it (TC-A / UX audit P0-5).  null = not chosen.
  const [explicitMySide, setExplicitMySide] = useState(null);
  useEffect(() => {
    setExplicitMySide(null);
  }, [selectedTeam?.name, selectedLeagueKey]);
  // ONE answer to "which side is the selected team's" for 2-side trades —
  // the War Room, Simulate impact and the "You" badge all read it.
  const teamSide = useMemo(
    () =>
      selectedTeam && sides.length === 2
        ? resolveTeamSide(sides, teamRosterNames(selectedTeam), explicitMySide)
        : { side: null, basis: "ambiguous" },
    [sides, selectedTeam, teamRosterNames, explicitMySide],
  );
  const mySideIdx = useMemo(() => {
    if (!selectedTeam) return -1;
    if (sides.length === 2) return teamSide.side ?? -1;
    const myRoster = teamRosterNames(selectedTeam);
    if (!myRoster.size) return -1;
    let bestIdx = -1;
    let bestHits = 0;
    sides.forEach((s, i) => {
      let hits = 0;
      for (const a of s.assets || []) {
        if (myRoster.has(a.name)) hits += 1;
      }
      if (hits > bestHits) {
        bestHits = hits;
        bestIdx = i;
      }
    });
    return bestHits > 0 ? bestIdx : -1;
  }, [sides, selectedTeam, teamRosterNames, teamSide]);

  // Can the headline speak at all?  Empty → no verdict anywhere (P0-6).
  const evalState = useMemo(() => tradeEvaluationState(sidesWithOverrides), [sidesWithOverrides]);
  const tradeIsEmpty = evalState.state === TRADE_EVAL_STATE.EMPTY;
  // An unpriced asset adds 0 to its side as an arithmetic neutral; no band,
  // gap verdict or balancer is computed over that 0 (MISSING IS NEVER ZERO).
  const tradeIsIncomplete = evalState.state === TRADE_EVAL_STATE.INCOMPLETE;

  // Legacy 2-team gap computations (for sticky tray + 2-team balancers)
  const pwTotalA = sideTotals[0]?.adjusted || 0;
  const pwTotalB = sideTotals[1]?.adjusted || 0;
  const linTotalA = sideTotals[0]?.raw || 0;
  const linTotalB = sideTotals[1]?.raw || 0;
  const pwGap = pwTotalA - pwTotalB;
  const pctGap =
    Math.max(pwTotalA, pwTotalB) > 0
      ? Math.round((Math.abs(pwGap) / Math.max(pwTotalA, pwTotalB)) * 100)
      : 0;
  // The base the ONE fairness-band owner is relative to (TC-C, owner
  // decision 3): the larger adjusted side.  Every 2-team band on this page
  // (tray, balancers, the "add to balance" side) reads it.
  const pwLarger = Math.max(pwTotalA, pwTotalB);
  const pwGapIsFair = isFairGap(pwGap, pwLarger);
  // 3+-team: the multi-team meter's own reading (one helper, shared with the
  // persistent summary bar) -- its base is the largest adjusted package any
  // side sends (tradeImbalance's base).
  const multiSummary = useMemo(() => multiTeamNetSummary(sideFlows), [sideFlows]);
  const multiLarger = multiSummary.largerSide;

  // Balancing suggestions (2-team mode only).
  //
  // Filter the candidate pool to the roster of whichever Sleeper team
  // owns the assets ALREADY on the behind side.  If the trade is
  // between Jason and team X, and Jason is behind, the suggestions
  // should come from Jason's roster — he's the one who'd add more
  // to his side.  Falls back to the full ranked pool when no team
  // match is found (manual-entry workflows, mixed assets, no Sleeper
  // data).  Also emits the inferred team name so the UI can label
  // "Add from [team]:" instead of a generic "consider adding".
  // Equalizer candidate pool for one side.  This is a ROSTER-AWARE
  // RECOMMENDATION, so it uses real ownership (``heldAssetKeysInTrade`` /
  // ``unusedTeamPickEntries``): a player or owned pick already in the
  // trade is not suggested again, a team's SECOND "2027 Mid 1st" stays a
  // candidate after its first is in, and a copy the team does not hold is
  // never offered — the equalizer must not claim a team owns four
  // Jeffersons.  Manual construction is NOT gated by this (owner decision
  // 2026-10-03: calculator quantities are unlimited).  Without a team,
  // board pick rows are market references and stay eligible.
  const balancerPool = useCallback(
    (sideIdx, team) => {
      const inTradeUnique = heldAssetKeysInTrade(sides);
      const excluded = (r) => !isTradeableBoardRow(r);
      if (team) {
        const roster = teamRosterNames(team);
        const players = rows.filter(
          (r) =>
            r.assetClass !== "pick" &&
            roster.has(r.name) &&
            !inTradeUnique.has(tradeEntryKey(r)) &&
            !excluded(r),
        );
        const picks = unusedTeamPickEntries(
          pickEntriesByTeam.get(team.name) || [],
          sides,
          sideIdx,
        ).filter((e) => !excluded(e));
        const pool = [...players, ...picks];
        if (pool.length) return { pool, teamName: team.name || null };
      }
      // Fallback when no team can be inferred (or the inferred team has
      // nothing left).  Preserves existing behaviour when Sleeper data is
      // unavailable.
      return {
        pool: rows.filter((r) => !inTradeUnique.has(tradeEntryKey(r)) && !excluded(r)),
        teamName: null,
      };
    },
    [sides, rows, teamRosterNames, pickEntriesByTeam],
  );

  // TC-E — immediate math vs expensive analysis.  The meter, the tray and the
  // sticky result are synchronous local math; the balancer search is not: it
  // re-simulates the whole trade once per candidate (and once per pair), which
  // measured 33 ms per run over a 120-asset roster pool and 76 ms over the
  // full board (Node, warm; several times that on a phone).  It used to run in
  // the SAME render as the verdict, so every edit paid for it before the new
  // band could paint.  It now reads a deferred snapshot (useDeferredValue, the
  // Perfect Draft pattern): the verdict commits first and the search follows
  // at low priority.  Suggestions are shown only while the snapshot is the
  // trade on screen -- a stale suggestion for the previous trade is never
  // rendered under the new one (request-sequencing rule, applied to a
  // deferred computation).
  const balancerInput = useMemo(
    () => ({
      sides,
      sidesWithOverrides,
      sideFlows,
      pwGap,
      pwGapIsFair,
      tradeIsIncomplete,
      multiLarger,
      inferTeamForSide,
      balancerPool,
    }),
    [
      sides,
      sidesWithOverrides,
      sideFlows,
      pwGap,
      pwGapIsFair,
      tradeIsIncomplete,
      multiLarger,
      inferTeamForSide,
      balancerPool,
    ],
  );
  const deferredBalancerInput = useDeferredValue(balancerInput);
  const balancersCurrent = deferredBalancerInput === balancerInput;

  const deferredBalancers = useMemo(() => {
    const b = deferredBalancerInput;
    if (b.sides.length !== 2) return { list: [], teamName: null };
    if (b.tradeIsIncomplete) return { list: [], teamName: null };
    if (b.pwGapIsFair) return { list: [], teamName: null };
    // Behind side = the one whose total is LOWER.
    const behindSideIdx = b.pwGap > 0 ? 1 : 0;
    const behindSide = b.sides[behindSideIdx];
    const behindTeam = b.inferTeamForSide(behindSide);
    const { pool, teamName } = b.balancerPool(behindSideIdx, behindTeam);
    // The gap is NOT passed in.  ``findBalancers`` takes the trade and
    // measures the post-add gap through the same path the meter renders,
    // so a raw value can never be matched against an adjusted target
    // (defect #800).
    // combos: when no single asset lands inside the fair band, a pair from
    // the same roster is tried too (TC-B / TCM-F03), simulated whole.
    const list = findBalancers(b.sidesWithOverrides, behindSideIdx, pool, valueMode, {
      settings,
      combos: true,
    });
    return { list, teamName };
  }, [deferredBalancerInput, settings, valueMode]);

  // For 3+ teams, find balancers for the team getting the best deal
  // (they should add more to their give to even things out).  Uses
  // the destination-aware NET flow (received − given) so the target
  // is whoever profited most after each asset was routed to its
  // chosen destination.  Falling back to the raw total index would
  // pick whoever put the fewest pieces on the table — a different
  // question entirely.
  const deferredMultiBalancers = useMemo(() => {
    const b = deferredBalancerInput;
    if (b.sides.length <= 2) return null;
    if (b.tradeIsIncomplete) return null;
    const nets = b.sideFlows.map((f) => f.net);
    const worstIdx = nets.indexOf(Math.min(...nets)); // most negative = overpaying
    const bestIdx = nets.indexOf(Math.max(...nets)); // most positive = getting a deal
    const gap = nets[bestIdx] - nets[worstIdx];
    if (isFairGap(gap, b.multiLarger)) return null;
    // Panel renders on the side that needs to GIVE more (the one with
    // the best deal right now).  Filter the suggestion pool to that
    // side's Sleeper team so the "add more" list is players they
    // actually own.  Same fallback to full pool when inference fails.
    const underpayingSide = b.sides[bestIdx];
    const underpayingTeam = b.inferTeamForSide(underpayingSide);
    const { pool, teamName } = b.balancerPool(bestIdx, underpayingTeam);
    const suggestions = findBalancers(b.sidesWithOverrides, bestIdx, pool, valueMode, {
      settings,
      toSideIdx: worstIdx,
      combos: true,
    });
    return {
      overpayingIdx: worstIdx,
      underpayingIdx: bestIdx, // panel rendered on the side that needs to give more
      gap,
      suggestions,
      teamName,
    };
  }, [deferredBalancerInput, settings, valueMode]);

  const balancersPending = !balancersCurrent;
  const balancers = balancersCurrent ? deferredBalancers : NO_BALANCERS;
  const multiBalancers = balancersCurrent ? deferredMultiBalancers : null;
  // "Is the 3+-team trade fair?" is immediate math (the same rule the deferred
  // search starts from), so it never waits for the suggestions.
  const multiGapIsFair = useMemo(() => {
    if (sides.length <= 2 || tradeIsIncomplete) return true;
    const nets = sideFlows.map((f) => f.net);
    return isFairGap(Math.max(...nets) - Math.min(...nets), multiLarger);
  }, [sides.length, tradeIsIncomplete, sideFlows, multiLarger]);

  // Inline search helper.  Nothing already in the trade is hidden: every
  // asset is repeatable in the calculator (owner decision 2026-10-03), so
  // a search result is still offered after its first add.  Market
  // references come FIRST and owned picks second, each group with its own
  // limit (``searchCalculatorAssets``), so a team's own picks can never
  // crowd the Early/Mid/Late references out of the visible rows; the
  // dropdown renders the two groups with headings
  // (``groupTradeSearchResults``).  Ownership is DISPLAYED, never a limit —
  // an owned pick already in the trade stays addable.
  const searchAssets = useCallback(
    (query, sideIdx = null) => {
      // The eligibility rule lives in ``lib/trade-logic`` so the call
      // sites on this page cannot drift apart again.  What it excludes is
      // the suppressed generic-tier pick ALIASES (rows the backend cleared
      // because a slot-specific sibling exists), not a hardcoded year: the
      // old ``/^2026/`` also removed the 72 slot rows the current-year
      // board is priced on, so searching "2026" returned nothing at all
      // (W08-F004).
      const team = Number.isInteger(sideIdx) ? sideTeamNames[sideIdx] : null;
      const owned = team ? pickEntriesByTeam.get(team) || [] : [];
      return searchCalculatorAssets(rows, query, owned);
    },
    [rows, sideTeamNames, pickEntriesByTeam],
  );

  // ── Side management ─────────────────────────────────────────────────
  function addToSide(row, sideIdx) {
    if (!row) return;
    // Every asset is repeatable (lib/trade-assets, owner decision
    // 2026-10-03): a second tap adds a second copy, on either side.
    // ``canAddEntry`` only rejects an invalid row.
    setSides((prev) => {
      if (!canAddEntry(prev, row)) return prev;
      return prev.map((s, i) => {
        if (i !== sideIdx) return s;
        // 3+-team trades need an explicit destination per asset so the
        // fairness bar can compute each side's NET flow.  Seed the
        // default (next side, circular) whenever we're adding to a
        // multi-side trade.  2-team trades leave destinations empty —
        // ``computeSideFlows`` handles the implicit "other side" case.
        const nextDestinations = { ...(s.destinations || {}) };
        const key = tradeEntryKey(row);
        // A further copy of a repeated line keeps that line's routing.
        if (prev.length > 2 && nextDestinations[key] == null) {
          nextDestinations[key] = defaultDestination(i, prev.length);
        }
        return {
          ...s,
          assets: [...s.assets, row],
          destinations: nextDestinations,
        };
      });
    });
  }

  function setAssetDestination(sideIdx, entryKey, destIdx) {
    setSides((prev) =>
      prev.map((s, i) => {
        if (i !== sideIdx) return s;
        const next = { ...(s.destinations || {}) };
        next[entryKey] = Number(destIdx);
        return { ...s, destinations: next };
      }),
    );
  }

  function addToActiveSide(row) {
    addToSide(row, activeSide);
  }

  // Inline-search add: drop the row onto the side, clear that side's
  // query so the dropdown collapses, and re-focus the input so the
  // soft keyboard stays up for the next addition.
  function addFromSearch(row, sideIdx) {
    addToSide(row, sideIdx);
    setSideQueries((prev) => ({ ...prev, [sideIdx]: "" }));
    requestAnimationFrame(() => {
      sideInputRefs.current[sideIdx]?.focus({ preventScroll: true });
    });
  }

  // Register add-to-trade callback so popup/search can add players
  useEffect(() => {
    registerAddToTrade?.(addToActiveSide);
    return () => registerAddToTrade?.(null);
  }, [registerAddToTrade, activeSide]); // eslint-disable-line react-hooks/exhaustive-deps

  function setValueOverride(name, rawInput) {
    const num = parseFloat(String(rawInput).replace(/,/g, ""));
    setValueOverrides((prev) => {
      if (!Number.isFinite(num) || num <= 0) {
        if (!(name in prev)) return prev;
        const next = { ...prev };
        delete next[name];
        return next;
      }
      return { ...prev, [name]: num };
    });
  }

  function clearValueOverride(name) {
    setValueOverrides((prev) => {
      if (!(name in prev)) return prev;
      const next = { ...prev };
      delete next[name];
      return next;
    });
  }

  // Removes ONE copy of the line ``entryKey`` (lib/trade-assets): with
  // two copies of any asset on a side, one remains.  The line's routing
  // and value override go only when its last copy does.
  function removeFromSide(entryKey, sideIdx) {
    setSides((prev) =>
      prev.map((s, i) => {
        if (i !== sideIdx) return s;
        const assets = removeOneEntry(s.assets, entryKey);
        const nextDestinations = { ...(s.destinations || {}) };
        if (countEntries(assets, entryKey) === 0) delete nextDestinations[entryKey];
        return { ...s, assets, destinations: nextDestinations };
      }),
    );
    if (countEntries(sides, entryKey) <= 1) clearValueOverride(entryKey);
  }

  function clearTrade() {
    setSides((prev) =>
      prev.map((s) => ({ ...s, assets: [], destinations: {} })),
    );
    setValueOverrides({});
    setExplicitMySide(null);
    setHistoryOrigin(null);
  }

  function swapSides() {
    if (sides.length === 2) {
      // The user's side moves with its assets.
      setExplicitMySide((s) => (s === 0 ? 1 : s === 1 ? 0 : null));
      setSides((prev) => [
        { ...prev[1], id: 0, label: "A" },
        { ...prev[0], id: 1, label: "B" },
      ]);
      setActiveSide((s) => (s === 0 ? 1 : 0));
    } else {
      // Rotate: side i takes the previous side's assets.  Each asset
      // moves one slot forward, so its destination also rotates one
      // slot forward to preserve the user's chosen routing.
      setSides((prev) => {
        const n = prev.length;
        return prev.map((s, i) => {
          const srcIdx = (i + n - 1) % n;
          const src = prev[srcIdx];
          const nextDestinations = {};
          for (const [name, dest] of Object.entries(src.destinations || {})) {
            const parsed = Number(dest);
            if (!Number.isInteger(parsed)) continue;
            const rotated = (parsed + 1) % n;
            // Drop self-references that could sneak in post-rotation;
            // ``defaultDestination`` will take over in ``computeSideFlows``.
            if (rotated !== i) nextDestinations[name] = rotated;
          }
          return {
            id: i,
            label: SIDE_LABELS[i],
            assets: src.assets,
            destinations: nextDestinations,
          };
        });
      });
    }
  }

  function addTeam() {
    if (sides.length >= MAX_SIDES) return;
    setSides((prev) => {
      const newCount = prev.length + 1;
      // Going from N → N+1.  When the previous trade was 2-team the
      // assets had implicit "other side" destinations; now we need
      // explicit ones so the NET flow math has a valid starting point.
      // Seed the default (next side circular) for any asset that
      // doesn't already have an entry.  Assets that already have a
      // destination keep it — the user's chosen routing is preserved.
      const withDestinations = prev.map((s, i) => {
        const nextDest = { ...(s.destinations || {}) };
        for (const asset of s.assets) {
          const key = tradeEntryKey(asset);
          if (nextDest[key] == null) {
            nextDest[key] = defaultDestination(i, newCount);
          }
        }
        return { ...s, destinations: nextDest };
      });
      return [...withDestinations, createSide(prev.length)];
    });
  }

  function removeTeam(idx) {
    if (sides.length <= MIN_SIDES) return;
    setSides((prev) => {
      const next = prev.filter((_, i) => i !== idx);
      const newCount = next.length;
      // Reletter remaining sides AND rewrite destinations so any
      // asset that was targeting the removed side — or one of the
      // now-shifted sides — points at a valid slot.  Destinations
      // that would collapse onto the side itself fall back to the
      // default (next side circular).
      return next.map((s, i) => {
        const remapped = {};
        for (const [name, dest] of Object.entries(s.destinations || {})) {
          const parsed = Number(dest);
          if (!Number.isInteger(parsed)) continue;
          if (parsed === idx) {
            // Asset was going to the removed side — reassign.
            remapped[name] = defaultDestination(i, newCount);
            continue;
          }
          const shifted = parsed > idx ? parsed - 1 : parsed;
          if (shifted >= 0 && shifted < newCount && shifted !== i) {
            remapped[name] = shifted;
          } else {
            remapped[name] = defaultDestination(i, newCount);
          }
        }
        return {
          ...s,
          id: i,
          label: SIDE_LABELS[i],
          destinations: remapped,
        };
      });
    });
    // Keep the per-side team selection/lock arrays index-aligned with
    // the surviving sides (splice the removed slot) so a locked team
    // can't slide onto the wrong side after a removal.
    setSideTeamNames((prev) => prev.filter((_, i) => i !== idx));
    setSideTeamLocked((prev) => prev.filter((_, i) => i !== idx));
    // Fix activeSide if it's out of bounds
    setActiveSide((prev) => Math.min(prev, sides.length - 2));
  }

  // ── KTC trade-calculator URL import ───────────────────────────────
  // Paste a https://keeptradecut.com/trade-calculator?teamOne=...&teamTwo=...
  // URL, POST to the backend for name resolution, then replace Sides
  // A and B with the resolved rows.  Any sides beyond B are kept
  // untouched so a 3-team trade doesn't lose its 3rd slot just
  // because a 2-side KTC URL was imported.  Unresolved KTC IDs
  // surface as a warning in ``ktcImportStatus`` so the user knows
  // one or more pieces were dropped.
  const importKtcTradeUrl = useCallback(async () => {
    const url = (ktcImportUrl || "").trim();
    if (!url) {
      setKtcImportError("Paste a KTC trade-calculator URL first.");
      return;
    }
    if (!url.includes("keeptradecut.com")) {
      setKtcImportError("URL must be from keeptradecut.com.");
      return;
    }

    // Request sequencing (TC-E): only the newest import may land, Cancel
    // retires one in flight, and an import never replaces a trade the user
    // edited while it was loading -- that would overwrite a newer trade with
    // an older request's answer.
    const seq = (ktcImportSeqRef.current += 1);
    const startedOn = sidesSignatureRef.current;
    setKtcImportBusy(true);
    setKtcImportError("");
    setKtcImportStatus("");
    try {
      const res = await fetch("/api/trade/import-ktc", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ url }),
        cache: "no-store",
      });
      const data = await res.json().catch(() => ({}));
      if (seq !== ktcImportSeqRef.current) return;
      if (sidesSignatureRef.current !== startedOn) {
        setKtcImportError(
          "The trade changed while the import was loading, so nothing was replaced. Load it again to replace sides A and B.",
        );
        return;
      }
      if (!res.ok || data?.ok === false) {
        setKtcImportError(data?.error || `HTTP ${res.status}`);
        return;
      }

      const sideOneEntries = Array.isArray(data.sideOne) ? data.sideOne : [];
      const sideTwoEntries = Array.isArray(data.sideTwo) ? data.sideTwo : [];
      const unresolvedOne = data?.unresolved?.sideOne || [];
      const unresolvedTwo = data?.unresolved?.sideTwo || [];

      // Resolve each KTC-returned name → our canonical row (exact →
      // case-insensitive → normalized → pick label; same-name rows are
      // split by KTC's stated position).  See lib/ktc-import.js.
      // Residual misses and ambiguous names are surfaced to the user.
      const nameIndex = buildKtcNameIndex(rows);
      const resolvePick = (name) =>
        parsePickToken(name)
          ? resolvePickRow(name, rowByLowerName, pickAliases)
          : null;
      const one = resolveKtcEntries(sideOneEntries, nameIndex, { resolvePick });
      const two = resolveKtcEntries(sideTwoEntries, nameIndex, { resolvePick });

      // Replace sides A and B in place.  Nothing is deduped: an asset KTC
      // lists twice is two copies and both load, on either side (owner
      // decision 2026-10-03 — calculator quantities are hypothetical).
      const cleanedOne = one.found;
      const cleanedTwo = two.found;

      // Seeds default destinations in a 3+-team trade and drops stale
      // routing — the shared bulk-load rule (lib/trade-logic).
      setSides((prev) =>
        applyImportedSides(prev, [cleanedOne, cleanedTwo], "replace"),
      );
      setValueOverrides({});

      const warnings = [];
      if (unresolvedOne.length)
        warnings.push(
          `unknown KTC id(s) on side A: ${unresolvedOne.join(", ")}`,
        );
      if (unresolvedTwo.length)
        warnings.push(
          `unknown KTC id(s) on side B: ${unresolvedTwo.join(", ")}`,
        );
      if (one.missing.length)
        warnings.push(`no board match for: ${one.missing.join(", ")}`);
      if (two.missing.length)
        warnings.push(`no board match for: ${two.missing.join(", ")}`);
      const ambiguousNames = [...one.ambiguous, ...two.ambiguous];
      if (ambiguousNames.length)
        warnings.push(
          `more than one board player named ${ambiguousNames.join(", ")} — check the loaded player`,
        );
      if (data?.playerMap?.source === "last_good")
        warnings.push(
          `KTC unreachable — used a saved KTC player list from ${Math.round(
            Number(data.playerMap.ageHours) || 0,
          )}h ago`,
        );
      const totalLoaded = cleanedOne.length + cleanedTwo.length;
      const totalExpected = sideOneEntries.length + sideTwoEntries.length;
      if (totalLoaded === 0) {
        setKtcImportError(
          warnings.length
            ? `Nothing loaded — ${warnings.join("; ")}`
            : "Nothing loaded.",
        );
      } else {
        const summary = `Loaded ${totalLoaded}/${totalExpected} players`;
        setKtcImportStatus(
          warnings.length ? `${summary} — ${warnings.join("; ")}` : summary,
        );
        // Collapse the import row on success so the user isn't
        // staring at the URL field; leave status visible below.
        setKtcImportOpen(false);
      }
    } catch (err) {
      if (seq !== ktcImportSeqRef.current) return;
      setKtcImportError(err?.message || "Import failed");
    } finally {
      if (seq === ktcImportSeqRef.current) setKtcImportBusy(false);
    }
  }, [ktcImportUrl, rows, rowByLowerName, pickAliases]);

  // ── Import trade control (KTC URL / screenshot) ───────────────────
  const toggleImportMenu = useCallback(() => {
    setImportMenuOpen((open) => !open);
    prefetch(loadKtcImportPanel);
    if (screenshotStatus !== null) return;
    setScreenshotStatus("loading");
    fetch("/api/trade/import-screenshot/status", { cache: "no-store" })
      .then((r) => r.json().catch(() => ({})))
      .then((d) => {
        const status = d && typeof d === "object" ? d : {};
        setScreenshotStatus(status);
        if (status.enabled === true) prefetch(loadScreenshotImport);
      })
      // Unreachable status = the feature is not offered (fail closed).
      .catch(() => setScreenshotStatus({ enabled: false, available: false }));
  }, [screenshotStatus]);

  const screenshotEntryVisible =
    screenshotStatus === "loading" ||
    (screenshotStatus !== null && screenshotStatus.enabled === true);

  // Confirmed screenshot import: ONE sides update (lib/trade-logic
  // applyImportedSides). Replace is a bulk load and resets value overrides
  // like the KTC path; Add keeps the user's edits on the assets already in
  // the trade.
  const importScreenshotSides = useCallback((importedSides, mode) => {
    const n =
      (importedSides?.[0]?.length || 0) + (importedSides?.[1]?.length || 0);
    setSides((prev) => applyImportedSides(prev, importedSides, mode));
    if (mode !== "add") setValueOverrides({});
    setScreenshotImportOpen(false);
    setScreenshotImportNote(
      `Imported ${n} ${n === 1 ? "asset" : "assets"} from screenshot${
        mode === "add" ? " (added to the current trade)" : ""
      }`,
    );
  }, []);

  const exportKtcUrl = useCallback(async () => {
    setExportStatus("");
    const sideOne = (sides[0]?.assets || []).map((r) => r.name);
    const sideTwo = (sides[1]?.assets || []).map((r) => r.name);
    if (!sideOne.length && !sideTwo.length) {
      setExportStatus("Nothing to export.");
      return;
    }
    // Sequenced like the import (TC-E): a link for an older trade is never
    // copied after the trade changed, and only the newest request reports.
    const seq = (ktcExportSeqRef.current += 1);
    const startedOn = sidesSignatureRef.current;
    try {
      const res = await fetch("/api/trade/export-ktc", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ sideOne, sideTwo }),
        cache: "no-store",
      });
      const data = await res.json().catch(() => ({}));
      if (seq !== ktcExportSeqRef.current) return;
      if (sidesSignatureRef.current !== startedOn) {
        setExportStatus("The trade changed before the KTC link was ready, so nothing was copied. Copy it again.");
        return;
      }
      if (!res.ok || !data.ok) {
        setExportStatus(data?.error || "KTC export failed.");
        return;
      }
      try {
        await navigator.clipboard.writeText(data.url);
      } catch {
        /* clipboard blocked */
      }
      const miss = [
        ...(data.unresolved?.sideOne || []),
        ...(data.unresolved?.sideTwo || []),
      ];
      setExportStatus(
        "KTC URL copied" +
          (miss.length ? ` \u2014 unmatched: ${miss.join(", ")}` : ""),
      );
    } catch (e) {
      if (seq !== ktcExportSeqRef.current) return;
      setExportStatus("KTC export failed: " + (e?.message || e));
    }
  }, [sides]);

  const _downloadFile = useCallback((filename, text, mime) => {
    const blob = new Blob([text], { type: mime });
    const url = URL.createObjectURL(blob);
    const el = document.createElement("a");
    el.href = url;
    el.download = filename;
    document.body.appendChild(el);
    el.click();
    el.remove();
    URL.revokeObjectURL(url);
  }, []);

  const exportCsv = useCallback(() => {
    const iso = new Date().toISOString().slice(0, 19).replace(/[:T]/g, "-");
    _downloadFile(
      `trade-${iso}.csv`,
      tradeWorkspaceToCSV(sides, valueMode, valuationBasisLabel(rawData)),
      "text/csv",
    );
    setExportStatus("CSV downloaded.");
  }, [sides, valueMode, rawData, _downloadFile]);

  const exportJson = useCallback(() => {
    const iso = new Date().toISOString().slice(0, 19).replace(/[:T]/g, "-");
    _downloadFile(
      `trade-${iso}.json`,
      tradeWorkspaceToJSON(sides, valueMode, activeSide),
      "application/json",
    );
    setExportStatus("JSON downloaded.");
  }, [sides, valueMode, activeSide, _downloadFile]);

  // ── Share-URL + simulator actions ─────────────────────────────────
  // Build a share-URL from the current trade and copy to clipboard.
  // Falls back to selecting the URL in a prompt when the clipboard
  // API is unavailable (older Safari / non-HTTPS contexts).
  const copyShareLink = useCallback(async () => {
    try {
      const payload = {
        // One name per COPY plus each owned pick's canonical id, so the
        // link restores quantity and distinct identity exactly
        // (``encodeTrade`` run-length-groups the copies per line).
        sides: sides.map((s) => ({
          name: s.label ? `Side ${s.label}` : "",
          players: (s.assets || []).map((a) => a.name),
          assetIds: (s.assets || []).map((a) => a.assetId || null),
          // 3+-team routing travels with the link (TC-A); a 2-team trade
          // routes implicitly and carries none.
          destinations:
            sides.length > 2
              ? (s.assets || []).map((a) => {
                  const d = s.destinations?.[tradeEntryKey(a)];
                  return Number.isInteger(d) ? d : null;
                })
              : [],
        })),
        // #842: the analysis mode travels with the link.
        teamContext: useTeamContext,
        // TC-A: the package model these totals were computed under.
        packageModel: ACTIVE_PACKAGE_MODEL_ID,
      };
      const url = buildShareUrl(payload);
      // A link that cannot carry the whole trade is still offered, but the
      // user is told what it drops instead of "copied".
      const limits = shareLinkLimits(payload);
      const lossNote = limits.complete
        ? ""
        : ` It will NOT reproduce this trade exactly: it has ${describeShareTruncation(
            limits.reasons,
          )}, beyond what a share link may carry.`;
      const tone = limits.complete ? "positive" : "warning";
      if (navigator?.clipboard?.writeText) {
        await navigator.clipboard.writeText(url);
        setShareStatus({ tone, text: `Share link copied to clipboard.${lossNote}` });
      } else if (typeof window !== "undefined") {
        // Surface the URL so the user can copy it manually.
        window.prompt("Copy this share link:", url);
        setShareStatus({ tone, text: `Share link ready.${lossNote}` });
      }
    } catch (err) {
      setShareStatus({ tone: "warning", text: err?.message || "Could not copy share link." });
    }
  }, [sides, useTeamContext]);

  // Pure impact-on-my-roster simulator.  2-team trades only:
  // whichever side matches the user's selected Sleeper team is
  // treated as "sending" (players OUT) and the other side as
  // "receiving" (players IN).  Picks and players are sent as one
  // payload each because the simulator backend treats them
  // identically — both resolve through the same row-index.
  // The War Room's question: the same side mapping "Simulate impact" uses.
  const warRoomRequest = useMemo(
    () =>
      selectedTeam && sides.length === 2
        ? tradeRequestForTeam(
            sides,
            teamRosterNames(selectedTeam),
            selectedTeam.name,
            explicitMySide,
          )
        : null,
    [sides, selectedTeam, teamRosterNames, explicitMySide],
  );
  // The War Room's immediate trade-value summary (owner directive 2026-10-19,
  // Part 4): EXACTLY the calculator headline's totals for the selected team's
  // side (overrides included), shown while the personalized analysis runs --
  // never a YES / NO.  An asset with no board value and no override gets no
  // total at all (MISSING IS NEVER ZERO); `warRoomValueSummaryFor` decides.
  const warRoomValueSummary = useMemo(
    () =>
      sides.length === 2 && warRoomRequest
        ? warRoomValueSummaryFor({
            sideTotals,
            mySide: warRoomRequest.mySide,
            evaluation: evalState,
            overrideCount: Object.keys(valueOverrides).length,
          })
        : null,
    [sides.length, warRoomRequest, sideTotals, evalState, valueOverrides],
  );
  // Both sides hold assets but nothing says which one is the team's: ask.
  const sideChoiceNeeded =
    Boolean(selectedTeam) &&
    sides.length === 2 &&
    teamSide.side == null &&
    sides.every((s) => (s.assets || []).length > 0);

  // The question "Simulate impact" answered.  Any trade edit, Clear Trade,
  // team or league change invalidates the shown result (TC-A / UX audit
  // P0-2); the hook's request sequence drops a late answer for an old one.
  const simSignature = useMemo(
    () => simulationSignature(sides, selectedTeam?.name, selectedLeagueKey),
    [sides, selectedTeam, selectedLeagueKey],
  );
  useEffect(() => {
    resetSim();
  }, [simSignature, resetSim]);

  const runSimulateTrade = useCallback(() => {
    if (sides.length !== 2) return;
    if (!selectedTeam) return;
    prefetch(loadSimulationPanel);
    // The ONE side mapping (`lib/trade-war-room.js`), shared with the Trade
    // War Room so the two can never disagree about which way a trade points:
    // the side holding more of this team's players is the side it GIVES.
    const request = tradeRequestForTeam(
      sides,
      teamRosterNames(selectedTeam),
      selectedTeam?.name,
      explicitMySide,
    );
    if (!request) return;
    const { playersIn, playersOut, picksIn, picksOut, pickAssetIdsIn, pickAssetIdsOut } =
      request;
    simulateTrade(
      {
        teamName: selectedTeam?.name,
        playersIn,
        playersOut,
        picksIn,
        picksOut,
        pickAssetIdsIn,
        pickAssetIdsOut,
      },
      { signature: simSignature },
    );
  }, [sides, selectedTeam, teamRosterNames, simulateTrade, simSignature, explicitMySide]);

  // ── Suggestions logic ─────────────────────────────────────────────
  const parseRoster = useCallback(() => {
    return rosterInput
      .split(/[,\n]+/)
      .map((s) => s.trim())
      .filter(Boolean);
  }, [rosterInput]);

  function selectTeam(idx) {
    const i = Number(idx);
    setSelectedTeamIdx(i);
    localStorage.setItem(TEAM_KEY, String(i));

    if (i < 0 || !sleeperTeams || !sleeperTeams[i]) {
      setLeagueRosters(null);
      return;
    }

    const team = sleeperTeams[i];
    const picks = (teamPickLabels(team) || []).map((p) => {
      const m = p.match(/^(\d{4})\s+(\d)\./);
      if (m) {
        const round =
          { 1: "1st", 2: "2nd", 3: "3rd", 4: "4th" }[m[2]] || `${m[2]}th`;
        return `${m[1]} ${round}`;
      }
      return p.replace(/\s*\(.*\)/, "").trim();
    });
    const rosterNames = [...(team.players || []), ...picks];
    const newInput = rosterNames.join("\n");
    setRosterInput(newInput);
    localStorage.setItem(ROSTER_KEY, newInput);

    const opponents = sleeperTeams
      .filter((_, oi) => oi !== i)
      .map((t) => ({ team_name: t.name, players: t.players || [] }));
    setLeagueRosters(opponents);

    // Propagate to the global team context (``useTeam().selectedTeam``)
    // so a pick made via THIS in-page dropdown — not just the topbar
    // TeamSwitcher — also updates surfaces gated on it, e.g. the
    // "Simulate impact" button below, which reads ``selectedTeam``
    // directly. Guarded against the value that produced this same call
    // via the topbar-sync effect above, so the two effects don't feed
    // back into each other.
    if (i !== topbarTeamIdx) {
      setSelectedTeam(team);
    }
  }

  // Auto-fetch suggestions whenever the user lands on the page with
  // a populated roster — surfaces the proactive "Recommended right
  // now" rail without requiring the user to scroll down + click
  // ``Get Suggestions`` first.  Re-fires when:
  //   * roster contents change (paste / reset)
  //   * selected league/team changes (incl. picks regenerate)
  //   * loading completes (cold-load arrives after first paint)
  // Debounced via a ref so a rapid roster edit doesn't spam the API.
  //
  // Two failure modes the cancel logic has to thread:
  //
  //   (A) ``rows`` ref churns mid-load (``useSettings`` hydrates and
  //       triggers a second ``useDynastyData`` fetch) but ``bodyKey``
  //       is unchanged.  An older shape unconditionally cancelled the
  //       timer on every dep change; combined with the ``lastBody ===
  //       bodyKey`` short-circuit, the timer was killed and never
  //       re-armed, so ``fetchSuggestions`` never fired and the rail
  //       stayed hidden.
  //
  //   (B) The user switches leagues / clears the roster / starts a
  //       reload, so the preconditions now fail.  An armed timer from
  //       a prior valid render would otherwise fire ~500ms later and
  //       dispatch ``fetchSuggestions`` with stale render state.
  //
  // The shape below cancels exactly when preconditions newly fail OR
  // when ``bodyKey`` changes, and otherwise leaves the pending timer
  // alone.  ``lastBody`` is reset on the precondition-fail branch so a
  // fresh timer arms when the user returns to a valid state.
  const proactiveFetchRef = useRef({ lastBody: null, timer: null });
  const suggestionsSeqRef = useRef(0);
  const suggestionsInFlightRef = useRef(false);
  useEffect(() => {
    const cancelPending = () => {
      if (proactiveFetchRef.current.timer) {
        clearTimeout(proactiveFetchRef.current.timer);
        proactiveFetchRef.current.timer = null;
      }
      proactiveFetchRef.current.lastBody = null;
      // A fetch still in flight answers a state that no longer holds.
      if (suggestionsInFlightRef.current) {
        suggestionsSeqRef.current += 1;
        suggestionsInFlightRef.current = false;
        setSuggestionsLoading(false);
      }
    };
    if (loading || teamLoading) {
      cancelPending();
      // Deliberately does NOT clear ``suggestionsPending``.  Loading
      // means "we don't know yet", which is the RESERVE state, not the
      // collapse state — and clearing it here is invisible in the same
      // frame (both slot branches gate on ``!loading``) while poisoning
      // the FIRST ``!loading`` paint: React commits that frame with an
      // empty slot and only re-arms the flag post-commit.
      //
      // ``teamLoading`` is in this gate for the same reason and is the
      // one that actually bites.  ``useTeam`` resolves the roster AFTER
      // ``useDynastyData`` resolves the contract, so on the first
      // ``!loading`` render the roster is still empty — which fell
      // through to the "fewer than 3 rostered players" bail below and
      // collapsed the slot for a team that was about to arrive.  That
      // is what inserted 229px above ``trade-controls`` a beat later.
      return;
    }
    if (error || leagueMismatch) {
      cancelPending();
      setSuggestionsPending(false);
      return;
    }
    if (!rows || rows.length === 0) {
      cancelPending();
      setSuggestionsPending(false);
      return;
    }
    // A roster is still inbound while the topbar's team either has no
    // answer yet (``null``) or has one the local picker hasn't adopted.
    // ``selectTeam`` is what populates ``rosterInput``, and it runs
    // post-commit from the sync effect above — so for one render
    // ``parseRoster()`` is empty for a team that is definitely coming.
    const rosterInbound =
      topbarTeamIdx == null ||
      (topbarTeamIdx >= 0 && topbarTeamIdx !== selectedTeamIdx);
    const roster = parseRoster();
    if (roster.length < 3) {
      cancelPending();
      // Fewer than 3 rostered players: no fetch will happen, so the
      // slot collapses and the rail simply never appears — but only
      // once we know none is inbound.  Collapsing during the sync gap
      // is what made this page's CLS bimodal: it depended on whether
      // the roster beat the paint.
      if (!rosterInbound) setSuggestionsPending(false);
      return;
    }
    const bodyKey = `${selectedLeagueKey || ""}|${roster.join("|")}`;
    if (proactiveFetchRef.current.lastBody === bodyKey) return;
    proactiveFetchRef.current.lastBody = bodyKey;
    // The roster (or league) just changed — clear stale suggestions
    // so the rail doesn't keep rendering the previous team's ideas
    // while we fetch fresh ones.  Without this reset, a user who
    // switches teams via the topbar TeamSwitcher would see the
    // OLD team's "Recommended right now" cards until they manually
    // hit "Get Suggestions."  The bump retires any fetch still in flight for
    // the previous roster (TC-E): it must not land during the debounce.
    suggestionsSeqRef.current += 1;
    setSuggestions(null);
    setSuggestionsError(null);
    setSuggestionsPending(true);
    if (proactiveFetchRef.current.timer) {
      clearTimeout(proactiveFetchRef.current.timer);
    }
    proactiveFetchRef.current.timer = setTimeout(() => {
      proactiveFetchRef.current.timer = null;
      fetchSuggestions();
    }, 500);
    // No re-run cleanup: cancellation is handled inline above so a
    // benign ``rows`` ref churn doesn't kill the pending fetch, and
    // the unmount effect below tears down anything still in flight
    // on teardown.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [
    loading,
    teamLoading,
    error,
    leagueMismatch,
    rows,
    rosterInput,
    selectedLeagueKey,
    topbarTeamIdx,
    selectedTeamIdx,
  ]);

  // Unmount-only cleanup for the proactive-fetch debounce timer — kept
  // separate from the auto-fetch effect above so a dep-driven re-run
  // doesn't cancel a pending fetch.
  useEffect(() => {
    return () => {
      if (proactiveFetchRef.current.timer) {
        clearTimeout(proactiveFetchRef.current.timer);
        proactiveFetchRef.current.timer = null;
      }
    };
  }, []);

  async function fetchSuggestions() {
    // Request sequencing (TC-E): a team switch fires a fresh fetch while the
    // previous team's may still be in flight; only the newest may publish, so
    // a slow answer for the OLD roster can never replace the new one.
    const seq = (suggestionsSeqRef.current += 1);
    const current = () => seq === suggestionsSeqRef.current;
    const roster = parseRoster();
    if (roster.length < 3) {
      setSuggestionsError("Enter at least 3 player names to get suggestions.");
      setSuggestionsPending(false);
      return;
    }
    setSuggestionsLoading(true);
    suggestionsInFlightRef.current = true;
    setSuggestionsError(null);
    setSuggestions(null);
    localStorage.setItem(ROSTER_KEY, rosterInput);
    try {
      // Attach the active league key so the backend validates
      // against the registry and serves/rejects for the right
      // league.  The endpoint falls back to the user's saved
      // preference when leagueKey is absent, but passing it
      // explicitly keeps the response league unambiguous when the
      // user has just switched leagues and the new key hasn't
      // round-tripped to user_kv yet.
      const body = leagueRosters
        ? { roster, league_rosters: leagueRosters }
        : { roster };
      if (selectedLeagueKey) body.leagueKey = selectedLeagueKey;
      // /settings → "Trade Suggestion KTC Cap" slider.  When the
      // user hasn't customized, the backend's default applies (150).
      const cap = Number(settings?.ktcSuggestionTopN);
      if (Number.isFinite(cap) && cap > 0) body.ktc_top_n = cap;
      const res = await fetch("/api/trade/suggestions", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(withValuationMode(body)),
      });
      const data = await res.json().catch(() => ({}));
      if (!current()) return;
      if (!res.ok) {
        setSuggestionsError(data.error || `Server error (${res.status})`);
        return;
      }
      setSuggestions(data);
    } catch (err) {
      if (!current()) return;
      setSuggestionsError("Could not reach suggestion service.");
    } finally {
      if (current()) {
        suggestionsInFlightRef.current = false;
        setSuggestionsLoading(false);
        setSuggestionsPending(false);
      }
    }
  }

  function applySuggestion(s) {
    const giveRows = s.give.map((p) => rowByName.get(p.name)).filter(Boolean);
    const recvRows = s.receive
      .map((p) => rowByName.get(p.name))
      .filter(Boolean);
    // Apply to first two sides, reset others.  Suggestions are
    // inherently 2-team; wipe the 3rd+ side contents (and their
    // destination maps) so stale multi-team routing doesn't linger.
    setSides((prev) => {
      const sideCount = prev.length;
      const seedDestinations = (assets, sideIdx) => {
        if (sideCount <= 2) return {};
        const out = {};
        for (const asset of assets) {
          out[tradeEntryKey(asset)] = defaultDestination(sideIdx, sideCount);
        }
        return out;
      };
      return prev.map((side, i) => {
        if (i === 0)
          return {
            ...side,
            assets: giveRows,
            destinations: seedDestinations(giveRows, 0),
          };
        if (i === 1)
          return {
            ...side,
            assets: recvRows,
            destinations: seedDestinations(recvRows, 1),
          };
        return { ...side, assets: [], destinations: {} };
      });
    });
    setValueOverrides({});
  }

  // Count per category
  const suggestionCounts = useMemo(() => {
    if (!suggestions) return {};
    return Object.fromEntries(
      SUGG_TYPES.map((t) => [t.key, (suggestions[t.key] || []).length]),
    );
  }, [suggestions]);

  // Balancer payload for a given side — the label + list the SideCard
  // renders.  Returns null when that side has no balancer suggestion.
  function balancersForSide(sideIdx) {
    const isUnderpaying =
      sides.length === 2 ? !pwGapIsFair && (sideIdx === 0 ? pwGap < 0 : pwGap > 0) : false;
    // The deferred search has not answered THIS trade yet: say so on the
    // side it will answer for, instead of removing the panel as if nothing
    // narrows the gap (unknown is not false).
    if (balancersPending && !tradeIsIncomplete) {
      const nets = sides.length > 2 ? sideFlows.map((f) => f.net) : null;
      const target =
        sides.length === 2
          ? isUnderpaying
          : !multiGapIsFair && sideIdx === nets.indexOf(Math.max(...nets));
      if (target) {
        return { label: "Finding assets that narrow the gap…", list: [], pending: true };
      }
    }
    if (sides.length === 2 && isUnderpaying && balancers.list.length > 0) {
      return {
        label: balancers.teamName
          ? `Add from ${balancers.teamName}'s roster`
          : "To balance, consider adding",
        list: balancers.list,
      };
    }
    if (
      multiBalancers &&
      sideIdx === multiBalancers.underpayingIdx &&
      multiBalancers.suggestions.length > 0
    ) {
      const losing = `Side ${sides[multiBalancers.overpayingIdx]?.label} loses ${Math.round(
        multiBalancers.gap,
      ).toLocaleString()}`;
      return {
        label: multiBalancers.teamName
          ? `Add from ${multiBalancers.teamName}'s roster (${losing})`
          : `To balance (${losing})`,
        list: multiBalancers.suggestions,
      };
    }
    return null;
  }

  const hasAssets = sides.some((s) => (s.assets || []).length > 0);
  // The verdict bar's decision word: the War Room's own headline, only while
  // it answers the trade on screen (an "updating" answer is for an older one).
  const trayDecisionText =
    sides.length === 2 && decisionSummary.status === "ok"
      ? decisionSummary.decision?.headlineText || null
      : null;
  // Which side's card lists the balancing suggestions, for the Next steps
  // pointer (TC-B / TCM-O11) -- read from the page's own balancer state.
  const balancerSideLabel =
    sides.length === 2
      ? balancers.list.length
        ? sides[pwGap > 0 ? 1 : 0]?.label || null
        : null
      : multiBalancers?.suggestions?.length
        ? sides[multiBalancers.underpayingIdx]?.label || null
        : null;

  return (
    <div className={`main-shell ${styles.page} trade-page psi-editorial`}>
      <PageHeader
        eyebrow="Trades"
        title="Trade Calculator"
        description="Multi-team trade calculator with live fairness visualization."
      />

      {/* TC-D2 / TCM-D09: the "Market / My league" control is gone -- the
          league-adjusted lens is withdrawn server-side (#822; CLAUDE.md
          "valuation_mode: accepted, ignored"), so the control changed
          nothing.  The note below is gated on the CONTRACT, never the
          setting, and renders nothing on the market board. */}
      <ValueBasisNote contract={rawData} />

      {loading ? (
        // 4 rows ~= 213px, the measured height of the suggestions rail
        // that occupies this same slot once loading completes.  At 6
        // rows it was 258px, so the loading -> content transition moved
        // everything below it up 45px.
        <Panel flush>
          <SkeletonTable rows={4} columns={4} />
        </Panel>
      ) : null}
      {loading ? (
        <span className="ds-visually-hidden">Loading player pool...</span>
      ) : null}

      {error ? (
        <Banner tone="negative" title="Couldn't load the player pool">
          {error}
        </Banner>
      ) : null}

      {!loading && !error && leagueMismatch ? (
        <Banner tone="warning" title="Roster data not ready for this league">
          Rankings and values are available (scoring is shared), but
          team-specific features — Sleeper roster import, &quot;Simulate on my
          team&quot;, and league-mate pickers — need this league&apos;s scrape
          to finish. Switch back to the primary league to use them.
        </Banner>
      ) : null}

      {!loading && !error ? (
        <>
          {/* ── TC-D WORKSPACE ────────────────────────────────────
              Five layers in reading order (./trade-layout.jsx): Trade
              Builder, Immediate Result, Final Decision, Supporting
              Intelligence, Ideas & tools.  Desktop (>= 1024) puts the
              result and the decision echo in a sticky right column; below
              that it is one column with this section nav and the verdict
              bar at the foot of the screen. */}
          {/* TC-E: the one polite announcement of a final decision change.
              Outside every responsive container, so it is never inside a
              display:none column at any width. */}
          <TradeVerdictAnnouncer
            summary={sides.length === 2 ? decisionSummary : { status: "multi", decision: null }}
          />
          <TradeSectionNav />
          <div className={styles.workspace}>
            {/* ── 1. TRADE BUILDER ─────────────────────────────── */}
            <section
              id="trade-builder"
              className={`${styles.layer} ${styles.layerBuilder}`}
              aria-labelledby="trade-builder-title"
            >
              <h2 id="trade-builder-title" className={styles.layerTitle}>
                Trade builder
              </h2>
              <Panel dense className="trade-controls">
                <div className={styles.controls}>
                  <Button onClick={swapSides}>
                    {sides.length === 2 ? "Swap Sides" : "Rotate Sides"}
                  </Button>
                  <Button onClick={clearTrade}>Clear Trade</Button>
                  <Button
                    onClick={() => setValueOverrides({})}
                    disabled={!Object.keys(valueOverrides).length}
                  >
                    Reset Values
                  </Button>
                  {sides.length < MAX_SIDES ? (
                    <Button onClick={addTeam}>Add Team</Button>
                  ) : null}
                  <Button
                    ref={importMenuButtonRef}
                    onClick={toggleImportMenu}
                    onKeyDown={(e) => {
                      if (e.key === "Escape" && importMenuOpen) closeToolbarGroup(setImportMenuOpen, importMenuButtonRef);
                    }}
                    aria-expanded={importMenuOpen}
                    aria-controls="trade-import-options"
                    icon={
                      <Icon
                        name={importMenuOpen ? "chevron-up" : "chevron-down"}
                        size={12}
                      />
                    }
                  >
                    Import trade
                  </Button>
                  {importMenuOpen ? (
                    <span
                      id="trade-import-options"
                      role="group"
                      aria-label="Import trade from"
                      className={styles.importOptions}
                      onKeyDown={(e) => {
                        if (e.key === "Escape") closeToolbarGroup(setImportMenuOpen, importMenuButtonRef);
                      }}
                    >
                      <Button
                        variant="ghost"
                        onClick={() => {
                          setImportMenuOpen(false);
                          setKtcImportOpen(true);
                          setKtcImportError("");
                        }}
                      >
                        From KeepTradeCut URL
                      </Button>
                      {screenshotEntryVisible ? (
                        <Button
                          variant="ghost"
                          loading={screenshotStatus === "loading"}
                          onClick={() => {
                            setImportMenuOpen(false);
                            setScreenshotImportNote("");
                            setScreenshotImportOpen(true);
                          }}
                        >
                          From screenshot
                        </Button>
                      ) : null}
                    </span>
                  ) : null}
                  <Button onClick={copyShareLink} disabled={!hasAssets}>
                    Copy share link
                  </Button>
                  {/* TC-D2 (UX audit P2-8): the export actions sit in one
                      "More" group instead of three primary toolbar buttons. */}
                  <Button
                    ref={moreMenuButtonRef}
                    onClick={() => setMoreMenuOpen((open) => !open)}
                    onKeyDown={(e) => {
                      if (e.key === "Escape" && moreMenuOpen) closeToolbarGroup(setMoreMenuOpen, moreMenuButtonRef);
                    }}
                    aria-expanded={moreMenuOpen}
                    aria-controls="trade-more-options"
                    icon={<Icon name={moreMenuOpen ? "chevron-up" : "chevron-down"} size={12} />}
                  >
                    More
                  </Button>
                  {moreMenuOpen ? (
                    <span
                      id="trade-more-options"
                      role="group"
                      aria-label="More trade actions"
                      className={styles.importOptions}
                      onKeyDown={(e) => {
                        if (e.key === "Escape") closeToolbarGroup(setMoreMenuOpen, moreMenuButtonRef);
                      }}
                    >
                      <Button
                        variant="ghost"
                        onClick={() => {
                          closeToolbarGroup(setMoreMenuOpen, moreMenuButtonRef);
                          exportKtcUrl();
                        }}
                        disabled={sides.length !== 2 || !hasAssets}
                      >
                        Copy KTC URL
                      </Button>
                      <Button
                        variant="ghost"
                        onClick={() => {
                          closeToolbarGroup(setMoreMenuOpen, moreMenuButtonRef);
                          exportCsv();
                        }}
                        disabled={!hasAssets}
                      >
                        Download CSV
                      </Button>
                      <Button
                        variant="ghost"
                        onClick={() => {
                          closeToolbarGroup(setMoreMenuOpen, moreMenuButtonRef);
                          exportJson();
                        }}
                        disabled={!hasAssets}
                      >
                        Download JSON
                      </Button>
                    </span>
                  ) : null}
                  {/* The answer to an action the user just took (copy / download),
                      read out politely (TC-E). */}
                  <span className={styles.controlsNote} role="status">
                    {exportStatus}
                  </span>
                </div>
              </Panel>

              {pickOwnershipUnknown.length ? (
                <Banner tone="warning" title={PICK_OWNERSHIP_UNAVAILABLE_LABEL}>
                  {describePickOwnershipReason(pickOwnershipUnknown[0].reason)} Owned picks for{" "}
                  {pickOwnershipUnknown.map((t) => t.name).join(", ")} cannot be listed or
                  suggested; market picks (e.g. a Mid 1st) can still be added.
                </Banner>
              ) : null}

              {historyOrigin ? (
                <Banner
                  tone="warning"
                  title="Opened from Trade History — today's view, not a replay"
                  onDismiss={() => setHistoryOrigin(null)}
                >
                  <span data-testid="trade-history-origin">
                    This completed trade{historyOrigin.tradedAt ? ` (made ${historyOrigin.tradedAt})` : ""}{" "}
                    is valued with today&apos;s board, rosters and roster needs. It is not
                    what the trade looked like when it was made: an as-of replay is not
                    built yet.
                  </span>
                </Banner>
              ) : null}

              {shareStatus ? (
                <Banner tone={shareStatus.tone} onDismiss={() => setShareStatus(null)}>
                  {shareStatus.text}
                </Banner>
              ) : null}

              {ktcImportOpen ? (
                <KtcImportPanel
                  url={ktcImportUrl}
                  onUrlChange={setKtcImportUrl}
                  busy={ktcImportBusy}
                  error={ktcImportError}
                  onSubmit={importKtcTradeUrl}
                  onCancel={() => {
                    // Cancel retires an import still in flight (TC-E).
                    ktcImportSeqRef.current += 1;
                    setKtcImportBusy(false);
                    setKtcImportOpen(false);
                    setKtcImportError("");
                    setKtcImportUrl("");
                  }}
                />
              ) : null}

              {ktcImportStatus && !ktcImportOpen ? (
                <Banner tone="info" onDismiss={() => setKtcImportStatus("")}>
                  KTC import: {ktcImportStatus}
                </Banner>
              ) : null}

              {/* Gated here: rendering the lazy dialog is what requests its chunk. */}
              {screenshotImportOpen ? (
                <ScreenshotImportDialog
                  onClose={() => setScreenshotImportOpen(false)}
                  onImport={importScreenshotSides}
                  hasExistingAssets={hasAssets}
                  rows={rows}
                  rowByName={rowByName}
                  rowByLowerName={rowByLowerName}
                  pickAliases={pickAliases}
                  status={
                    screenshotStatus && typeof screenshotStatus === "object"
                      ? screenshotStatus
                      : null
                  }
                />
              ) : null}

              {screenshotImportNote && !screenshotImportOpen ? (
                <Banner
                  tone="positive"
                  onDismiss={() => setScreenshotImportNote("")}
                >
                  {screenshotImportNote}
                </Banner>
              ) : null}

              {tradeHasPicks && sleeperTeams ? (
                <PickTeamSelectors
                  sides={sides}
                  sleeperTeams={sleeperTeams}
                  sideTeamNames={sideTeamNames}
                  stackGateUnmet={stackGateUnmet}
                  stackBudgetsUnavailable={stackBudgetsUnavailable}
                  onSetTeam={(i, v) => {
                    setSideTeamNames((prev) => {
                      const next = [...prev];
                      next[i] = v;
                      return next;
                    });
                    // Picking a team locks it (don't re-infer); the blank
                    // option unlocks → auto-infer resumes.
                    setSideTeamLocked((prev) => {
                      const next = [...prev];
                      next[i] = v != null;
                      return next;
                    });
                  }}
                />
              ) : null}

              {/* ── BUILD ────────────────────────────────────────────
                  The side cards are where a trade is actually assembled,
                  and they used to sit BELOW the verdict and six analysis
                  panels — you scrolled past every answer to reach the
                  question.  They lead now; the verdict follows as you fill
                  them, and the sticky tray keeps it on screen while you
                  edit. */}
              <div
                className={styles.sidesGrid}
                data-sides={String(Math.min(4, sides.length))}
              >
                {sides.map((side, sideIdx) => (
                  <SideCard
                    key={side.id}
                    side={side}
                    sideIdx={sideIdx}
                    sides={sides}
                    total={
                      sideTotals[sideIdx] || { raw: 0, adjustment: 0, adjusted: 0 }
                    }
                    isMySide={sideIdx === mySideIdx}
                    selectedTeam={selectedTeam}
                    sideQuery={sideQueries[sideIdx]}
                    isFocused={focusedSideIdx === sideIdx}
                    searchResults={
                      focusedSideIdx === sideIdx
                        ? searchAssets(sideQueries[sideIdx] || "", sideIdx)
                        : []
                    }
                    settings={settings}
                    valueMode={valueMode}
                    valueOverrides={valueOverrides}
                    incoming={sideFlowAssets[sideIdx]?.incoming || []}
                    balancers={balancersForSide(sideIdx)}
                    canRemoveTeam={sides.length > MIN_SIDES}
                    onSideQueryChange={(idx, v) =>
                      setSideQueries((prev) => ({ ...prev, [idx]: v }))
                    }
                    onSideFocus={(idx) => {
                      setFocusedSideIdx(idx);
                      setActiveSide(idx);
                    }}
                    onSideBlur={(idx) => {
                      // Delay so a tap on a result registers before the
                      // dropdown unmounts (onMouseDown also pre-empts blur;
                      // this is the belt-and-braces guard for touch).
                      setTimeout(() => {
                        setFocusedSideIdx((prev) => (prev === idx ? null : prev));
                      }, 120);
                    }}
                    onAddFromSearch={addFromSearch}
                    onOpenPlayer={openPlayerPopup}
                    onSetValueOverride={setValueOverride}
                    onClearValueOverride={clearValueOverride}
                    onRemoveAsset={removeFromSide}
                    onSetDestination={setAssetDestination}
                    onRemoveTeam={removeTeam}
                    onAddBalancer={(b, idx) => {
                      // The candidate ENTRY, so an owned pick keeps its id.  A
                      // pair (TC-B / TCM-F03) adds both of its entries.
                      if (b?.isCombo && Array.isArray(b.entries)) {
                        for (const entry of b.entries) addToSide(entry, idx);
                        return;
                      }
                      const row = b?.entry || rowByName.get(b?.name);
                      if (row) addToSide(row, idx);
                    }}
                    onAddCopy={(entry, idx) => addToSide(entry, idx)}
                    registerInputRef={(idx, el) => {
                      sideInputRefs.current[idx] = el;
                    }}
                    sheetMode={narrow}
                    onOpenSheet={(idx) => {
                      setActiveSide(idx);
                      setSheetSideIdx(idx);
                    }}
                  />
                ))}
              </div>
              {/* Gated here: rendering the lazy sheet is what requests its chunk. */}
              {narrow && sheetSideIdx != null && sides[sheetSideIdx] ? (
                <TradeAssetSheet
                  side={sides[sheetSideIdx]}
                  sideIdx={sheetSideIdx}
                  searchAssets={searchAssets}
                  settings={settings}
                  onAdd={addToSide}
                  onClose={() => setSheetSideIdx(null)}
                />
              ) : null}
            </section>

            {/* ── 2. IMMEDIATE RESULT (+ the decision echo) ─────────
                Sticky beside the builder on desktop. */}
            <aside className={styles.layerAside} aria-label="Result and decision">
              <section
                id="trade-result"
                className={styles.resultPanel}
                aria-labelledby="trade-result-title"
              >
                <div className={styles.layerHead}>
                  <h2 id="trade-result-title" className={styles.layerTitle}>
                    Immediate result
                  </h2>
                  <TradeVerdictHelp />
                </div>
                {sides.length === 2 && !tradeIsEmpty && !tradeIsIncomplete ? (
                  <ImmediateResultTable sides={sides} sideTotals={sideTotals} />
                ) : null}
                {/* The package comparison: fairness band + the explanations
                    behind it.  `sidesSend`: every side lists what that team
                    sends, so the meter names the bigger PACKAGE and the team
                    that receives it. */}
                {/* sidesWithOverrides, not sides: the Monte Carlo panel inside the
                    meter simulates around the SAME per-asset values the meter's
                    totals are built from (TC-A / UX audit P0-1). */}
                <TradeMeter
                  sides={sidesWithOverrides}
                  sideTotals={sideTotals}
                  flows={sideFlows}
                  valueMode={valueMode}
                  settings={settings}
                  sidesSend
                />

                {/* STACK-NOTE-ONLY:BEGIN — withdrawn stack effect: shown, labelled, NOT in the totals. */}
                {stackNote && stackNote.some((v) => Math.round(v) !== 0) ? (
                  <p
                    className={styles.controlsNote}
                    title="Change in each team's zero-sum effective auction power from this pick swap, in board-value units. Experimental and not calibrated, so it is kept out of the package totals, the verdict and the balancing suggestions."
                  >
                    <strong>Experimental context</strong> — Draft-capital stack effect
                    (experimental, not calibrated):{" "}
                    {stackNote
                      .map((raw, i) => {
                        const v = Math.round(raw);
                        return `Side ${sides[i]?.label ?? i + 1}: ${v > 0 ? "+" : ""}${v}`;
                      })
                      .join(" · ")}
                    . Not included in the totals or verdict.
                  </p>
                ) : null}
                {draftCapitalFailed && tradeHasPicks ? (
                  <p className={styles.controlsNote} data-testid="draft-capital-unavailable">
                    Draft-capital note unavailable: this league&apos;s draft-capital board could not
                    be read. The totals and verdict never use it.
                  </p>
                ) : null}
                {stackLibFailed && stackLibWanted ? (
                  <p className={styles.controlsNote}>
                    Draft-capital note unavailable: its model could not be loaded.
                  </p>
                ) : null}
                {stackNotOwned ? (
                  <p className={styles.controlsNote}>
                    Draft-capital note skips{" "}
                    {stackNotOwned.map((x) => x.label).join(", ")}: not held by the team on that side.
                  </p>
                ) : null}
                {/* STACK-NOTE-ONLY:END */}
              </section>
              {/* Layer 3's echo: the War Room's own answer, reported up
                  through onDecision (desktop only; below 1024 the War Room
                  follows directly and the verdict bar carries the word). */}
              <DecisionSummary
                summary={sides.length === 2 ? decisionSummary : { status: "multi", decision: null }}
              />
              {/* The meter's plain-English reading and the independent tally
                  follow the decision echo, so the decision stays on the
                  first desktop screen (UX audit §7.2: today it starts at
                  y=1,019 at 1366x900). */}
              <div className={styles.resultNotes}>
                {/* The plain-English reading of the meter above — it explains
                    the verdict, so it belongs with it rather than folded away
                    among the alternative-currency second opinions. */}
                {tradeIsIncomplete ? null : (
                  <TradeFairnessExplanation sides={sidesWithOverrides} sideTotals={sideTotals} />
                )}

                {/* The one-glance independent tally (TC-B / TCM-K03).  BARE sides,
                    like the per-source table: an override changes the headline,
                    never what a source sees.  Rendering it is what requests its
                    chunk, so it waits for two filled sides. */}
                {sides.filter((s) => (s.assets || []).length > 0).length >= 2 ? (
                  <TradeOpinionTally sides={sides} />
                ) : null}
              </div>
            </aside>

            {/* ── 3. FINAL DECISION ────────────────────────────── */}
            <section
              id="trade-decision"
              className={`${styles.layer} ${styles.layerDecision}`}
              aria-label="Final decision"
            >
              {/* ── TRADE WAR ROOM (#792 / #1173 / #843 / #842) ────────
                  What this trade does to the selected team's actual
                  roster, in plain English (owner directive 2026-10-19):
                  the ONE recommendation, then Trade value / Impact on your
                  team / Does it fit your roster?  Every number is the
                  backend's; while the analysis runs the War Room shows the
                  calculator's own trade value (`valueSummary`), never a
                  YES / NO. */}
              {sides.length === 2 ? (
                <TradeWarRoom
                  request={warRoomRequest}
                  leagueKey={selectedLeagueKey || ""}
                  useTeamContext={useTeamContext}
                  onTeamContextChange={setUseTeamContext}
                  overrideCount={Object.keys(valueOverrides).length}
                  teamName={selectedTeam?.name || ""}
                  sideChoiceNeeded={sideChoiceNeeded}
                  chosenSide={teamSide.basis === "explicit" ? teamSide.side : null}
                  onChooseSide={setExplicitMySide}
                  onDecision={setDecisionSummary}
                  valueSummary={warRoomValueSummary}
                />
              ) : (
                // TC-B / TCM-G09: the decision owner analyses ONE team's side of a
                // two-team trade.  A 3+-team trade gets no YES / NO; the War Room
                // itself says so (`sideCount`) instead of silently disappearing.
                <TradeWarRoom sideCount={sides.length} />
              )}
            </section>

            {/* ── 4. SUPPORTING INTELLIGENCE ───────────────────── */}
            <section
              id="trade-intelligence"
              className={`${styles.layer} ${styles.layerIntel}`}
              aria-labelledby="trade-intelligence-title"
            >
              <h2 id="trade-intelligence-title" className={styles.layerTitle}>
                Supporting intelligence
              </h2>
              {/* TC-D2: one drilldown per question (UX audit §7.1 layer 4).
                  Only the open tab is rendered, so each panel's chunk and
                  request wait for the user -- the contract the folded panels
                  had.  Nothing here computes a value, a band or a verdict. */}
              <TradeIntelTabs
                active={intelTab}
                onChange={setIntelTab}
                panels={{
                  value: () => (
                    <>
                      <TradePackageBreakdown
                        sides={sidesWithOverrides}
                        sideTotals={sideTotals}
                        valueMode={valueMode}
                      />
                      {/* Multi-team flow visual — 3+ sides only; the 2-team
                          meter already makes flow obvious for a 1-on-1 deal. */}
                      {sides.length >= 3 ? (
                        <MultiTradeFlow
                          sides={sides}
                          sideFlowAssets={sideFlowAssets}
                          valueMode={valueMode}
                          settings={settings}
                        />
                      ) : null}
                      {/* ── SECOND OPINIONS ──────────────────────────────
                          Panels that each re-answer "is this fair?" in a
                          different currency: the per-vendor breakdown and BDVM
                          fundamentals.  Each is worth having and none is the
                          verdict, so they stay folded until asked for. */}
                      <CollapsiblePanel
                        title="Second opinions"
                        subtitle="Per-source breakdown and fundamentals"
                        defaultCollapsed
                        mountCollapsedChildren={false}
                      >
                        {/* No valueMode: Second Opinions owns its own comparison
                            basis and must not inherit a display toggle. */}
                        <TradeSourceBreakdown
                          sides={sides}
                          settings={settings}
                          hasOverrides={Object.keys(valueOverrides).length > 0}
                        />
                        <BdvmTradePanel sides={sides} leagueKey={selectedLeagueKey} />
                      </CollapsiblePanel>
                    </>
                  ),
                  // TCM-H13: the one roster-consequence surface beside the
                  // decision -- Simulate impact lives here, not in the toolbar.
                  roster: () => (
                    <>
                      {sides.length !== 2 ? (
                        <p className={styles.intelLead}>
                          Roster impact covers two-team trades; this {sides.length}-team trade
                          has none.
                        </p>
                      ) : !selectedTeam ? (
                        <p className={styles.intelLead}>
                          Pick your team to see what this trade does to your roster.
                        </p>
                      ) : (
                        <>
                          <p className={styles.intelLead}>
                            The roster answer that counts toward the decision is in the{" "}
                            <a href="#trade-decision" className={styles.inlineLink}>
                              Trade War Room
                            </a>
                            . Simulate impact applies this trade to your roster and shows the
                            full before / after.
                          </p>
                          <span>
                            <Button
                              variant="primary"
                              onClick={runSimulateTrade}
                              disabled={simLoading || !hasAssets || !warRoomRequest}
                              loading={simLoading}
                              title="Apply this trade to your roster and see before/after roster value"
                            >
                              Simulate impact
                            </Button>
                          </span>
                        </>
                      )}
                      {/* Gated here, not only inside the panel: rendering the
                          lazy component is what requests its chunk.  Shown only
                          for the trade, team and league it answered. */}
                      {(simResult || simError) && simResultSignature === simSignature ? (
                        <SimulationPanel
                          id="trade-simulation"
                          simResult={simResult}
                          simError={simError}
                          selectedTeam={selectedTeam}
                          onReset={resetSim}
                          onRetry={runSimulateTrade}
                          overrideCount={Object.keys(valueOverrides).length}
                        />
                      ) : null}
                    </>
                  ),
                  season: () => (
                    <RosTradeFitPanel
                      sides={sides}
                      settings={settings}
                      leagueKey={selectedLeagueKey || ""}
                    />
                  ),
                  // Recorded real trades: mounted only while this tab is open,
                  // so a closed tab never refetches on a trade edit.
                  market: () => (
                    <RecentRealTrades sides={sides} leagueKey={selectedLeagueKey || ""} />
                  ),
                  reasoning: () => (
                    <TradeDecisionReasoning
                      decision={
                        sides.length === 2 && decisionSummary.status === "ok"
                          ? decisionSummary.decision
                          : null
                      }
                      emptyText={
                        sides.length !== 2
                          ? SUMMARY_STATE_TEXT.multi
                          : SUMMARY_STATE_TEXT[
                              decisionSummary.status === "updating"
                                ? "loading"
                                : decisionSummary.status
                            ] || SUMMARY_STATE_TEXT.idle
                      }
                    />
                  ),
                }}
              />
            </section>

            {/* ── 5. IDEAS & TOOLS ─────────────────────────────── */}
            <section
              id="trade-tools"
              className={`${styles.layer} ${styles.layerTools}`}
              aria-labelledby="trade-tools-title"
            >
              <h2 id="trade-tools-title" className={styles.layerTitle}>
                Ideas &amp; tools
              </h2>
              {hasAssets ? (
                <TradeNextActions
                  sides={sides}
                  leagueKey={selectedLeagueKey || ""}
                  myTeam={selectedTeam?.name || ""}
                  mySideIdx={sides.length === 2 ? teamSide.side : null}
                  sideTeamNames={sideTeamNames}
                  evalState={evalState.state}
                  isFair={sides.length === 2 ? pwGapIsFair : multiGapIsFair}
                  balancerSideLabel={balancerSideLabel}
                  balancersPending={balancersPending}
                  decisionRunId={
                    sides.length === 2 && decisionSummary.status === "ok"
                      ? decisionSummary.runId || null
                      : null
                  }
                />
              ) : null}

              {/* The proactive rail (one top idea per category) sits with
                  the desk it summarises since TC-D — it used to precede the
                  builder (UX audit §7.1, layer 5).  Three-state slot, same
                  pattern as the dashboard's TopSignalsRail: RESERVE while the
                  suggestions fetch is pending, RENDER once it lands, COLLAPSE
                  if it resolves empty — absence-then-presence above the
                  builder was 79% of /trade's 0.139 CLS. */}
              {!loading && !error && !leagueMismatch && suggestions?.totalSuggestions > 0 ? (
                <ProactiveSuggestionsRail
                  suggestions={suggestions}
                  onApply={(s) => {
                    applySuggestion(s);
                    window.scrollTo({ top: 0, behavior: "smooth" });
                  }}
                />
              ) : !loading && !error && !leagueMismatch && suggestionsPending ? (
                <SuggestionsRailPlaceholder />
              ) : null}

              <SuggestionsDesk
                sleeperTeams={sleeperTeams}
                selectedTeamIdx={selectedTeamIdx}
                onSelectTeam={selectTeam}
                leagueRosters={leagueRosters}
                rosterInput={rosterInput}
                onRosterInputChange={(v) => {
                  setRosterInput(v);
                  setSelectedTeamIdx(-1);
                  setLeagueRosters(null);
                }}
                onFetch={fetchSuggestions}
                loading={suggestionsLoading}
                error={suggestionsError}
                suggestions={suggestions}
                suggestionTab={suggestionTab}
                onTabChange={setSuggestionTab}
                suggestionCounts={suggestionCounts}
                rosterCount={parseRoster().length}
                onApply={applySuggestion}
              />
            </section>
          </div>

          {/* Sticky verdict tray — 2-team only, keeps the verdict in
              view while the user scrolls the side ledgers.  TC-D: the
              persistent verdict bar below 1024 px (the desktop workspace
              keeps the result and decision in its sticky column instead);
              it carries the War Room's decision word and links to it. */}
          {sides.length === 2 ? (
            <div className="trade-sticky-tray">
              <div className="trade-tray-main">
                <div>
                  <div className="label">Side A</div>
                  <div className="value">
                    {Math.round(pwTotalA).toLocaleString()}
                  </div>
                </div>
                <a
                  href="#trade-decision"
                  className={styles.trayDecisionLink}
                  style={{ flex: 1, maxWidth: 220 }}
                >
                  {/* Verdict bar: marker position is layout math from
                      verdictBarPosition(), the same helper the pre-R4
                      tray used. */}
                  {tradeIsEmpty || tradeIsIncomplete ? null : (
                    <div className={styles.verdictTrack} aria-hidden="true">
                      <div className={styles.verdictField} />
                      <div
                        className={`${styles.verdictMarker} ${
                          colorFromGap(pwGap, pwLarger) === "green"
                            ? styles.verdictMarkerPositive
                            : colorFromGap(pwGap, pwLarger) === "red"
                              ? styles.verdictMarkerNegative
                              : ""
                        }`}
                        style={{
                          "--marker-pos": `${verdictBarPosition(pwGap)}%`,
                        }}
                      />
                    </div>
                  )}
                  {/* Same vocabulary as the meter's badge — one set of
                      verdict words per page (meterVerdict, the ONE
                      fairness-band owner, lib/fairness-bands.js).
                      No band on an empty trade (UX audit P0-6). */}
                  {tradeIsEmpty ? (
                    <div className="verdict" data-trade-state={evalState.state}>
                      Add assets to compare
                    </div>
                  ) : tradeIsIncomplete ? (
                    <div className="verdict" data-trade-state={evalState.state}>
                      Incomplete — {evalState.unpriced.length} unpriced, no verdict
                    </div>
                  ) : (
                    <>
                      <div
                        className={`verdict ${colorFromGap(pwGap, pwLarger)}`}
                        data-trade-gap={pwGap}
                      >
                        {meterVerdict(pwGap, pwLarger).label}
                        {pctGap > 0 ? ` (${pctGap}%)` : ""}
                      </div>
                      <div className={styles.controlsNote}>
                        Gap {Math.round(pwGap).toLocaleString()}
                        {trayDecisionText ? (
                          <span data-testid="tray-decision"> · {trayDecisionText}</span>
                        ) : null}
                      </div>
                    </>
                  )}
                </a>
                <div>
                  <div className="label">Side B</div>
                  <div className="value">
                    {Math.round(pwTotalB).toLocaleString()}
                  </div>
                </div>
              </div>
            </div>
          ) : (
            // TC-D2: the persistent summary for a 3+-team trade (the multi-team
            // meter's own net flows and band; no YES / NO exists for it).
            <MultiTeamSummaryBar sides={sides} summary={multiSummary} evalState={evalState} />
          )}
        </>
      ) : null}
    </div>
  );
}
