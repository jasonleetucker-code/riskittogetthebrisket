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

// ── Canonical name join key — NOT HERE ─────────────────────────────
// This file used to export a `normalizePlayerName` that claimed to
// mirror `normalize_player_name()` in `src/utils/name_clean.py`.  It
// did not: it was missing the apostrophe rule, so "Ja'Marr Chase"
// produced "ja marr chase" where the backend produces "jamarr chase".
// It also had zero production callers — only its own test file
// imported it — so nothing ever caught the drift.  Removed 2026-07-29.
//
// The real, VERIFIED JS mirror is
// `frontend/lib/player-name-match.js::normalizePlayerNameKey`, pinned
// against the Python function by the shared fixture
// `tests/fixtures/name_key_cases.json` (halves:
// `frontend/__tests__/name-key-parity.test.js` and
// `tests/utils/test_name_key_parity.py`).  Import that one — do not
// re-add a second implementation here.

// IDP position priority. When a Sleeper player is multi-position
// eligible (fantasy_positions array, slash-joined string like "DL/LB",
// or an explicit array input) we collapse to a single canonical family
// using DL > DB > LB. LB is emitted only when the player is
// exclusively LB-eligible — this mirrors the Python helper
// ``src/utils/name_clean.py::resolve_idp_position`` so the frontend
// never disagrees with the backend on position assignment.
export const IDP_PRIORITY = ["DL", "DB", "LB"];

const _NON_IDP_ALIASES = new Set(["QB", "RB", "WR", "TE", "K", "P", "PICK"]);

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

