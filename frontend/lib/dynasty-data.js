// ── RANKINGS — UNIFIED BOARD (materialization only) ──────────────────────────
// This file (frontend/lib/dynasty-data.js) is the canonical frontend home for:
//   • RANKING_SOURCES       — read-only mirror of the backend source registry,
//                             consumed by the rankings/settings/trade pages to
//                             render sortable source columns and toggles.
//   • buildRows()           — pure materialization pass from API contract to
//                             the flat row shape every page renders.
//   • mergeRankingsDelta()  — applies a compact delta payload onto a cached
//                             base contract (see fetchDynastyData).
//   • fetchDynastyData()    — entry point for useDynastyData.  Fetches the
//                             base contract from /api/dynasty-data and, when
//                             the user has customized source weights, POSTs
//                             the override map to /api/rankings/overrides
//                             to merge a delta onto the base.
//
// !! There is NO frontend ranking engine anymore !!
//
// The backend canonical pipeline in ``src/api/data_contract.py`` is the
// single source of truth for every ranking-related field on the row:
// ``canonicalConsensusRank``, ``rankDerivedValue``, ``sourceRanks``,
// ``sourceRankMeta``, ``blendedSourceRank``, ``sourceRankSpread``,
// ``isSingleSource``, ``hasSourceDisagreement``, ``confidenceBucket``,
// ``marketGapDirection``, ``marketGapMagnitude``, ``anomalyFlags``, and
// the derived Hill-curve value.  The frontend reads those fields
// verbatim from the API contract and renders them.  When the user
// customizes source weights, the OVERRIDE endpoint re-runs the same
// ``_compute_unified_rankings()`` on the backend and returns a compact
// delta payload; the delta merge is the ONLY client-side modification
// to ranking fields.
//
// Historically this file carried a JS-side ranking fallback that
// duplicated the backend math as a safety net for stale offline
// payloads.  That fallback was removed when the override path was
// unified through the backend — it was dead code in normal operation
// and a drift hazard.  If ``buildRows`` is ever handed a payload
// with zero backend stamps, it now fails fast (logs an error and
// returns an empty rows array) rather than silently re-computing.
// ─────────────────────────────────────────────────────────────────────────────

const OFFENSE = new Set(["QB", "RB", "WR", "TE"]);
const IDP = new Set(["DL", "DE", "DT", "LB", "DB", "CB", "S", "EDGE"]);
// Positions that may never enter the ranked board or user-facing surfaces.
const UNSUPPORTED = new Set(["OL", "OT", "OG", "C", "G", "T", "LS"]);

// ── Canonical name join key ──────────────────────────────────────────
// Mirrors normalize_player_name() in src/utils/name_clean.py.  Collapses
// punctuation, diacritics, apostrophes, casing, generational suffixes
// (Jr / Sr / II-VI), and adjacent single-letter initials so
// "T.J. Watt", "TJ Watt", and "t.j. watt" all produce "tj watt".
// Exported for any consumer (tests, manual enrichment, dev-tools) that
// needs to reproduce the backend join semantics.
const _SUFFIX_RE = /\b(jr|sr|ii|iii|iv|v|dr)\b\.?/gi;
const _NON_ALNUM_RE = /[^a-z0-9]+/g;

export function normalizePlayerName(name) {
  if (name === null || name === undefined) return "";
  // NFKD-style ASCII fold.
  const folded = String(name)
    .normalize("NFKD")
    .replace(/[\u0300-\u036f]/g, "")
    .toLowerCase()
    .trim()
    .replace(/&/g, " and ");
  let s = folded.replace(_SUFFIX_RE, "");
  s = s.replace(_NON_ALNUM_RE, " ").trim();
  s = s.replace(/\s+/g, " ");
  // Collapse adjacent single-letter initials so "t j watt" → "tj watt".
  const parts = s.split(" ").filter(Boolean);
  const collapsed = [];
  for (let i = 0; i < parts.length; i++) {
    if (parts[i].length === 1 && /[a-z]/.test(parts[i])) {
      let initials = parts[i];
      while (
        i + 1 < parts.length &&
        parts[i + 1].length === 1 &&
        /[a-z]/.test(parts[i + 1])
      ) {
        i += 1;
        initials += parts[i];
      }
      collapsed.push(initials);
    } else {
      collapsed.push(parts[i]);
    }
  }
  return collapsed.join(" ");
}

// IDP position priority. When a Sleeper player is multi-position
// eligible (fantasy_positions array, slash-joined string like "DL/LB",
// or an explicit array input) we collapse to a single canonical family
// using DL > DB > LB. LB is emitted only when the player is
// exclusively LB-eligible — this mirrors the Python helper
// ``src/utils/name_clean.py::resolve_idp_position`` so the frontend
// never disagrees with the backend on position assignment.
export const IDP_PRIORITY = ["DL", "DB", "LB"];

const _NON_IDP_ALIASES = new Set([
  "QB", "RB", "WR", "TE", "K", "P", "PICK",
]);

function _collectIdpFamilies(raw, state) {
  const accept = (token) => {
    if (!token) return;
    const t = String(token).toUpperCase().trim();
    if (!t) return;
    // Split on every separator a multi-position payload might use.
    // Sleeper's fantasy_positions array arrives here already split
    // (via the Array.isArray branch below), but CSV / delta payloads
    // can carry "DL,LB", "DL/LB", "DL|LB", or "DL LB" as a single
    // string. Keep parity with src/utils/name_clean.resolve_idp_position.
    if (/[/,|\s]/.test(t)) {
      t.split(/[/,|\s]+/).forEach(accept);
      return;
    }
    const stripped = t.replace(/\d+$/, "") || t;
    if (["DL", "DE", "DT", "EDGE", "NT"].includes(stripped)) {
      state.found.add("DL");
    } else if (["DB", "CB", "S", "SS", "FS"].includes(stripped)) {
      state.found.add("DB");
    } else if (["LB", "ILB", "OLB", "MLB"].includes(stripped)) {
      state.found.add("LB");
    } else if (_NON_IDP_ALIASES.has(stripped)) {
      state.sawNonIdp = true;
    }
  };
  if (Array.isArray(raw)) raw.forEach(accept);
  else accept(raw);
}

export function resolveIdpPosition(...candidates) {
  const state = { found: new Set(), sawNonIdp: false };
  for (const cand of candidates) {
    _collectIdpFamilies(cand, state);
  }
  for (const fam of IDP_PRIORITY) {
    if (!state.found.has(fam)) continue;
    if (fam === "LB" && state.sawNonIdp) {
      // LB must be exclusive per the product rule; mixed non-IDP
      // context means we refuse to emit LB. Match the Python helper.
      return "";
    }
    return fam;
  }
  return "";
}

export function normalizePos(pos) {
  const idp = resolveIdpPosition(pos);
  if (idp) return idp;
  const p = String(pos || "").toUpperCase();
  if (p === "P") return "K";
  return p;
}

