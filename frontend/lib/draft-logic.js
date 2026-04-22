/**
 * Draft-board logic — pure inflation math + state helpers for the
 * live auction dashboard at ``/draft``.
 *
 * Ported from Jason's "Inflation" Google Sheet
 * (https://docs.google.com/spreadsheets/d/17wa6qdZ1Y8ckb4TIVZ4_C71g0skvtk9UZy43zSFzRlA).
 * Every number matches a cell in that sheet; every formula has a
 * comment pointing at the column it came from.
 *
 * Formulas:
 *
 *   Inflation          = Remaining League $ / Undrafted PreDraft $
 *   Inflated Fair      = PreDraft $ × Inflation
 *   Budget Advantage   = My Remaining / Avg $ per Other Team
 *   My Max Bid         = PreDraft × (1 + Aggression × (Advantage − 1)) × Inflation
 *   Enforce Up To      = Inflated Fair × Enforce %
 *
 * No React dependencies — fully testable.
 */

// ── Storage key ─────────────────────────────────────────────────────────
export const DRAFT_STORAGE_KEY = "next_draft_board_v1";

// ── Defaults (match the sheet's ``Settings`` block) ─────────────────────
export const DEFAULT_TOTAL_BUDGET = 1200;
export const DEFAULT_TEAM_COUNT = 12;
export const DEFAULT_AGGRESSION = 0.09;
export const DEFAULT_ENFORCE_PCT = 0.8;

// ── Default team roster ─────────────────────────────────────────────────
// Total league pool is $1200 (the sum of DEFAULT_ROOKIES.preDraft).  The
// sheet reports Russini Panini (Jason) at $417 and "Other Teams
// Remaining" at $784 spread across the remaining 11 teams — we split
// that 783 as ``71 × 10 + 73`` to sum exactly to 1200 with integer
// budgets.  The user will almost always replace these with their real
// carry-over balances, but defaulting to the sheet's anchor keeps the
// opening inflation math matching the sheet cell-for-cell.
export const DEFAULT_TEAMS = [
  { name: "Russini Panini", initialBudget: 417 },
  { name: "Ed", initialBudget: 71 },
  { name: "Brent", initialBudget: 71 },
  { name: "Joey", initialBudget: 71 },
  { name: "MaKayla", initialBudget: 71 },
  { name: "Ty", initialBudget: 71 },
  { name: "Kich", initialBudget: 71 },
  { name: "Eric", initialBudget: 71 },
  { name: "Collin", initialBudget: 71 },
  { name: "Roy", initialBudget: 71 },
  { name: "Blaine", initialBudget: 71 },
  { name: "Joel", initialBudget: 73 },
];