// SCALE CONTRACT (math audit 2026-07-30, finding H1).  ``raw`` and
// ``full`` are NOT the same scale and must never substitute for each
// other:
//
//   raw  — the legacy scraper composite, ~1.131x the canonical board
//          (measured; ``BOARD_TO_COMPOSITE_K`` in src/trade/finder.py).
//          This is the UI's explicit "Raw" value mode.
//   full — the canonical board value (``rankDerivedValue``), the number
//          every page, sum and threshold is calibrated against.
//
// ``full`` used to fall back through ``_finalAdjusted -> _composite ->
// raw``, so a row the backend declined to price silently contributed a
// composite-scale number to board-scale sums (team value, trade sides,
// waiver gaps, portfolio totals).  It no longer does: an unpriced row
// reports 0 and drops out of those sums rather than distorting them.
// ``_canonicalDisplayValue`` is not read because nothing has ever
// written it — the backend field of that name does not exist.
export function inferValueBundle(player = {}) {
  const raw =
    Number(
      player._rawComposite ?? player._rawMarketValue ?? player._composite ?? 0,
    ) || 0;
  // Board value only.  The legacy ``players`` dict carries
  // ``rankDerivedValue`` mirrored from the contract row; when it is
  // absent the board declined to price this row and there is no
  // board-scale number to report.
  const full = Number(player.rankDerivedValue ?? 0) || 0;
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
    // KeepTradeCut TE+ Superflex board — the canonical KTC retail
    // signal as of 2026-04-28.  KTC publishes both a standard SF
    // view and a TE+ sub-board from the same per-player API payload
    // (``superflexValues.value`` + ``superflexValues.tep`` level 1),
    // and one scrape produces both CSVs.  Historically both were
    // registered as separate blend sources, but the standard ``ktc``
    // vote duplicated this one (identical values for non-TE rows;
    // TEP-correction converged them on TE rows), so it was retired
    // from the blend.  The standard ``ktc`` raw value is still loaded
    // into ``canonicalSiteValues`` (free side-effect of the same
    // scrape) so the KTC arbitrage finder + per-source winner row on
    // /trade can keep displaying both side-by-side; only the blend
    // vote was removed.  Mirrors the `is_retail: True` flag on the
    // backend `_RANKING_SOURCES` entry.
    key: "ktcSfTep",
    displayName: "KeepTradeCut SF-TE++",
    // Compact label is just "KTC" since the standard ``ktc`` source
    // was retired from the blend 2026-04-28; ktcSfTep is now the
    // sole KTC voter.  ``displayName`` keeps the SF-TEP suffix for
    // detailed views where the underlying board matters.
    columnLabel: "KTC",
    scope: "overall_offense",
    positionGroup: null,
    depth: null,
    weight: 1.0,
    isBackbone: false,
    isRetail: true,
    isRankSignal: false,
    isTepPremium: true,
    // Head of the `ktc` correlation group: `fantasyNavigatorSf`
    // republishes KTC-derived values, so the two are one vote's worth
    // of evidence, not two.  Sources with no declared group are
    // independent and default to a singleton named after themselves.
    correlationGroup: "ktc",
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
    isRankSignal: false,
    // IDPTradeCalc is scraped with TEP=True (see Dynasty Scraper.py):
    // raw values come from ``value_sftep`` columns, which already bake
    // in a TE-premium board.  Treated as TEP-native so it gets the
    // small 1.10× nudge instead of the full non-TEP boost.
    isTepPremium: true,
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
    correlationGroup: "dlf",
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
    // DLF Dynasty Rookie Superflex — 6-expert consensus covering the
    // current rookie class only (QB/RB/WR/TE prospects).  The raw
    // rookie-only rank is crosswalked at blend time through a rookie
    // ladder built from KTC's current ranks on offensive rookies, so
    // DLF's #1 rookie inherits KTC's rank-for-top-rookie scale while
    // DLF's ORDERING remains intact.  Synthetic "2026 Pick R.SS" rows
    // appended during CSV enrichment also nudge rookie pick values.
    key: "dlfRookieSf",
    correlationGroup: "dlf",
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
    correlationGroup: "dlf",
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
    // DLF Dynasty Rookie IDP — rookie-only DL/LB/DB prospects.
    // Translated against IDPTC's rookie ladder.  Does NOT stamp onto
    // picks because rookie IDP ranks are not a strong signal for
    // pick-slot value (most rookie drafts prioritize offensive
    // prospects at the top).
    key: "dlfRookieIdp",
    correlationGroup: "dlf",
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
    // The IDP Show (Adamidp) — Substack-hosted full-universe IDP
    // rankings board.  Includes rookies, edge/interior split.
    // Data loaded by scripts/fetch_idpshow.py from a Datawrapper
    // iframe embedded in the paywalled article; session cookies
    // are refreshed manually ~quarterly (Substack captcha blocks
    // automated login).  ~420 rows.  Rank-signal via the OVR
    // column; needs shared-market translation for Hill input.
    key: "idpShow",
    displayName: "The IDP Show (Adamidp)",
    columnLabel: "IDP Show",
    scope: "overall_idp",
    positionGroup: null,
    depth: 420,
    weight: 1.0,
    isBackbone: false,
    isRetail: false,
    isTepPremium: false,
    needsSharedMarketTranslation: true,
    excludesRookies: false,
    isRankSignal: true,
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
    // FantasyCalc Dynasty Superflex trade values — crowd-sourced
    // community values fetched from the public JSON API at
    // api.fantasycalc.com/values/current
    // (?isDynasty=true&numQbs=2&numTeams=12&ppr=1) via
    // scripts/fetch_fantasycalc.py.  Same board that powers
    // https://www.fantasycalc.com/dynasty-rankings.  ~450+ offensive
    // players (QB/RB/WR/TE) after filtering.  Mirrors the backend
    // `_RANKING_SOURCES` entry in src/api/data_contract.py.
    //
    // FantasyCalc is standard Superflex (numQbs=2) but does NOT
    // natively account for TE premium — declared `isTepPremium:
    // false` so the global tepMultiplier boost applies to its
    // contribution, just like Dynasty Daddy SF or FlockFantasy SF.
    // Signal=rank (2026-07-25): FantasyCalc's crowd values decay far
    // faster down the board than the KTC-anchored consensus, so the
    // value-direct path made it a systematic Hampel outlier (~55-58%
    // of its votes dropped every week since it was added).  Now
    // routed through the rank-signal path like Dynasty Daddy SF —
    // see the _SOURCE_CSV_PATHS entry in src/api/data_contract.py.
    key: "fantasyCalc",
    displayName: "FantasyCalc Dynasty SF",
    columnLabel: "FC",
    scope: "overall_offense",
    extraScopes: [],
    positionGroup: null,
    depth: 450,
    weight: 1.0,
    isBackbone: false,
    isRetail: false,
    isRankSignal: true,
    isTepPremium: false,
    needsSharedMarketTranslation: false,
    excludesRookies: false,
  },
  {
    // OTC Fantasy Football Superflex trade-derived values — fetched
    // from otcffb.com/api/trade-values?format=sf via
    // scripts/fetch_otcffb.py.  Public JSON, no auth.  ~470 offensive
    // players covering QB/RB/WR/TE on a 0-100 value scale derived
    // from OTCFFB's tracked community trades.  Mirrors the backend
    // _RANKING_SOURCES entry in src/api/data_contract.py.
    //
    // Standard Superflex — no TE premium baked in.  The frontend
    // settings.tepMultiplier boost applies to its contribution like
    // FantasyCalc / Dynasty Daddy SF / Flock Fantasy SF.
    // Signal=rank (2026-07-25): same conversion as fantasyCalc — the
    // 0-100 trade-derived values decay far faster than consensus and
    // were Hampel-dropped on 56-86% of rows; now routed through the
    // rank-signal path.  See src/api/data_contract.py for analysis.
    key: "otcffbSf",
    displayName: "OTC Fantasy Football SF",
    columnLabel: "OTC",
    scope: "overall_offense",
    extraScopes: [],
    positionGroup: null,
    depth: 460,
    weight: 1.0,
    isBackbone: false,
    isRetail: false,
    isRankSignal: true,
    isTepPremium: false,
    needsSharedMarketTranslation: false,
    excludesRookies: false,
  },
  {
    // Fantasy Navigator superflex dynasty board — public JSON API
    // fetched by scripts/fetch_fantasynavigator.py (~800 offense
    // rows).  KTC-derived values (rows carry ktc_player_id), so
    // partially correlated with ktcSfTep — documented in the Python
    // registry.  Standard SF scoring, no TE premium baked in: the
    // settings.tepMultiplier boost applies to its contribution.
    // Signal=rank from day one (KTC-adjacent decay shape).
    key: "fantasyNavigatorSf",
    displayName: "Fantasy Navigator SF",
    columnLabel: "FN",
    scope: "overall_offense",
    extraScopes: [],
    positionGroup: null,
    depth: 460,
    weight: 1.0,
    isBackbone: false,
    isRetail: false,
    isRankSignal: true,
    isTepPremium: false,
    needsSharedMarketTranslation: false,
    excludesRookies: false,
    // Member of the `ktc` correlation group — every FN row carries a
    // `ktc_player_id` and the site credits KeepTradeCut as a source.
    // FN agreeing with KTC is not independent confirmation.
    correlationGroup: "ktc",
  },
  {
    // Play for Keeps Dynasty master board — PFK's hand-maintained
    // dynasty rankings via scripts/fetch_pfk.py (~496 offense rows,
    // picks dropped).  Independent human signal.  Standard SF
    // scoring, no TE premium: the settings.tepMultiplier boost
    // applies to its contribution.  Signal=rank; native values are
    // preserved server-side for display/audit.
    key: "pfkDynasty",
    displayName: "Play for Keeps Dynasty",
    columnLabel: "PFK",
    scope: "overall_offense",
    extraScopes: [],
    positionGroup: null,
    depth: 460,
    weight: 1.0,
    isBackbone: false,
    isRetail: false,
    isRankSignal: true,
    isTepPremium: false,
    needsSharedMarketTranslation: false,
    excludesRookies: false,
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
    // Signal=rank as of 2026-04-22 (PR #215): Dynasty Daddy's top
    // values cluster at a 10,200 display ceiling which collapsed
    // relative ordering under value-direct normalisation.  Source is
    // now routed through the shared Hill curve via its value-ordered
    // rank column; the frontend UI renders the rank column, not raw
    // value, via ``sourceOriginalRanks.dynastyDaddySf``.
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
    isRankSignal: true,
    isTepPremium: false,
    needsSharedMarketTranslation: false,
    excludesRookies: false,
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
    correlationGroup: "fantasyPros",
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
    // FantasyPros Dynasty IDP expert consensus.  Combined IDP page
    // (dynasty-idp.php) is authoritative for cross-position ordering;
    // individual DL/LB/DB pages are used only as depth extension via
    // monotone piecewise-linear anchor curves fit from the overlap
    // (see scripts/fetch_fantasypros_idp.py).  Conceptually mirrors
    // DLF IDP; weight normalized to 1.0 alongside every other
    // registered source.  Mirrors the backend `_RANKING_SOURCES`
    // entry in src/api/data_contract.py.
    key: "fantasyProsIdp",
    correlationGroup: "fantasyPros",
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
    // FantasyPros / Pat Fitzmaurice Dynasty Trade Value Chart —
    // monthly offense board covering QB/RB/WR/TE.  Fetched by
    // scripts/fetch_fantasypros_fitzmaurice.py, which resolves the
    // date-rotating article URL, extracts four Datawrapper iframes
    // (one per position), and grabs each chart's dataset.csv.  Per
    // position we pick the league-appropriate value column (SF Value
    // for QB, TEP Value for TE, Trade Value for RB/WR) — so
    // Fitzmaurice's Superflex + TE-Premium native numbers align
    // with our league scoring.  Rank-signal (restored 2026-04-22):
    // the 0-101 value scale caps hard at the top with the top dozen
    // players bunched between 80 and 101, which the value-direct
    // branch collapsed into a narrow top band that the Hampel filter
    // correctly rejected (19% drop rate).  Routing through the rank
    // path instead feeds Fitzmaurice's global 1-indexed rank into
    // the shared Hill curve.  Mirrors the backend
    // ``_SOURCE_CSV_PATHS["fantasyProsFitzmaurice"].signal = "rank"``.
    key: "fantasyProsFitzmaurice",
    correlationGroup: "fantasyPros",
    displayName: "FantasyPros / Pat Fitzmaurice SF-TEP",
    columnLabel: "Fitzmaurice",
    scope: "overall_offense",
    extraScopes: [],
    positionGroup: null,
    depth: 350,
    weight: 1.0,
    isBackbone: false,
    isRetail: false,
    isRankSignal: true,
    isTepPremium: true,
    needsSharedMarketTranslation: false,
    excludesRookies: false,
  },
  {
    // Flock Fantasy Dynasty Superflex rankings — expert consensus.
    // Standard SF — no TE premium.  tepMultiplier boost applies.
    key: "flockFantasySf",
    correlationGroup: "flockFantasy",
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
    // Flock Fantasy Dynasty Superflex ROOKIE rankings — multi-expert
    // averaged ranks of the current incoming rookie class only
    // (~95 QB/RB/WR/TE prospects).  Same translation behaviour as
    // dlfRookieSf — the within-class rank is crosswalked through KTC's
    // offense rookie ladder so Flock's #1 rookie inherits KTC's
    // scale-for-top-rookie.  Pick nudging is not wired for this source;
    // dlfRookieSf already stamps synthetic "2026 Pick R.SS" rows.
    key: "flockFantasySfRookies",
    correlationGroup: "flockFantasy",
    displayName: "Flock Fantasy Rookie SF",
    columnLabel: "Flock RK",
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
    // Signal=rank as of 2026-04-22 (PR #215): Boone's 0-141 value
    // scale has seven players in the 110-141 band which collapsed
    // relative ordering under value-direct.  Source now routed
    // through the shared Hill curve via its ``rank`` column; the UI
    // renders Boone's published rank via ``sourceOriginalRanks.yahooBoone``
    // (the raw ``boone_value`` column is preserved on row payloads
    // for display but no longer drives the blend).
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
    isRankSignal: true,
    isTepPremium: true,
    needsSharedMarketTranslation: false,
    excludesRookies: false,
  },
  {
    // DraftSharks offense dynasty board (QB/RB/WR/TE).  The
    // ``fetch_draftsharks.py`` scraper splits DS's single
    // offense-combined DOM by position family into two CSVs, so
    // this is the SF slice only.  Value signal off the ``3D Value +``
    // column.  DraftSharks IS scraped from the TE-PREMIUM superflex
    // board (fetch_draftsharks.py RANKINGS_URL =
    // /dynasty-rankings/te-premium-superflex), so its values already
    // bake in TE premium — TEP-native like KTC SF-TE++ / DN SF-TEP /
    // Yahoo Boone.  isTepPremium:true so TE rows get only the small
    // native nudge, not the larger non-TEP boost (mis-flagged false
    // until 2026-05-16, which double-counted TEP for DS and inflated
    // top TEs like Brock Bowers).  Lockstep with
    // src/api/data_contract.py::_RANKING_SOURCES.
    key: "draftSharks",
    correlationGroup: "draftSharks",
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
    isTepPremium: true,
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
    correlationGroup: "draftSharks",
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

// ── Source vendor grouping ───────────────────────────────────────────
// Several vendors publish multiple sibling boards (e.g. DLF ships SF +
// IDP + rookie-SF + rookie-IDP as four separate scraped sources so the
// backend can weight and translate each scope independently).  For
// end-user display this sub-source split is noise — if we list every
// sub-source in the trade breakdown, a rookie-for-veteran trade lights
// up DLF as "Side A wins on DLF RK, Side B wins on DLF SF" when really
// those are just two views of the same vendor opinion.
//
// ``SOURCE_VENDORS`` maps each canonical source key to its vendor
// identifier.  UI components that want to present one-row-per-vendor
// (e.g. the trade per-source breakdown) sum ``valueContribution``
// across every sub-source belonging to a vendor for each trade side,
// then render one consolidated row.  Sources whose key doesn't appear
// here stand alone under their own key (fallback handled in consumers).
//
// ``SOURCE_VENDOR_LABELS`` supplies the display label for each vendor
// row; components can fall back to the first matching sub-source's
// ``columnLabel`` if a vendor has no explicit label here.
export const SOURCE_VENDORS = {
  dlfSf: "dlf",
  dlfIdp: "dlf",
  dlfRookieSf: "dlf",
  dlfRookieIdp: "dlf",
  fantasyProsSf: "fantasyPros",
  fantasyProsIdp: "fantasyPros",
  flockFantasySf: "flock",
  flockFantasySfRookies: "flock",
  draftSharks: "draftSharks",
  draftSharksIdp: "draftSharks",
};

export const SOURCE_VENDOR_LABELS = {
  dlf: "DLF",
  fantasyPros: "FantasyPros",
  flock: "Flock Fantasy",
  draftSharks: "Draft Sharks",
};

/**
 * Return the vendor identifier for a source key.  Falls back to the
 * source key itself when the source isn't part of a multi-board
 * vendor (e.g. ktc, idpTradeCalc, dynastyDaddySf, yahooBoone,
 * dynastyNerdsSfTep, fantasyProsFitzmaurice — single-board vendors).
 */
export function vendorForSource(sourceKey) {
  if (!sourceKey) return "";
  return SOURCE_VENDORS[sourceKey] || sourceKey;
}

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

/**
 * Same predicate as ``tepMultiplierIsCustomized`` but for the
 * parallel ``tepNativeMultiplier`` knob.  Treated identically: ``null``
 * / ``undefined`` / non-finite values mean "use the backend default
 * (1.10)" so ``fetchDynastyData`` skips posting the field.
 */
export function tepNativeMultiplierIsCustomized(tepNativeMultiplier) {
  if (tepNativeMultiplier === null || tepNativeMultiplier === undefined)
    return false;
  const n = Number(tepNativeMultiplier);
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

  // Board-scale keys only — see the SCALE CONTRACT note on
  // ``inferValueBundle``.  ``values.displayValue`` / ``finalAdjusted`` /
  // ``overall`` all mirror the backend's ``rankDerivedValue`` and are
  // null when the board declined to price the row;
  // ``values.rawComposite`` is the legacy composite and stays out of
  // this chain.
  const displayVal = Number(player?.values?.displayValue ?? 0) || 0;
  const internalVal =
    Number(player?.values?.finalAdjusted ?? player?.values?.overall ?? 0) || 0;
  const rawValues = {
    raw: Number(player?.values?.rawComposite ?? 0) || 0,
    full: displayVal || internalVal,
  };

  const canonicalSites =
    player.canonicalSiteValues && typeof player.canonicalSiteValues === "object"
      ? player.canonicalSiteValues
      : {};
  // Raw scrape values for sources whose published board is the
  // user-meaningful display number (e.g. KTC TE++).  Backend stamps
  // this sparsely; absent → empty object.  Read by the popup chip
  // render and the per-player chart for ``_RAW_VALUE_PREFERRED_KEYS``
  // so the displayed value matches the source's website.
  const rawSourceValues =
    player.rawSourceValues && typeof player.rawSourceValues === "object"
      ? player.rawSourceValues
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
    // Stable Sleeper id for ID-first ownership resolution.  Backend
    // playersArray rows and mergeRankingsDelta-synthesized rows carry
    // it as ``playerId``; ``_sleeperId`` covers any legacy-shaped row
    // routed through this materializer (Codex rounds 5+7 on PR #535;
    // keep in lockstep with the legacy materializer + override
    // synthesis).
    playerId: String(player.playerId || player._sleeperId || "").trim() || null,
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
    // Missing confidence stays NULL, never 0 (audit N2, 2026-07-29).
    // 256 of 1094 live rows carry no ``marketConfidence``; coercing
    // those to 0 put them under the 0.35 ``low_conf_unstable``
    // threshold, so the MONITOR rule fired on rows that simply lack the
    // field rather than on genuinely low-confidence ones.
    // That rule was retired 2026-07-30, so nothing consumes this for a
    // verdict any more — but absent-is-not-zero is the right contract for
    // a measurement regardless, and this is the row field the terminal
    // signal context reads.
    // C1-U5: prefer the honest name, fall back to the deprecated alias so a
    // bundle can serve an old payload and vice versa during a rolling deploy.
    // The null-not-zero rule below is unchanged (audit N2).
    confidence: Number.isFinite(
      Number(player.marketBreadthAgreementIndex ?? player.marketConfidence),
    )
      ? Number(player.marketBreadthAgreementIndex ?? player.marketConfidence)
      : null,
    marketLabel: "",
    canonicalSites,
    rawSourceValues,
    canonicalConsensusRank: backendRank,
    rankDerivedValue: backendValue,
    canonicalTierId: Number(player.canonicalTierId) || null,
    // Rank movement since the previous scrape.  Positive = moved
    // UP, negative = down, null = new or previously unranked.
    rankChange:
      typeof player.rankChange === "number" ? player.rankChange : null,
    // Audit stamps from the backend post-passes.  Rendered in the
    // PlayerPopup and (for ``twoWayPlayerBoost``) as an optional
    // inline badge on the rankings row.
    marketCorridorClamp:
      player.marketCorridorClamp &&
      typeof player.marketCorridorClamp === "object"
        ? player.marketCorridorClamp
        : null,
    twoWayPlayerBoost:
      player.twoWayPlayerBoost && typeof player.twoWayPlayerBoost === "object"
        ? player.twoWayPlayerBoost
        : null,
    sourceRanks: backendSourceRanks,
    // Post-Hampel-filter rank map used by display helpers
    // (display-helpers.js::marketEdge / marketGapLabel) so retail-vs-
    // consensus edge labels agree with backend marketGapDirection /
    // confidence / anomaly flags, all of which are computed on the
    // post-Hampel set.  Falls back to `{}` for legacy payloads.
    effectiveSourceRanks:
      player.effectiveSourceRanks &&
      typeof player.effectiveSourceRanks === "object"
        ? player.effectiveSourceRanks
        : {},
    droppedSources: Array.isArray(player.droppedSources)
      ? player.droppedSources
      : [],
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
    // ``marketGapValueRatio`` is the live number (relative gap in value
    // space).  ``marketGapMagnitude`` is the retired rank-space field, which
    // the backend now stamps None on every row; it is forwarded only so a
    // consumer reading it sees the explicit null rather than an absent key.
    marketGapValueRatio: player.marketGapValueRatio ?? null,
    marketGapMagnitude: player.marketGapMagnitude ?? null,
    sourceOriginalRanks:
      player.sourceOriginalRanks &&
      typeof player.sourceOriginalRanks === "object"
        ? player.sourceOriginalRanks
        : {},
    // Native vendor values for rank-signal sources — the real number
    // behind the synthetic encoding in canonicalSites (parallel map
    // to sourceOriginalRanks; keep both materializers in lockstep).
    sourceNativeValues:
      player.sourceNativeValues && typeof player.sourceNativeValues === "object"
        ? player.sourceNativeValues
        : {},
    // NFL years of experience (0 = rookie) — drives the experience
    // filter; null when the Sleeper blob never matched this player.
    yearsExp:
      Number.isFinite(Number(player.yearsExp)) && player.yearsExp !== null
        ? Number(player.yearsExp)
        : Number.isFinite(Number(player._yearsExp)) && player._yearsExp !== null
          ? Number(player._yearsExp)
          : null,
    identityResolutionConfidence: Number(
      player.identityResolutionConfidence ?? player.identityConfidence ?? 0.7,
    ),
    // Deprecated alias, emitted for the declared window so a component that
    // still reads the old name keeps working while it migrates.
    identityConfidence: Number(
      player.identityResolutionConfidence ?? player.identityConfidence ?? 0.7,
    ),
    identityMethod: String(player.identityMethod || "name_only"),
    quarantined: Boolean(player.quarantined),
    // rankHistory: array of { date, rank } points stamped by the
    // backend from ``data/rank_history.jsonl`` (up to 180 days).  The
    // PlayerPopup mini-chart reads this directly; defaults to null
    // when the player wasn't ranked at the time of any snapshot.
    rankHistory: Array.isArray(player.rankHistory) ? player.rankHistory : null,
    raw: player,
  };
}