export function classifyPos(pos) {
  const p = normalizePos(pos);
  if (OFFENSE.has(p)) return "offense";
  if (IDP.has(p)) return "idp";
  if (p === "PICK") return "pick";
  if (p === "K" || UNSUPPORTED.has(p)) return "excluded";
  return "other";
}

// Note: The frontend no longer ranks any players.  Position
// eligibility, IDP backbone construction, coverage-weighted blending,
// and the Hill curve all live in ``src/api/data_contract.py``.  The
// backend stamps every rankable row and the frontend materializes
// those stamps verbatim.

export function inferValueBundle(player = {}) {
  const raw = Number(player._rawComposite ?? player._rawMarketValue ?? player._composite ?? 0) || 0;
  // Prefer 1–9999 display value; fall back to internal calibrated value
  const display = Number(player._canonicalDisplayValue ?? 0) || 0;
  const internal = Number(player._finalAdjusted ?? player._composite ?? raw) || raw;
  const full = display || internal;
  return {
    raw: Math.round(raw),
    full: Math.round(full),
  };
}

export function getSiteKeys(data) {
  const sites = Array.isArray(data?.sites) ? data.sites : [];
  return sites.map((s) => String(s?.key || "")).filter(Boolean);
}

// ── Rank precedence helper ────────────────────────────────────────────
// Single source of truth for rank resolution across all frontend surfaces.
// canonicalConsensusRank (backend-authored) wins when present; otherwise
// falls back to computedConsensusRank (sort-order rank assigned in buildRows).
export function resolvedRank(row) {
  return row?.canonicalConsensusRank ?? row?.computedConsensusRank ?? Infinity;
}