// ── Seed rookie pool ────────────────────────────────────────────────────
// Verbatim from the Inflation tab (columns A-C).  Sums to $1200 to keep
// the league-wide accounting consistent with the sheet.  PreDraft values
// are the user's own valuations — the app lets them be edited inline.
export const DEFAULT_ROOKIES = [
  { rank: 1, name: "Jeremiyah Love", preDraft: 135 },
  { rank: 2, name: "Fernando Mendoza", preDraft: 102 },
  { rank: 3, name: "Makai Lemon", preDraft: 90 },
  { rank: 4, name: "Carnell Tate", preDraft: 83 },
  { rank: 5, name: "Jordyn Tyson", preDraft: 73 },
  { rank: 6, name: "Sonny Styles", preDraft: 66 },
  { rank: 7, name: "Caleb Downs", preDraft: 61 },
  { rank: 8, name: "Kenyon Sadiq", preDraft: 55 },
  { rank: 9, name: "Emmanuel McNeil-Warren", preDraft: 51 },
  { rank: 10, name: "Dillon Thieneman", preDraft: 45 },
  { rank: 11, name: "David Bailey", preDraft: 41 },
  { rank: 12, name: "Arvell Reese", preDraft: 36 },
  { rank: 13, name: "CJ Allen", preDraft: 32 },
  { rank: 14, name: "KC Concepcion", preDraft: 29 },
  { rank: 15, name: "Omar Cooper", preDraft: 26 },
  { rank: 16, name: "Denzel Boston", preDraft: 24 },
  { rank: 17, name: "Eli Stowers", preDraft: 21 },
  { rank: 18, name: "Ty Simpson", preDraft: 19 },
  { rank: 19, name: "Jadarian Price", preDraft: 17 },
  { rank: 20, name: "Rueben Bain", preDraft: 15 },
  { rank: 21, name: "Jonah Coleman", preDraft: 14 },
  { rank: 22, name: "Mike Washington", preDraft: 13 },
  { rank: 23, name: "Nicholas Singleton", preDraft: 11 },
  { rank: 24, name: "Emmett Johnson", preDraft: 10 },
  { rank: 25, name: "Elijah Sarratt", preDraft: 9 },
  { rank: 26, name: "Chris Brazzell", preDraft: 9 },
  { rank: 27, name: "Chris Bell", preDraft: 8 },
  { rank: 28, name: "Zachariah Branch", preDraft: 7 },
  { rank: 29, name: "Germie Bernard", preDraft: 7 },
  { rank: 30, name: "Malachi Fields", preDraft: 6 },
  { rank: 31, name: "Max Klare", preDraft: 5 },
  { rank: 32, name: "Kaytron Allen", preDraft: 5 },
  { rank: 33, name: "Ja'Kobi Lane", preDraft: 5 },
  { rank: 34, name: "Garrett Nussmeier", preDraft: 4 },
  { rank: 35, name: "Skyler Bell", preDraft: 4 },
  { rank: 36, name: "Michael Trigg", preDraft: 4 },
  { rank: 37, name: "Jake Golday", preDraft: 4 },
  { rank: 38, name: "Joe Royer", preDraft: 3 },
  { rank: 39, name: "Anthony Hill", preDraft: 3 },
  { rank: 40, name: "Josiah Trotter", preDraft: 3 },
  { rank: 41, name: "Ted Hurst", preDraft: 3 },
  { rank: 42, name: "Adam Randall", preDraft: 3 },
  { rank: 43, name: "Bryce Lance", preDraft: 3 },
  { rank: 44, name: "Demond Claiborne", preDraft: 3 },
  { rank: 45, name: "Justin Joly", preDraft: 2 },
  { rank: 46, name: "Cashius Howell", preDraft: 2 },
  { rank: 47, name: "Brenen Thompson", preDraft: 2 },
  { rank: 48, name: "Oscar Delp", preDraft: 2 },
  { rank: 49, name: "Vinny Anthony", preDraft: 2 },
  { rank: 50, name: "Akheem Mesidor", preDraft: 2 },
  { rank: 51, name: "Sam Roush", preDraft: 2 },
  { rank: 52, name: "A.J. Haulcy", preDraft: 2 },
  { rank: 53, name: "Keldric Faulk", preDraft: 2 },
  { rank: 54, name: "Peter Woods", preDraft: 2 },
  { rank: 55, name: "Kevin Coleman", preDraft: 2 },
  { rank: 56, name: "Tanner Koziol", preDraft: 2 },
  { rank: 57, name: "Deion Burks", preDraft: 2 },
  { rank: 58, name: "Reggie Virgil", preDraft: 2 },
  { rank: 59, name: "Eric McAlister", preDraft: 2 },
  { rank: 60, name: "John Michael Gyllenborg", preDraft: 2 },
  { rank: 61, name: "De'Zhaun Stribling", preDraft: 1 },
  { rank: 62, name: "Drew Allar", preDraft: 1 },
  { rank: 63, name: "Roman Hemby", preDraft: 1 },
  { rank: 64, name: "Jeff Caldwell", preDraft: 1 },
  { rank: 65, name: "Le'Veon Moss", preDraft: 1 },
  { rank: 66, name: "Carson Beck", preDraft: 1 },
  { rank: 67, name: "Seth McGowan", preDraft: 1 },
  { rank: 68, name: "Cade Klubnik", preDraft: 1 },
  { rank: 69, name: "J'Mari Taylor", preDraft: 1 },
  { rank: 70, name: "CJ Daniels", preDraft: 1 },
  { rank: 71, name: "Caleb Douglas", preDraft: 1 },
  { rank: 72, name: "Aaron Anderson", preDraft: 1 },
];