function _materializeLegacyDictRow(name, player, posMap) {
  if (!player || typeof player !== "object") return null;
  const isPick =
    /\b(20\d{2})\s+(early|mid|late)?\s*(1st|2nd|3rd|4th|5th|6th|round|r\d|pick)/i.test(
      name,
    ) || /^20\d{2}\s+pick/i.test(name);
  const pos = isPick
    ? "PICK"
    : normalizePos(posMap[name] || player.position || "");
  if (classifyPos(pos) === "excluded") return null;

  const rawValues = inferValueBundle(player);
  const canonicalSites =
    player._canonicalSiteValues &&
    typeof player._canonicalSiteValues === "object"
      ? player._canonicalSiteValues
      : {};
  // Legacy dict rows carry raw scrape values at the top level (e.g.
  // ``player.ktcSfTep``).  Mirror the playersArray materializer's
  // ``rawSourceValues`` field for the popup chip render — KTC TE++
  // is the only entry today.  Sparse: only present when the raw
  // value is a positive integer.
  const rawSourceValues = {};
  for (const k of ["ktcSfTep"]) {
    const v = Number(player?.[k]);
    if (Number.isFinite(v) && v > 0) rawSourceValues[k] = Math.round(v);
  }
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
    // Stable Sleeper id, materialized so ID-first ownership
    // resolution works on the DEFAULT view=app path too — the legacy
    // dict carries it as _sleeperId only (Codex round 5 on PR #535;
    // keep in lockstep with the playersArray materializer + override
    // synthesis).
    playerId: String(player._sleeperId || "").trim() || null,
    pos: pos || "?",
    team: String(player.team || ""),
    age: Number(player.age) || null,
    // Combine BOTH upstream rookie signals like the contract row
    // builder does (_formatFitRookie = format-fit pass, _isRookie =
    // scraper's zero-experience flag) — the live export has rookies
    // carrying only _isRookie, so reading one signal alone made
    // rookie filters exclude every actual rookie on the view=app
    // path (Codex round 4 on PR #535).
    rookie: Boolean(
      player._formatFitRookie || player._isRookie || player.rookie,
    ),
    assetClass: classifyPos(pos || "?"),
    values,
    siteCount: Number(player.sourceCount || player._sites || 0),
    // ``_marketReliabilityScore`` DOES NOT EXIST (audit N2, 2026-07-29).
    // It appeared exactly once in the entire repo — right here, the
    // consumer — and nothing has ever produced it: 0 of 1076 players in
    // the live payload carry it, while 838 carry ``_marketConfidence``.
    // So this field was permanently 0, which is under the 0.35
    // threshold, so ``low_conf_unstable`` fired for every eligible row
    // on the legacy path. Reads the field that is actually stamped, and
    // keeps absent as null rather than 0. (That rule was retired
    // 2026-07-30; reading the real field is still correct.)
    // C1-U5: same lockstep as the playersArray materializer above.
    confidence: Number.isFinite(
      Number(player._marketBreadthAgreementIndex ?? player._marketConfidence),
    )
      ? Number(player._marketBreadthAgreementIndex ?? player._marketConfidence)
      : null,
    marketLabel: String(player._marketReliabilityLabel || ""),
    canonicalSites,
    rawSourceValues,
    canonicalConsensusRank: backendRank,
    rankDerivedValue: backendValue,
    canonicalTierId: Number(player._canonicalTierId) || null,
    sourceRanks:
      player.sourceRanks && typeof player.sourceRanks === "object"
        ? player.sourceRanks
        : {},
    // See ``_materializePlayerArrayRow`` for the rationale on these
    // two fields — keep both materializers in lockstep.
    effectiveSourceRanks:
      player.effectiveSourceRanks &&
      typeof player.effectiveSourceRanks === "object"
        ? player.effectiveSourceRanks
        : {},
    droppedSources: Array.isArray(player.droppedSources)
      ? player.droppedSources
      : [],
    sourceRankMeta:
      player.sourceRankMeta && typeof player.sourceRankMeta === "object"
        ? player.sourceRankMeta
        : {},
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
    sourceAudit:
      player.sourceAudit && typeof player.sourceAudit === "object"
        ? player.sourceAudit
        : null,
    marketGapDirection: String(player.marketGapDirection || "none"),
    // ``marketGapValueRatio`` is the live number (relative gap in value
    // space).  ``marketGapMagnitude`` is the retired rank-space field, which
    // the backend now stamps None on every row; it is forwarded only so a
    // consumer reading it sees the explicit null rather than an absent key.
    marketGapValueRatio: player.marketGapValueRatio ?? null,
    marketGapMagnitude: player.marketGapMagnitude ?? null,
    sourceOriginalRanks:
      player.sourceOriginalRanks &&
      typeof player.sourceOriginalRanks === "object"
        ? player.sourceOriginalRanks
        : {},
    // Native vendor values for rank-signal sources — the real number
    // behind the synthetic encoding in canonicalSites (parallel map
    // to sourceOriginalRanks; keep both materializers in lockstep).
    sourceNativeValues:
      player.sourceNativeValues && typeof player.sourceNativeValues === "object"
        ? player.sourceNativeValues
        : {},
    // NFL years of experience (0 = rookie) — drives the experience
    // filter; null when the Sleeper blob never matched this player.
    yearsExp:
      Number.isFinite(Number(player.yearsExp)) && player.yearsExp !== null
        ? Number(player.yearsExp)
        : Number.isFinite(Number(player._yearsExp)) && player._yearsExp !== null
          ? Number(player._yearsExp)
          : null,
    identityResolutionConfidence: Number(
      player.identityResolutionConfidence ?? player.identityConfidence ?? 0.7,
    ),
    // Deprecated alias, emitted for the declared window so a component that
    // still reads the old name keeps working while it migrates.
    identityConfidence: Number(
      player.identityResolutionConfidence ?? player.identityConfidence ?? 0.7,
    ),
    identityMethod: String(player.identityMethod || "name_only"),
    quarantined: Boolean(player.quarantined),
    // Same history field, mirrored onto the legacy-dict code path.
    rankHistory: Array.isArray(player.rankHistory) ? player.rankHistory : null,
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
    if (
      r &&
      Number.isInteger(r.canonicalConsensusRank) &&
      r.canonicalConsensusRank > 0
    ) {
      return true;
    }
  }
  return false;
}

