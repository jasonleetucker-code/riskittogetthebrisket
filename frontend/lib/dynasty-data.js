// ── RANKINGS — UNIFIED BOARD ─────────────────────────────────────────────────
// This file (frontend/lib/dynasty-data.js) is the canonical frontend home for:
//   • rankToValue()         — Hill-style rank-to-value formula (offline fallback)
//   • computeUnifiedRanks() — per-source rank → normalize → unified overall sort
//   • OVERALL_RANK_LIMIT    — overall board cap (800)
//
// The backend authority is src/api/data_contract.py (_compute_unified_rankings).
//
// !! When changing ranking logic, formula constants, or eligibility rules !!
// !! you MUST update BOTH files and BOTH test suites to stay in sync.     !!
//   • JS tests:     frontend/__tests__/dynasty-data.test.js
//   • Python tests: tests/api/test_rankings_our_rank.py
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

export function normalizePos(pos) {
  const p = String(pos || "").toUpperCase();
  if (["DE", "DT", "EDGE", "NT"].includes(p)) return "DL";
  if (["CB", "S", "FS", "SS"].includes(p)) return "DB";
  if (["OLB", "ILB"].includes(p)) return "LB";
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

// Positions eligible for the unified board.  Mirrors
// `_RANKABLE_POSITIONS` in src/api/data_contract.py.  PICK is included
// here because KTC prices rookie picks natively and the overall_offense
// scope admits them.
const RANKABLE = new Set(["QB", "RB", "WR", "TE", "DL", "LB", "DB", "PICK"]);

// ── Source scope tokens (mirror src/canonical/idp_backbone.py) ──────
// See src/canonical/idp_backbone.py for the authoritative definitions.
// These MUST stay in sync with VALID_SOURCE_SCOPES on the backend.
export const SOURCE_SCOPE_OVERALL_OFFENSE = "overall_offense";
export const SOURCE_SCOPE_OVERALL_IDP = "overall_idp";
export const SOURCE_SCOPE_POSITION_IDP = "position_idp";

// Translation method tokens — also mirror the Python constants.
export const TRANSLATION_DIRECT = "direct";
export const TRANSLATION_EXACT = "exact";
export const TRANSLATION_INTERPOLATED = "interpolated";
export const TRANSLATION_EXTRAPOLATED = "extrapolated";
export const TRANSLATION_FALLBACK = "fallback";

const IDP_POSITION_GROUPS = ["DL", "LB", "DB"];
const OFFENSE_POSITIONS = new Set(["QB", "RB", "WR", "TE"]);
const IDP_POSITIONS_SET = new Set(IDP_POSITION_GROUPS);

// Scope eligibility predicate — mirrors _scope_eligible() in
// src/api/data_contract.py.  A row only receives a rank from a source
// if its position falls within the source's scope.
function scopeEligible(pos, scope, positionGroup) {
  const p = String(pos || "").toUpperCase();
  if (scope === SOURCE_SCOPE_OVERALL_OFFENSE) {
    return OFFENSE_POSITIONS.has(p) || p === "PICK";
  }
  if (scope === SOURCE_SCOPE_OVERALL_IDP) {
    return IDP_POSITIONS_SET.has(p);
  }
  if (scope === SOURCE_SCOPE_POSITION_IDP) {
    return Boolean(positionGroup) && p === String(positionGroup).toUpperCase();
  }
  return false;
}

// ── IDP backbone construction ───────────────────────────────────────
// Mirrors build_backbone_from_rows() in src/canonical/idp_backbone.py.
// Walks every row, keeps IDP entries with a positive value in the
// backbone source, sorts descending, and records per-position-group
// ladders of overall-IDP ranks.
//
// When ``includeSharedMarket`` is true the builder also emits a
// sharedMarketIdpLadder — combined offense+IDP ranks at which IDP
// entries appear in the backbone source's value pool.  IDP-only
// expert boards (DLF) crosswalk through this ladder so their raw IDP
// rank 1 is translated into the combined-pool rank of the best IDP
// instead of being fed to the Hill curve as shared-market rank 1.
function buildIdpBackbone(rows, sourceKey, includeSharedMarket = false) {
  const ladders = {};
  for (const pg of IDP_POSITION_GROUPS) ladders[pg] = [];
  if (!sourceKey) {
    return {
      ladders,
      depth: 0,
      sharedMarketIdpLadder: [],
      sharedMarketDepth: 0,
    };
  }

  const eligible = [];
  const combined = [];
  rows.forEach((r) => {
    const pos = String(r?.pos || "").toUpperCase();
    const isIdp = IDP_POSITIONS_SET.has(pos);
    const isOffense = OFFENSE_POSITIONS.has(pos) || pos === "PICK";
    if (!isIdp && !(includeSharedMarket && isOffense)) return;
    const val = Number(r?.canonicalSites?.[sourceKey]);
    if (!Number.isFinite(val) || val <= 0) return;
    const name = String(r?.name || "");
    if (isIdp) eligible.push({ val, pos, name });
    if (includeSharedMarket) combined.push({ val, pos, name, isIdp });
  });
  eligible.sort((a, b) => b.val - a.val || a.name.toLowerCase().localeCompare(b.name.toLowerCase()));

  let depth = 0;
  eligible.forEach((e, i) => {
    const overall = i + 1;
    if (ladders[e.pos]) ladders[e.pos].push(overall);
    depth = overall;
  });

  const sharedMarketIdpLadder = [];
  let sharedMarketDepth = 0;
  if (includeSharedMarket && combined.length) {
    combined.sort(
      (a, b) =>
        b.val - a.val ||
        a.name.toLowerCase().localeCompare(b.name.toLowerCase())
    );
    sharedMarketDepth = combined.length;
    combined.forEach((e, i) => {
      if (e.isIdp) sharedMarketIdpLadder.push(i + 1);
    });
  }

  return { ladders, depth, sharedMarketIdpLadder, sharedMarketDepth };
}

// ── Position-rank translation ───────────────────────────────────────
// Mirrors translate_position_rank() in src/canonical/idp_backbone.py.
// Translates a within-position rank (e.g. DL4) into a synthetic
// overall-IDP rank using the backbone ladder.  Integer ranks inside
// the ladder are exact anchors; fractional ranks interpolate linearly;
// ranks past the tail extrapolate with the average of the last few
// steps; empty ladders fall back to a pass-through.
function translatePositionRank(positionRank, ladder) {
  if (!Array.isArray(ladder) || ladder.length === 0) {
    const safe = Math.max(1, Math.round(Math.max(1, Number(positionRank) || 1)));
    return { rank: safe, method: TRANSLATION_FALLBACK };
  }

  let pr = Number(positionRank);
  if (!Number.isFinite(pr) || pr < 1) pr = 1;

  const n = ladder.length;
  // Integer exact anchor
  if (pr === Math.floor(pr) && pr >= 1 && pr <= n) {
    return { rank: Math.max(1, ladder[pr - 1]), method: TRANSLATION_EXACT };
  }
  // Interpolation inside the ladder
  if (pr >= 1 && pr <= n) {
    const lowIdx = Math.floor(pr) - 1;
    const frac = pr - Math.floor(pr);
    const low = ladder[lowIdx];
    const high = ladder[Math.min(lowIdx + 1, n - 1)];
    const synthetic = low + (high - low) * frac;
    return { rank: Math.max(1, Math.round(synthetic)), method: TRANSLATION_INTERPOLATED };
  }
  // Extrapolation past the tail
  let step;
  if (n === 1) {
    step = Math.max(1, ladder[0]);
  } else {
    const tail = Math.min(5, n - 1);
    let sum = 0;
    for (let i = 1; i <= tail; i++) sum += ladder[n - i] - ladder[n - i - 1];
    step = Math.max(1, sum / tail);
  }
  const overshoot = pr - n;
  let synthetic = Math.round(ladder[n - 1] + step * overshoot);
  if (synthetic <= ladder[n - 1]) synthetic = ladder[n - 1] + 1;
  return { rank: Math.max(1, synthetic), method: TRANSLATION_EXTRAPOLATED };
}

// Coverage-aware blend weight — mirrors coverage_weight() in
// src/canonical/idp_backbone.py.  Shallow positional lists get scaled
// down linearly; full-board sources keep their declared weight.
const MIN_FULL_COVERAGE_DEPTH = 60;
function coverageWeight(declaredWeight, depth) {
  const w = Math.max(0, Number(declaredWeight) || 0);
  if (depth === null || depth === undefined) return w;
  const d = Number(depth);
  if (!Number.isFinite(d)) return w;
  if (d <= 0) return 0;
  const factor = Math.min(1, d / Math.max(1, MIN_FULL_COVERAGE_DEPTH));
  return w * factor;
}

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

// ── Rank-to-value curve (OFFLINE FALLBACK ONLY) ───────────────────────
// PRIMARY authority: src/api/data_contract.py (_compute_unified_rankings)
// stamps canonicalConsensusRank + rankDerivedValue onto the API response
// using rank_to_value() in src/canonical/player_valuation.py.  This
// function is only invoked when backend fields are absent (stale data,
// offline mode, unit tests).
//
// Formula: value = max(1, min(9999, round(1 + 9998 / (1 + ((rank-1)/45)^1.10))))
//   • rank 1  → 9999 (exact; denominator = 1)
//   • midpoint (rank 45) → ~5000
//   • Hill-style: flatter at top, longer tail than inverse-power
//
// Tests: tests/api/test_rankings_our_rank.py
export function rankToValue(rank) {
  if (!rank || rank <= 0) return 0;
  return Math.max(1, Math.min(9999, Math.round(1 + 9998 / (1 + Math.pow((rank - 1) / 45, 1.10)))));
}

// ── Unified ranking (frontend fallback) ──────────────────────────────
// The backend (_compute_unified_rankings in data_contract.py) is the
// authoritative source for canonicalConsensusRank and rankDerivedValue.
// This function is only invoked as a fallback when backend fields are
// absent (stale data, offline mode).
//
// The logic mirrors the backend scope-aware pipeline end-to-end:
//   1. Build the IDP backbone ladder from the designated backbone
//      source (the first overall_idp source with isBackbone=true).
//   2. For each registered source, rank only rows eligible under its
//      scope (overall_offense / overall_idp / position_idp).  Position-
//      only sources translate their raw rank into a synthetic overall-
//      IDP rank via the backbone ladder.
//   3. Convert each effective rank through rankToValue(), then blend
//      sources using a coverage-aware weighted mean so shallow lists
//      never overpower deep boards.
//   4. Sort the unified board and stamp canonicalConsensusRank plus
//      transparency metadata (sourceRanks, sourceRankMeta, confidence,
//      market gap, anomaly flags, backward-compat ktcRank/idpRank).
//
// Source registry — keep in sync with `_RANKING_SOURCES` in
// src/api/data_contract.py.  Adding a new position-only source is a
// purely declarative change (add an entry here and on the backend).
const OVERALL_RANK_LIMIT = 800;
// ── Source weight policy ─────────────────────────────────────────────
// Every registered source is declared with `weight: 1.0`.  All six
// sources contribute equally to the coverage-aware Hill-curve blend.
// Earlier revisions boosted the four expert boards to `weight: 3.0`,
// but that was a silent override that never surfaced in the settings
// page and quietly tilted every ranking toward expert consensus.
// Mirror any future change in `src/api/data_contract.py::_RANKING_SOURCES`.
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
    scope: SOURCE_SCOPE_OVERALL_OFFENSE,
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
    key: "idpTradeCalc",
    displayName: "IDP Trade Calculator",
    columnLabel: "IDPTC",
    scope: SOURCE_SCOPE_OVERALL_IDP,
    extraScopes: [SOURCE_SCOPE_OVERALL_OFFENSE],
    positionGroup: null,
    depth: null,
    weight: 1.0,
    isBackbone: true,
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
    scope: SOURCE_SCOPE_OVERALL_IDP,
    positionGroup: null,
    depth: 185,
    weight: 1.0,
    isBackbone: false,
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
    scope: SOURCE_SCOPE_OVERALL_OFFENSE,
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
    scope: SOURCE_SCOPE_OVERALL_OFFENSE,
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
    scope: SOURCE_SCOPE_OVERALL_IDP,
    positionGroup: null,
    depth: 100,
    weight: 1.0,
    isBackbone: false,
    isRetail: false,
    isRankSignal: true,
    needsSharedMarketTranslation: true,
    excludesRookies: true,
  },
];

