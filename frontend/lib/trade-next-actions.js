/**
 * trade-next-actions — where the trade being built can go next (TC-B /
 * TCM-O11, O12, O13, L01).
 *
 * The ONE owner of the deep-link contract between /trade and the existing
 * trade engines: it builds the links /trade emits AND parses the parameters
 * the target page reads (`parseArbitrageQuery`), so the two sides cannot
 * drift.  Nothing here generates, values or ranks a trade — every
 * destination is an existing engine (finder / Package Builder / Best Trade /
 * Golden Upgrades on /arbitrage, Manager Scout on /trades, Manager
 * Intelligence on /managers, the Trade Database) or an existing owner
 * (`/api/user/trade-desk`, `/api/manager-scout/offer-evidence`).
 *
 * The share-link format (`lib/trade-share.js`) is NOT touched: other pages
 * seed /trade through it, and these links point AWAY from /trade.
 */

import { tradeEntryLabel } from "./trade-assets.js";

/** /arbitrage tools a link may open — the ids of `TOOL_TABS` there. */
export const ARBITRAGE_TOOL_IDS = ["golden", "scan", "best", "builder", "desk"];

const MAX_PARAM_LEN = 120;

function cleanParam(value) {
  const text = String(value ?? "").trim();
  return text && text.length <= MAX_PARAM_LEN ? text : "";
}

/**
 * `/arbitrage?tool=<id>&team=<name>[&opponent=<name>]`.  An unknown tool is
 * refused (null) rather than linking to a page that would ignore it.
 */
export function arbitrageHref(tool, { team = "", opponent = "" } = {}) {
  if (!ARBITRAGE_TOOL_IDS.includes(tool)) return null;
  const params = new URLSearchParams({ tool });
  const t = cleanParam(team);
  const o = cleanParam(opponent);
  if (t) params.set("team", t);
  if (o && o !== t) params.set("opponent", o);
  return `/arbitrage?${params.toString()}`;
}

/**
 * Read what `arbitrageHref` wrote.  `teamNames` are the league's current
 * teams: a team the league does not have is dropped, never guessed.
 * Returns `{ tool, team, opponent }`, each null when absent or invalid.
 */
export function parseArbitrageQuery(search, teamNames = []) {
  const params = new URLSearchParams(search || "");
  const tool = params.get("tool");
  const names = new Set((teamNames || []).map((n) => String(n)));
  const team = cleanParam(params.get("team"));
  const opponent = cleanParam(params.get("opponent"));
  return {
    tool: ARBITRAGE_TOOL_IDS.includes(tool) ? tool : null,
    team: team && names.has(team) ? team : null,
    opponent: opponent && names.has(opponent) && opponent !== team ? opponent : null,
  };
}

/**
 * The Trade Database pre-filtered to this trade's assets
 * (`/market/trade-database?players=<sleeper ids>&picks=<board pick names>`,
 * the parameters that page reads).  Players travel by their stable Sleeper
 * id (the same ref `lib/recent-real-trades.js::referenceQueryFromSides`
 * sends), picks by their board row (an owned pick by the market row it is
 * priced on).  A player with no id cannot be linked and is COUNTED in
 * `unlinked`, never dropped silently or matched by name.
 */
export function tradeDatabaseHref(sides) {
  const players = [];
  const picks = [];
  let unlinked = 0;
  for (const side of sides || []) {
    for (const a of side?.assets || []) {
      if (!a) continue;
      if (a.assetClass === "pick" || a.pos === "PICK") {
        if (a.name && !picks.includes(a.name)) picks.push(a.name);
        continue;
      }
      const id = String(a.playerId ?? a?.raw?.playerId ?? "").trim();
      if (id) {
        if (!players.includes(id)) players.push(id);
      } else {
        unlinked += 1;
      }
    }
  }
  if (!players.length && !picks.length) return { href: null, unlinked };
  const params = new URLSearchParams();
  if (players.length) params.set("players", players.join(","));
  if (picks.length) params.set("picks", picks.join(","));
  return { href: `/market/trade-database?${params.toString()}`, unlinked };
}

/** Manager Scout's league tendencies table lives on /trades. */
export const MANAGER_SCOUT_HREF = "/trades";
/** Manager Intelligence (any Sleeper username) lives on /managers. */
export const MANAGER_INTEL_HREF = "/managers";

/**
 * Who is on each side of a two-team trade, for the actions that need both
 * teams (partner evidence, Save to Trade Desk, the finder links).
 *
 * `mySideIdx` is the page's ONE answer to "which side is the selected team"
 * (`resolveTeamSide`); `sideTeamNames` is the page's per-side team
 * resolution.  Returns `{ ok, myTeam, opponent, mySideIdx, reason }`;
 * `reason` names what is missing instead of guessing a team.
 */
