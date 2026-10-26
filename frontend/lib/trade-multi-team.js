/**
 * trade-multi-team — the private /trade side of N-team Analyze Trade (spec
 * docs/trade/NTEAM_TRADE_ENGINE_SPEC.md §3.2, §5.1; owner directive
 * 2026-10-20 §7).
 *
 * The builder's sides are abstract buckets: any board row can go on any side
 * and copies are allowed (owner decision 2026-10-03).  The authoritative
 * analysis (`POST /api/trade/analyze-multi`) needs a TEAM-ATTRIBUTED ledger
 * instead: every side bound to a distinct league team by `rosterId`, every
 * asset identified by its canonical id, every destination explicit.  This
 * module turns the builder state into that request, or into the named reasons
 * it cannot — it never guesses, never re-routes silently, and never prices
 * anything.  Every number the multi-team War Room shows comes back from the
 * server verbatim.
 *
 * Identity is by id only: a team is its Sleeper `roster_id`, a player is
 * `p:<sleeperId>`, a pick is its canonical league pick id
 * (`pick:<leagueKey>:<season>:r<round>:o<origin>`, from
 * `sleeper.teams[].pickDetails[].assetId`).  Display names decide nothing.
 */

import { tradeEntryKey } from "./trade-assets.js";
export {
  MULTI_TEAM_ENDPOINT,
  effectiveBindings,
  entryAssetRef,
  inferSideRosterId,
  probeMultiTeamAnalysis,
  teamHoldings,
  teamOptions,
  teamRosterId,
} from "./trade-team-binding.js";
import { entryAssetRef, teamHoldings, teamRosterId } from "./trade-team-binding.js";

export const MULTI_TEAM_VERSION = "multi_team_v1";

/** Plain words for the reasons a builder trade is not ready for Analyze. */
export const LEDGER_REASON_TEXT = {
  too_few_sides: "A multi-team analysis needs at least two teams.",
  unbound_side: "Assign each side to a league team to analyze.",
  duplicate_team: "Each league team can be on only one side.",
  generic_pick:
    "is a market pick reference, not a league pick. Pick the team's own pick from that side's search to analyze.",
  no_player_id: "has no league player id, so the analysis cannot identify it.",
  duplicate_asset:
    "is in the trade more than once. A team can trade an asset only once; copies are for the calculator only.",
  shared_line:
    "shares its name with a different asset on this side, so the two cannot be routed separately. Remove one of them to analyze.",
  invalid_destination: "needs a destination team on another side.",
  not_on_team: "is not on that team's roster.",
  idle_team: "neither sends nor receives anything. Remove the side or route an asset to it.",
  empty_trade: "Add at least one asset to the trade.",
};

function reasonText(r) {
  const base = LEDGER_REASON_TEXT[r.code] || "This trade is not ready to analyze.";
  return r.label ? `${r.label} ${base}` : base;
}

/**
 * Build the `/api/trade/analyze-multi` body for the builder's trade.
 *
 * @param {object} args
 * @param {object[]} args.sides      builder sides (`{label, assets, destinations}`)
 * @param {(number|null)[]} args.bindings  rosterId per side (null = unbound)
 * @param {object[]} args.teams      `sleeper.teams` of the loaded contract
 * @returns {{ok: true, request: {teams: number[], assets: {id, from, to}[]}, sideRosterIds: number[]}
 *          | {ok: false, reasons: {code, sideIdx?, label?, text}[]}}
 *
 * Refused, with a named reason each (nothing is coerced): an unbound side, a
 * team on two sides, an asset with no canonical id (a generic market pick, a
 * row with no player id), the same asset twice, two different assets sharing
 * one side line (and so one destination), a missing / self / out-of-range
 * destination (3+ sides; two sides route to each other), an asset the bound
 * team does not hold in the loaded contract, a side that neither sends nor
 * receives, and an empty trade.  Ownership is re-verified by the server
 * against the same snapshot (409 `stale_assets`); this check only explains
 * the refusal before the request is sent.
 */