// ── Player ID slug ──────────────────────────────────────────────────────
/**
 * Produce a stable slug from a player name.  Used as the key on picks
 * so renaming a player in the roster doesn't orphan their pick.  Callers
 * that want to rename a player should update both the roster entry and
 * any pick entries that reference the old slug.
 */
export function playerSlug(name) {
  return String(name || "")
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, "-")
    .replace(/^-+|-+$/g, "");
}

// ── Default workspace ───────────────────────────────────────────────────
/**
 * Build a pristine default workspace.  Called on first visit and when
 * the user clicks "Reset".
 */
export function createDefaultWorkspace() {
  return {
    version: 1,
    settings: {
      myTeamIdx: 0,
      aggression: DEFAULT_AGGRESSION,
      enforcePct: DEFAULT_ENFORCE_PCT,
    },
    teams: DEFAULT_TEAMS.map((t) => ({ ...t })),
    players: DEFAULT_ROOKIES.map((p) => ({
      id: playerSlug(p.name),
      rank: p.rank,
      name: p.name,
      preDraft: p.preDraft,
    })),
    picks: [], // { playerId, teamIdx, amount, ts }
  };
}

// ── Derived stats ───────────────────────────────────────────────────────
/**
 * Compute every derived value the UI renders from a workspace.  All
 * money values are rounded to the nearest whole dollar; the sheet
 * rounds in the same places so the display matches.
 *
 * Returns:
 *   totalBudget, totalSpent, remainingLeague, myTeamName,
 *   myStarting, mySpent, myRemaining, otherTeamsRemaining,
 *   avgPerOtherTeam, budgetAdvantage, undraftedPreDraft, inflation,
 *   leagueSpentPct, teamStats[], enrichedPlayers[]
 *
 * ``enrichedPlayers`` carries, per row:
 *   id, rank, name, preDraft, pick (|| null), drafted (bool),
 *   mine (bool), inflatedFair, myMaxBid, enforceUpTo, valueVsFair
 *
 * Undrafted rows get live inflation + max-bid; drafted rows get
 * ``valueVsFair`` = InflatedFairAtDraftTime − pick.amount (approx; we
 * use current inflation as the fair-price proxy since the sheet does
 * the same when its history snapshot is current).
 */