// ── Source registry (read-only mirror) ──────────────────────────────
// Mirrors ``_RANKING_SOURCES`` in ``src/api/data_contract.py`` —
// pytest parity check ``tests/api/test_source_registry_parity.py``
// diffs the two registries on every run.  Consumers (rankings page,
// settings, trade page) read this list to enumerate sortable source
// columns, render column labels, and drive per-source toggles.
//
// Every registered source declares `weight: 1.0` so all sources
// contribute equally to the backend's coverage-aware Hill-curve
// blend.  Do NOT diverge the declared weight here from the Python
// registry — the parity test will fail.
//
// Source scope and translation method tokens are string literals
// directly in the object, mirroring the backend constants exactly.
// These are only metadata for UI rendering and display; the frontend
// never acts on the scope — the backend computes every rank.
export const RANKING_SOURCES = [
  {
    // KeepTradeCut is the retail offense market — community trade values
    // scraped from a public-facing trade calculator.  This is what casual
    // trade partners see and anchor on, so it's flagged `isRetail: true`
    // and fed into the market-gap signal as the "retail" side against
    // every other (expert) source.  Mirrors the `is_retail: True` flag
    // on the backend `_RANKING_SOURCES` entry in src/api/data_contract.py.
    key: "ktc",
    displayName: "KeepTradeCut",
    columnLabel: "KTC",
    scope: "overall_offense",
    positionGroup: null,
    depth: null,
    weight: 1.0,
    isBackbone: false,
    isRetail: true,
    // KTC is a standard SF community trade calculator — the default
    // scraped view does NOT bake in TE premium.  The per-row TE boost
    // from `settings.tepMultiplier` (see trade-logic.js::effectiveValue)
    // applies to KTC's contribution on the blended board.
    isTepPremium: false,
  },
  {
    // IDP Trade Calculator's value pool covers both offense (via the
    // site's autocomplete) and IDP in the same 0-9999 scale.  Register
    // under overall_idp (as the IDP backbone) AND overall_offense (as a
    // second opinion for offensive players) — mirrors the backend
    // _RANKING_SOURCES entry in src/api/data_contract.py.  The two
    // scope passes act on disjoint row sets so sourceRanks never
    // collides for the same source key.
    // Weight = 1.0 — IDPTC was previously weighted 2.0 when it was
    // the sole IDP anchor; now that DS SF/IDP + FG SF/IDP are also
    // cross-market anchors, every source gets one equal vote in the
    // live blend.
    key: "idpTradeCalc",
    displayName: "IDP Trade Calculator",
    columnLabel: "IDPTC",
    scope: "overall_idp",
    extraScopes: ["overall_offense"],
    positionGroup: null,
    depth: null,
    weight: 1.0,
    isBackbone: true,
    isRetail: false,
    // IDPTradeCalc's offense board is a standard SF calculator — no
    // TE premium baked in.
    isTepPremium: false,
  },
  {
    // DLF (Dynasty League Football) full-board IDP rankings.  Mirrors
    // the backend `_RANKING_SOURCES` entry in src/api/data_contract.py.
    // 185-player expert consensus; overall_idp scope; not a backbone.
    //
    // IDP-only expert boards (needsSharedMarketTranslation=true) have
    // their raw IDP ordinal rank translated through a *shared-market
    // IDP ladder* built from the backbone source's combined
    // offense+IDP value pool.  Without this translation DLF rank 1
    // would hit the Hill curve as overall rank 1 → value 9999, as if
    // DLF priced both offense and IDP together.  With translation, DLF
    // rank 1 becomes the combined-pool rank of the best IDP in the
    // backbone (typically ~30-50), correctly calibrating DLF against
    // the retail offense market.
    key: "dlfIdp",
    displayName: "Dynasty League Football IDP",
    columnLabel: "DLF IDP",
    scope: "overall_idp",
    positionGroup: null,
    depth: 185,
    weight: 1.0,
    isBackbone: false,
    isRetail: false,
    isTepPremium: false,
    needsSharedMarketTranslation: true,
    excludesRookies: true,
    isRankSignal: true,
  },
  {
    // DLF Dynasty Superflex rankings — offense expert consensus.
    // Curated 6-expert board with Rank / Avg / Pos / Name columns.
    // Includes rookies (unlike DLF IDP).  Mirrors the backend entry
    // in src/api/data_contract.py::_RANKING_SOURCES.
    //
    // Rank-signal: CSV has an explicit Rank column.  The backend
    // converts ranks to synthetic monotonic values for sort purposes;
    // the UI must render sourceOriginalRanks.dlfSf, never the synthetic.
    key: "dlfSf",
    displayName: "Dynasty League Football Superflex",
    columnLabel: "DLF SF",
    scope: "overall_offense",
    positionGroup: null,
    depth: 280,
    weight: 1.0,
    isBackbone: false,
    isRetail: false,
    isRankSignal: true,
    // DLF's dynasty Superflex board is a standard SF consensus — no
    // TE premium.  The CSV columns (Rank / Avg / Pos / Name / 6 expert
    // columns) contain no TEP indicator.  Raw source:
    // dynastyleaguefootball.com/dynasty-rankings/superflex.  The
    // tepMultiplier applies to DLF SF's contribution on the blended
    // board.
    isTepPremium: false,
  },
  {
    // Dynasty Nerds Superflex + TE Premium rankings — scraped inline
    // from the DR_DATA JS constant on dynastynerds.com/dynasty-rankings/sf-tep/.
    // Expert consensus (Rich / Matt / Garret / Jared + community),
    // 294 non-zero players covering QB / RB / WR / TE including rookies.
    // Conceptually mirrors DLF SF; weight normalized to 1.0 alongside
    // every other registered source.  Mirrors the backend
    // `_RANKING_SOURCES` entry in src/api/data_contract.py.
    key: "dynastyNerdsSfTep",
    displayName: "Dynasty Nerds SF-TEP",
    columnLabel: "DN SF-TEP",
    scope: "overall_offense",
    positionGroup: null,
    depth: 300,
    weight: 1.0,
    isBackbone: false,
    isRetail: false,
    isRankSignal: true,
    // Dynasty Nerds SF-TEP IS a TE-premium native board.  The URL
    // slug is literally /dynasty-rankings/sf-tep/ and the DR_DATA
    // inline JSON carries the SFLEXTEP array which already bakes
    // TE premium into each player's rank.  Flagged so the settings
    // UI can show users that this source does not need the
    // tepMultiplier boost on top of its contribution.
    isTepPremium: true,
  },
  {
    // FantasyPros Dynasty Superflex rankings — offense expert consensus
    // scraped from fantasypros.com/nfl/rankings/dynasty-superflex.php
    // via scripts/fetch_fantasypros_offense.py.  Single flat board
    // covering QB/RB/WR/TE.  Mirrors the backend `_RANKING_SOURCES`
    // entry in src/api/data_contract.py.
    //
    // FantasyPros' dynasty superflex board is a standard SF consensus —
    // no TE premium baked in.  The frontend `settings.tepMultiplier`
    // boost applies to its blended contribution.
    key: "fantasyProsSf",
    displayName: "FantasyPros Dynasty Superflex",
    columnLabel: "FP SF",
    scope: "overall_offense",
    positionGroup: null,
    depth: 250,
    weight: 1.0,
    isBackbone: false,
    isRetail: false,
    isRankSignal: true,
    isTepPremium: false,
  },
  {
    // Dynasty Daddy Superflex trade values — crowd-sourced community
    // values fetched from the public JSON API at
    // dynasty-daddy.com/api/v1/player/all/today?market=14 via
    // scripts/fetch_dynasty_daddy.py.  Market 14 is the SF/dynasty
    // format.  ~400+ offensive players (QB/RB/WR/TE) after filtering.
    // Mirrors the backend `_RANKING_SOURCES` entry in
    // src/api/data_contract.py.
    //
    // Dynasty Daddy's SF trade values are standard SF scoring — no
    // TE premium baked in.  The frontend `settings.tepMultiplier`
    // boost applies to its blended contribution.
    key: "dynastyDaddySf",
    displayName: "Dynasty Daddy Superflex",
    columnLabel: "DD",
    scope: "overall_offense",
    extraScopes: [],
    positionGroup: null,
    depth: 320,
    weight: 1.0,
    isBackbone: false,
    isRetail: false,
    isRankSignal: false,
    isTepPremium: false,
    needsSharedMarketTranslation: false,
    excludesRookies: false,
  },
  {
    // FantasyPros Dynasty IDP expert consensus.  Combined IDP page
    // (dynasty-idp.php) is authoritative for cross-position ordering;
    // individual DL/LB/DB pages are used only as depth extension via
    // monotone piecewise-linear anchor curves fit from the overlap
    // (see scripts/fetch_fantasypros_idp.py).  Conceptually mirrors
    // DLF IDP; weight normalized to 1.0 alongside every other
    // registered source.  Mirrors the backend `_RANKING_SOURCES`
    // entry in src/api/data_contract.py.
    key: "fantasyProsIdp",
    displayName: "FantasyPros Dynasty IDP",
    columnLabel: "FP IDP",
    scope: "overall_idp",
    positionGroup: null,
    depth: 100,
    weight: 1.0,
    isBackbone: false,
    isRetail: false,
    isTepPremium: false,
    isRankSignal: true,
    needsSharedMarketTranslation: true,
    excludesRookies: true,
  },
  {
    // Flock Fantasy Dynasty Superflex rankings — expert consensus.
    // Standard SF — no TE premium.  tepMultiplier boost applies.
    key: "flockFantasySf",
    displayName: "Flock Fantasy Superflex",
    columnLabel: "FF",
    scope: "overall_offense",
    extraScopes: [],
    positionGroup: null,
    depth: 370,
    weight: 1.0,
    isBackbone: false,
    isRetail: false,
    isRankSignal: true,
    isTepPremium: false,
    needsSharedMarketTranslation: false,
    excludesRookies: false,
  },
  {
    // FootballGuys Dynasty Rankings — offense half (QB/RB/WR/TE) of
    // the user-managed PDF export.  6-expert consensus; dense within-
    // universe rank produced by scripts/parse_footballguys_pdf.py.
    // Standard SF — tepMultiplier boost applies on top of the blend.
    key: "footballGuysSf",
    displayName: "FootballGuys Dynasty SF",
    columnLabel: "FBG SF",
    scope: "overall_offense",
    extraScopes: [],
    positionGroup: null,
    depth: 500,
    weight: 1.0,
    isBackbone: false,
    isRetail: false,
    isRankSignal: true,
    isTepPremium: false,
    needsSharedMarketTranslation: false,
    excludesRookies: false,
  },
  {
    // FootballGuys Dynasty Rankings — IDP half (DE/DT/LB/CB/S) of the
    // same PDF export.  3-expert IDP consensus; translates through the
    // shared-market IDP ladder.  Includes rookie IDP prospects.
    key: "footballGuysIdp",
    displayName: "FootballGuys Dynasty IDP",
    columnLabel: "FBG IDP",
    scope: "overall_idp",
    extraScopes: [],
    positionGroup: null,
    depth: 400,
    weight: 1.0,
    isBackbone: false,
    isRetail: false,
    isRankSignal: true,
    isTepPremium: false,
    needsSharedMarketTranslation: true,
    excludesRookies: false,
  },
  {
    // Yahoo / Justin Boone Dynasty Trade Value Charts — offense board
    // (QB/RB/WR/TE) scraped monthly from sports.yahoo.com by
    // scripts/fetch_yahoo_boone.py.  The scraper follows Yahoo's 308
    // redirects from prior-month URLs to the newest live article, so
    // the seed URLs auto-resolve to the latest version each run.
    //
    // TE-premium native: the scraper pulls Boone's 2QB column for QBs
    // and his TE Prem. column for TEs, matching our Superflex + TEP
    // league format.  Flagged `isTepPremium: true` so the frontend
    // surfaces a "TEP NATIVE" badge and the global tepMultiplier
    // boost does NOT compound on this source.
    //
    // Value-signal (2026-04-21): the scraper writes Boone's
    // published trade value in ``boone_value`` (0-~141 scale) and the
    // backend blend rescales linearly so Boone's top player
    // contributes 9999.  The ``rank`` column is still preserved and
    // the UI renders Boone's published rank via
    // ``sourceOriginalRanks.yahooBoone``.  `isRankSignal` is false now
    // because the blend no longer uses the rank column as its vote.
    key: "yahooBoone",
    displayName: "Yahoo / Justin Boone SF-TEP",
    columnLabel: "Boone",
    scope: "overall_offense",
    extraScopes: [],
    positionGroup: null,
    depth: 500,
    weight: 1.0,
    isBackbone: false,
    isRetail: false,
    isRankSignal: false,
    isTepPremium: true,
    needsSharedMarketTranslation: false,
    excludesRookies: false,
  },
  {
    // FantasyPros / Pat Fitzmaurice Dynasty Trade Value Chart —
    // monthly offense board covering QB/RB/WR/TE.  Fetched by
    // scripts/fetch_fantasypros_fitzmaurice.py, which resolves the
    // date-rotating article URL, extracts four Datawrapper iframes
    // (one per position), and grabs each chart's dataset.csv.  Per
    // position we pick the league-appropriate value column (SF Value
    // for QB, TEP Value for TE, Trade Value for RB/WR) — so
    // Fitzmaurice's Superflex + TE-Premium native numbers align
    // with our league scoring.  Value-signal: the blend rescales
    // Fitzmaurice's top player (typically a QB at ~101) to 9999.
    key: "fantasyProsFitzmaurice",
    displayName: "FantasyPros / Pat Fitzmaurice SF-TEP",
    columnLabel: "Fitzmaurice",
    scope: "overall_offense",
    extraScopes: [],
    positionGroup: null,
    depth: 350,
    weight: 1.0,
    isBackbone: false,
    isRetail: false,
    isRankSignal: false,
    isTepPremium: true,
    needsSharedMarketTranslation: false,
    excludesRookies: false,
  },
  {
    // DLF Dynasty Rookie Superflex — 6-expert consensus covering the
    // current rookie class only (QB/RB/WR/TE prospects).  The raw
    // rookie-only rank is crosswalked at blend time through a rookie
    // ladder built from KTC's current ranks on offensive rookies, so
    // DLF's #1 rookie inherits KTC's rank-for-top-rookie scale while
    // DLF's ORDERING remains intact.  Synthetic "2026 Pick R.SS" rows
    // appended during CSV enrichment also nudge rookie pick values.
    key: "dlfRookieSf",
    displayName: "Dynasty League Football Rookie SF",
    columnLabel: "DLF RK",
    scope: "overall_offense",
    extraScopes: [],
    positionGroup: null,
    depth: 50,
    weight: 1.0,
    isBackbone: false,
    isRetail: false,
    isRankSignal: true,
    isTepPremium: false,
    needsSharedMarketTranslation: false,
    needsRookieTranslation: true,
    excludesRookies: false,
  },
  {
    // DLF Dynasty Rookie IDP — rookie-only DL/LB/DB prospects.
    // Translated against IDPTC's rookie ladder.  Does NOT stamp onto
    // picks because rookie IDP ranks are not a strong signal for
    // pick-slot value (most rookie drafts prioritize offensive
    // prospects at the top).
    key: "dlfRookieIdp",
    displayName: "Dynasty League Football Rookie IDP",
    columnLabel: "DLF RK-IDP",
    scope: "overall_idp",
    extraScopes: [],
    positionGroup: null,
    depth: 50,
    weight: 1.0,
    isBackbone: false,
    isRetail: false,
    isRankSignal: true,
    isTepPremium: false,
    needsSharedMarketTranslation: false,
    needsRookieTranslation: true,
    excludesRookies: false,
  },
  {
    // DraftSharks offense dynasty board (QB/RB/WR/TE).  The
    // ``fetch_draftsharks.py`` scraper splits DS's single
    // offense-combined DOM by position family into two CSVs, so
    // this is the SF slice only.  Value signal off the ``3D Value +``
    // column; DraftSharks' scoring is standard dynasty (not TE-
    // premium native), so the frontend ``tepMultiplier`` applies.
    key: "draftSharks",
    displayName: "Draft Sharks Dynasty",
    columnLabel: "DS",
    scope: "overall_offense",
    extraScopes: [],
    positionGroup: null,
    depth: 500,
    weight: 1.0,
    isBackbone: false,
    isRetail: false,
    isRankSignal: false,
    isTepPremium: false,
    needsSharedMarketTranslation: false,
    excludesRookies: false,
  },
  {
    // DraftSharks IDP dynasty board (DL/LB/DB).  Mirror of the
    // offense entry — same scraper writes the IDP CSV filtered by
    // position family, with cross-universe ``3D Value +`` preserved
    // (e.g. Carson Schwesinger = 44 as IDP rank 1, not the IDP-
    // only-page rescaled 81).
    key: "draftSharksIdp",
    displayName: "Draft Sharks IDP Dynasty",
    columnLabel: "DS IDP",
    scope: "overall_idp",
    extraScopes: [],
    positionGroup: null,
    depth: 400,
    weight: 1.0,
    isBackbone: false,
    isRetail: false,
    isRankSignal: false,
    isTepPremium: false,
    needsSharedMarketTranslation: false,
    excludesRookies: false,
  },
];