export function buildMultiTeamLedger({ sides, bindings, teams }) {
  const list = Array.isArray(sides) ? sides : [];
  const n = list.length;
  const reasons = [];
  const push = (r) => reasons.push({ ...r, text: reasonText(r) });
  if (n < 2) {
    push({ code: "too_few_sides" });
    return { ok: false, reasons };
  }
  const rids = list.map((_, i) => (Number.isInteger(bindings?.[i]) ? bindings[i] : null));
  const teamById = new Map();
  for (const t of teams || []) {
    const rid = teamRosterId(t);
    if (rid != null) teamById.set(rid, t);
  }
  rids.forEach((rid, i) => {
    if (rid == null || !teamById.has(rid)) push({ code: "unbound_side", sideIdx: i });
  });
  const seenTeams = new Map();
  rids.forEach((rid, i) => {
    if (rid == null) return;
    if (seenTeams.has(rid)) push({ code: "duplicate_team", sideIdx: i });
    else seenTeams.set(rid, i);
  });

  const legs = [];
  const seenAssets = new Set();
  const sends = list.map(() => 0);
  const receives = list.map(() => 0);
  let total = 0;
  list.forEach((side, i) => {
    const held =
      rids[i] != null && teamById.has(rids[i]) ? teamHoldings(teamById.get(rids[i])) : null;
    // A destination is stored per side LINE (`tradeEntryKey` — the owned-pick
    // id, else the board row name).  Two DIFFERENT assets that share a line
    // key on one side would share one destination, so that line is refused
    // by name rather than routed as though they were one (E1-F3).
    const idsByLine = new Map();
    for (const entry of side?.assets || []) {
      const ref = entryAssetRef(entry);
      if (!ref.id) continue;
      const key = tradeEntryKey(entry);
      if (!idsByLine.has(key)) idsByLine.set(key, new Set());
      idsByLine.get(key).add(ref.id);
    }
    const sharedLines = new Set(
      [...idsByLine].filter(([, ids]) => ids.size > 1).map(([key]) => key),
    );
    const reportedShared = new Set();
    for (const entry of side?.assets || []) {
      total += 1;
      const label = String(entry?.assetLabel || entry?.name || "An asset");
      const ref = entryAssetRef(entry);
      if (!ref.id) {
        push({ code: ref.reason, sideIdx: i, label });
        continue;
      }
      if (sharedLines.has(tradeEntryKey(entry))) {
        const key = tradeEntryKey(entry);
        if (!reportedShared.has(key)) {
          reportedShared.add(key);
          push({ code: "shared_line", sideIdx: i, label });
        }
        continue;
      }
      if (seenAssets.has(ref.id)) {
        push({ code: "duplicate_asset", sideIdx: i, label });
        continue;
      }
      seenAssets.add(ref.id);
      let dest;
      if (n === 2) dest = 1 - i;
      else {
        const parsed = Number((side?.destinations || {})[tradeEntryKey(entry)]);
        dest =
          Number.isInteger(parsed) && parsed >= 0 && parsed < n && parsed !== i ? parsed : null;
      }
      if (dest == null) {
        push({ code: "invalid_destination", sideIdx: i, label });
        continue;
      }
      if (held && !held.has(ref.id)) push({ code: "not_on_team", sideIdx: i, label });
      sends[i] += 1;
      receives[dest] += 1;
      legs.push({ id: ref.id, fromIdx: i, toIdx: dest });
    }
  });
  if (total === 0) push({ code: "empty_trade" });
  else {
    list.forEach((side, i) => {
      if (sends[i] === 0 && receives[i] === 0) {
        push({
          code: "idle_team",
          sideIdx: i,
          label: `Side ${side?.label ?? i + 1}`,
        });
      }
    });
  }
  if (reasons.length) return { ok: false, reasons };
  const assets = legs
    .map((l) => ({ id: l.id, from: rids[l.fromIdx], to: rids[l.toIdx] }))
    .sort((a, b) => (a.id < b.id ? -1 : a.id > b.id ? 1 : 0));
  return {
    ok: true,
    request: { teams: [...rids].sort((a, b) => a - b), assets },
    sideRosterIds: rids,
  };
}