export function computeDraftStats(workspace) {
  const ws = workspace || createDefaultWorkspace();
  const teams = Array.isArray(ws.teams) ? ws.teams : [];
  const players = Array.isArray(ws.players) ? ws.players : [];
  const picks = Array.isArray(ws.picks) ? ws.picks : [];
  const settings = ws.settings || {};
  const myTeamIdx = Number.isInteger(settings.myTeamIdx)
    ? Math.max(0, Math.min(teams.length - 1, settings.myTeamIdx))
    : 0;
  const aggression = Number.isFinite(settings.aggression)
    ? settings.aggression
    : DEFAULT_AGGRESSION;
  const enforcePct = Number.isFinite(settings.enforcePct)
    ? settings.enforcePct
    : DEFAULT_ENFORCE_PCT;

  // League-wide money accounting.  ``initialBudget`` is the PER-TEAM
  // entrance budget — for carry-over leagues this varies by team, so
  // we sum to get ``totalBudget`` rather than assuming uniform split.
  const totalBudget = teams.reduce(
    (s, t) => s + (Number(t.initialBudget) || 0),
    0,
  );
  const totalSpent = picks.reduce(
    (s, p) => s + (Number(p.amount) || 0),
    0,
  );
  const remainingLeague = Math.max(0, totalBudget - totalSpent);

  // My team's money.
  const myTeam = teams[myTeamIdx] || { name: "", initialBudget: 0 };
  const myStarting = Number(myTeam.initialBudget) || 0;
  const mySpent = picks
    .filter((p) => p.teamIdx === myTeamIdx)
    .reduce((s, p) => s + (Number(p.amount) || 0), 0);
  const myRemaining = Math.max(0, myStarting - mySpent);

  // Other teams' money (aggregate).  Used for the budget-advantage
  // factor — the sheet divides the aggregate by (teams − 1) rather
  // than weighting per-team, which is what we mirror here.
  const otherTeamsRemaining = Math.max(0, remainingLeague - myRemaining);
  const otherTeamCount = Math.max(1, teams.length - 1);
  const avgPerOtherTeam = otherTeamsRemaining / otherTeamCount;
  // Guard: divide-by-zero when every other team is tapped.  Fall back
  // to "no advantage" (1.0) so MyMaxBid stays at PreDraft × Inflation.
  const rawBudgetAdvantage =
    avgPerOtherTeam > 0 ? myRemaining / avgPerOtherTeam : 1;
  // The sheet displays BAF at 2dp (e.g. 5.85) and uses THAT truncated
  // value inside the MaxBid formula.  Truncating here — rather than
  // carrying full precision — is what makes MaxBid for Jeremiyah
  // Love come out to 193 instead of 194, matching the sheet
  // cell-for-cell.
  const budgetAdvantage = Math.floor(rawBudgetAdvantage * 100) / 100;

  // Inflation denominator: the sheet uses ``TotalAuction$ − Σ (sold
  // players' preDraft $)`` rather than the dynamic sum of undrafted
  // preDraft values.  The difference matters when the preDraft column
  // doesn't sum to exactly ``totalBudget`` — which is the common case,
  // because users tune preDraft values for *relative* player worth and
  // those don't have to land on the budget total.  Using ``totalBudget``
  // as the baseline keeps the opening inflation pinned at 1.0 so Fair
  // Price == PreDraft$ at the start regardless of column-sum drift,
  // matching the sheet cell-for-cell.
  const pickedPlayerIds = new Set(picks.map((p) => p.playerId));
  const playerPreDraftById = new Map(
    players.map((p) => [p.id, Number(p.preDraft) || 0]),
  );
  const soldPreDraft = picks.reduce(
    (s, pk) => s + (playerPreDraftById.get(pk.playerId) || 0),
    0,
  );
  const expectedPoolRemaining = Math.max(1, totalBudget - soldPreDraft);
  const inflation = remainingLeague / expectedPoolRemaining;

  // Kept for the "Board $ left" display card.  This is the literal sum
  // of still-on-the-board preDraft values — different from the
  // inflation denominator above when the column doesn't sum to budget.
  const undraftedPreDraft = players
    .filter((p) => !pickedPlayerIds.has(p.id))
    .reduce((s, p) => s + (Number(p.preDraft) || 0), 0);
  const leagueSpentPct = totalBudget > 0 ? totalSpent / totalBudget : 0;

  // Per-team stats (name, initial, spent, remaining).
  const teamStats = teams.map((t, idx) => {
    const spent = picks
      .filter((p) => p.teamIdx === idx)
      .reduce((s, p) => s + (Number(p.amount) || 0), 0);
    const initial = Number(t.initialBudget) || 0;
    const remaining = Math.max(0, initial - spent);
    const picksCount = picks.filter((p) => p.teamIdx === idx).length;
    return {
      idx,
      name: t.name || `Team ${idx + 1}`,
      initialBudget: initial,
      spent,
      remaining,
      picksCount,
      isMine: idx === myTeamIdx,
    };
  });

  // Pick lookup (playerId → pick) for the player-row enrichment.
  const pickByPlayer = new Map();
  for (const pk of picks) pickByPlayer.set(pk.playerId, pk);

  const enrichedPlayers = players.map((p) => {
    const pick = pickByPlayer.get(p.id) || null;
    const preDraft = Math.max(0, Number(p.preDraft) || 0);
    // The sheet truncates (FLOOR) these derived dollar values rather
    // than rounding — matching that is the difference between
    // "MaxBid 193" (sheet) vs "MaxBid 194" (round).  Keeping the UI
    // cell-for-cell identical to the sheet means the user can trust
    // that the two views agree.
    const inflatedFair = Math.floor(preDraft * inflation);
    const myMaxBid = Math.floor(
      preDraft * (1 + aggression * (budgetAdvantage - 1)) * inflation,
    );
    const enforceUpTo = Math.floor(inflatedFair * enforcePct);
    const drafted = !!pick;
    const mine = drafted && pick.teamIdx === myTeamIdx;
    const valueVsFair =
      drafted && Number.isFinite(Number(pick.amount))
        ? inflatedFair - Number(pick.amount)
        : null;
    return {
      ...p,
      preDraft,
      pick,
      drafted,
      mine,
      inflatedFair: Math.max(0, inflatedFair),
      myMaxBid: Math.max(0, myMaxBid),
      enforceUpTo: Math.max(0, enforceUpTo),
      valueVsFair,
    };
  });

  return {
    totalBudget,
    totalSpent,
    remainingLeague,
    myTeamName: myTeam.name || "",
    myStarting,
    mySpent,
    myRemaining,
    otherTeamsRemaining,
    avgPerOtherTeam,
    budgetAdvantage,
    undraftedPreDraft,
    inflation,
    leagueSpentPct,
    teamStats,
    enrichedPlayers,
  };
}

