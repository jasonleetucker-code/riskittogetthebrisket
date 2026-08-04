"use client";

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import dynamic from "next/dynamic";
import { useDynastyData } from "@/components/useDynastyData";
import {
  VALUE_MODES,
  STORAGE_KEY,
  verdictFromGap,
  colorFromGap,
  verdictBarPosition,
  adjustedSideTotals,
  multiAdjustedSideTotals,
  sideTotal,
  effectiveValue,
  findBalancers,
  parsePickToken,
  resolvePickRow,
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
} from "@/lib/trade-logic";
import {
  parsePickAsset,
  pickAuctionDollars,
  buildSlotDollarGrid,
  buildLeagueStacks,
} from "@/lib/pick-stack";
import { valuationBasisLabel, valuationBasisOf } from "@/lib/dynasty-data";
import { useSettings } from "@/components/useSettings";
import { useApp } from "@/components/AppShell";
import { buildShareUrl, parseShareParam } from "@/lib/trade-share";
import { useTradeSimulator } from "@/components/useTradeSimulator";
import { useTeam } from "@/components/useTeam";
import SharedTradeMeter from "@/components/trade/TradeMeter";
import TradeFairnessExplanation from "@/components/trade/TradeFairnessExplanation";
import {
  Banner,
  Button,
  CollapsiblePanel,
  InfoTip,
  Panel,
  PageHeader,
  SegmentedControl,
  Select,
  SkeletonTable,
} from "@/components/ds";
import {
  KtcImportPanel,
  MobileQuickAddBar,
  PickTeamSelectors,
  ProactiveSuggestionsRail,
  SuggestionsRailPlaceholder,
  SideCard,
  SimulationPanel,
  SuggestionsDesk,
  SUGG_TYPES,
} from "./trade-sections";
import { withValuationMode } from "@/lib/valuation-mode";
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
const dyn = (loader) => dynamic(loader, { ssr: false });
const TradeSourceBreakdown = dyn(() => import("@/components/trade/TradeSourceBreakdown"));
const RosTradeFitPanel = dyn(() => import("@/components/RosTradeFitPanel"));
const BdvmTradePanel = dyn(() => import("@/components/BdvmTradePanel"));
const TradeDeltaHistogram = dyn(() => import("@/components/graphs/TradeDeltaHistogram"));
const MultiTradeFlow = dyn(() => import("@/components/graphs/MultiTradeFlow"));