// Legacy export retained for any consumer that previously imported
// the flat source-key list.  New callers should use RANKING_SOURCES.
const SOURCE_KEYS = RANKING_SOURCES.map((s) => s.key);

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
// `buildRows`/`computeUnifiedRanks` accept a `siteOverrides` map that
// lets the settings page apply per-user include/weight knobs on top of
// the canonical `RANKING_SOURCES` defaults.  The map shape is:
//
//   {
//     ktc:     { include: true, weight: 1.0 },
//     dlfSf:   { include: false },
//     fantasyProsIdp: { weight: 0.5 },
//     …
//   }
//
// Any source not mentioned in the map inherits its registry defaults
// (every registered source is enabled by default with its declared
// weight of 1.0).  The two helpers below resolve overrides
// consistently so the ranking pipeline, the settings inventory, and
// any future consumer all agree on "active" vs "disabled" and on the
// effective weight for a given source.
function sourceOverride(siteOverrides, key) {
  if (!siteOverrides || typeof siteOverrides !== "object") return null;
  const ov = siteOverrides[key];
  return ov && typeof ov === "object" ? ov : null;
}

function isSourceEnabled(siteOverrides, src) {
  const ov = sourceOverride(siteOverrides, src.key);
  if (ov && ov.include === false) return false;
  return true;
}