// ── State mutators (pure) ───────────────────────────────────────────────
/**
 * Record a draft pick.  Returns a new workspace; does not mutate.
 * If the player is already drafted, the pick is replaced (so an edit
 * is a no-op record-the-same-pick call).
 */
export function recordPick(workspace, { playerId, teamIdx, amount }) {
  if (!playerId || !Number.isInteger(teamIdx)) return workspace;
  const amt = Math.max(0, Number(amount) || 0);
  const picks = (workspace.picks || []).filter((p) => p.playerId !== playerId);
  picks.push({ playerId, teamIdx, amount: amt, ts: Date.now() });
  return { ...workspace, picks };
}

/** Undo the most recent pick (by ts). */
export function undoLastPick(workspace) {
  const picks = workspace.picks || [];
  if (picks.length === 0) return workspace;
  const sorted = [...picks].sort((a, b) => (b.ts || 0) - (a.ts || 0));
  const toRemove = sorted[0];
  return {
    ...workspace,
    picks: picks.filter((p) => p !== toRemove),
  };
}

/** Remove a specific pick (used for the edit flow). */
export function removePick(workspace, playerId) {
  return {
    ...workspace,
    picks: (workspace.picks || []).filter((p) => p.playerId !== playerId),
  };
}

/** Update a player's PreDraft $ inline. */
export function updatePlayerPreDraft(workspace, playerId, newPreDraft) {
  const players = (workspace.players || []).map((p) =>
    p.id === playerId
      ? { ...p, preDraft: Math.max(0, Number(newPreDraft) || 0) }
      : p,
  );
  return { ...workspace, players };
}

/** Update a team's name or initial budget. */
export function updateTeam(workspace, teamIdx, patch) {
  const teams = (workspace.teams || []).map((t, i) =>
    i === teamIdx ? { ...t, ...patch } : t,
  );
  return { ...workspace, teams };
}

/** Update a settings field (myTeamIdx / aggression / enforcePct). */
export function updateSettings(workspace, patch) {
  return {
    ...workspace,
    settings: { ...(workspace.settings || {}), ...patch },
  };
}

