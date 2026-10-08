/**
 * recent-real-trades — the pure half of the /trade "Recent real trades"
 * section (C3-CALC-01 / TC-07 + TC-10).
 *
 * Two jobs, neither of them valuation:
 *
 *   1. turn the calculator's side entries into the identity refs the
 *      backend matches on — Sleeper player ids, board pick-row names and
 *      owned league-pick ids.  Nothing here parses a pick label or matches
 *      a name; the backend resolves every ref through src/identity.
 *   2. turn the ledger's format facts into display text.  An unknown field
 *      renders as unknown ("QB ?"), never as a default — TC-10 forbids
 *      fabricating format to make a card look complete.
 *
 * No trade here is graded and no value is read: these are reference facts.
 */

function uniq(list) {
  return [...new Set(list)];
}

/**
 * `{players, picks, pickAssetIds}` for every entry on every side.  Owned
 * league picks travel by their canonical id (never their market row name,
 * which is a display convention for an unknown slot).
 */
export function referenceQueryFromSides(sides) {
  const players = [];
  const picks = [];
  const pickAssetIds = [];
  for (const side of sides || []) {
    for (const entry of side?.assets || []) {
      if (!entry) continue;
      if (entry.assetId) {
        pickAssetIds.push(String(entry.assetId));
      } else if (entry.assetClass === "pick" || entry.pos === "PICK") {
        if (entry.name) picks.push(String(entry.name));
      } else {
        const pid = String(entry.playerId ?? entry?.raw?.playerId ?? "").trim();
        if (pid) players.push(pid);
      }
    }
  }
  return {
    players: uniq(players).sort(),
    picks: uniq(picks).sort(),
    pickAssetIds: uniq(pickAssetIds).sort(),
  };
}

export function referenceQueryIsEmpty(q) {
  return !q || (!q.players.length && !q.picks.length && !q.pickAssetIds.length);
}

/** Query string for /api/market/trades/reference (comma-joined values). */
export function referenceQueryString(q, leagueKey) {
  const params = new URLSearchParams();
  if (leagueKey) params.set("leagueKey", leagueKey);
  if (q.players.length) params.set("players", q.players.join(","));
  if (q.picks.length) params.set("picks", q.picks.join(","));
  if (q.pickAssetIds.length) params.set("pickAssetIds", q.pickAssetIds.join(","));
  return params.toString();
}

const KTC_TEP = { 0: "No TEP", 1: "TE+", 2: "TE++", 3: "TE+++" };

/**
 * Display tags in a fixed order.  Each is `{key, text, known}`; `known:
 * false` tags are still rendered (as unknown) so a missing fact is visible.
 */
export function formatTagList(tags) {
  const t = tags || {};
  const out = [];
  const add = (key, text, known) => out.push({ key, text, known });
  add("qb", t.superflex === true ? "SF" : t.superflex === false ? "1QB" : "QB ?", t.superflex != null);
  add("teams", t.teams != null ? `${t.teams} teams` : "Teams ?", t.teams != null);
  add(
    "starters",
    t.starters != null ? `${t.starters} starters` : "Starters ?",
    t.starters != null,
  );
  if (t.ktcTepLevel != null) {
    add("te", `${KTC_TEP[t.ktcTepLevel] ?? `TEP ${t.ktcTepLevel}`} (KTC setting)`, true);
  } else if (t.teScoringEdge != null) {
    add("te", t.teScoringEdge ? "TE premium" : "No TE premium", true);
  } else {
    add("te", "TE premium ?", false);
  }
  if (t.pprPerReception != null) {
    add("ppr", `${t.pprPerReception} PPR`, true);
  } else if (t.ktcPprCode != null) {
    add("ppr", `PPR code ${t.ktcPprCode} (KTC setting)`, true);
  } else {
    add("ppr", "PPR ?", false);
  }
  add("idp", t.idp === true ? "IDP" : t.idp === false ? "No IDP" : "IDP ?", t.idp != null);
  if (t.bestBall === true) add("bestBall", "Best ball", true);
  if (t.season) add("season", `${t.season} season`, true);
  return out;
}