// ── Retail source registry helpers ───────────────────────────────────
// Mirrors `_retail_source_keys()` on the backend.  "Retail" sources are
// flagged in the registry with `isRetail: true` and represent the
// casual/market side of the market-gap signal (today just KTC).  Every
// non-retail registered source forms the "consensus" side.  Adding a
// second retail source (e.g. a future Sleeper trade-values feed) is a
// pure registry change — gap-label rendering, edge-summary filters,
// and page-level display all read from these helpers, so no call sites
// need to be edited when a new retail source is registered.

/**
 * Return an array of ranking source keys flagged as retail.
 * Derived from RANKING_SOURCES on every call so tests that mutate the
 * registry (or future runtime config reloads) see updated membership.
 */
export function getRetailSourceKeys() {
  return RANKING_SOURCES.filter((s) => s.isRetail).map((s) => s.key);
}

/**
 * Return the label to use for the retail side of the market-gap signal.
 * When exactly one source is flagged retail, its column label is used
 * directly (today: "KTC").  When multiple sources are flagged retail,
 * the generic label "Retail" is used instead.
 */
export function getRetailLabel() {
  const retail = RANKING_SOURCES.filter((s) => s.isRetail);
  if (retail.length === 1) return retail[0].columnLabel;
  return "Retail";
}