export function tradeParties({ sides, mySideIdx, myTeam, sideTeamNames }) {
  const base = { ok: false, myTeam: myTeam || null, opponent: null, mySideIdx: null };
  if (!Array.isArray(sides) || sides.length !== 2) return { ...base, reason: "not_two_team" };
  if (!myTeam) return { ...base, reason: "no_team_selected" };
  if (mySideIdx !== 0 && mySideIdx !== 1) return { ...base, reason: "side_unknown" };
  const other = 1 - mySideIdx;
  const opponent = (sideTeamNames || [])[other] || null;
  if (!opponent) return { ...base, mySideIdx, reason: "opponent_unknown" };
  if (opponent === myTeam) return { ...base, mySideIdx, reason: "opponent_is_my_team" };
  return { ok: true, myTeam, opponent, mySideIdx, reason: null };
}

const PARTY_REASON_TEXT = {
  not_two_team: "Available for two-team trades.",
  no_team_selected: "Pick your team first.",
  side_unknown: "Say which side is your team first.",
  opponent_unknown:
    "No team can be identified for the other side — add one of that team's players.",
  opponent_is_my_team: "Both sides resolve to your team.",
};

export function tradePartiesText(reason) {
  return PARTY_REASON_TEXT[reason] || "Not available for this trade.";
}

function packageAsset(a) {
  const isPick = a?.assetClass === "pick" || a?.pos === "PICK";
  const label = tradeEntryLabel(a);
  const out = { name: label, isPick };
  if (a?.assetId) out.assetId = a.assetId;
  if (label !== a?.name && a?.name) out.boardRowName = a.name;
  if (!isPick && a?.pos && a.pos !== "?") out.position = String(a.pos).split("/")[0];
  return out;
}

/** The Trade Desk caps a side at this many assets (src/trade/trade_desk.py). */
export const DESK_MAX_ASSETS_PER_SIDE = 8;

/**
 * The `/api/user/trade-desk` create body for the trade being built
 * (`source: "calculator"`), or `{ body: null, reason }`.  One desk asset per
 * calculator COPY: the desk records exactly what is on the calculator.
 */
export function deskBodyFromCalculator({ sides, parties, leagueKey }) {
  if (!parties?.ok) return { body: null, reason: parties?.reason || "not_two_team" };
  if (!leagueKey) return { body: null, reason: "no_league" };
  const send = (sides[parties.mySideIdx]?.assets || []).map(packageAsset);
  const receive = (sides[1 - parties.mySideIdx]?.assets || []).map(packageAsset);
  if (!send.length || !receive.length) return { body: null, reason: "one_side_empty" };
  if (send.length > DESK_MAX_ASSETS_PER_SIDE || receive.length > DESK_MAX_ASSETS_PER_SIDE) {
    return { body: null, reason: "too_many_assets" };
  }
  return {
    body: {
      leagueKey,
      myTeam: parties.myTeam,
      opponent: parties.opponent,
      source: "calculator",
      send,
      receive,
    },
    reason: null,
  };
}

const DESK_REASON_TEXT = {
  one_side_empty: "Add assets to both sides first.",
  too_many_assets: `The Trade Desk holds at most ${DESK_MAX_ASSETS_PER_SIDE} assets per side.`,
  no_league: "No league is selected.",
};

export function deskReasonText(reason) {
  return DESK_REASON_TEXT[reason] || tradePartiesText(reason);
}

/**
 * The `/api/manager-scout/offer-evidence` body: what the OPPONENT would
 * receive (the user's side) and send, for the one Manager Scout owner.
 */
export function offerEvidenceBody({ sides, parties }) {
  if (!parties?.ok) return null;
  const theyReceive = (sides[parties.mySideIdx]?.assets || []).map(packageAsset);
  const theySend = (sides[1 - parties.mySideIdx]?.assets || []).map(packageAsset);
  if (!theyReceive.length && !theySend.length) return null;
  return { myTeam: parties.myTeam, opponent: parties.opponent, theyReceive, theySend };
}

export function offerEvidenceUrl(leagueKey) {
  const base = "/api/manager-scout/offer-evidence";
  return leagueKey ? `${base}?leagueKey=${encodeURIComponent(leagueKey)}` : base;
}

/**
 * The balancing next step, from the page's own balancer state: where the
 * suggestions are, or why there are none.  Never a second balancer.
 *   state: "empty" | "incomplete" | "fair" | "suggested" | "none_found" | "multi"
 */
export function balanceStep({ evalState, isFair, balancerSideLabel, sideCount }) {
  if (evalState === "empty") return { state: "empty", text: "Add assets to compare first." };
  if (evalState === "incomplete") {
    return {
      state: "incomplete",
      text: "Price every asset first: balancing is not computed over an unpriced piece.",
    };
  }
  if (isFair) return { state: "fair", text: "Already inside the fair band — nothing to balance." };
  if (balancerSideLabel) {
    return {
      state: "suggested",
      text: `Balancing suggestions are listed under Side ${balancerSideLabel}.`,
      href: `#trade-side-${balancerSideLabel}-balancers`,
    };
  }
  return {
    state: sideCount > 2 ? "multi" : "none_found",
    text: "No single asset from that roster narrows the gap.",
  };
}