function effectiveDeclaredWeight(siteOverrides, src) {
  const ov = sourceOverride(siteOverrides, src.key);
  if (ov && Number.isFinite(Number(ov.weight)) && Number(ov.weight) >= 0) {
    return Number(ov.weight);
  }
  return Number(src.weight ?? 1);
}

// `siteOverrides` is considered "customized" if ANY registered source
// has an include flag set to false OR a weight value that does not
// match its registry default.  When customized, the frontend-computed
// ranking values take precedence over backend-stamped values so user
// knobs actually affect the displayed rankings.
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

// ── FALLBACK RANKING PIPELINE ────────────────────────────────────────
// This function is primarily a FALLBACK for offline/stale-data
// scenarios where the backend has not stamped authoritative fields.
// It mirrors the backend's `_compute_unified_rankings()` logic so the
// frontend can compute the same board independently.
//
// When `opts.bypassBackendStamps` is true (automatically set by
// `buildRows` whenever the user has customized `siteOverrides`), the
// function's output becomes AUTHORITATIVE and overrides any
// backend-stamped fields.  That is how the settings page's toggle
// and weight sliders actually affect what the user sees: a
// non-default override forces a full frontend recompute using the
// user's configuration instead of trusting the server blend.
//
// If you need to change canonical ranking logic (the unbiased
// default), change it in `src/api/data_contract.py::_compute_unified_rankings`
// and mirror it here — the two paths must stay aligned.
function computeUnifiedRanks(rows, opts = {}) {
  const siteOverrides = opts.siteOverrides || {};
  const bypassBackend = Boolean(opts.bypassBackendStamps);
  // ── Phase 0: Build the IDP backbone from the designated source ──
  // The builder seeds the shared-market IDP ladder only when the
  // backbone source declares overall_offense in its extraScopes (i.e.
  // prices offense + IDP on a shared 0-9999 scale).  Non-backbone IDP
  // sources flagged ``needsSharedMarketTranslation`` use that ladder
  // as a crosswalk so their raw rank 1 is mapped to the combined-pool
  // rank of the best IDP, not treated as overall rank 1.
  const backboneSrc = RANKING_SOURCES.find(
    (s) => s.scope === SOURCE_SCOPE_OVERALL_IDP && s.isBackbone
  );
  const backboneExtraScopes = Array.isArray(backboneSrc?.extraScopes)
    ? backboneSrc.extraScopes
    : [];
  const backboneHasSharedMarket = backboneExtraScopes.includes(
    SOURCE_SCOPE_OVERALL_OFFENSE
  );
  const backbone = backboneSrc
    ? buildIdpBackbone(rows, backboneSrc.key, backboneHasSharedMarket)
    : {
        ladders: { DL: [], LB: [], DB: [] },
        depth: 0,
        sharedMarketIdpLadder: [],
        sharedMarketDepth: 0,
      };
  const sharedMarketLadder = Array.isArray(backbone.sharedMarketIdpLadder)
    ? backbone.sharedMarketIdpLadder
    : [];
  const sharedMarketDepth = Number(backbone.sharedMarketDepth) || 0;

  // ── Phase 1: Combined-pass ordinal ranking per source ──
  const sourceRanksByRow = new Map(); // row idx -> { sourceKey: effectiveRank }
  const sourceMetaByRow = new Map();  // row idx -> { sourceKey: metaDict }

  for (const src of RANKING_SOURCES) {
    // Respect per-user include toggles: a source turned off in settings
    // is skipped entirely here so it contributes zero signal to the
    // blend.  This is the authoritative path — the Phase 2-3 loop below
    // only iterates over sources that survived this filter.
    if (!isSourceEnabled(siteOverrides, src)) continue;

    // A source may contribute to multiple scopes (e.g. IDPTradeCalc
    // lists both offense and IDP players in one value pool on a shared
    // 0-9999 scale).  Earlier revisions ran a separate ordinal pass per
    // scope, which restarted at rank 1 in each scope and destroyed the
    // cross-universe ordering encoded in the raw values — the #1 IDP
    // and the #1 offense player both got rank 1 → value 9999.
    //
    // Instead, gather every row eligible under ANY of this source's
    // declared scopes into ONE pool and rank them together.  For
    // single-scope sources this is equivalent to the old per-scope pass.
    // For dual-scope IDPTradeCalc it preserves combined offense+IDP
    // ordering: Will Anderson's raw IDPTC value 5963 lands at overall
    // rank ~40 alongside the full offense ladder, not rank 1 of a
    // restarted IDP-only pass.
    const allScopes = [src.scope, ...(src.extraScopes || [])];
    const eligible = [];
    rows.forEach((r, idx) => {
      if (!RANKABLE.has(r.pos)) return;
      let rowScope = null;
      for (const s of allScopes) {
        if (scopeEligible(r.pos, s, src.positionGroup)) {
          rowScope = s;
          break;
        }
      }
      if (!rowScope) return;
      const val = Number(r.canonicalSites?.[src.key]);
      if (!Number.isFinite(val) || val <= 0) return;
      const tiebreakName = String(r.name || "").toLowerCase();
      eligible.push({ idx, val, scope: rowScope, tiebreakName });
    });
    // Secondary sort by lowercased name mirrors the backend Phase 1
    // tiebreaker in _compute_unified_rankings and the backbone builder,
    // so tied raw values produce the same ordinal ranks regardless of
    // input order.
    eligible.sort(
      (a, b) => b.val - a.val || a.tiebreakName.localeCompare(b.tiebreakName)
    );

    const needsSharedMarket =
      Boolean(src.needsSharedMarketTranslation) && !src.isBackbone;

    eligible.forEach((e, rank) => {
      const rawRank = rank + 1;
      let effectiveRank = rawRank;
      let method = TRANSLATION_DIRECT;
      let ladderDepthMeta = null;
      let backboneDepthMeta = null;
      let sharedMarketTranslated = false;

      // position_idp sources (shallow positional lists like DL-only)
      // still get backbone translation.  overall_* scopes — including
      // the cross-universe combined pool — pass through directly unless
      // the source is an IDP-only expert board that opts in to the
      // shared-market crosswalk (e.g. DLF).
      if (e.scope === SOURCE_SCOPE_POSITION_IDP && src.positionGroup) {
        const ladder = backbone.ladders[String(src.positionGroup).toUpperCase()] || [];
        const translated = translatePositionRank(rawRank, ladder);
        effectiveRank = translated.rank;
        method = translated.method;
        ladderDepthMeta = ladder.length;
        backboneDepthMeta = backbone.depth;
      } else if (needsSharedMarket && e.scope === SOURCE_SCOPE_OVERALL_IDP) {
        const translated = translatePositionRank(rawRank, sharedMarketLadder);
        effectiveRank = translated.rank;
        method = translated.method;
        ladderDepthMeta = sharedMarketLadder.length;
        backboneDepthMeta = sharedMarketDepth;
        sharedMarketTranslated = true;
      }

      if (!sourceRanksByRow.has(e.idx)) sourceRanksByRow.set(e.idx, {});
      if (!sourceMetaByRow.has(e.idx)) sourceMetaByRow.set(e.idx, {});
      sourceRanksByRow.get(e.idx)[src.key] = effectiveRank;
      sourceMetaByRow.get(e.idx)[src.key] = {
        scope: e.scope,
        positionGroup: src.positionGroup || null,
        rawRank,
        effectiveRank,
        method,
        ladderDepth: ladderDepthMeta,
        backboneDepth: backboneDepthMeta,
        depth: src.depth ?? null,
        // Stamp the effective declared weight (registry default OR
        // user override) onto the per-row meta so the rankings audit
        // panel tells the truth about what weight was applied.
        weight: effectiveDeclaredWeight(siteOverrides, src),
        sharedMarketTranslated,
      };
    });
  }

  // ── Phase 2-3: Coverage-aware weighted Hill-curve blend ──
  const srcByKey = new Map(RANKING_SOURCES.map((s) => [s.key, s]));
  const ranked = [];
  for (const [idx, ranks] of sourceRanksByRow) {
    const meta = sourceMetaByRow.get(idx) || {};
    let weightedSum = 0;
    let weightTotal = 0;
    for (const [sourceKey, effRank] of Object.entries(ranks)) {
      const srcDef = srcByKey.get(sourceKey) || {};
      // Apply user weight override on top of the registry default.
      // `effectiveDeclaredWeight` resolves to the override when set,
      // otherwise to the canonical `RANKING_SOURCES` weight (1.0 for
      // every source in the current registry).
      const declaredWeight = effectiveDeclaredWeight(siteOverrides, srcDef);
      const effectiveWeight = coverageWeight(declaredWeight, srcDef.depth ?? null);
      const value = rankToValue(effRank);
      weightedSum += value * effectiveWeight;
      weightTotal += effectiveWeight;
      if (meta[sourceKey]) {
        meta[sourceKey].valueContribution = Math.round(value);
        meta[sourceKey].effectiveWeight = Math.round(effectiveWeight * 10000) / 10000;
      }
    }
    let blended;
    if (weightTotal > 0) {
      blended = weightedSum / weightTotal;
    } else {
      const vals = Object.values(ranks).map((r) => rankToValue(r));
      blended = vals.length ? vals.reduce((s, v) => s + v, 0) / vals.length : 0;
    }
    ranked.push({ idx, blended, ranks, meta });
  }

  // ── Phase 4: Unified sort + stamp ──
  ranked.sort(
    (a, b) =>
      b.blended - a.blended ||
      String(rows[a.idx].name || "").localeCompare(String(rows[b.idx].name || ""))
  );

  ranked.slice(0, OVERALL_RANK_LIMIT).forEach((entry, i) => {
    const r = rows[entry.idx];
    const backendRank = Number(r.raw?.canonicalConsensusRank || r.canonicalConsensusRank);
    const backendValue = Number(r.raw?.rankDerivedValue);

    const sourceRankValues = Object.values(entry.ranks);
    const blendedSourceRank =
      sourceRankValues.reduce((s, v) => s + v, 0) / sourceRankValues.length;

    // Default path: prefer backend-stamped authoritative fields; fall
    // back to frontend-computed values when backend fields are absent.
    // Override path: when `bypassBackend` is true (user has customized
    // siteOverrides), ignore backend stamps entirely and use the
    // frontend recompute.  That is how toggle/weight controls
    // materially affect the displayed rankings.
    if (bypassBackend) {
      r.canonicalConsensusRank = i + 1;
      r.rankDerivedValue = Math.round(entry.blended);
      r.sourceRanks = entry.ranks;
      r.sourceRankMeta = entry.meta;
      r.blendedSourceRank = blendedSourceRank;
      r.sourceCount = sourceRankValues.length;
    } else {
      r.canonicalConsensusRank =
        Number.isInteger(backendRank) && backendRank > 0 ? backendRank : i + 1;
      r.rankDerivedValue =
        Number.isFinite(backendValue) && backendValue > 0
          ? backendValue
          : Math.round(entry.blended);
      // sourceRanks: prefer backend when present (has richer per-source metadata)
      const backendSourceRanks = r.raw?.sourceRanks;
      r.sourceRanks = backendSourceRanks && typeof backendSourceRanks === "object" && Object.keys(backendSourceRanks).length > 0
        ? backendSourceRanks : entry.ranks;
      // sourceRankMeta: prefer backend
      const backendMeta = r.raw?.sourceRankMeta;
      r.sourceRankMeta = backendMeta && typeof backendMeta === "object" && Object.keys(backendMeta).length > 0
        ? backendMeta : entry.meta;
      // blendedSourceRank: prefer backend, fall back to frontend average
      const backendBlended = Number(r.raw?.blendedSourceRank);
      r.blendedSourceRank = Number.isFinite(backendBlended) ? backendBlended : blendedSourceRank;
      // sourceCount: prefer backend
      const backendSrcCount = Number(r.raw?.sourceCount);
      r.sourceCount = Number.isInteger(backendSrcCount) && backendSrcCount > 0
        ? backendSrcCount : sourceRankValues.length;
    }

    // Backbone fallback caution: any position_idp source that had to
    // translate with an empty ladder marks the whole row.
    r.idpBackboneFallback = Object.values(entry.meta).some(
      (m) => m && m.method === TRANSLATION_FALLBACK
    );

    const spread =
      sourceRankValues.length >= 2
        ? Math.max(...sourceRankValues) - Math.min(...sourceRankValues)
        : null;
    r.sourceRankSpread = r.raw?.sourceRankSpread ?? spread;
    r.isSingleSource = r.raw?.isSingleSource ?? sourceRankValues.length === 1;
    r.hasSourceDisagreement =
      r.raw?.hasSourceDisagreement ?? (spread !== null && spread > 80);
    r.marketGapDirection = r.raw?.marketGapDirection ?? "none";
    r.marketGapMagnitude = r.raw?.marketGapMagnitude ?? null;

    if (r.raw?.confidenceBucket) {
      r.confidenceBucket = r.raw.confidenceBucket;
      r.confidenceLabel = r.raw.confidenceLabel || "";
    } else if (sourceRankValues.length >= 2 && spread !== null) {
      if (spread <= 30) {
        r.confidenceBucket = "high";
        r.confidenceLabel = "High — multi-source, tight agreement";
      } else if (spread <= 80) {
        r.confidenceBucket = "medium";
        r.confidenceLabel = "Medium — multi-source, moderate spread";
      } else {
        r.confidenceBucket = "low";
        r.confidenceLabel = "Low — single source or wide disagreement";
      }
    } else {
      r.confidenceBucket = "low";
      r.confidenceLabel = "Low — single source or wide disagreement";
    }
    r.anomalyFlags = Array.isArray(r.raw?.anomalyFlags) ? r.raw.anomalyFlags : [];

    // Backward compat: consumers still read ktcRank / idpRank directly.
    if (entry.ranks.ktc) r.ktcRank = entry.ranks.ktc;
    if (entry.ranks.idpTradeCalc) r.idpRank = entry.ranks.idpTradeCalc;
  });
}