// ── Source override helpers ──────────────────────────────────────────
// The settings page writes per-source include/weight knobs into
// ``settings.siteWeights``.  Those maps flow through
// ``useDynastyData`` → ``fetchDynastyData`` → the backend rankings
// override endpoint, which re-runs the canonical pipeline with the
// override (and the TE-premium multiplier) threaded in.  There is no
// frontend ranking engine anymore, so the only helper we need on the
// client is the "customized" predicate below — it decides whether to
// hit the override endpoint.
//
// Any source not mentioned in the map inherits its registry defaults
// (every registered source is enabled by default with its declared
// weight of 1.0).  The map shape is:
//
//   {
//     ktc:     { include: true, weight: 1.0 },
//     dlfSf:   { include: false },
//     fantasyProsIdp: { weight: 0.5 },
//     …
//   }

/**
 * A ``siteOverrides`` map is "customized" if ANY registered source has
 * include set to false OR a weight value that differs from its
 * registry default.  When customized, ``fetchDynastyData`` POSTs the
 * map to the backend rankings override endpoint.  When not customized
 * it just returns the base contract.
 */
export function siteOverridesAreCustomized(siteOverrides) {
  if (!siteOverrides || typeof siteOverrides !== "object") return false;
  for (const src of RANKING_SOURCES) {
    const ov = siteOverrides[src.key];
    if (!ov || typeof ov !== "object") continue;
    if (ov.include === false) return true;
    if (Object.prototype.hasOwnProperty.call(ov, "weight")) {
      const w = Number(ov.weight);
      if (Number.isFinite(w) && w !== Number(src.weight ?? 1)) return true;
    }
  }
  return false;
}

/**
 * A TE premium multiplier is "customized" when the caller has passed
 * an explicit finite number — i.e. the user dragged the slider on
 * /settings and the value is no longer the ``null`` sentinel that
 * means "auto from league".
 *
 * Previously this function considered 1.0 to be "default" and any
 * value strictly > 1.0 to be customized, but that shape couldn't
 * express "auto derived from my Sleeper league" — the frontend
 * default of 1.15 always looked customized even when it matched the
 * league-derived value.  The new shape uses ``null`` for "inherit
 * from backend" and a finite number for "explicit override".  The
 * backend's ``rankingsOverride.tepMultiplierDerived`` carries the
 * league-derived default so the UI can render it without re-fetching
 * the registry.
 *
 * Returns ``true`` when the caller has posted a finite number (they
 * want to override the derived default).  Returns ``false`` for
 * ``null`` / ``undefined`` / non-finite values (auto-from-league
 * path — ``fetchDynastyData`` skips posting ``tep_multiplier`` in
 * the body and the backend derives from Sleeper).
 */
export function tepMultiplierIsCustomized(tepMultiplier) {
  if (tepMultiplier === null || tepMultiplier === undefined) return false;
  const n = Number(tepMultiplier);
  return Number.isFinite(n);
}

// ── Row materialization ──────────────────────────────────────────────
// ``buildRows`` materializes the backend contract (``playersArray``
// or legacy ``players`` dict) into the flat row shape every frontend
// surface consumes.  The ranking/value fields are pulled directly
// from the backend contract — the backend canonical engine in
// ``src/api/data_contract.py::_compute_unified_rankings`` is the
// single source of truth for ``canonicalConsensusRank``,
// ``rankDerivedValue``, ``sourceRanks``, ``sourceRankMeta``, and the
// trust/audit fields.
//
// Override handling: when the user customizes source weights via
// settings, ``useDynastyData`` POSTs the override map to the backend
// endpoint ``POST /api/rankings/overrides?view=delta`` which returns
// a compact delta payload.  ``fetchDynastyData`` merges the delta
// onto the cached base contract before calling ``buildRows``, so the
// rows materialize with override-adjusted ranks.  ``buildRows``
// itself is a pure materializer — it does not rank, blend,
// translate, or mix anything on its own.
//
// Fail-fast: if ``buildRows`` is called on a non-empty payload whose
// rows carry zero backend rank stamps, it logs an error and returns
// an empty array.  This path used to invoke a local fallback blend
// (~280 lines of drift-prone JS code that duplicated the backend
// math).  The fallback was removed once the override path was
// unified through the backend — its silent presence in production
// logs was a bug signal, not a safety net.  An empty-with-error
// board is strictly better than a quietly-wrong one.

