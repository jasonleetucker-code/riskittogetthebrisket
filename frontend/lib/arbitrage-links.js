/**
 * arbitrage-links — the ONE owner of the /arbitrage deep-link contract.
 *
 * Two link shapes reach /arbitrage, and both are written and read here so a
 * link one surface emits cannot be misread by a reader another surface owns:
 *
 *   1. Tool links from /trade "Next steps" (TC-B / TCM-O11):
 *      `/arbitrage?tool=<id>&team=<team name>[&opponent=<team name>]`
 *   2. Package Builder seeds from Manager Intelligence (Batch D):
 *      `/arbitrage?tool=builder&league=<leagueKey>&opponent=<owner user id>
 *       [&target=<board name>]`
 *
 * They share `tool` and `opponent`, so the shape is decided by the `league`
 * parameter: only a seed carries it.  Without that rule a tool link's team
 * NAME was parsed as a malformed owner id and the builder reported "the
 * link's team could not be read" on a perfectly good link.
 *
 * Pure and import-free on purpose: /trade and /managers both import it, and
 * neither should pull the other's page code into its chunk.
 */

/** /arbitrage tools a link may open — the ids of `TOOL_TABS` there. */
export const ARBITRAGE_TOOL_IDS = ["golden", "scan", "best", "builder", "desk"];

const MAX_PARAM_LEN = 120;

function cleanParam(value) {
  const text = String(value ?? "").trim();
  return text && text.length <= MAX_PARAM_LEN ? text : "";
}

function readParams(search) {
  if (typeof search !== "string" || !search) return null;
  try {
    return new URLSearchParams(search.startsWith("?") ? search.slice(1) : search);
  } catch {
    return null;
  }
}

// ── 1. Tool links (team names) ──────────────────────────────────────────

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

// ── 2. Package Builder seeds (owner ids) ────────────────────────────────
//
// The opponent travels as the team's permanent Sleeper owner id, never its
// display name, and is resolved against the loaded league's teams by the
// view (`seedOpponentTeam` in lib/package-builder) — a seed for a league or
// owner the page does not hold applies nothing and says so.

export const BUILDER_SEED_TOOL = "builder";
const SEED_OWNER_RE = /^\d{1,24}$/;
const SEED_LEAGUE_RE = /^[a-z][a-z0-9_-]{0,63}$/;
const SEED_TARGET_MAX = 64;

/** The builder seed link, or null when the owner id is not a valid one. */
export function builderSeedHref({ leagueKey, opponentOwner, target } = {}) {
  const owner = String(opponentOwner ?? "");
  const league = String(leagueKey ?? "");
  if (!SEED_OWNER_RE.test(owner) || !SEED_LEAGUE_RE.test(league)) return null;
  const params = new URLSearchParams({
    tool: BUILDER_SEED_TOOL,
    league,
    opponent: owner,
  });
  const t = String(target ?? "").trim();
  if (t && t.length <= SEED_TARGET_MAX) params.set("target", t);
  return `/arbitrage?${params.toString()}`;
}

/**
 * The seed a ``/arbitrage`` URL carries, or null when it is not a seed link
 * (no `league` parameter — e.g. a /trade tool link).  Untrusted input: a seed
 * link with a malformed owner or league is returned EMPTY, so the view can
 * say nothing was pre-filled rather than half-apply it.
 */
export function parseBuilderSeed(search) {
  const params = readParams(search);
  if (!params || params.get("tool") !== BUILDER_SEED_TOOL) return null;
  if (!params.has("league")) return null;
  const owner = params.get("opponent") || "";
  const league = params.get("league") || "";
  if (!SEED_OWNER_RE.test(owner) || !SEED_LEAGUE_RE.test(league)) {
    return { opponentOwner: "", leagueKey: "", target: "" };
  }
  const t = String(params.get("target") || "").trim();
  return {
    opponentOwner: owner,
    leagueKey: league,
    target: t && t.length <= SEED_TARGET_MAX ? t : "",
  };
}

// ── The one reader /arbitrage calls ─────────────────────────────────────

/**
 * Read either link shape.  `teamNames` are the league's current teams: a team
 * the league does not have is dropped, never guessed.  Returns
 * `{ tool, team, opponent, seed }`; `opponent` is a team NAME and is always
 * null on a seed link (there it is an owner id, carried in `seed`).
 */
export function parseArbitrageQuery(search, teamNames = []) {
  const params = readParams(search) || new URLSearchParams();
  const tool = params.get("tool");
  const seed = parseBuilderSeed(search);
  const names = new Set((teamNames || []).map((n) => String(n)));
  const team = cleanParam(params.get("team"));
  const opponent = seed ? "" : cleanParam(params.get("opponent"));
  return {
    tool: ARBITRAGE_TOOL_IDS.includes(tool) ? tool : null,
    team: team && names.has(team) ? team : null,
    opponent: opponent && names.has(opponent) && opponent !== team ? opponent : null,
    seed,
  };
}