/** One string per analysis question: the ledger plus everything that changes the answer. */
export function multiRequestKey(request, { leagueKey = "", useTeamContext = true } = {}) {
  if (!request) return "";
  return JSON.stringify([request.teams, request.assets, leagueKey || "", useTeamContext !== false]);
}

/**
 * Is this response the answer to THIS request?  The War Room never shows a
 * result for a different trade: version, league, team set and ledger must
 * all match what was asked.
 */
export function validMultiPayload(data, request, { leagueKey = "" } = {}) {
  if (!data || typeof data !== "object" || !request) return false;
  if (data.multiTeamVersion !== MULTI_TEAM_VERSION) return false;
  if (leagueKey && data.leagueKey && data.leagueKey !== leagueKey) return false;
  if (!Array.isArray(data.teams) || data.teams.length !== request.teams.length) return false;
  const got = data.teams.map((t) => t?.rosterId);
  if (JSON.stringify(got) !== JSON.stringify(request.teams)) return false;
  const legs = (data.ledger?.legs || []).map((l) => [l?.id, l?.from, l?.to]);
  const asked = request.assets.map((a) => [a.id, a.from, a.to]);
  if (JSON.stringify(legs) !== JSON.stringify(asked)) return false;
  for (const t of data.teams) {
    if (!t?.analysis?.decision || !t?.fairness || !Array.isArray(t?.gives)) return false;
  }
  return Boolean(data.summary && Array.isArray(data.summary.lines));
}

/** Plain words for a failed multi-team analysis (`{error, message, reason}` bodies). */
export function multiErrorText(status, data) {
  const code = data?.error;
  if (code === "multi_team_analysis_disabled") {
    return "multi-team analysis is switched off on this server";
  }
  if (code === "stale_assets") {
    return "one or more assets are not held by the team sending them in the latest rosters";
  }
  if (code === "data_not_ready") return "the league rosters are not ready yet";
  if (code === "package_model_unavailable") return "the active package model is not available";
  if (status === 401) return "you need to sign in again";
  if (status === 400 && typeof data?.message === "string" && data.message) {
    return data.message.replace(/\.$/, "").replace(/^./, (c) => c.toLowerCase());
  }
  if (code === "timeout") return "it took too long to answer";
  if (status >= 500) return "the server could not analyze it";
  return "the analysis could not be completed";
}

/** Errors that trying the same request again cannot fix. */
export function multiErrorRetryable(status, data) {
  const code = data?.error;
  if (
    code === "multi_team_analysis_disabled" ||
    code === "invalid_trade" ||
    code === "invalid_request"
  ) {
    return false;
  }
  return status !== 400 && status !== 409;
}

/** Display words for a team's market-fairness state (C4: never the decision). */
export const FAIRNESS_STATE_WORDS = {
  FAIR: "Fair",
  NOT_FAIR: "Not fair",
  UNABLE: "Unable to determine",
};
export const FAIRNESS_STATE_TONES = {
  FAIR: "positive",
  NOT_FAIR: "warning",
  UNABLE: "neutral",
};
export const FAIRNESS_LEVEL_WORDS = {
  fair: "within the fair band",
  slight: "a slight edge",
  unfair: "an unfair gap",
  lopsided: "a lopsided gap",
};
export const FAIRNESS_REASON_WORDS = {
  asset_not_evaluable: "an asset in this team's part of the trade has no value on the board",
  ownership_unverifiable:
    "who holds every asset in this team's part of the trade could not be confirmed",
  evaluation_unavailable: "an asset value is quarantined or stale",
};
export const OVERALL_FAIRNESS_WORDS = {
  all_teams_fair: "The trade is within the fair band for every team.",
  not_all_teams_fair: "The trade is outside the fair band for at least one team.",
  evidence_insufficient: "There is not enough reliable evidence to judge every team.",
};

/** Tone for the 5-level category (private only). */
export const CATEGORY_TONES = {
  STRONGLY_FAVORABLE: "positive",
  FAVORABLE: "positive",
  APPROXIMATELY_EVEN: "neutral",
  UNFAVORABLE: "negative",
  STRONGLY_UNFAVORABLE: "negative",
  UNAVAILABLE: "neutral",
};