function _materializePlayerArrayRow(player) {
  if (!player || typeof player !== "object") return null;
  const name = String(player.displayName || player.canonicalName || "").trim();
  if (!name) return null;
  const pos = normalizePos(player.position || "");
  const cls = classifyPos(pos);
  if (cls === "excluded") return null;

  // Prefer 1–9999 display value; fall back to internal calibrated value
  const displayVal = Number(player?.values?.displayValue ?? 0) || 0;
  const internalVal = Number(
    player?.values?.finalAdjusted ?? player?.values?.overall ?? 0
  ) || 0;
  const rawValues = {
    raw: Number(player?.values?.rawComposite ?? 0) || 0,
    full: displayVal || internalVal,
  };

  const canonicalSites =
    player.canonicalSiteValues && typeof player.canonicalSiteValues === "object"
      ? player.canonicalSiteValues
      : {};

  // Backend-authoritative: these come straight from the contract's
  // override-aware ranking pipeline.
  const backendRank = Number(player.canonicalConsensusRank) || null;
  const backendValue = Number(player.rankDerivedValue) || null;
  const backendSourceRanks =
    player.sourceRanks && typeof player.sourceRanks === "object"
      ? player.sourceRanks
      : {};
  const backendSourceRankMeta =
    player.sourceRankMeta && typeof player.sourceRankMeta === "object"
      ? player.sourceRankMeta
      : {};
  const backendBlendedSourceRank =
    player.blendedSourceRank != null ? Number(player.blendedSourceRank) : null;
  const backendSourceCount = Number(player.sourceCount || 0);

  return {
    name,
    pos: pos || "?",
    team: String(player.team || ""),
    age: Number(player.age) || null,
    rookie: Boolean(player.rookie),
    assetClass: String(player.assetClass || classifyPos(pos || "?")),
    values: {
      raw: Math.round(rawValues.raw),
      // When a backend override response has stamped a new
      // ``rankDerivedValue``, prefer it over the scraper's
      // ``displayValue`` so the user's settings shift the displayed
      // Value column too.  This is the trade-calculator-feeds-
      // rankings single-value pipe.
      full: Math.round(backendValue || rawValues.full),
    },
    // siteCount: intentionally preserved — used by trade calculator and
    // other non-rankings views.  Rankings pages hide this column, but the
    // field must remain on the row contract.  Do NOT remove it.
    siteCount: backendSourceCount,
    confidence: Number(player.marketConfidence ?? 0),
    marketLabel: "",
    canonicalSites,
    canonicalConsensusRank: backendRank,
    rankDerivedValue: backendValue,
    rankDerivedValueUncalibrated:
      Number(player.rankDerivedValueUncalibrated) || null,
    canonicalConsensusRankUncalibrated:
      Number(player.canonicalConsensusRankUncalibrated) || null,
    canonicalTierId: Number(player.canonicalTierId) || null,
    sourceRanks: backendSourceRanks,
    sourceRankMeta: backendSourceRankMeta,
    blendedSourceRank: backendBlendedSourceRank,
    sourceCount: backendSourceCount,
    // Value-chain audit fields — exposed so the PlayerPopup can show
    // each pipeline stage (anchor + subgroup → calibration) as a
    // transparent sequence rather than a single opaque final number.
    // ``sourceSpread`` is a pure transparency metric (mean absolute
    // deviation of per-source value contributions around the trimmed
    // center); it is NOT a penalty — λ·MAD was retired 2026-04-20.
    sourceSpread:
      typeof player.sourceSpread === "number" ? player.sourceSpread : null,
    madPenaltyApplied:
      typeof player.madPenaltyApplied === "number"
        ? player.madPenaltyApplied
        : null,
    anchorValue: Number(player.anchorValue) || null,
    subgroupBlendValue: Number(player.subgroupBlendValue) || null,
    subgroupDelta:
      typeof player.subgroupDelta === "number" ? player.subgroupDelta : null,
    alphaShrinkage:
      typeof player.alphaShrinkage === "number" ? player.alphaShrinkage : null,
    softFallbackCount:
      typeof player.softFallbackCount === "number"
        ? player.softFallbackCount
        : 0,
    idpCalibrationMultiplier:
      typeof player.idpCalibrationMultiplier === "number"
        ? player.idpCalibrationMultiplier
        : null,
    idpFamilyScale:
      typeof player.idpFamilyScale === "number" ? player.idpFamilyScale : null,
    idpCalibrationPositionRank:
      Number(player.idpCalibrationPositionRank) || null,
    sourceRankPercentileSpread:
      typeof player.sourceRankPercentileSpread === "number"
        ? player.sourceRankPercentileSpread
        : null,
    // Trust/transparency fields — pass through from backend contract.
    confidenceBucket: String(player.confidenceBucket || "none"),
    confidenceLabel: String(player.confidenceLabel || ""),
    anomalyFlags: Array.isArray(player.anomalyFlags) ? player.anomalyFlags : [],
    isSingleSource: Boolean(player.isSingleSource),
    hasSourceDisagreement: Boolean(player.hasSourceDisagreement),
    sourceRankSpread: player.sourceRankSpread ?? null,
    marketGapDirection: String(player.marketGapDirection || "none"),
    marketGapMagnitude: player.marketGapMagnitude ?? null,
    sourceOriginalRanks: player.sourceOriginalRanks && typeof player.sourceOriginalRanks === "object"
      ? player.sourceOriginalRanks : {},
    identityConfidence: Number(player.identityConfidence ?? 0.7),
    identityMethod: String(player.identityMethod || "name_only"),
    quarantined: Boolean(player.quarantined),
    raw: player,
  };
}

function _materializeLegacyDictRow(name, player, posMap) {
  if (!player || typeof player !== "object") return null;
  const isPick = /\b(20\d{2})\s+(early|mid|late)?\s*(1st|2nd|3rd|4th|5th|6th|round|r\d|pick)/i.test(name) || /^20\d{2}\s+pick/i.test(name);
  const pos = isPick ? "PICK" : normalizePos(posMap[name] || player.position || "");
  if (classifyPos(pos) === "excluded") return null;

  const rawValues = inferValueBundle(player);
  const canonicalSites = player._canonicalSiteValues && typeof player._canonicalSiteValues === "object" ? player._canonicalSiteValues : {};
  const backendRank = Number(player._canonicalConsensusRank) || null;
  const backendValue = Number(player.rankDerivedValue) || null;
  // Mirror the playersArray materializer's single-value pipe: when a
  // backend ``rankDerivedValue`` is stamped, prefer it over the
  // legacy ``_finalAdjusted`` as the displayed ``values.full``.
  const values = {
    raw: rawValues.raw,
    full: backendValue || rawValues.full,
  };

  return {
    name,
    pos: pos || "?",
    team: String(player.team || ""),
    age: Number(player.age) || null,
    rookie: Boolean(player._formatFitRookie),
    assetClass: classifyPos(pos || "?"),
    values,
    siteCount: Number(player.sourceCount || player._sites || 0),
    confidence: Number(player._marketReliabilityScore ?? 0),
    marketLabel: String(player._marketReliabilityLabel || ""),
    canonicalSites,
    canonicalConsensusRank: backendRank,
    rankDerivedValue: backendValue,
    rankDerivedValueUncalibrated:
      Number(player.rankDerivedValueUncalibrated) || null,
    canonicalConsensusRankUncalibrated:
      Number(player.canonicalConsensusRankUncalibrated) || null,
    canonicalTierId: Number(player._canonicalTierId) || null,
    sourceRanks: player.sourceRanks && typeof player.sourceRanks === "object" ? player.sourceRanks : {},
    sourceRankMeta: player.sourceRankMeta && typeof player.sourceRankMeta === "object" ? player.sourceRankMeta : {},
    blendedSourceRank: player.blendedSourceRank ?? null,
    sourceCount: Number(player.sourceCount || 0),
    confidenceBucket: String(player.confidenceBucket || "none"),
    confidenceLabel: String(player.confidenceLabel || ""),
    anomalyFlags: Array.isArray(player.anomalyFlags) ? player.anomalyFlags : [],
    isSingleSource: Boolean(player.isSingleSource),
    isStructurallySingleSource: Boolean(player.isStructurallySingleSource),
    hasSourceDisagreement: Boolean(player.hasSourceDisagreement),
    sourceRankSpread: player.sourceRankSpread ?? null,
    sourceRankPercentileSpread: player.sourceRankPercentileSpread ?? null,
    sourceAudit: player.sourceAudit && typeof player.sourceAudit === "object" ? player.sourceAudit : null,
    marketGapDirection: String(player.marketGapDirection || "none"),
    marketGapMagnitude: player.marketGapMagnitude ?? null,
    sourceOriginalRanks: player.sourceOriginalRanks && typeof player.sourceOriginalRanks === "object"
      ? player.sourceOriginalRanks : {},
    identityConfidence: Number(player.identityConfidence ?? 0.7),
    identityMethod: String(player.identityMethod || "name_only"),
    quarantined: Boolean(player.quarantined),
    raw: player,
  };
}

/**
 * Returns true if any row carries a positive integer
 * ``canonicalConsensusRank`` stamp from the backend pipeline.  Checks
 * "any" rather than "all" because the backend caps the board near
 * the tail, so players past the cap legitimately have
 * ``canonicalConsensusRank === null``.
 */