export function buildRows(data, opts = {}) {
  const players = data?.players || {};
  const playersArray = Array.isArray(data?.playersArray) ? data.playersArray : [];
  const posMap = data?.sleeper?.positions || {};
  const rows = [];

  // Resolve user-level source overrides (from the settings page) into
  // the `computeUnifiedRanks` opts bag.  When overrides diverge from
  // the registry defaults, `bypassBackendStamps` flips on so the
  // frontend fallback becomes authoritative — user knobs actually
  // affect the displayed rank instead of being overwritten by the
  // server's canonical blend.
  const siteOverrides = opts.siteOverrides || {};
  const customized = siteOverridesAreCustomized(siteOverrides);
  const rankOpts = {
    siteOverrides,
    bypassBackendStamps: customized,
  };

  if (playersArray.length) {
    for (const player of playersArray) {
      if (!player || typeof player !== "object") continue;
      const name = String(player.displayName || player.canonicalName || "").trim();
      if (!name) continue;
      const pos = normalizePos(player.position || "");
      const cls = classifyPos(pos);
      if (cls === "excluded") continue;

      // Prefer 1–9999 display value; fall back to internal calibrated value
      const displayVal = Number(player?.values?.displayValue ?? 0) || 0;
      const internalVal = Number(
        player?.values?.finalAdjusted ?? player?.values?.overall ?? 0
      ) || 0;
      const values = {
        raw: Number(player?.values?.rawComposite ?? 0) || 0,
        full: displayVal || internalVal,
      };

      const canonicalSites =
        player.canonicalSiteValues && typeof player.canonicalSiteValues === "object"
          ? player.canonicalSiteValues
          : {};

      rows.push({
        name,
        pos: pos || "?",
        team: String(player.team || ""),
        age: Number(player.age) || null,
        rookie: Boolean(player.rookie),
        assetClass: String(player.assetClass || classifyPos(pos || "?")),
        values: {
          raw: Math.round(values.raw),
          full: Math.round(values.full),
        },
        // siteCount: intentionally preserved — used by trade calculator and
        // other non-rankings views.  Rankings pages hide this column, but the
        // field must remain on the row contract.  Do NOT remove it.
        siteCount: Number(player.sourceCount || 0),
        confidence: Number(player.marketConfidence ?? 0),
        marketLabel: "",
        canonicalSites,
        canonicalConsensusRank: Number(player.canonicalConsensusRank) || null,
        canonicalTierId: Number(player.canonicalTierId) || null,
        // Trust/transparency fields — pass through from backend contract.
        // These are backend-authoritative; the frontend preserves them as-is.
        confidenceBucket: String(player.confidenceBucket || "none"),
        confidenceLabel: String(player.confidenceLabel || ""),
        anomalyFlags: Array.isArray(player.anomalyFlags) ? player.anomalyFlags : [],
        isSingleSource: Boolean(player.isSingleSource),
        hasSourceDisagreement: Boolean(player.hasSourceDisagreement),
        blendedSourceRank: player.blendedSourceRank ?? null,
        sourceRankSpread: player.sourceRankSpread ?? null,
        marketGapDirection: String(player.marketGapDirection || "none"),
        marketGapMagnitude: player.marketGapMagnitude ?? null,
        // Identity quality fields — backend-authoritative
        sourceOriginalRanks: player.sourceOriginalRanks && typeof player.sourceOriginalRanks === "object"
          ? player.sourceOriginalRanks : {},
        sourceRankMeta: player.sourceRankMeta && typeof player.sourceRankMeta === "object"
          ? player.sourceRankMeta : {},
        identityConfidence: Number(player.identityConfidence ?? 0.7),
        identityMethod: String(player.identityMethod || "name_only"),
        quarantined: Boolean(player.quarantined),
        raw: player,
      });
    }

    computeUnifiedRanks(rows, rankOpts);
    // Sort by unified canonicalConsensusRank (backend-authoritative when present).
    rows.sort((a, b) => {
      const ra = a.canonicalConsensusRank ?? Infinity;
      const rb = b.canonicalConsensusRank ?? Infinity;
      if (ra !== rb) return ra - rb;
      return (b.values.full || 0) - (a.values.full || 0);
    });
    rows.forEach((r, i) => {
      r.computedConsensusRank = i + 1;
      r.rank = r.canonicalConsensusRank ?? r.computedConsensusRank;
    });
    return rows;
  }

  for (const [name, player] of Object.entries(players)) {
    if (!player || typeof player !== "object") continue;
    const isPick = /\b(20\d{2})\s+(early|mid|late)?\s*(1st|2nd|3rd|4th|5th|6th|round|r\d|pick)/i.test(name) || /^20\d{2}\s+pick/i.test(name);
    const pos = isPick ? "PICK" : normalizePos(posMap[name] || player.position || "");
    if (classifyPos(pos) === "excluded") continue;

    const values = inferValueBundle(player);
    const canonicalSites = player._canonicalSiteValues && typeof player._canonicalSiteValues === "object" ? player._canonicalSiteValues : {};

    rows.push({
      name,
      pos: pos || "?",
      team: String(player.team || ""),
      age: Number(player.age) || null,
      rookie: Boolean(player._formatFitRookie),
      assetClass: classifyPos(pos || "?"),
      values,
      // siteCount: intentionally preserved — used by trade calculator and
      // other non-rankings views.  Rankings pages hide this column, but the
      // field must remain on the row contract.  Do NOT remove it.
      siteCount: Number(player._sites || 0),
      confidence: Number(player._marketReliabilityScore ?? 0),
      marketLabel: String(player._marketReliabilityLabel || ""),
      canonicalSites,
      canonicalConsensusRank: Number(player._canonicalConsensusRank) || null,
      canonicalTierId: Number(player._canonicalTierId) || null,
      // Trust/transparency fields — prefer backend-mirrored values from
      // the legacy dict; fall back to safe defaults.  computeUnifiedRanks()
      // may further overwrite these for ranked players.
      confidenceBucket: String(player.confidenceBucket || "none"),
      confidenceLabel: String(player.confidenceLabel || ""),
      anomalyFlags: Array.isArray(player.anomalyFlags) ? player.anomalyFlags : [],
      isSingleSource: Boolean(player.isSingleSource),
      isStructurallySingleSource: Boolean(player.isStructurallySingleSource),
      hasSourceDisagreement: Boolean(player.hasSourceDisagreement),
      blendedSourceRank: player.blendedSourceRank ?? null,
      sourceRankSpread: player.sourceRankSpread ?? null,
      sourceRankPercentileSpread: player.sourceRankPercentileSpread ?? null,
      sourceAudit: player.sourceAudit && typeof player.sourceAudit === "object"
        ? player.sourceAudit
        : null,
      marketGapDirection: String(player.marketGapDirection || "none"),
      marketGapMagnitude: player.marketGapMagnitude ?? null,
      sourceOriginalRanks: player.sourceOriginalRanks && typeof player.sourceOriginalRanks === "object"
        ? player.sourceOriginalRanks : {},
      sourceRankMeta: player.sourceRankMeta && typeof player.sourceRankMeta === "object"
        ? player.sourceRankMeta : {},
      identityConfidence: Number(player.identityConfidence ?? 0.7),
      identityMethod: String(player.identityMethod || "name_only"),
      quarantined: Boolean(player.quarantined),
      raw: player,
    });
  }

  computeUnifiedRanks(rows, rankOpts);
  rows.sort((a, b) => {
    const ra = a.canonicalConsensusRank ?? Infinity;
    const rb = b.canonicalConsensusRank ?? Infinity;
    if (ra !== rb) return ra - rb;
    return (b.values.full || 0) - (a.values.full || 0);
  });
  rows.forEach((r, i) => {
    r.computedConsensusRank = i + 1;
    r.rank = r.canonicalConsensusRank ?? r.computedConsensusRank;
  });
  return rows;
}

export async function fetchDynastyData() {
  const res = await fetch("/api/dynasty-data", { cache: "no-store" });
  if (!res.ok) {
    const txt = await res.text();
    throw new Error(`Failed to load dynasty data: ${res.status} ${txt}`);
  }
  const json = await res.json();

  // The Next.js API route wraps the payload: { ok, source, data: <contract> }
  // The Python backend alias returns the raw contract: { players, playersArray, version, ... }
  // Normalize both shapes to { ok, source, data }.
  if (json && typeof json === "object" && !json.data && (json.players || json.playersArray)) {
    return {
      ok: true,
      source: json.dataSource?.type
        ? `backend:${json.dataSource.type}`
        : json.date
          ? `contract:${json.date}`
          : "backend",
      data: json,
    };
  }

  return json;
}