export function buildRows(data) {
  const players = data?.players || {};
  const playersArray = Array.isArray(data?.playersArray)
    ? data.playersArray
    : [];
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
  // When a valuation overlay is applied, ranked rows sort by the SERVED
  // rank rather than by value.  Python rounds half-to-even and JS rounds
  // half-up, so `consensus x factor` can differ by one unit between the
  // two — enough to swap adjacent rows against the ranks the server
  // sent, which renders as a `#100, #101, #100` stutter in the `#`
  // column.  Null-rank rows still interleave by value.
  const overlayActive = Boolean(data?.valuationOverlay);
  rows.sort((a, b) => {
    if (overlayActive) {
      const ra = a.canonicalConsensusRank ?? null;
      const rb = b.canonicalConsensusRank ?? null;
      if (ra != null && rb != null) return ra - rb;
    }
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
    } else if (r.assetClass === "pick" || overlayActive) {
      // With an overlay active the local ordinal would be derived from
      // ADJUSTED values — a client-computed rank in the `#` column,
      // which is the one thing `buildRows` must never produce.
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
// The multi-MB base contract is fetched by every ``useDynastyData``
// mount — and the hook mounts at least twice per page (AppShell + the
// page itself), with more mounts on league/auth events.  This block
// collapses all of that onto one network fetch:
//
//   * ``_cachedBaseContract`` — last successful payload.  Cache key is
//     ``(leagueKey, view)``; TTL is ``_BASE_CONTRACT_TTL_MS`` (30s,
//     matching the server's ``Cache-Control: max-age=30`` — the client
//     never holds data longer than the HTTP layer already permits).
//     After the TTL the refetch goes out with ``cache: "no-cache"``,
//     so an unchanged contract revalidates to a 304 instead of a
//     multi-MB re-download.
//   * ``_inflightBaseContract`` — in-flight promise, so concurrent
//     mounts share one request instead of racing duplicates.
//   * Invalidation: ``_resetBaseContractCache()`` (league switch via
//     ``useLeague``, tests) and the module-scope ``auth:changed``
//     listener below.  Errors are never cached.
//
// NOTE: rankings are scoped by scoring profile (see CLAUDE.md).  When
// two leagues share a profile they share this cached contract.  We
// still pass ``leagueKey`` on the wire so the server can stamp the
// response with the right league's ``sleeper`` block (or null it
// when the specific league's roster data isn't loaded yet).
const _BASE_CONTRACT_TTL_MS = 30_000;
let _cachedBaseContract = null;
let _cachedBaseContractKey = "";
let _cachedBaseContractAt = 0;
let _inflightBaseContract = null; // { key, promise }

// Memo of the final merged override result (base + delta).  Keyed on
// the POST body + league + the base contract's object identity, so a
// new base generation (or league switch) invalidates it naturally.
// Same 30s TTL as the base cache.  Collapses the duplicate
// ``POST /api/rankings/overrides`` fired by the double-mounted hook.
let _cachedOverrideResult = null; // { key, base, at, value }
let _inflightOverrideResult = null; // { key, base, promise }

// Key to read the active league from localStorage — written by
// ``useLeague`` whenever the user switches leagues.  We can't
// ``useLeague`` here because this module is imported by
// ``useLeague`` itself (via ``_resetBaseContractCache``); localStorage
// is the cycle-safe way to share the value.
const LEAGUE_LOCAL_KEY = "next_active_league_v1";

function _readActiveLeagueKey() {
  if (typeof window === "undefined") return "";
  try {
    return localStorage.getItem(LEAGUE_LOCAL_KEY) || "";
  } catch {
    return "";
  }
}

/** Clear every in-memory contract cache (base, merged override
 * result, in-flight markers).  Called on league switch (``useLeague``),
 * on ``auth:changed``, and from tests. */
export function _resetBaseContractCache() {
  _cachedBaseContract = null;
  _cachedBaseContractKey = "";
  _cachedBaseContractAt = 0;
  _inflightBaseContract = null;
  _cachedOverrideResult = null;
  _inflightOverrideResult = null;
}

// Login/logout must drop cached private payloads immediately — the
// TTL alone would let a just-logged-out session keep rendering them.
// (League switches already call ``_resetBaseContractCache`` directly
// via ``useLeague``.)
if (typeof window !== "undefined") {
  window.addEventListener("auth:changed", _resetBaseContractCache);
}

async function _fetchBaseContract() {
  const leagueKey = _readActiveLeagueKey();
  // Mobile / slow-network callers get the compact view (~500KB vs
  // ~4MB full) — the frontend materializer tolerates the pruned
  // fields.  Lazy import so this module stays SSR-safe.
  let view = null;
  try {
    const dp = await import("./device-profile.js");
    view = dp.preferredDataView?.() || null;
  } catch {
    // device-profile is advisory only; absence just keeps old default.
  }
  const cacheKey = `${leagueKey}|${view || ""}`;
  if (
    _cachedBaseContract &&
    _cachedBaseContractKey === cacheKey &&
    Date.now() - _cachedBaseContractAt < _BASE_CONTRACT_TTL_MS
  ) {
    return _cachedBaseContract;
  }
  if (_inflightBaseContract && _inflightBaseContract.key === cacheKey) {
    return _inflightBaseContract.promise;
  }
  const promise = _fetchBaseContractNetwork(leagueKey, view, cacheKey);
  _inflightBaseContract = { key: cacheKey, promise };
  try {
    return await promise;
  } finally {
    if (_inflightBaseContract && _inflightBaseContract.promise === promise) {
      _inflightBaseContract = null;
    }
  }
}

async function _fetchBaseContractNetwork(leagueKey, view, cacheKey) {
  // Append leagueKey so the server can stamp ``meta.leagueKey`` and
  // ``meta.sleeperDataReady`` correctly on the response.  When the
  // active league shares the scoring profile with the loaded
  // contract, the server serves the common rankings with a nulled
  // ``sleeper`` block.  When profiles differ, the server 503s and
  // we surface the error the same way as any other data failure.
  const params = new URLSearchParams();
  if (leagueKey) params.set("leagueKey", leagueKey);
  if (view && view !== "delta") params.set("view", view);
  const qs = params.toString();
  const url = qs ? `${DEFAULT_DATA_URL}?${qs}` : DEFAULT_DATA_URL;
  // ``no-cache`` (not ``no-store``): the browser may STORE the response
  // but must REVALIDATE before every reuse.  The backend serves this
  // contract with ``Cache-Control: private, max-age=30,
  // stale-while-revalidate=300`` plus an ``ETag``, and the
  // ``_private_api_gate`` middleware 401s unauthenticated requests
  // before any 304 can be minted — so after logout the revalidation
  // fails and the cached payload is never replayed.  What ``no-cache``
  // buys over ``no-store``: an unchanged contract answers with a
  // zero-body 304 instead of a multi-MB re-download on every
  // navigation past the in-memory TTL.
  const res = await fetch(url, { cache: "no-cache" });
  if (!res.ok) {
    const txt = await res.text();
    throw new Error(`Failed to load dynasty data: ${res.status} ${txt}`);
  }
  const json = await res.json();

  // The Next.js API route wraps the payload: { ok, source, data: <contract> }
  // The Python backend alias returns the raw contract.  Normalize both.
  let wrapped;
  if (
    json &&
    typeof json === "object" &&
    !json.data &&
    (json.players || json.playersArray)
  ) {
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
    _cachedBaseContractKey = cacheKey;
    _cachedBaseContractAt = Date.now();
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
/**
 * Which board produced the numbers in `contract` — "market" or
 * "leagueAdjusted".
 *
 * Read this rather than `settings.valuationMode`. The setting is what
 * the user ASKED for; this is what they GOT, and the two legitimately
 * diverge:
 *
 *   - the overlay fetch can fail, and `fetchDynastyData` degrades to
 *     the market board rather than serving half a lens;
 *   - the version pin in `applyValuationOverlay` refuses an overlay
 *     built against a different scrape;
 *   - the server can find no roster snapshot, so scarcity is
 *     unmeasurable, and returns market values with a note.
 *
 * In every one of those the setting still says "leagueAdjusted" while
 * the numbers are market. Labelling off the setting would assert a
 * basis the board does not have — which is the whole failure this
 * accessor exists to prevent.
 *
 * Accepts either the contract or its `{data}` envelope.
 */
export function valuationBasisOf(contract) {
  const data = contract?.data || contract;
  if (!data) return "market";
  if (data.valuationOverlay?.mode === "leagueAdjusted") return "leagueAdjusted";
  return "market";
}

/**
 * Human-readable one-liner naming the basis, for export headers and
 * page disclosures. Exports need this most: once a spreadsheet leaves
 * the app nothing distinguishes adjusted values from market ones.
 */
export function valuationBasisLabel(contract) {
  return valuationBasisOf(contract) === "leagueAdjusted"
    ? "League-adjusted (positional scarcity from this league's rosters)"
    : "Market consensus";
}

export function mergeRankingsDelta(baseContract, delta) {
  if (!baseContract || !delta) return baseContract;
  const base = baseContract.data || baseContract;
  const rankingsDelta = delta.rankingsDelta;
  if (!rankingsDelta || !Array.isArray(rankingsDelta.players))
    return baseContract;
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

  // Carry the server-composed valuation basis onto the SAME field the
  // client-side overlay path stamps, so every consumer has one question
  // to ask instead of two.
  //
  // Without this the server-composed board (custom weights + the lens,
  // which the server now computes) would arrive with adjusted values and
  // NO `valuationOverlay`, and /trade's "Valued on your league's board"
  // banner — which gates on that field — would go silent on precisely
  // the board that most needs labelling.
  //
  // The server's stamp is authoritative over the request: it can degrade
  // to market when there is no roster snapshot, without the user's
  // setting changing. `serverComposed` marks the provenance so a reader
  // can tell the two paths apart.
  if (delta.meta?.valuationMode === "leagueAdjusted") {
    mergedData.valuationOverlay = {
      mode: "leagueAdjusted",
      serverComposed: true,
      adjustedCount: delta.valuationAdjustment?.adjustedCount ?? null,
    };
  } else if (delta.meta?.valuationNote) {
    // Requested but not delivered. Record why rather than leaving the
    // absence to be read as "the user never asked".
    mergedData.valuationOverlay = null;
    mergedData.valuationNote = delta.meta.valuationNote;
  }

  const basePlayersArray = Array.isArray(base.playersArray)
    ? base.playersArray
    : [];

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
        basePlayer[playerKey] ||
          basePlayer.displayName ||
          basePlayer.canonicalName ||
          "",
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
    const posMap = (base.sleeper && base.sleeper.positions) || {};
    const PICK_RE =
      /\b(20\d{2})\s+(early|mid|late)?\s*(1st|2nd|3rd|4th|5th|6th|round|r\d|pick)/i;
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
        // Stable Sleeper id — required by ID-first ownership
        // resolution (player-filters resolveOwnerTeam); without it
        // every override-synthesized row degrades to name lookup and
        // offense/IDP name twins can inherit each other's owner
        // (Codex round 3 on PR #535).
        playerId: String(legacy._sleeperId || "").trim() || null,
        position: isPick ? "PICK" : String(posMap[id] || legacy.position || ""),
        team: legacy.team != null ? legacy.team : null,
        age: legacy.age != null ? legacy.age : null,
        // Override-invariant like team/age: without this copy the
        // experience filters return an empty board whenever a source
        // override is active (fail-closed predicate over null).
        yearsExp: legacy._yearsExp != null ? legacy._yearsExp : null,
        rookie: Boolean(
          legacy._formatFitRookie || legacy._isRookie || legacy.rookie,
        ),
        assetClass: String(legacy.assetClass || ""),
        identityResolutionConfidence: Number(
          legacy.identityResolutionConfidence ??
            legacy.identityConfidence ??
            0.7,
        ),
        identityConfidence: Number(
          legacy.identityResolutionConfidence ??
            legacy.identityConfidence ??
            0.7,
        ),
        identityMethod: String(legacy.identityMethod || "name_only"),
        // Carry forward the pre-override canonical site values so
        // the retail-vs-consensus gap column can fall back when the
        // delta dropped a source.
        canonicalSiteValues:
          legacy._canonicalSiteValues &&
          typeof legacy._canonicalSiteValues === "object"
            ? legacy._canonicalSiteValues
            : {},
        // Vendor-native values are override-INVARIANT (toggling a
        // source never changes what the vendor published), so the
        // delta deliberately omits them — copy from the legacy
        // mirror or the tooltips lose natives while an override is
        // active (Codex review on PR #532 round 8).
        sourceNativeValues:
          legacy.sourceNativeValues &&
          typeof legacy.sourceNativeValues === "object"
            ? legacy.sourceNativeValues
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

// League-scoped, unlike ``_cachedBaseContract`` which is
// scoring-profile-scoped. Reset together on a league switch.
let _cachedValuationOverlay = null;
let _inflightValuationOverlay = null;

export function _resetValuationOverlayCache() {
  _cachedValuationOverlay = null;
  _inflightValuationOverlay = null;
}

async function _fetchValuationOverlay() {
  if (_cachedValuationOverlay) return _cachedValuationOverlay;
  if (_inflightValuationOverlay) return _inflightValuationOverlay;
  const promise = _fetchValuationOverlayNetwork();
  _inflightValuationOverlay = promise;
  try {
    return await promise;
  } finally {
    if (_inflightValuationOverlay === promise) {
      _inflightValuationOverlay = null;
    }
  }
}

async function _fetchValuationOverlayNetwork() {
  try {
    const leagueKey = _readActiveLeagueKey();
    const qs = leagueKey ? `?leagueKey=${encodeURIComponent(leagueKey)}` : "";
    const res = await fetch(`/api/valuation/league-adjusted${qs}`, {
      cache: "no-store",
    });
    if (!res.ok) {
      console.warn(
        `[dynasty-data] valuation overlay ${res.status}; serving market values`,
      );
      return null;
    }
    const body = await res.json();
    if (!body || body.isNoop) return null;
    _cachedValuationOverlay = body;
    return body;
  } catch (err) {
    console.warn(
      "[dynasty-data] valuation overlay fetch failed; serving market values",
      err,
    );
    return null;
  }
}

/**
 * Apply the league-adjusted valuation overlay to a contract.
 *
 * NOT ``mergeRankingsDelta``.  That function's runtime-view branch
 * synthesizes ``playersArray`` from delta entries only, so a player the
 * delta doesn't mention disappears; and its ``activePlayerIds`` branch
 * nulls the rank of anything absent.  Both are correct for a dense
 * override delta and catastrophic for this overlay, where ``factors``
 * is sparse and absence means "unchanged".
 *
 * Writes TWO key sets, because the two materializers disagree:
 *   - ``playersArray`` rows carry ``canonicalConsensusRank`` / ``canonicalTierId``
 *   - the legacy ``players`` dict carries ``_canonicalConsensusRank`` /
 *     ``_canonicalTierId`` — but ``rankDerivedValue`` with no underscore
 *
 * The legacy path is the DEFAULT one (``server.py`` pops ``playersArray``
 * off the runtime payload), so an applier that writes only the first set
 * moves the value and leaves the rank stale — on the path that actually
 * ships, and nowhere else.
 *
 * Copy-on-write: untouched rows are returned by reference.
 */
/**
 * Where the experimental league-aware number goes on the client.
 * Must stay identical to ``EXPERIMENTAL_VALUE_FIELD`` in
 * ``src/league_intel/overlay.py`` — the server and client appliers
 * disagreeing about a field name is how the server ended up scaling
 * ``rankDerivedValue`` while leaving ``values.*`` at market.
 */
export const EXPERIMENTAL_LEAGUE_ADJUSTED_VALUE =
  "experimentalLeagueAdjustedValue";

export function applyValuationOverlay(baseContract, overlay) {
  if (!baseContract || !overlay) return baseContract;
  const factors = overlay.factors;
  if (
    !factors ||
    typeof factors !== "object" ||
    Object.keys(factors).length === 0
  ) {
    return baseContract;
  }

  const data = baseContract.data || baseContract;

  // Version pin.  Overlay ranks are computed against one contract
  // build; a scrape landing between the base fetch and the overlay
  // fetch would apply board B's ranks to board A's values.  Refuse
  // outright rather than half-apply — a board whose ranks disagree with
  // its values is worse than the market board.
  const baseStamp = data.scrapeTimestamp;
  const overlayStamp = overlay.scrapeTimestamp;
  if (baseStamp && overlayStamp && baseStamp !== overlayStamp) {
    console.warn(
      "[dynasty-data] valuation overlay is for a different scrape " +
        `(base ${baseStamp} vs overlay ${overlayStamp}); serving market values`,
    );
    return baseContract;
  }

  const ranks = overlay.ranks || {};
  const tiers = overlay.tiers || {};
  const scale = (v, f) => {
    const n = Number(v);
    return Number.isFinite(n) && n > 0 ? Math.round(n * f) : v;
  };

  const nextData = {
    ...data,
    valuationOverlay: { mode: "leagueAdjusted", ...overlay },
  };

  if (Array.isArray(data.playersArray) && data.playersArray.length > 0) {
    nextData.playersArray = data.playersArray.map((row) => {
      const key = String(row?.displayName || row?.canonicalName || "").trim();
      const f = factors[key];
      const hasRank = Object.prototype.hasOwnProperty.call(ranks, key);
      if (!f && !hasRank) return row;
      const next = { ...row };
      if (f) {
        // WITHDRAWN 2026-08-14 — mirrors src/league_intel/overlay.py.
        // The canonical value and its aliases are left alone; the
        // adjusted number goes to its own field. This path is currently
        // unreachable (`leagueAdjusted` is false), but a client applier
        // that still overwrote canonical would be a loaded gun pointed at
        // the invariant the rest of this change establishes.
        next[EXPERIMENTAL_LEAGUE_ADJUSTED_VALUE] = scale(
          row.rankDerivedValue,
          f,
        );
      }
      if (hasRank) {
        next.canonicalConsensusRank = ranks[key];
        if (tiers[key] != null) next.canonicalTierId = tiers[key];
      } else if (f) {
        // Moved in value but not on the ranked board (past the cap, or
        // an anchor slot pick). Leave the rank null rather than letting
        // buildRows derive one from the adjusted sort order.
        next.canonicalConsensusRank = null;
      }
      // "moved up N since the previous scrape" is a statement about the
      // market board. Next to an adjusted rank it is simply false.
      next.rankChange = null;
      return next;
    });
  }

  if (data.players && typeof data.players === "object") {
    const nextPlayers = {};
    for (const [name, row] of Object.entries(data.players)) {
      const f = factors[name];
      const hasRank = Object.prototype.hasOwnProperty.call(ranks, name);
      if (!f && !hasRank) {
        nextPlayers[name] = row;
        continue;
      }
      const next = { ...row };
      if (f) {
        // Same rule on the legacy dict path — canonical untouched.
        next[EXPERIMENTAL_LEAGUE_ADJUSTED_VALUE] = scale(
          row.rankDerivedValue,
          f,
        );
      }
      if (hasRank) {
        next._canonicalConsensusRank = ranks[name];
        if (tiers[name] != null) next._canonicalTierId = tiers[name];
      } else if (f) {
        next._canonicalConsensusRank = null;
      }
      next._rankChange = null;
      nextPlayers[name] = next;
    }
    nextData.players = nextPlayers;
  }

  return { ...baseContract, source: "backend:leagueAdjusted", data: nextData };
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
  const rawTepNative = opts.tepNativeMultiplier;
  const tepNativeMultiplier =
    rawTepNative === null || rawTepNative === undefined
      ? null
      : Number.isFinite(Number(rawTepNative))
        ? Number(rawTepNative)
        : null;
  const sitesCustomized = siteOverridesAreCustomized(siteOverrides);
  const tepCustomized = tepMultiplierIsCustomized(tepMultiplier);
  const tepNativeCustomized =
    tepNativeMultiplierIsCustomized(tepNativeMultiplier);

  // CUSTOM MIX DISABLED 2026-08-14 — enforced SERVER-SIDE, deliberately.
  //
  // `siteWeights`, `tepMultiplier` and `tepNativeMultiplier` all live in
  // `next_settings_v2` in localStorage, are never server-synced, and all
  // three ride this override path — which returned the recomputed board
  // under `rankDerivedValue` (it is in `_DELTA_PLAYER_FIELDS`). Two
  // devices with different stored settings therefore rendered different
  // canonical values for one player, exactly as `valuationMode` did.
  //
  // The withdrawal lives in `normalize_source_overrides`, NOT here. The
  // client may still post its stored mix; the server ignores it, serves
  // the canonical board and says why in `warnings`. That is the point:
  // canonical value is authority-owned, so the guarantee cannot depend on
  // every client agreeing to stop asking — including stale bundles and
  // direct callers, which a client-side flag would not cover.
  //
  // Narrower than `valuationMode` was: server-side engines read
  // `latest_contract_data` and never saw the override board, and neither
  // history writer runs on this path — so trade math and recorded history
  // were already canonical-safe. The exposure was the /rankings display.
  //
  // The LEAGUE-DERIVED TE premium is unaffected and still applies: the
  // server derives it from the league's own Sleeper `bonus_rec_te`. Only
  // the user's manual override is withdrawn.
  const customized = sitesCustomized || tepCustomized || tepNativeCustomized;

  // WITHDRAWN 2026-08-14 — one canonical methodology. `readValuationMode`
  // now always answers `market`, so callers that still pass a mode get
  // the canonical board. Kept as a named constant rather than deleted so
  // the composition branches below stay readable and a future validated
  // methodology has one flag to flip.
  const leagueAdjusted = false;

  // Default path (no overrides): fetch + cache the base contract.
  // The backend will derive tep_multiplier from the operator's
  // Sleeper league ``bonus_rec_te`` and bake it into the blend for
  // us, so the frontend doesn't need to POST anything.
  if (!customized) {
    const base = await _fetchBaseContract();
    if (!leagueAdjusted) return base;
    const overlay = await _fetchValuationOverlay();
    // A failed overlay fetch degrades to the market board. Half a
    // valuation lens is not a lens.
    return overlay ? applyValuationOverlay(base, overlay) : base;
  }

  // Source overrides + league-adjusted are now composed SERVER-SIDE.
  //
  // They were previously refused outright, and correctly so: the
  // overlay endpoint computes its ranks against the un-overridden
  // board, so applying them here would give the ranks of
  // `default_consensus x factor` when the right answer is the rank of
  // `overridden_consensus x factor`. No client-side sequencing fixes
  // that — the server had simply never computed that board.
  //
  // It does now. `valuation_mode` rides the override POST, the backend
  // runs the override pipeline first and applies the scarcity factors
  // to the resulting values, then re-ranks the adjusted board through
  // the same `compact_ranks_and_tiers` the default path uses. The
  // delta comes back with values, ranks and tiers that all describe
  // one board.
  //
  // `meta.valuationMode` on the response says which lens actually
  // produced it, because the server can still degrade to market (no
  // roster snapshot => no measurable scarcity). Callers read that
  // rather than assuming they got what they asked for.

  // Override path: POST the override map + TE premium multiplier to
  // the backend delta endpoint, then merge the delta onto the
  // cached base contract.  The backend bakes TEP into every TE's
  // rankDerivedValue stamp before producing the delta, so the
  // frontend never needs to multiply on render.

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
  if (tepNativeCustomized) {
    body.tep_native_multiplier = tepNativeMultiplier;
  }
  if (leagueAdjusted) {
    // Asking for the lens narrows this request to one league — the
    // backend 503s on a league mismatch when this is set, because
    // scarcity is measured from one league's rosters and the resulting
    // board is not shareable across leagues that merely share scoring.
    body.valuation_mode = "leagueAdjusted";
  }

  // Merged-result memo: the double-mounted hook fires two identical
  // override requests per page; serve the second from memory.  Key =
  // POST body + active league; a cached VALUE is additionally pinned
  // to the base contract object it was merged onto (a new base
  // generation or league switch yields a different reference) and the
  // shared 30s TTL.  Only successful merges are cached — a
  // fallback-to-base result must stay retryable.
  const overrideKey = `${JSON.stringify(body)}|${_readActiveLeagueKey()}`;
  if (
    _cachedOverrideResult &&
    _cachedOverrideResult.key === overrideKey &&
    _cachedOverrideResult.base === _cachedBaseContract &&
    _cachedBaseContract &&
    Date.now() - _cachedBaseContractAt < _BASE_CONTRACT_TTL_MS &&
    Date.now() - _cachedOverrideResult.at < _BASE_CONTRACT_TTL_MS
  ) {
    return _cachedOverrideResult.value;
  }
  if (_inflightOverrideResult && _inflightOverrideResult.key === overrideKey) {
    return _inflightOverrideResult.promise;
  }
  // Base fetch and overrides POST run CONCURRENTLY — the POST never
  // needed the base payload (only the merge does), yet they used to
  // run serially, putting a full extra round-trip on the critical
  // path of every first page view.
  const promise = _postOverridesAndMerge(
    _fetchBaseContract(),
    body,
    overrideKey,
  );
  _inflightOverrideResult = { key: overrideKey, promise };
  try {
    return await promise;
  } finally {
    if (
      _inflightOverrideResult &&
      _inflightOverrideResult.promise === promise
    ) {
      _inflightOverrideResult = null;
    }
  }
}

async function _postOverridesAndMerge(basePromise, body, overrideKey) {
  // Kick the POST off immediately (it never needed the base payload)
  // and hold its failure in-band so the two error semantics stay
  // exactly what they were on the serial path:
  //   * base fetch failure → THROWS out of fetchDynastyData (the page
  //     shows its error state);
  //   * overrides POST failure → falls back to the base contract.
  const postPromise = fetch(`${RANKINGS_OVERRIDES_URL}?view=delta`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
    cache: "no-store",
  }).catch((err) => {
    if (typeof console !== "undefined" && console.warn) {
      console.warn(
        "[dynasty-data] /api/rankings/overrides request failed:",
        err?.message || err,
      );
    }
    return null;
  });
  const base = await basePromise;
  try {
    const overrideRes = await postPromise;
    if (overrideRes && overrideRes.ok) {
      const deltaPayload = await overrideRes.json();
      if (
        deltaPayload &&
        deltaPayload.mode === "delta" &&
        deltaPayload.rankingsDelta
      ) {
        const merged = mergeRankingsDelta(base, deltaPayload);
        _cachedOverrideResult = {
          key: overrideKey,
          base,
          at: Date.now(),
          value: merged,
        };
        return merged;
      }
      // Full-contract fallback: the backend may have returned a full
      // payload (e.g. proxy stripped view=delta).  Pass through.
      if (deltaPayload && (deltaPayload.players || deltaPayload.playersArray)) {
        const passthrough = {
          ok: true,
          source: "backend:override",
          data: deltaPayload,
        };
        _cachedOverrideResult = {
          key: overrideKey,
          base,
          at: Date.now(),
          value: passthrough,
        };
        return passthrough;
      }
    } else if (overrideRes && typeof console !== "undefined" && console.warn) {
      console.warn(
        `[dynasty-data] /api/rankings/overrides returned ${overrideRes.status}; ` +
          "falling through to base contract.",
      );
    }
  } catch (err) {
    if (typeof console !== "undefined" && console.warn) {
      console.warn(
        "[dynasty-data] /api/rankings/overrides response handling failed:",
        err?.message || err,
      );
    }
  }

  // Override endpoint failed — return the base contract unchanged.
  return base;
}

/**
 * Warm the base-contract cache without waiting for settings hydration.
 *
 * The base contract does not depend on user settings — only the
 * overrides POST does — yet the data hook's fetch effect gates on
 * ``settingsHydrated``, so the largest download of the page used to
 * start only after the settings store + auth probe settled.  Calling
 * this from the hook's mount effect starts the download immediately;
 * the real ``fetchDynastyData`` call then hits the in-flight promise
 * (or the fresh cache) instead of the network.  Errors are swallowed:
 * this is purely advisory warming, and the real fetch surfaces them.
 */
export function prefetchBaseContract() {
  try {
    const p = _fetchBaseContract();
    if (p && typeof p.catch === "function") p.catch(() => {});
    return p;
  } catch {
    return null;
  }
}