function _hasBackendRankStamps(rows) {
  for (const r of rows) {
    if (r && Number.isInteger(r.canonicalConsensusRank) && r.canonicalConsensusRank > 0) {
      return true;
    }
  }
  return false;
}

export function buildRows(data) {
  const players = data?.players || {};
  const playersArray = Array.isArray(data?.playersArray) ? data.playersArray : [];
  const posMap = data?.sleeper?.positions || {};
  const rows = [];

  if (playersArray.length) {
    for (const player of playersArray) {
      const row = _materializePlayerArrayRow(player);
      if (row) rows.push(row);
    }
  } else {
    for (const [name, player] of Object.entries(players)) {
      const row = _materializeLegacyDictRow(name, player, posMap);
      if (row) rows.push(row);
    }
  }

  // Fail-fast: a non-empty payload with zero backend rank stamps is a
  // hard bug signal (stale file, pipeline failure, upstream scrape
  // down).  Log an error and return an empty rows array so the UI
  // surface's existing "no players" error banner kicks in instead of
  // silently recomputing a drift-prone local blend.
  if (rows.length > 0 && !_hasBackendRankStamps(rows)) {
    if (typeof console !== "undefined" && console.error) {
      console.error(
        "[dynasty-data] buildRows received a payload with zero backend rank stamps. " +
          "This is a hard bug signal — the scrape pipeline is not stamping " +
          "canonicalConsensusRank.  Returning empty rows; the UI will surface a " +
          "'no players' error banner instead of rendering a silently-wrong board.",
      );
    }
    return [];
  }

  // Sort by rankDerivedValue desc so rows that intentionally carry
  // null canonicalConsensusRank (e.g. anchor-year slot picks — 2026
  // picks anchored to the matching rookie by value) still interleave
  // with players at the right position instead of collapsing to the
  // end of the table. For ranked rows this ordering matches the
  // integer-rank order because the backend has already made value
  // monotonic with rank; the change only affects null-rank rows.
  rows.sort((a, b) => {
    const va = Number(a.rankDerivedValue) || 0;
    const vb = Number(b.rankDerivedValue) || 0;
    if (vb !== va) return vb - va;
    // Tie-break: integer ranks first (so ties with null-rank picks
    // place the ranked player "above" the pick deterministically).
    const ra = a.canonicalConsensusRank ?? Infinity;
    const rb = b.canonicalConsensusRank ?? Infinity;
    return ra - rb;
  });
  rows.forEach((r, i) => {
    r.computedConsensusRank = i + 1;
    // Preserve null rank on rows the backend explicitly un-ranked
    // (anchor-year slot picks). Players still fall back to the
    // local computed ordinal as before; picks show no rank number.
    if (r.canonicalConsensusRank != null) {
      r.rank = r.canonicalConsensusRank;
    } else if (r.assetClass === "pick") {
      r.rank = null;
    } else {
      r.rank = r.computedConsensusRank;
    }
  });
  return rows;
}

// ── Backend override endpoint URL ────────────────────────────────────
const RANKINGS_OVERRIDES_URL = "/api/rankings/overrides";
const DEFAULT_DATA_URL = "/api/dynasty-data";

// ── Base contract cache ──────────────────────────────────────────────
// The rankings-override delta path needs a base payload to merge the
// delta onto.  We keep the last successfully loaded full contract in
// module-level state so the second call with overrides does not have
// to refetch the 2.5MB base payload.
let _cachedBaseContract = null;

/** Clear the in-memory base contract cache.  Useful for tests. */
export function _resetBaseContractCache() {
  _cachedBaseContract = null;
}

async function _fetchBaseContract() {
  const res = await fetch(DEFAULT_DATA_URL, { cache: "no-store" });
  if (!res.ok) {
    const txt = await res.text();
    throw new Error(`Failed to load dynasty data: ${res.status} ${txt}`);
  }
  const json = await res.json();

  // The Next.js API route wraps the payload: { ok, source, data: <contract> }
  // The Python backend alias returns the raw contract.  Normalize both.
  let wrapped;
  if (json && typeof json === "object" && !json.data && (json.players || json.playersArray)) {
    wrapped = {
      ok: true,
      source: json.dataSource?.type
        ? `backend:${json.dataSource.type}`
        : json.date
          ? `contract:${json.date}`
          : "backend",
      data: json,
    };
  } else {
    wrapped = json;
  }
  if (wrapped && wrapped.data) {
    _cachedBaseContract = wrapped;
  }
  return wrapped;
}