const TIMING_TEXT = {
  exact: "Format confirmed at trade time",
  post_trade: "Format captured after the trade",
  unconfirmed: "Format captured before the trade, not yet re-confirmed",
  changed_after_trade: "League format changed after the trade",
  unknown: "Format timing unknown",
};

export function formatTimingText(trade) {
  return TIMING_TEXT[trade?.formatTiming] || TIMING_TEXT.unknown;
}

const DISPOSITION_TEXT = {
  NATIVE_COMPARABLE: "Same format as this league",
  VALIDATED_TRANSFORMABLE: "Comparable after a validated translation",
  BROAD_CONTEXT: "Broad context only — format differs or is unproven",
  TARGET_UNSUPPORTED: "Not comparable to this league",
};

/** The ledger's own disposition, or why there is none for this league. */
export function formatMatchText(trade) {
  const fm = trade?.formatMatch;
  if (!fm) return "Format match unknown";
  if (!fm.appliesToThisLeague) return "Format match not computed for this league";
  return DISPOSITION_TEXT[fm.disposition] || "Format match unknown";
}

const SOURCE_TEXT = {
  KTC_MARKET: "KTC trade database",
  SHARP_DISCOVERY: "Sharp-discovered Sleeper league",
  OWN_LEAGUE: "This league",
};

export function sourceText(trade) {
  const labels = (trade?.provenance || []).map((p) => SOURCE_TEXT[p] || p);
  return labels.length ? labels.join(" + ") : "Source unknown";
}

export function assetText(asset) {
  if (!asset) return "";
  if (asset.label) {
    // KTC files its default "Mid" tier at the generic grade: the vendor
    // never said which tier, so the label must not claim one.
    if (asset.pick?.gradeNote === "ktc_mid_is_vendor_default") {
      return `${asset.label} (KTC "Mid" — tier not stated)`;
    }
    return asset.label;
  }
  if (asset.kind === "player") return "Player not on board";
  if (asset.kind === "pick") return "Unresolved pick";
  return "Unresolved asset";
}

export function sideHeading(trade, idx) {
  if (trade?.sidesSemantics === "received_per_roster") return `Team ${idx + 1} received`;
  return `Package ${String.fromCharCode(65 + idx)}`;
}

/**
 * Plain-language caveats for one trade, from the ledger's own caveat codes.
 * An unrecognised code is still shown (as itself) rather than dropped.
 */
export function caveatTexts(trade) {
  const out = [];
  for (const code of trade?.caveats || []) {
    const [kind, n] = String(code).split(":");
    if (kind === "sleeper_trade_faab_component_not_recorded") {
      out.push("FAAB in the trade not recorded");
    } else if (kind === "released_in_trade") {
      out.push(`${n || "Some"} player${n === "1" ? "" : "s"} released in the trade (not exchanged)`);
    } else if (kind.startsWith("partial_record")) {
      out.push("Partial record — part of the trade was not captured");
    } else {
      out.push(String(code));
    }
  }
  if (trade?.possibleOverlap) out.push("May duplicate another listed trade");
  return out;
}

/** Withheld-row counts in words; privacy reasons are summed, never itemised. */
export function withheldText(withheld) {
  if (!withheld) return null;
  let gameType = 0;
  let other = 0;
  for (const [reason, n] of Object.entries(withheld)) {
    if (reason === "game_type_not_verified_dynasty") gameType += n;
    else other += n;
  }
  const parts = [];
  if (gameType) parts.push(`${gameType} not shown because the league was not verified as dynasty`);
  if (other) parts.push(`${other} not shown for privacy or source reasons`);
  return parts.length ? `${parts.join("; ")}.` : null;
}

/**
 * Classify a non-ok response.  A 4xx the user's request caused is not the
 * same statement as "the server has no ledger", and must not read like it.
 */
export function referenceFailureKind(status) {
  if (status === 401 || status === 403) return "auth";
  if (status >= 400 && status < 500) return "request_error";
  return "unavailable";
}