/**
 * Merge per-team auction $ from ``/api/draft-capital`` onto a workspace.
 *
 * The draft-capital endpoint returns one row per team that's carrying
 * carry-over auction dollars — typically 10 of 12 teams (the two with
 * $0 budget are usually omitted from the API response because they
 * traded every rookie pick away).  We merge by case-insensitive team
 * name, preserving:
 *
 *   - Any team the user already renamed manually (we match the
 *     original name so a manual rename doesn't block the merge).
 *   - Teams that already have picks recorded against them (we NEVER
 *     blow away budgets mid-draft; callers should only invoke this
 *     when ``workspace.picks`` is empty, or explicitly ack the reset).
 *
 * Any team in the capital feed that doesn't already exist on the
 * board is appended to the end.  Teams on the board but missing from
 * the feed keep their existing budget (or default to 0 if this is a
 * fresh load).  A ``myTeamIdx`` remap is also returned so the UI can
 * re-pin the user's team even if the order changes.
 *
 * @param {object} workspace - existing workspace (mutated into a new copy)
 * @param {{team: string, auctionDollars: number}[]} teamTotals
 *   — raw ``teamTotals`` array from the /api/draft-capital payload
 * @param {object} [opts]
 * @param {boolean} [opts.preserveCustomNames=true]  — when true, a
 *   manually-edited team name is kept if its budget matches the feed;
 *   when false, the feed's names win.
 * @returns {{workspace: object, matched: number, added: number, missing: string[]}}
 */
export function mergeDraftCapitalTeams(workspace, teamTotals, opts = {}) {
  const preserveNames = opts.preserveCustomNames !== false;
  const ws = workspace || createDefaultWorkspace();
  const existing = Array.isArray(ws.teams) ? ws.teams : [];
  const feed = Array.isArray(teamTotals) ? teamTotals : [];

  // Build a case-insensitive lookup from the feed.
  const feedByKey = new Map();
  for (const entry of feed) {
    const name = String(entry?.team || "").trim();
    if (!name) continue;
    feedByKey.set(name.toLowerCase(), {
      name,
      auctionDollars: Math.max(0, Number(entry?.auctionDollars) || 0),
    });
  }

  const myTeamIdx = Number.isInteger(ws.settings?.myTeamIdx)
    ? ws.settings.myTeamIdx
    : 0;
  const myTeamNameBefore = existing[myTeamIdx]?.name || "";

  // Walk existing teams, matching by name.  Unmatched entries keep
  // their current budget — the UI can flag them as "missing from
  // capital feed" if needed.
  const usedFeedKeys = new Set();
  const merged = existing.map((t) => {
    const key = String(t.name || "").toLowerCase();
    const hit = feedByKey.get(key);
    if (!hit) return { ...t };
    usedFeedKeys.add(key);
    return {
      name: preserveNames && t.name ? t.name : hit.name,
      initialBudget: hit.auctionDollars,
    };
  });

  // Append any feed teams not already on the board.  These are the
  // rows that just showed up in the capital feed — most likely after
  // a Sleeper re-sync.
  const missing = [];
  for (const [key, hit] of feedByKey.entries()) {
    if (usedFeedKeys.has(key)) continue;
    merged.push({ name: hit.name, initialBudget: hit.auctionDollars });
    missing.push(hit.name);
  }

  // Re-locate my team by name so the selection survives the merge.
  let nextMyIdx = merged.findIndex(
    (t) => String(t.name || "").toLowerCase() === myTeamNameBefore.toLowerCase(),
  );
  if (nextMyIdx < 0) nextMyIdx = myTeamIdx >= 0 && myTeamIdx < merged.length ? myTeamIdx : 0;

  return {
    workspace: {
      ...ws,
      teams: merged,
      settings: { ...(ws.settings || {}), myTeamIdx: nextMyIdx },
    },
    matched: usedFeedKeys.size,
    added: missing.length,
    missing,
  };
}

/**
 * True when the workspace has never been modified beyond defaults.
 * Used to decide whether auto-load from ``/api/draft-capital`` is
 * safe — we don't want to clobber budgets the user has already
 * edited by hand.
 */