// ── Rankings delta merge ──────────────────────────────────────────────
// Applies a compact delta payload (from ``POST /api/rankings/overrides?view=delta``)
// onto a cached base contract, producing a new contract object with
// override-adjusted ranks and values.  The base contract is NOT
// mutated — we shallow-copy the top-level object and deep-copy the
// ``playersArray`` entries that are touched.  Unchanged players keep
// their base identity, team, age, canonical sites, and identity
// quality untouched.
//
// Runtime vs full payload:
// ────────────────────────
// The frontend's default data fetch hits ``/api/data?view=app`` on
// the backend, which returns the "runtime" view that strips
// ``playersArray`` to keep the first-paint payload small.  The
// legacy ``players`` dict (keyed by displayName) is the only
// per-player collection in that view.  When an override delta
// arrives, we therefore synthesize a fresh ``playersArray`` from
// the delta entries plus the legacy dict for identity fields —
// delta provides the override-sensitive fields (ranks, values,
// sourceRanks, confidence, gap) and the legacy dict + sleeper
// position map provide the invariant identity fields (position,
// team, age, rookie flag).  The merged contract always carries a
// populated ``playersArray`` so ``buildRows`` uses the authoritative
// playersArray materializer and never falls back to the legacy
// dict path for override rows.
//
// When the base contract already carries a populated playersArray
// (e.g. the ``/api/data`` full view, or test fixtures), we take
// the simpler path of iterating basePlayersArray and deep-merging
// delta fields onto each matched entry.
export function mergeRankingsDelta(baseContract, delta) {
  if (!baseContract || !delta) return baseContract;
  const base = baseContract.data || baseContract;
  const rankingsDelta = delta.rankingsDelta;
  if (!rankingsDelta || !Array.isArray(rankingsDelta.players)) return baseContract;
  const playerKey = rankingsDelta.playerKey || "displayName";
  const deltaByKey = new Map();
  for (const entry of rankingsDelta.players) {
    if (!entry || !entry.id) continue;
    deltaByKey.set(String(entry.id), entry);
  }
  const activeIds = new Set(
    (rankingsDelta.activePlayerIds || []).map((s) => String(s)),
  );

  const mergedData = {
    ...base,
    rankingsOverride: delta.rankingsOverride || base.rankingsOverride,
    date: delta.date || base.date,
    generatedAt: delta.generatedAt || base.generatedAt,
  };

  const basePlayersArray = Array.isArray(base.playersArray) ? base.playersArray : [];

  if (basePlayersArray.length > 0) {
    // Fast path: base already has a fully-materialized playersArray,
    // so we iterate it and apply delta-entry fields in place.
    const mergedPlayersArray = new Array(basePlayersArray.length);
    for (let i = 0; i < basePlayersArray.length; i++) {
      const basePlayer = basePlayersArray[i];
      if (!basePlayer) {
        mergedPlayersArray[i] = basePlayer;
        continue;
      }
      const id = String(
        basePlayer[playerKey] || basePlayer.displayName || basePlayer.canonicalName || "",
      );
      const deltaEntry = deltaByKey.get(id);
      if (!deltaEntry) {
        mergedPlayersArray[i] = basePlayer;
        continue;
      }
      const next = { ...basePlayer };
      for (const field of Object.keys(deltaEntry)) {
        if (field === "id") continue;
        next[field] = deltaEntry[field];
      }
      if (!activeIds.has(id)) {
        next.canonicalConsensusRank = null;
      }
      mergedPlayersArray[i] = next;
    }
    mergedData.playersArray = mergedPlayersArray;
  } else {
    // Runtime-view path: the base contract only has the legacy
    // ``players`` dict (playersArray was stripped to minimize
    // first-paint payload).  We synthesize one playersArray entry
    // per delta player by reading identity fields from the legacy
    // dict + ``sleeper.positions`` map.  This keeps ``buildRows``
    // on its authoritative playersArray path and guarantees the
    // override is actually reflected in the materialized rows.
    const legacyPlayers =
      base.players && typeof base.players === "object" ? base.players : {};
    const posMap =
      (base.sleeper && base.sleeper.positions) || {};
    const PICK_RE = /\b(20\d{2})\s+(early|mid|late)?\s*(1st|2nd|3rd|4th|5th|6th|round|r\d|pick)/i;
    const synthesizedArray = [];
    for (const deltaEntry of rankingsDelta.players) {
      if (!deltaEntry || !deltaEntry.id) continue;
      const id = String(deltaEntry.id);
      const legacy =
        legacyPlayers[id] && typeof legacyPlayers[id] === "object"
          ? legacyPlayers[id]
          : {};
      const isPick = PICK_RE.test(id) || /^20\d{2}\s+pick/i.test(id);
      // Start with a minimal identity envelope.  Delta fields
      // override anything override-sensitive (values, ranks,
      // sourceRanks, confidence, gap, etc.), and the legacy dict
      // supplies the identity / invariant fields the playersArray
      // materializer reads on rows (position, team, age, etc.).
      const row = {
        displayName: id,
        canonicalName: String(legacy.canonicalName || id),
        position: isPick
          ? "PICK"
          : String(posMap[id] || legacy.position || ""),
        team: legacy.team != null ? legacy.team : null,
        age: legacy.age != null ? legacy.age : null,
        rookie: Boolean(legacy._formatFitRookie || legacy.rookie),
        assetClass: String(legacy.assetClass || ""),
        identityConfidence: Number(legacy.identityConfidence ?? 0.7),
        identityMethod: String(legacy.identityMethod || "name_only"),
        // Carry forward the pre-override canonical site values so
        // the retail-vs-consensus gap column can fall back when the
        // delta dropped a source.
        canonicalSiteValues:
          legacy._canonicalSiteValues && typeof legacy._canonicalSiteValues === "object"
            ? legacy._canonicalSiteValues
            : {},
      };
      for (const field of Object.keys(deltaEntry)) {
        if (field === "id") continue;
        row[field] = deltaEntry[field];
      }
      if (!activeIds.has(id)) {
        row.canonicalConsensusRank = null;
      }
      synthesizedArray.push(row);
    }
    mergedData.playersArray = synthesizedArray;
  }

  return {
    ...baseContract,
    ok: true,
    source: "backend:override:delta",
    data: mergedData,
  };
}

export async function fetchDynastyData(opts = {}) {
  const siteOverrides = opts.siteOverrides || null;
  // Preserve ``null`` / ``undefined`` as "inherit derived default"
  // rather than coercing to 1.0.  A finite number is treated as the
  // explicit override the user set via the slider.
  const rawTep = opts.tepMultiplier;
  const tepMultiplier =
    rawTep === null || rawTep === undefined
      ? null
      : Number.isFinite(Number(rawTep))
        ? Number(rawTep)
        : null;
  const sitesCustomized = siteOverridesAreCustomized(siteOverrides);
  const tepCustomized = tepMultiplierIsCustomized(tepMultiplier);
  const customized = sitesCustomized || tepCustomized;

  // Default path (no overrides): fetch + cache the base contract.
  // The backend will derive tep_multiplier from the operator's
  // Sleeper league ``bonus_rec_te`` and bake it into the blend for
  // us, so the frontend doesn't need to POST anything.
  if (!customized) {
    return _fetchBaseContract();
  }

  // Override path: POST the override map + TE premium multiplier to
  // the backend delta endpoint, then merge the delta onto the
  // cached base contract.  The backend bakes TEP into every TE's
  // rankDerivedValue stamp before producing the delta, so the
  // frontend never needs to multiply on render.
  const base = _cachedBaseContract || (await _fetchBaseContract());

  // Build the POST body: start from the siteOverrides map (legacy
  // shape) and stamp the tep_multiplier field on top only when the
  // user has an explicit override.  When the slider is in "auto"
  // (null) the body omits tep_multiplier entirely; the backend's
  // ``normalize_tep_multiplier`` returns ``None`` for an absent key
  // and ``build_api_data_contract`` derives from the Sleeper league
  // context.
  const body = { ...(siteOverrides || {}) };
  if (tepCustomized) {
    body.tep_multiplier = tepMultiplier;
  }

  try {
    const overrideRes = await fetch(`${RANKINGS_OVERRIDES_URL}?view=delta`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
      cache: "no-store",
    });
    if (overrideRes.ok) {
      const deltaPayload = await overrideRes.json();
      if (deltaPayload && deltaPayload.mode === "delta" && deltaPayload.rankingsDelta) {
        return mergeRankingsDelta(base, deltaPayload);
      }
      // Full-contract fallback: the backend may have returned a full
      // payload (e.g. proxy stripped view=delta).  Pass through.
      if (deltaPayload && (deltaPayload.players || deltaPayload.playersArray)) {
        return {
          ok: true,
          source: "backend:override",
          data: deltaPayload,
        };
      }
    } else if (typeof console !== "undefined" && console.warn) {
      console.warn(
        `[dynasty-data] /api/rankings/overrides returned ${overrideRes.status}; ` +
          "falling through to base contract.",
      );
    }
  } catch (err) {
    if (typeof console !== "undefined" && console.warn) {
      console.warn(
        "[dynasty-data] /api/rankings/overrides request failed:",
        err?.message || err,
      );
    }
  }

  // Override endpoint failed — return the base contract unchanged.
  return base;
}