export default function TradePage() {
  const { loading, error, rows, rawData } = useDynastyData();
  const {
    settings,
    hydrated: settingsHydrated,
    update: updateSetting,
  } = useSettings();
  const { openPlayerPopup, registerAddToTrade } = useApp();
  const [valueMode, setValueMode] = useState("full");

  // Multi-team state: array of { id, label, assets }
  const [sides, setSides] = useState([createSide(0), createSide(1)]);
  const [activeSide, setActiveSide] = useState(0); // index into sides
  // Per-side inline search: each side renders its own search input, so
  // adding a player is one tap away — no overlay, no "+ Add" button.
  // ``sideQueries[i]`` holds side i's current input string;
  // ``focusedSideIdx`` controls which side's dropdown is visible.
  const [sideQueries, setSideQueries] = useState({});
  const [focusedSideIdx, setFocusedSideIdx] = useState(null);
  const sideInputRefs = useRef({});
  const [hydrated, setHydrated] = useState(false);

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
  const [exportStatus, setExportStatus] = useState("");

  // Share + simulator state.
  const [shareStatus, setShareStatus] = useState("");
  const [shareHydrated, setShareHydrated] = useState(false);
  const {
    simulate: simulateTrade,
    result: simResult,
    loading: simLoading,
    error: simError,
    reset: resetSim,
  } = useTradeSimulator();
  // useTeam is already league-aware: ``selectedTeam`` resolves
  // against the active league, ``idpEnabled`` comes from the
  // league config, ``leagueMismatch`` flags the data-not-ready
  // state.  We use all three below to render the right picker
  // options, auto-attach the right league to trade suggestions,
  // and show a clear "data not ready" banner when needed.
  const {
    selectedTeam,
    idpEnabled,
    leagueMismatch,
    selectedLeagueKey,
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
      for (const pickLabel of team.picks || []) {
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

  // ── Stack-aware trade verdicts ───────────────────────────────────────
  // A pick's worth depends on the receiving team's existing draft
  // capital.  We pull the league's draft-capital ($1200) board, value
  // every pick in the trade (tier picks = slot-average — see
  // lib/pick-stack), recompute zero-sum effective auction power
  // before/after the routed swap, and fold each team's change in
  // premium into its side total.  Picks REQUIRE a resolved team on
  // every side they touch; until then the verdict falls back to pure
  // board value with a prompt.
  const [draftCapital, setDraftCapital] = useState(null);
  useEffect(() => {
    let alive = true;
    // Scope to the page's own league so the stack math never mixes a
    // switched active league's teams/picks with another league's
    // draft-capital board (matches how useDynastyData scopes its
    // contract fetch).
    const qs = selectedLeagueKey
      ? `?leagueKey=${encodeURIComponent(selectedLeagueKey)}`
      : "";
    setDraftCapital(null);
    fetch(`/api/draft-capital${qs}`)
      .then((r) => (r.ok ? r.json() : null))
      .then((d) => {
        if (alive && d && Array.isArray(d.picks)) setDraftCapital(d);
      })
      .catch(() => {});
    return () => {
      alive = false;
    };
  }, [selectedLeagueKey]);

  const currentDraftYear = useMemo(() => {
    const fromContract = Number(rawData?.currentDraftYear);
    if (Number.isFinite(fromContract) && fromContract > 2000)
      return fromContract;
    const fromDC = parseInt(String(draftCapital?.season || ""), 10);
    return Number.isFinite(fromDC) ? fromDC : null;
  }, [rawData, draftCapital]);

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
          const dest = s.destinations?.[a.name];
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
          const nextMode = String(restored.valueMode || "full");
          if (VALUE_MODES.some((m) => m.key === nextMode))
            setValueMode(nextMode);
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
    try {
      const neededSides = Math.max(2, state.sides.length);
      const ensureSides = (prev) => {
        let next = prev;
        while (next.length < neededSides)
          next = [...next, createSide(next.length)];
        return next;
      };
      setSides((prev) => {
        const base = ensureSides(prev);
        return base.map((side, i) => {
          const incoming = state.sides[i];
          if (!incoming) return { ...side, assets: [], destinations: {} };
          const resolved = [];
          const seen = new Set();
          for (const name of incoming.players || []) {
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
            if (!row || seen.has(row.name)) continue;
            seen.add(row.name);
            resolved.push(row);
          }
          const nextDestinations = {};
          if (base.length > 2) {
            for (const row of resolved) {
              nextDestinations[row.name] = defaultDestination(i, base.length);
            }
          }
          return { ...side, assets: resolved, destinations: nextDestinations };
        });
      });
      setValueOverrides({});
      setShareStatus("Loaded shared trade from link.");
    } catch {
      setShareStatus("Share link was malformed — ignored.");
    } finally {
      setShareHydrated(true);
    }
  }, [hydrated, shareHydrated, rows, rowByName]);

  // Apply per-player value overrides to the sides for all value calculations.
  // Only modifies the asset rows that have an override; everything else passes through.
  const sidesWithOverrides = useMemo(() => {
    if (!Object.keys(valueOverrides).length) return sides;
    return sides.map((s) => ({
      ...s,
      assets: s.assets.map((r) => {
        const ov = valueOverrides[r.name];
        if (ov == null) return r;
        return { ...r, customValue: ov };
      }),
    }));
  }, [sides, valueOverrides]);

  // League stacks + routed pick-$ moves for the effective-power lens.
  // null whenever the lens can't / shouldn't apply (no draft data, no
  // picks, or the team gate is unmet) → verdict stays pure board value.
  const stackContext = useMemo(() => {
    if (!draftCapital || !sleeperTeams || !tradeHasPicks || stackGateUnmet) {
      return null;
    }
    // Year-keyed slot-$ grid (handles the Sleeper-derived payload's two
    // seasons with colliding round/slot pairs — see buildSlotDollarGrid).
    const slotGrid = buildSlotDollarGrid(draftCapital);
    const teamsPerRound = Number(draftCapital.numTeams) || 12;
    const ctx = {
      slotGrid,
      teamsPerRound,
      currentDraftYear,
      boardValueByName,
    };
    // Future-year picks per team from Sleeper ownership.  Exclude every
    // year the payload already accounts for in teamTotals so nothing is
    // double-counted: the workbook path covers only the upcoming draft,
    // but the Sleeper-derived (non-default-league) path covers BOTH the
    // current and next season.  ``coveredPickYears`` states this
    // explicitly; fall back to [currentDraftYear] if it's absent.
    const coveredYears = new Set(
      (Array.isArray(draftCapital.coveredPickYears) &&
      draftCapital.coveredPickYears.length
        ? draftCapital.coveredPickYears
        : [currentDraftYear]
      )
        .map(Number)
        .filter((y) => Number.isFinite(y)),
    );
    const pickRowsByTeam = {};
    for (const team of sleeperTeams) {
      const out = [];
      for (const label of team.picks || []) {
        const row = resolvePickRow(label, rowByLowerName, pickAliases);
        if (!row) continue;
        const parsed = parsePickAsset(row.name);
        if (!parsed) continue;
        if (coveredYears.has(parsed.year)) continue;
        out.push(row.name);
      }
      if (out.length) pickRowsByTeam[team.name] = out;
    }
    const leagueStacks = buildLeagueStacks(draftCapital, pickRowsByTeam, ctx);

    const n = sidesWithOverrides.length;
    const moves = [];
    sidesWithOverrides.forEach((s, i) => {
      for (const a of s.assets || []) {
        if (a.assetClass !== "pick") continue;
        let to;
        if (n === 2) {
          to = 1 - i;
        } else {
          const dest = s.destinations?.[a.name];
          to = Number.isInteger(dest) ? dest : defaultDestination(i, n);
        }
        if (to == null || to === i || to < 0 || to >= n) continue;
        moves.push({
          from: i,
          to,
          dollars: pickAuctionDollars(a.name, ctx),
          board: effectiveValue(a, valueMode, settings),
        });
      }
    });
    if (moves.length === 0) return null;
    return { sideTeams: sideTeamNames, leagueStacks, moves };
  }, [
    draftCapital,
    sleeperTeams,
    tradeHasPicks,
    stackGateUnmet,
    currentDraftYear,
    boardValueByName,
    rowByLowerName,
    pickAliases,
    sidesWithOverrides,
    sideTeamNames,
    valueMode,
    settings,
  ]);

  // ── Computed totals for all sides ────────────────────────────────────
  // Both 2-team and N-team trades use the KTC-style Value Adjustment.
  // For N ≥ 3, each side's VA is computed against the merged opposition
  // (every other side's assets flattened) — see
  // ``computeMultiSideAdjustments`` in trade-logic.js.  ``stackContext``
  // (when present) additionally folds the draft-capital stack effect
  // into each side's adjusted total.
  const sideTotals = useMemo(() => {
    if (sidesWithOverrides.length === 2) {
      const [a, b] = adjustedSideTotals(
        sidesWithOverrides[0].assets,
        sidesWithOverrides[1].assets,
        valueMode,
        settings,
        stackContext,
      );
      return [a, b];
    }
    if (sidesWithOverrides.length > 2) {
      return multiAdjustedSideTotals(
        sidesWithOverrides.map((s) => s.assets),
        valueMode,
        settings,
        stackContext,
      );
    }
    return sidesWithOverrides.map((s) => {
      const raw = sideTotal(s.assets, valueMode, settings);
      return { raw, adjustment: 0, stackAdjustment: 0, adjusted: raw };
    });
  }, [sidesWithOverrides, valueMode, settings, stackContext]);

  // Per-side flow totals: given / received / net.  In 2-team trades
  // the destinations map is ignored (assets implicitly go to the other
  // side).  In 3+-team trades each asset's destination drives the NET
  // flow, which is what the multi-team fairness bar renders.
  const sideFlows = useMemo(
    () =>
      computeSideFlows(sidesWithOverrides, valueMode, settings, stackContext),
    [sidesWithOverrides, valueMode, settings, stackContext],
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
  const mySideIdx = useMemo(() => {
    if (!selectedTeam) return -1;
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
  }, [sides, selectedTeam, teamRosterNames]);

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
  const balancers = useMemo(() => {
    if (sides.length !== 2) return { list: [], teamName: null };
    if (Math.abs(pwGap) < 350) return { list: [], teamName: null };
    const allInTrade = new Set(
      sides.flatMap((s) => s.assets.map((a) => a.name)),
    );
    // Behind side = the one whose total is LOWER.
    const behindSideIdx = pwGap > 0 ? 1 : 0;
    const behindSide = sides[behindSideIdx];
    const behindTeam = inferTeamForSide(behindSide);
    let pool;
    let teamName = null;
    const is2026Pick = (r) => r.assetClass === "pick" && /^2026\b/.test(r.name);
    if (behindTeam) {
      const roster = teamRosterNames(behindTeam);
      pool = rows.filter(
        (r) => roster.has(r.name) && !allInTrade.has(r.name) && !is2026Pick(r),
      );
      teamName = behindTeam.name || null;
    }
    // Fallback when no team can be inferred (or the inferred team
    // has nothing left after subtracting what's already in the
    // trade).  Preserves existing behaviour when Sleeper data is
    // unavailable.
    if (!pool || pool.length === 0) {
      pool = rows.filter((r) => !allInTrade.has(r.name) && !is2026Pick(r));
      teamName = null;
    }
    const list = findBalancers(pwGap, pool, valueMode);
    return { list, teamName };
  }, [pwGap, rows, sides, valueMode, inferTeamForSide, teamRosterNames]);

  // For 3+ teams, find balancers for the team getting the best deal
  // (they should add more to their give to even things out).  Uses
  // the destination-aware NET flow (received − given) so the target
  // is whoever profited most after each asset was routed to its
  // chosen destination.  Falling back to the raw total index would
  // pick whoever put the fewest pieces on the table — a different
  // question entirely.
  const multiBalancers = useMemo(() => {
    if (sides.length <= 2) return null;
    const nets = sideFlows.map((f) => f.net);
    const worstIdx = nets.indexOf(Math.min(...nets)); // most negative = overpaying
    const bestIdx = nets.indexOf(Math.max(...nets)); // most positive = getting a deal
    const gap = nets[bestIdx] - nets[worstIdx];
    if (gap < 350) return null;
    const allInTrade = new Set(
      sides.flatMap((s) => s.assets.map((a) => a.name)),
    );
    // Panel renders on the side that needs to GIVE more (the one with
    // the best deal right now).  Filter the suggestion pool to that
    // side's Sleeper team so the "add more" list is players they
    // actually own.  Same fallback to full pool when inference fails.
    const underpayingSide = sides[bestIdx];
    const underpayingTeam = inferTeamForSide(underpayingSide);
    let pool;
    let teamName = null;
    const is2026Pick = (r) => r.assetClass === "pick" && /^2026\b/.test(r.name);
    if (underpayingTeam) {
      const roster = teamRosterNames(underpayingTeam);
      pool = rows.filter(
        (r) => roster.has(r.name) && !allInTrade.has(r.name) && !is2026Pick(r),
      );
      teamName = underpayingTeam.name || null;
    }
    if (!pool || pool.length === 0) {
      pool = rows.filter((r) => !allInTrade.has(r.name) && !is2026Pick(r));
      teamName = null;
    }
    const suggestions = findBalancers(gap, pool, valueMode);
    return {
      overpayingIdx: worstIdx,
      underpayingIdx: bestIdx, // panel rendered on the side that needs to give more
      gap,
      suggestions,
      teamName,
    };
  }, [sides, sideFlows, rows, valueMode, inferTeamForSide, teamRosterNames]);

  // All assets currently in any side (for picker exclusion)
  const allTradeNames = useMemo(() => {
    return new Set(sides.flatMap((s) => s.assets.map((r) => r.name)));
  }, [sides]);

  // Inline search helper: returns up to 5 best matches for the given
  // query, excluding anything already in the trade.  Sorted by
  // consensus rank ascending so the top hits are the most relevant
  // dynasty assets first — matches the KTC trade-calculator UX.
  const searchAssets = useCallback(
    (query) => {
      const q = (query || "").trim().toLowerCase();
      if (!q) return [];
      const list = rows.filter(
        (r) =>
          !allTradeNames.has(r.name) &&
          !(r.assetClass === "pick" && /^2026\b/.test(r.name)) &&
          r.name.toLowerCase().includes(q),
      );
      list.sort(
        (a, b) =>
          (a.blendedSourceRank ?? Infinity) - (b.blendedSourceRank ?? Infinity),
      );
      return list.slice(0, 5);
    },
    [rows, allTradeNames],
  );

  // ── Side management ─────────────────────────────────────────────────
  function addToSide(row, sideIdx) {
    if (!row) return;
    // Check all sides for duplicates
    if (allTradeNames.has(row.name)) return;
    setSides((prev) =>
      prev.map((s, i) => {
        if (i !== sideIdx) return s;
        if (s.assets.some((r) => r.name === row.name)) return s;
        // 3+-team trades need an explicit destination per asset so the
        // fairness bar can compute each side's NET flow.  Seed the
        // default (next side, circular) whenever we're adding to a
        // multi-side trade.  2-team trades leave destinations empty —
        // ``computeSideFlows`` handles the implicit "other side" case.
        const nextDestinations = { ...(s.destinations || {}) };
        if (prev.length > 2) {
          nextDestinations[row.name] = defaultDestination(i, prev.length);
        }
        return {
          ...s,
          assets: [...s.assets, row],
          destinations: nextDestinations,
        };
      }),
    );
  }

  function setAssetDestination(sideIdx, assetName, destIdx) {
    setSides((prev) =>
      prev.map((s, i) => {
        if (i !== sideIdx) return s;
        const next = { ...(s.destinations || {}) };
        next[assetName] = Number(destIdx);
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

  function removeFromSide(name, sideIdx) {
    setSides((prev) =>
      prev.map((s, i) => {
        if (i !== sideIdx) return s;
        const nextDestinations = { ...(s.destinations || {}) };
        delete nextDestinations[name];
        return {
          ...s,
          assets: s.assets.filter((r) => r.name !== name),
          destinations: nextDestinations,
        };
      }),
    );
    clearValueOverride(name);
  }

  function clearTrade() {
    setSides((prev) =>
      prev.map((s) => ({ ...s, assets: [], destinations: {} })),
    );
    setValueOverrides({});
  }

  function swapSides() {
    if (sides.length === 2) {
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
          if (nextDest[asset.name] == null) {
            nextDest[asset.name] = defaultDestination(i, newCount);
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
      if (!res.ok || data?.ok === false) {
        setKtcImportError(data?.error || `HTTP ${res.status}`);
        return;
      }

      const sideOneEntries = Array.isArray(data.sideOne) ? data.sideOne : [];
      const sideTwoEntries = Array.isArray(data.sideTwo) ? data.sideTwo : [];
      const unresolvedOne = data?.unresolved?.sideOne || [];
      const unresolvedTwo = data?.unresolved?.sideTwo || [];

      // Resolve each KTC-returned name → our canonical row.  Our
      // board and KTC share pick-name shapes ("2026 Early 1st") and
      // most player names verbatim, so a direct rowByName hit
      // covers the common case.  For near-matches we try a ladder
      // of increasingly permissive lookups (case-insensitive,
      // whitespace-normalized, suffix-stripped) before giving up —
      // historically this silently dropped picks + "Jr./III"
      // variants.  Residual misses are surfaced to the user.
      const _normalize = (s) =>
        String(s || "")
          .toLowerCase()
          .replace(/[.']/g, "")
          .replace(/\s+/g, " ")
          .replace(/\s+(jr|sr|ii|iii|iv|v)$/i, "")
          .trim();
      const lowerIndex = new Map();
      const normIndex = new Map();
      for (const r of rows) {
        if (!r?.name) continue;
        const low = r.name.toLowerCase();
        if (!lowerIndex.has(low)) lowerIndex.set(low, r);
        const norm = _normalize(r.name);
        if (!normIndex.has(norm)) normIndex.set(norm, r);
      }
      const resolveBatch = (entries) => {
        const found = [];
        const missing = [];
        for (const entry of entries) {
          // 1. Exact case match — fast path, covers 99%.
          let row = rowByName.get(entry.name);
          // 2. Case-insensitive match.
          if (!row)
            row = lowerIndex.get(String(entry.name || "").toLowerCase());
          // 3. Normalized (punctuation / whitespace / suffix-stripped).
          if (!row) row = normIndex.get(_normalize(entry.name));
          // 4. Pick token fallback — KTC's pick labels ("2026 1.09",
          //    "2027 Mid 1st") use a different shape than our
          //    canonical row names ("2026 Pick 1.09").  Walk the
          //    same ``resolvePickRow`` resolver league-analysis +
          //    the share-URL hydrator use so picks from KTC URLs
          //    actually load instead of silently dropping.
          if (!row && parsePickToken(entry.name)) {
            row = resolvePickRow(entry.name, rowByLowerName, pickAliases);
          }
          if (row) found.push(row);
          else missing.push(entry.name);
        }
        return { found, missing };
      };
      const one = resolveBatch(sideOneEntries);
      const two = resolveBatch(sideTwoEntries);

      // Replace sides A and B in place, dedup per-side and across
      // sides (addToSide normally does this — we mirror that guard
      // here since we're bypassing it for a bulk set).
      const seen = new Set();
      const clean = (rowsIn) => {
        const out = [];
        for (const r of rowsIn) {
          if (!r || seen.has(r.name)) continue;
          seen.add(r.name);
          out.push(r);
        }
        return out;
      };
      const cleanedOne = clean(one.found);
      const cleanedTwo = clean(two.found);

      setSides((prev) =>
        prev.map((s, i) => {
          if (i !== 0 && i !== 1) return s; // leave 3rd+ sides alone
          const replacement = i === 0 ? cleanedOne : cleanedTwo;
          // Seed default destinations for the newly-loaded assets when
          // we're in a 3+-team trade; 2-team trades ignore the map.
          // Old destinations referencing assets that aren't in the new
          // set are dropped so we don't accumulate stale routing.
          const nextDestinations = {};
          if (prev.length > 2) {
            for (const asset of replacement) {
              nextDestinations[asset.name] = defaultDestination(i, prev.length);
            }
          }
          return { ...s, assets: replacement, destinations: nextDestinations };
        }),
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
      setKtcImportError(err?.message || "Import failed");
    } finally {
      setKtcImportBusy(false);
    }
  }, [ktcImportUrl, rowByName]);

  const exportKtcUrl = useCallback(async () => {
    setExportStatus("");
    const sideOne = (sides[0]?.assets || []).map((r) => r.name);
    const sideTwo = (sides[1]?.assets || []).map((r) => r.name);
    if (!sideOne.length && !sideTwo.length) {
      setExportStatus("Nothing to export.");
      return;
    }
    try {
      const res = await fetch("/api/trade/export-ktc", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ sideOne, sideTwo }),
        cache: "no-store",
      });
      const data = await res.json();
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
        sides: sides.map((s) => ({
          name: s.label ? `Side ${s.label}` : "",
          players: (s.assets || []).map((a) => a.name),
        })),
      };
      const url = buildShareUrl(payload);
      if (navigator?.clipboard?.writeText) {
        await navigator.clipboard.writeText(url);
        setShareStatus("Share link copied to clipboard.");
      } else if (typeof window !== "undefined") {
        // Surface the URL so the user can copy it manually.
        window.prompt("Copy this share link:", url);
        setShareStatus("Share link ready.");
      }
    } catch (err) {
      setShareStatus(err?.message || "Could not copy share link.");
    }
  }, [sides]);

  // Pure impact-on-my-roster simulator.  2-team trades only:
  // whichever side matches the user's selected Sleeper team is
  // treated as "sending" (players OUT) and the other side as
  // "receiving" (players IN).  Picks and players are sent as one
  // payload each because the simulator backend treats them
  // identically — both resolve through the same row-index.
  const runSimulateTrade = useCallback(() => {
    if (sides.length !== 2) return;
    if (!selectedTeam) return;
    const myRosterNames = teamRosterNames(selectedTeam);
    // Score each side by how many of its assets the user owns.
    // Whichever side has more matches is "my side" (I'm giving).
    const scores = sides.map((s) => {
      let hits = 0;
      for (const a of s.assets || []) if (myRosterNames.has(a.name)) hits += 1;
      return hits;
    });
    let mySide = scores[0] >= scores[1] ? 0 : 1;
    if (scores[0] === 0 && scores[1] === 0) {
      // Neither side matches — default to "I'm giving side A" so the
      // user can flip via Swap Sides if needed.
      mySide = 0;
    }
    const otherSide = mySide === 0 ? 1 : 0;
    const isPickName = (name) => /\d{4}/.test(String(name || ""));
    const playersOut = [];
    const picksOut = [];
    for (const a of sides[mySide].assets || []) {
      if (isPickName(a.name)) picksOut.push(a.name);
      else playersOut.push(a.name);
    }
    const playersIn = [];
    const picksIn = [];
    for (const a of sides[otherSide].assets || []) {
      if (isPickName(a.name)) picksIn.push(a.name);
      else playersIn.push(a.name);
    }
    simulateTrade({
      teamName: selectedTeam?.name,
      playersIn,
      playersOut,
      picksIn,
      picksOut,
    });
  }, [sides, selectedTeam, teamRosterNames, simulateTrade]);

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
    const picks = (team.picks || []).map((p) => {
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
  useEffect(() => {
    const cancelPending = () => {
      if (proactiveFetchRef.current.timer) {
        clearTimeout(proactiveFetchRef.current.timer);
        proactiveFetchRef.current.timer = null;
      }
      proactiveFetchRef.current.lastBody = null;
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
    // hit "Get Suggestions."
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
    const roster = parseRoster();
    if (roster.length < 3) {
      setSuggestionsError("Enter at least 3 player names to get suggestions.");
      setSuggestionsPending(false);
      return;
    }
    setSuggestionsLoading(true);
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
      const data = await res.json();
      if (!res.ok) {
        setSuggestionsError(data.error || `Server error (${res.status})`);
        return;
      }
      setSuggestions(data);
    } catch (err) {
      setSuggestionsError("Could not reach suggestion service.");
    } finally {
      setSuggestionsLoading(false);
      setSuggestionsPending(false);
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
          out[asset.name] = defaultDestination(sideIdx, sideCount);
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
      sides.length === 2 ? (sideIdx === 0 ? pwGap < -350 : pwGap > 350) : false;
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

  return (
    <main className={`main-shell ${styles.page} trade-page`}>
      <PageHeader
        eyebrow="Trades"
        title="Trade Calculator"
        description="Multi-team trade calculator with live fairness visualization."
        actions={
          <SegmentedControl
            label="Value basis"
            // Unchecked until settings hydrate — see the matching note on
            // /rankings. It matters more here: a trade verdict rendered
            // under a basis label the user did not choose is the single
            // most dangerous thing this page can show.
            value={settingsHydrated ? settings.valuationMode || "market" : null}
            onChange={(v) => updateSetting("valuationMode", v)}
            options={[
              { value: "market", label: "Market" },
              { value: "leagueAdjusted", label: "My league" },
            ]}
          />
        }
      />

      {/* A trade verdict that silently changed basis is the most
          dangerous thing this page can do. Say which board it is on.

          Gated on the CONTRACT, not on `settings.valuationMode`. The
          setting is what the user asked for; the contract is what they
          got, and the two diverge whenever the overlay fetch fails, the
          scrape-version pin refuses, or the server finds no roster
          snapshot. Reading the setting would label a market board
          "league-adjusted" in exactly those cases.

          `valuationBasisOf` also covers the server-composed path
          (custom weights + the lens), which carries no client-applied
          overlay object of its own. */}
      {valuationBasisOf(rawData) === "leagueAdjusted" ? (
        <Banner tone="info" title="Valued on your league's board">
          Picks stay at market value.
          <InfoTip label="your league&apos;s board">
            <p>
              Values and ranks are adjusted for positional scarcity measured
              from this league&apos;s rosters.
            </p>
            <p>
              Draft picks carry no scarcity measurement, so they hold their
              market value while players move around them — which means a
              player-for-pick trade reads differently here than on the market
              board.
            </p>
          </InfoTip>
        </Banner>
      ) : null}

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

      {/* Mobile-only quick-add: the FIRST interactive element a phone
          user reaches, so populating a trade needs no scrolling. */}
      {!loading && !error ? (
        <MobileQuickAddBar
          activeSide={activeSide}
          sides={sides}
          onAddToActiveSide={addToActiveSide}
          searchAssets={searchAssets}
          settings={settings}
          onSetActiveSide={setActiveSide}
        />
      ) : null}

      {/* Three-state slot, same pattern as the dashboard's
          TopSignalsRail: RESERVE while the suggestions fetch is
          pending, RENDER once it lands, COLLAPSE if it resolves empty.
          The rail arrives ~500ms (debounce) + one round-trip after the
          rest of the page renders, so absence-then-presence inserted
          213px + a 16px stack gap ABOVE the trade controls and meter,
          shoving them down 229px — 79% of /trade's 0.139 CLS. */}
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

      {!loading && !error ? (
        <>
          <Panel dense className="trade-controls">
            <div className={styles.controls}>
              <Select
                value={valueMode}
                onChange={(e) => setValueMode(e.target.value)}
                aria-label="Value mode"
              >
                {VALUE_MODES.map((m) => (
                  <option key={m.key} value={m.key}>
                    {m.label}
                  </option>
                ))}
              </Select>
              <Button onClick={swapSides}>
                {sides.length === 2 ? "Swap Sides" : "Rotate Sides"}
              </Button>
              <Button onClick={clearTrade}>Clear Trade</Button>
              {sides.length < MAX_SIDES ? (
                <Button onClick={addTeam}>Add Team</Button>
              ) : null}
              <Button
                onClick={() => {
                  setKtcImportOpen((v) => !v);
                  setKtcImportError("");
                }}
                aria-expanded={ktcImportOpen}
              >
                Import KTC
              </Button>
              <Button onClick={copyShareLink} disabled={!hasAssets}>
                Copy share link
              </Button>
              <Button
                onClick={exportKtcUrl}
                disabled={sides.length !== 2 || !hasAssets}
              >
                Copy KTC URL
              </Button>
              <Button onClick={exportCsv} disabled={!hasAssets}>
                CSV
              </Button>
              <Button onClick={exportJson} disabled={!hasAssets}>
                JSON
              </Button>
              {sides.length === 2 && selectedTeam ? (
                <Button
                  variant="primary"
                  onClick={runSimulateTrade}
                  disabled={simLoading || !hasAssets}
                  loading={simLoading}
                  title={`Apply this trade to ${selectedTeam.name} and see before/after roster value`}
                >
                  Simulate impact
                </Button>
              ) : null}
              {exportStatus ? (
                <span className={styles.controlsNote}>{exportStatus}</span>
              ) : null}
            </div>
          </Panel>

          {shareStatus ? (
            <Banner tone="positive" onDismiss={() => setShareStatus("")}>
              {shareStatus}
            </Banner>
          ) : null}

          <SimulationPanel
            simResult={simResult}
            simError={simError}
            selectedTeam={selectedTeam}
            onReset={resetSim}
          />

          {ktcImportOpen ? (
            <KtcImportPanel
              url={ktcImportUrl}
              onUrlChange={setKtcImportUrl}
              busy={ktcImportBusy}
              error={ktcImportError}
              onSubmit={importKtcTradeUrl}
              onCancel={() => {
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

          {tradeHasPicks && sleeperTeams ? (
            <PickTeamSelectors
              sides={sides}
              sleeperTeams={sleeperTeams}
              sideTeamNames={sideTeamNames}
              stackGateUnmet={stackGateUnmet}
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
                    ? searchAssets(sideQueries[sideIdx] || "")
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
                onAddBalancer={(name, idx) => {
                  const row = rowByName.get(name);
                  if (row) addToSide(row, idx);
                }}
                registerInputRef={(idx, el) => {
                  sideInputRefs.current[idx] = el;
                }}
              />
            ))}
          </div>


          {/* ── VERDICT ──────────────────────────────────────────
              The answer, and the one number this page exists to
              produce. */}
          {/* Fairness verdict + the explanations behind it. */}
          <TradeMeter
            sides={sides}
            sideTotals={sideTotals}
            flows={sideFlows}
            valueMode={valueMode}
            settings={settings}
          />

          {/* Stack-effect transparency — never a silent verdict shift. */}
          {stackContext &&
          sideTotals.some((t) => Math.round(t?.stackAdjustment || 0) !== 0) ? (
            <p
              className={styles.controlsNote}
              title="Change in each team's zero-sum effective auction power from this pick swap, in board-value units. A stack that pulls clear of the field gains; an already-dominant stack saturates."
            >
              Draft-capital stack effect —{" "}
              {sideTotals
                .map((t, i) => {
                  const v = Math.round(t?.stackAdjustment || 0);
                  return `Side ${sides[i]?.label ?? i + 1}: ${v > 0 ? "+" : ""}${v}`;
                })
                .join(" · ")}
            </p>
          ) : null}


          {/* The plain-English reading of the meter above — it explains
              the verdict, so it belongs with it rather than folded away
              among the alternative-currency second opinions. */}
          <TradeFairnessExplanation sides={sides} sideTotals={sideTotals} />

          {/* ── SECOND OPINIONS ──────────────────────────────────
              Panels that each re-answer "is this fair?" in a different
              currency: per-vendor breakdown, rest-of-season fit, BDVM
              fundamentals, and the value-delta chart.  Each
              is worth having and none is the verdict, so they fold
              away by default instead of pushing the builder off
              screen.  Collapsed state is per-panel, so opening the one
              you rely on sticks for the session. */}
          <CollapsiblePanel
            title="Second opinions"
            subtitle="Per-source breakdown, rest-of-season fit, fundamentals and the value split"
            defaultCollapsed
            mountCollapsedChildren={false}
          >
          <TradeSourceBreakdown
            sides={sides}
            settings={settings}
            valueMode={valueMode}
          />
          <RosTradeFitPanel sides={sides} settings={settings} />
          <BdvmTradePanel sides={sides} leagueKey={selectedLeagueKey} />

          {sides.length === 2 ? (
            <Panel>
              <TradeDeltaHistogram
                sides={[
                  {
                    label: `Side ${sides[0]?.label || "A"}`,
                    total: sideTotals[0]?.adjusted || 0,
                  },
                  {
                    label: `Side ${sides[1]?.label || "B"}`,
                    total: sideTotals[1]?.adjusted || 0,
                  },
                ]}
              />
            </Panel>
          ) : null}

          {/* Multi-team flow visual — 3+ sides only; the 2-team meter
              already makes flow obvious for a 1-on-1 deal. */}
          {sides.length >= 3 ? (
            <MultiTradeFlow
              sides={sides}
              sideFlowAssets={sideFlowAssets}
              valueMode={valueMode}
              settings={settings}
            />
          ) : null}

          </CollapsiblePanel>

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

          {/* Sticky verdict tray — 2-team only, keeps the verdict in
              view while the user scrolls the side ledgers. */}
          {sides.length === 2 ? (
            <div className="trade-sticky-tray">
              <div className="trade-tray-main">
                <div>
                  <div className="label">Side A</div>
                  <div className="value">
                    {Math.round(pwTotalA).toLocaleString()}
                  </div>
                </div>
                <div style={{ flex: 1, maxWidth: 220 }}>
                  {/* Verdict bar: marker position is layout math from
                      verdictBarPosition(), the same helper the pre-R4
                      tray used. */}
                  <div className={styles.verdictTrack} aria-hidden="true">
                    <div className={styles.verdictField} />
                    <div
                      className={`${styles.verdictMarker} ${
                        colorFromGap(pwGap) === "green"
                          ? styles.verdictMarkerPositive
                          : colorFromGap(pwGap) === "red"
                            ? styles.verdictMarkerNegative
                            : ""
                      }`}
                      style={{
                        "--marker-pos": `${verdictBarPosition(pwGap)}%`,
                      }}
                    />
                  </div>
                  <div className={`verdict ${colorFromGap(pwGap)}`}>
                    {verdictFromGap(pwGap)}
                    {pctGap > 0 ? ` (${pctGap}%)` : ""}
                  </div>
                  <div className={styles.controlsNote}>
                    Gap {Math.round(pwGap).toLocaleString()}
                  </div>
                </div>
                <div>
                  <div className="label">Side B</div>
                  <div className="value">
                    {Math.round(pwTotalB).toLocaleString()}
                  </div>
                </div>
              </div>
            </div>
          ) : null}
        </>
      ) : null}
    </main>
  );
}