export function workspaceIsPristine(workspace) {
  const ws = workspace || {};
  if (!Array.isArray(ws.picks) || ws.picks.length !== 0) return false;
  const def = createDefaultWorkspace();
  if ((ws.teams || []).length !== def.teams.length) return false;
  for (let i = 0; i < def.teams.length; i++) {
    const a = ws.teams[i] || {};
    const b = def.teams[i];
    if (a.name !== b.name || a.initialBudget !== b.initialBudget) return false;
  }
  return true;
}

/** Add a new rookie row to the board. */
export function addPlayer(workspace, { name, preDraft }) {
  const id = playerSlug(name);
  if (!id) return workspace;
  const existing = (workspace.players || []).some((p) => p.id === id);
  if (existing) return workspace;
  const nextRank =
    (workspace.players || []).reduce(
      (max, p) => Math.max(max, Number(p.rank) || 0),
      0,
    ) + 1;
  return {
    ...workspace,
    players: [
      ...(workspace.players || []),
      { id, rank: nextRank, name, preDraft: Math.max(0, Number(preDraft) || 0) },
    ],
  };
}

/** Remove a rookie row and any pick referencing it. */
export function removePlayer(workspace, playerId) {
  return {
    ...workspace,
    players: (workspace.players || []).filter((p) => p.id !== playerId),
    picks: (workspace.picks || []).filter((p) => p.playerId !== playerId),
  };
}

// ── Serialization ───────────────────────────────────────────────────────
/** Validate + coerce a parsed localStorage payload into a workspace. */
export function hydrateWorkspace(parsed) {
  if (!parsed || typeof parsed !== "object") return createDefaultWorkspace();
  if (parsed.version !== 1) return createDefaultWorkspace();
  const def = createDefaultWorkspace();
  return {
    version: 1,
    settings: {
      myTeamIdx: Number.isInteger(parsed.settings?.myTeamIdx)
        ? parsed.settings.myTeamIdx
        : def.settings.myTeamIdx,
      aggression: Number.isFinite(parsed.settings?.aggression)
        ? parsed.settings.aggression
        : def.settings.aggression,
      enforcePct: Number.isFinite(parsed.settings?.enforcePct)
        ? parsed.settings.enforcePct
        : def.settings.enforcePct,
    },
    teams: Array.isArray(parsed.teams) && parsed.teams.length > 0
      ? parsed.teams.map((t, i) => ({
          name: String(t?.name || `Team ${i + 1}`),
          initialBudget: Math.max(0, Number(t?.initialBudget) || 0),
        }))
      : def.teams,
    players: Array.isArray(parsed.players) && parsed.players.length > 0
      ? parsed.players.map((p, i) => ({
          id: String(p?.id || playerSlug(p?.name) || `player-${i}`),
          rank: Number(p?.rank) || i + 1,
          name: String(p?.name || ""),
          preDraft: Math.max(0, Number(p?.preDraft) || 0),
        }))
      : def.players,
    picks: Array.isArray(parsed.picks)
      ? parsed.picks
          .map((p) => ({
            playerId: String(p?.playerId || ""),
            teamIdx: Number.isInteger(p?.teamIdx) ? p.teamIdx : -1,
            amount: Math.max(0, Number(p?.amount) || 0),
            ts: Number(p?.ts) || Date.now(),
          }))
          .filter((p) => p.playerId && p.teamIdx >= 0)
      : [],
  };
}

/** Bid-status classification for UI color coding. */
export function bidStatus(enrichedPlayer, currentBid) {
  if (!enrichedPlayer) return { level: "unknown", label: "" };
  if (enrichedPlayer.drafted) {
    if (enrichedPlayer.mine) return { level: "mine", label: "Mine" };
    return { level: "gone", label: "Gone" };
  }
  const bid = Math.max(0, Number(currentBid) || 0);
  if (bid <= 0) return { level: "idle", label: "Watching" };
  if (bid <= enrichedPlayer.enforceUpTo) return { level: "push", label: "Push up" };
  if (bid <= enrichedPlayer.myMaxBid) return { level: "target", label: "Sweet spot" };
  return { level: "pass", label: "Pass" };
}
