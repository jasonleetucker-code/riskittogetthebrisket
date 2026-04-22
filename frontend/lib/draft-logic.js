/**
 * Draft-board logic — pure inflation math + state helpers for the
 * live auction dashboard at ``/draft``.
 *
 * Originally ported from Jason's "Inflation" Google Sheet
 * (https://docs.google.com/spreadsheets/d/17wa6qdZ1Y8ckb4TIVZ4_C71g0skvtk9UZy43zSFzRlA);
 * Tier 1 upgrades (2026-04) extend it past the sheet in four ways:
 *
 *   1. ``preDraftAtPick`` snapshot on every pick so retroactive
 *      PreDraft edits don't corrupt historical inflation tracking.
 *   2. Per-team ``initialSlots`` accounting (from the live
 *      ``/api/draft-capital`` picks array) so "slots remaining"
 *      drives every budget calculation.
 *   3. Slot-adjusted ``effectiveBudget`` per team + per-player
 *      ``topCompetitorMax`` so MaxBid is capped by the richest
 *      rival that can still actually bid, not the mean.
 *   4. Phase multiplier (``slotPressure``) that ramps aggression
 *      as my roster nears full, plus tier-specific inflation
 *      (S / A / B / C / D buckets by PreDraft $) blended with
 *      global inflation under a confidence weight.
 *
 * Core formulas (post-upgrade):
 *
 *   Inflation            = RemainingLeague$ / (TotalAuction$ − Σ soldPreDraft)
 *   Tier heat(T)         = Σ paid in T / Σ preDraftAtPick in T
 *   Tier inflation(T)    = inflation × (conf × tier_heat + (1−conf) × 1)
 *   Budget Advantage(p)  = My Effective$ / (avg other effective$; min 1)
 *   Slot pressure        = 1 − myPicksRemaining / myInitialSlots
 *   Phase multiplier     = 1 + slotPressure × PHASE_LATE_BOOST
 *   Theoretical Max(p)   = PreDraft × (1 + Aggression × (BA−1)) × tierInflation(p) × phaseMultiplier
 *   Winning bid(p)       = min(Theoretical Max, topCompetitorMax + 1)
 *   Enforce Up To(p)     = Inflated Fair × Enforce %
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
/**
 * Default number of rookie picks per team before any trades.  The
 * actual per-team count is pulled from ``/api/draft-capital``'s
 * ``picks`` array on first load; this default only applies to a
 * pristine workspace before the fetch completes.
 */
export const DEFAULT_INITIAL_SLOTS = 6;
/**
 * How much slot pressure converts into MaxBid ramp-up.  At
 * ``slotPressure=1`` (my last pick) MaxBid scales by
 * ``1 + PHASE_LATE_BOOST`` (1.5× at the default).  Prevents the
 * "I have $300 and 2 slots left, unused $ is wasted" failure mode.
 */
export const PHASE_LATE_BOOST = 0.5;
/**
 * Minimum number of tier samples needed before tier inflation is
 * trusted at full weight.  With fewer samples, tier inflation is
 * confidence-blended toward 1.0 (no tier adjustment beyond global).
 */
export const TIER_CONFIDENCE_MIN_SAMPLES = 3;

// ── Tier partitioning ──────────────────────────────────────────────────
// PreDraft $ cutoffs for the 5-tier classification.  Tier inflation is
// computed independently per tier so "elite tier hot" (S-heavy overpays)
// is surfaced separately from "cheap tier clearing" (D-heavy $1 picks).
// Ordered from most expensive to least; a player's tier is the first
// bucket whose ``min`` they meet.
export const TIER_DEFS = [
  { key: "S", label: "Elite", min: 60 },
  { key: "A", label: "Starter", min: 25 },
  { key: "B", label: "Depth", min: 8 },
  { key: "C", label: "Dart", min: 3 },
  { key: "D", label: "Min", min: 0 },
];

/**
 * Classify a PreDraft $ value into one of the 5 tiers.
 * Returns the tier key (``"S"``, ``"A"``, ..., ``"D"``).
 */
export function tierForPreDraft(preDraft) {
  const v = Math.max(0, Number(preDraft) || 0);
  for (const t of TIER_DEFS) {
    if (v >= t.min) return t.key;
  }
  return "D";
}

// ── Default team roster ─────────────────────────────────────────────────
// Total league pool is $1200 (the sum of DEFAULT_ROOKIES.preDraft).  The
// sheet reports Russini Panini (Jason) at $417 and "Other Teams
// Remaining" at $784 spread across the remaining 11 teams — we split
// that 783 as ``71 × 10 + 73`` to sum exactly to 1200 with integer
// budgets.  The user will almost always replace these with their real
// carry-over balances, but defaulting to the sheet's anchor keeps the
// opening inflation math matching the sheet cell-for-cell.
export const DEFAULT_TEAMS = [
  { name: "Russini Panini", initialBudget: 417, initialSlots: DEFAULT_INITIAL_SLOTS },
  { name: "Ed", initialBudget: 71, initialSlots: DEFAULT_INITIAL_SLOTS },
  { name: "Brent", initialBudget: 71, initialSlots: DEFAULT_INITIAL_SLOTS },
  { name: "Joey", initialBudget: 71, initialSlots: DEFAULT_INITIAL_SLOTS },
  { name: "MaKayla", initialBudget: 71, initialSlots: DEFAULT_INITIAL_SLOTS },
  { name: "Ty", initialBudget: 71, initialSlots: DEFAULT_INITIAL_SLOTS },
  { name: "Kich", initialBudget: 71, initialSlots: DEFAULT_INITIAL_SLOTS },
  { name: "Eric", initialBudget: 71, initialSlots: DEFAULT_INITIAL_SLOTS },
  { name: "Collin", initialBudget: 71, initialSlots: DEFAULT_INITIAL_SLOTS },
  { name: "Roy", initialBudget: 71, initialSlots: DEFAULT_INITIAL_SLOTS },
  { name: "Blaine", initialBudget: 71, initialSlots: DEFAULT_INITIAL_SLOTS },
  { name: "Joel", initialBudget: 73, initialSlots: DEFAULT_INITIAL_SLOTS },
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

/**
 * Count per-team rookie pick ownership from the raw ``picks`` array
 * returned by ``/api/draft-capital``.  Each pick's ``currentOwner``
 * (a team display name) contributes +1 to that team's slot count.
 *
 * Returns a ``Map<teamNameLowerCase, count>``.  Callers should resolve
 * the map against their own team list by lowercased name.
 */
export function slotsByTeamFromPicks(picksArray) {
  const out = new Map();
  if (!Array.isArray(picksArray)) return out;
  for (const pk of picksArray) {
    const owner = String(pk?.currentOwner || "").trim().toLowerCase();
    if (!owner) continue;
    out.set(owner, (out.get(owner) || 0) + 1);
  }
  return out;
}

/**
 * Slot-adjusted effective budget — the maximum $ a team can actually
 * bid on a single player right now, reserving $1 per OTHER remaining
 * slot so they can still fill their roster.  This is the number that
 * belongs in ``topCompetitorMax`` — the mean or even max of raw
 * remaining $ overstates real bidding power for teams with many
 * slots to fill.
 *
 *   effectiveBudget = 0 if slotsRemaining <= 0
 *                   = max(0, remaining − max(0, slotsRemaining − 1))
 *
 * Examples:
 *   (remaining 100, slots 3) → bid up to $98, reserve $1 × 2
 *   (remaining 5, slots 5)  → bid up to $1, reserve $1 × 4
 *   (remaining 50, slots 0) → 0 (team has no roster space left)
 *   (remaining 0, slots 1)  → 0 (team can only bid $1 min, but
 *                             the conventional "0 means can't
 *                             bid more than $1" is noise; explicit
 *                             0 in the UI is clearer)
 */
export function effectiveBudgetFor(remaining, slotsRemaining) {
  const rem = Math.max(0, Number(remaining) || 0);
  const slots = Math.max(0, Number(slotsRemaining) || 0);
  if (slots <= 0) return 0;
  return Math.max(0, rem - Math.max(0, slots - 1));
}

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
    // picks: { playerId, teamIdx, amount, preDraftAtPick, ts }
    //   - preDraftAtPick: snapshot of the PreDraft $ at the moment the
    //     pick was recorded.  Used for historical tier inflation so a
    //     retroactive edit to ``players[n].preDraft`` doesn't corrupt
    //     the paid/expected ratios of already-drafted players.
    picks: [],
  };
}

// ── Derived stats ───────────────────────────────────────────────────────
/**
 * Compute every derived value the UI renders from a workspace.
 *
 * Tier 1 return shape adds (beyond the sheet-port baseline):
 *
 *   slotPressure          0..1 — how far through my own draft I am
 *   phaseMultiplier       1 + slotPressure × PHASE_LATE_BOOST
 *   topCompetitorMax      slot-adjusted max effective $ of any OTHER team
 *   tierHeat              { S/A/B/C/D: paidSum/preDraftSum or null }
 *   tierConfidence        { S/A/B/C/D: 0..1 } — sample-size weight
 *   teamStats[i]          + initialSlots, slotsDrafted, slotsRemaining,
 *                           effectiveBudget
 *   enrichedPlayers[p]    + tier, tierInflation, theoreticalMaxBid,
 *                           myWinningBid, exceedsMyCeiling
 *
 *   myMaxBid now carries the THEORETICAL ceiling (what you'd be
 *   willing to pay if the competitor set demanded it).  Actual
 *   bid-to-win is ``myWinningBid`` = min(myMaxBid, topCompetitorMax+1).
 *   The UI should surface myWinningBid as the headline figure and
 *   myMaxBid as the tooltip explainer.
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

  // League-wide money accounting.
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
  const myTeam = teams[myTeamIdx] || {
    name: "",
    initialBudget: 0,
    initialSlots: DEFAULT_INITIAL_SLOTS,
  };
  const myStarting = Number(myTeam.initialBudget) || 0;
  const mySpent = picks
    .filter((p) => p.teamIdx === myTeamIdx)
    .reduce((s, p) => s + (Number(p.amount) || 0), 0);
  const myRemaining = Math.max(0, myStarting - mySpent);

  // ── Slot accounting ────────────────────────────────────────────────
  // Per-team slots drafted + remaining.  ``initialSlots`` is set on
  // the team when ``/api/draft-capital`` merges; absent that, we
  // fall back to the 6-round default so pre-merge state still works.
  const picksByTeam = teams.map(() => []);
  for (const pk of picks) {
    if (
      Number.isInteger(pk.teamIdx) &&
      pk.teamIdx >= 0 &&
      pk.teamIdx < teams.length
    ) {
      picksByTeam[pk.teamIdx].push(pk);
    }
  }
  const initialSlotsByIdx = teams.map((t) =>
    Number.isFinite(Number(t?.initialSlots))
      ? Math.max(0, Number(t.initialSlots))
      : DEFAULT_INITIAL_SLOTS,
  );
  const slotsDraftedByIdx = picksByTeam.map((pks) => pks.length);
  const slotsRemainingByIdx = teams.map((_, i) =>
    Math.max(0, initialSlotsByIdx[i] - slotsDraftedByIdx[i]),
  );
  const remainingByIdx = teams.map((t, i) => {
    const spent = picksByTeam[i].reduce(
      (s, p) => s + (Number(p.amount) || 0),
      0,
    );
    return Math.max(0, (Number(t.initialBudget) || 0) - spent);
  });
  const effectiveBudgetByIdx = teams.map((_, i) =>
    effectiveBudgetFor(remainingByIdx[i], slotsRemainingByIdx[i]),
  );

  // My slot pressure drives the phase multiplier: at the start
  // pressure=0 and MaxBid is unchanged; at my final pick pressure=1
  // and MaxBid scales up by (1 + PHASE_LATE_BOOST).  This prevents
  // the "unused $ is wasted $" failure mode when I'm wealthy but
  // only have one roster slot left.
  const myInitialSlots = initialSlotsByIdx[myTeamIdx] || 0;
  const mySlotsRemaining = slotsRemainingByIdx[myTeamIdx] || 0;
  const slotPressure =
    myInitialSlots > 0
      ? Math.max(0, Math.min(1, 1 - mySlotsRemaining / myInitialSlots))
      : 0;
  const phaseMultiplier = 1 + slotPressure * PHASE_LATE_BOOST;

  // Top competitor ceiling: the single richest OTHER team, after
  // slot adjustment.  This is the real "ceiling I need to clear" on
  // any given player — bidding 1 above it wins.  Without this cap,
  // MaxBid hallucinates opponents that can't actually outbid me.
  let topCompetitorMax = 0;
  for (let i = 0; i < effectiveBudgetByIdx.length; i++) {
    if (i === myTeamIdx) continue;
    if (effectiveBudgetByIdx[i] > topCompetitorMax) {
      topCompetitorMax = effectiveBudgetByIdx[i];
    }
  }

  // Other teams' money (aggregate).
  const otherTeamsRemaining = Math.max(0, remainingLeague - myRemaining);
  const otherTeamCount = Math.max(1, teams.length - 1);
  const avgPerOtherTeam = otherTeamsRemaining / otherTeamCount;
  const rawBudgetAdvantage =
    avgPerOtherTeam > 0 ? myRemaining / avgPerOtherTeam : 1;
  // The sheet displays BAF at 2dp (e.g. 5.85) and uses THAT truncated
  // value inside the MaxBid formula.  Truncating here — rather than
  // carrying full precision — is what makes MaxBid for Jeremiyah
  // Love come out to 193 instead of 194, matching the sheet
  // cell-for-cell.
  const budgetAdvantage = Math.floor(rawBudgetAdvantage * 100) / 100;

  // ── Global inflation (sheet-compatible) ────────────────────────────
  // inflation = remainingLeague / (totalBudget − soldPreDraft).
  // soldPreDraft uses the SNAPSHOTTED preDraftAtPick on each pick so a
  // retroactive edit to player.preDraft doesn't rewrite history.
  const pickedPlayerIds = new Set(picks.map((p) => p.playerId));
  const playerPreDraftById = new Map(
    players.map((p) => [p.id, Number(p.preDraft) || 0]),
  );
  const soldPreDraft = picks.reduce((s, pk) => {
    const snap = Number.isFinite(Number(pk.preDraftAtPick))
      ? Math.max(0, Number(pk.preDraftAtPick))
      : playerPreDraftById.get(pk.playerId) || 0;
    return s + snap;
  }, 0);
  const expectedPoolRemaining = Math.max(1, totalBudget - soldPreDraft);
  const inflation = remainingLeague / expectedPoolRemaining;

  // Kept for the "Board $ left" display card.
  const undraftedPreDraft = players
    .filter((p) => !pickedPlayerIds.has(p.id))
    .reduce((s, p) => s + (Number(p.preDraft) || 0), 0);
  const leagueSpentPct = totalBudget > 0 ? totalSpent / totalBudget : 0;

  // ── Per-tier inflation (heat) ─────────────────────────────────────
  // tier_heat(T) = Σ paid / Σ preDraftAtPick within tier T.
  // Above 1.0 → tier was overpaid; remaining T players should mark up.
  // Below 1.0 → tier bargains; remaining T players mark down.
  //
  // Blended with 1.0 via a confidence weight based on sample count,
  // then multiplied on top of global inflation to produce
  // ``tierInflation`` (the actual modifier applied to fair/max bids).
  const tierHeat = {};
  const tierConfidence = {};
  const tierSampleCount = {};
  for (const def of TIER_DEFS) {
    const tierPicks = picks.filter((pk) => {
      const snap = Number.isFinite(Number(pk.preDraftAtPick))
        ? Math.max(0, Number(pk.preDraftAtPick))
        : playerPreDraftById.get(pk.playerId) || 0;
      return tierForPreDraft(snap) === def.key;
    });
    tierSampleCount[def.key] = tierPicks.length;
    if (tierPicks.length === 0) {
      tierHeat[def.key] = null;
      tierConfidence[def.key] = 0;
      continue;
    }
    const paidSum = tierPicks.reduce(
      (s, pk) => s + (Number(pk.amount) || 0),
      0,
    );
    const preSum = tierPicks.reduce((s, pk) => {
      const snap = Number.isFinite(Number(pk.preDraftAtPick))
        ? Math.max(0, Number(pk.preDraftAtPick))
        : playerPreDraftById.get(pk.playerId) || 0;
      return s + snap;
    }, 0);
    tierHeat[def.key] = preSum > 0 ? paidSum / preSum : 1;
    tierConfidence[def.key] = Math.min(
      1,
      tierPicks.length / TIER_CONFIDENCE_MIN_SAMPLES,
    );
  }

  // Resolve the effective tier multiplier for any PreDraft $.
  // At full confidence, this is tier_heat.  At zero confidence
  // (no tier picks yet), this is 1.0 (no tier adjustment beyond
  // global inflation).  The final per-player inflation applied to
  // fair price and max bid is ``inflation × effectiveTierMult``.
  function effectiveTierMultFor(preDraft) {
    const tier = tierForPreDraft(preDraft);
    const heat = tierHeat[tier];
    const conf = tierConfidence[tier];
    if (heat == null || conf <= 0) return 1;
    return conf * heat + (1 - conf) * 1;
  }

  // Per-team stats (name, initial, spent, remaining, slots, eff$).
  const teamStats = teams.map((t, idx) => {
    const spent = picksByTeam[idx].reduce(
      (s, p) => s + (Number(p.amount) || 0),
      0,
    );
    const initial = Number(t.initialBudget) || 0;
    const remaining = remainingByIdx[idx];
    const picksCount = picksByTeam[idx].length;
    return {
      idx,
      name: t.name || `Team ${idx + 1}`,
      initialBudget: initial,
      spent,
      remaining,
      picksCount,
      isMine: idx === myTeamIdx,
      initialSlots: initialSlotsByIdx[idx],
      slotsDrafted: slotsDraftedByIdx[idx],
      slotsRemaining: slotsRemainingByIdx[idx],
      effectiveBudget: effectiveBudgetByIdx[idx],
    };
  });

  // Pick lookup (playerId → pick) for the player-row enrichment.
  const pickByPlayer = new Map();
  for (const pk of picks) pickByPlayer.set(pk.playerId, pk);

  const enrichedPlayers = players.map((p) => {
    const pick = pickByPlayer.get(p.id) || null;
    const preDraft = Math.max(0, Number(p.preDraft) || 0);
    const tier = tierForPreDraft(preDraft);
    const tierMult = effectiveTierMultFor(preDraft);
    const combinedInflation = inflation * tierMult;

    // The sheet truncates (FLOOR) these derived dollar values.
    // We keep FLOOR for parity so numbers match the user's manual
    // sheet when both are in view.
    const inflatedFair = Math.floor(preDraft * combinedInflation);
    const theoreticalMaxBid = Math.floor(
      preDraft *
        (1 + aggression * (budgetAdvantage - 1)) *
        combinedInflation *
        phaseMultiplier,
    );
    // My winning bid = cap theoretical max at "what I need to beat"
    // (top competitor's slot-adjusted budget + 1).  If no one else
    // can bid (everyone bankrupt), winning bid collapses to 1.
    const competitorCeiling = Math.max(0, topCompetitorMax);
    const winByCompetitor = Math.max(1, competitorCeiling + 1);
    const myWinningBid = Math.max(
      0,
      Math.min(theoreticalMaxBid, winByCompetitor),
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
      tier,
      tierInflation: combinedInflation,
      pick,
      drafted,
      mine,
      inflatedFair: Math.max(0, inflatedFair),
      myMaxBid: Math.max(0, theoreticalMaxBid),
      theoreticalMaxBid: Math.max(0, theoreticalMaxBid),
      myWinningBid,
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
    myInitialSlots,
    mySlotsRemaining,
    slotPressure,
    phaseMultiplier,
    topCompetitorMax,
    otherTeamsRemaining,
    avgPerOtherTeam,
    budgetAdvantage,
    undraftedPreDraft,
    inflation,
    leagueSpentPct,
    tierHeat,
    tierConfidence,
    tierSampleCount,
    teamStats,
    enrichedPlayers,
  };
}

// ── State mutators (pure) ───────────────────────────────────────────────
/**
 * Record a draft pick.  Returns a new workspace; does not mutate.
 *
 * Snapshots ``preDraftAtPick`` at record time so historical tier
 * inflation remains accurate even if the user later edits the
 * player's PreDraft $ inline.  Without the snapshot, a retroactive
 * PreDraft edit would silently rewrite what the market "looked
 * like" when the pick landed — corrupting every downstream
 * paid-vs-expected diagnostic.
 *
 * If the player is already drafted, the pick is REPLACED (edit
 * flow) and the snapshot refreshes to the current PreDraft value.
 */
export function recordPick(workspace, { playerId, teamIdx, amount }) {
  if (!playerId || !Number.isInteger(teamIdx)) return workspace;
  const amt = Math.max(0, Number(amount) || 0);
  const picks = (workspace.picks || []).filter((p) => p.playerId !== playerId);
  const player = (workspace.players || []).find((p) => p.id === playerId);
  const preDraftAtPick = Math.max(0, Number(player?.preDraft) || 0);
  picks.push({
    playerId,
    teamIdx,
    amount: amt,
    preDraftAtPick,
    ts: Date.now(),
  });
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
 * The draft-capital endpoint returns one row per team in the league —
 * teams that traded every rookie pick away show up with
 * ``auctionDollars: 0`` rather than being omitted, so the dashboard
 * sees the full 12-team roster after the merge.
 *
 * Merge rules:
 *
 *   - Feed is authoritative.  If the feed has 12 teams, the post-
 *     merge board has exactly 12 teams (placeholder "Ed" / "Brent"
 *     / etc. defaults are replaced entirely).
 *   - Existing teams are matched against the feed by
 *     case-insensitive name.  A name match copies the feed's budget
 *     onto the existing row (preserving the user's preferred
 *     display name when ``preserveCustomNames`` is true).
 *   - Teams in the feed but not on the board are appended.
 *   - Teams ON the board that AREN'T in the feed get zeroed out —
 *     the feed is the source of truth for budget, so anyone it
 *     doesn't list has $0 to spend.  The user can still manually
 *     bump a budget back up if they're tracking a side deal.
 *
 * ``myTeamIdx`` is remapped by name so the merge can't accidentally
 * deselect the user's team.
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
  // Optional: raw ``picks`` array from the /api/draft-capital
  // response.  When provided, per-team rookie pick counts are set
  // as ``initialSlots`` on every matched/appended team so the
  // effective-budget math downstream is accurate.  Absent this
  // (e.g. teamTotals passed alone), teams keep their existing
  // ``initialSlots`` or fall back to the DEFAULT_INITIAL_SLOTS.
  const picksArray = Array.isArray(opts.picks) ? opts.picks : null;
  const slotsByKey = picksArray
    ? slotsByTeamFromPicks(picksArray)
    : new Map();

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

  // Empty feed — leave the workspace untouched rather than nuking
  // every placeholder team.  The fetch layer should already have
  // surfaced this as an error to the user; compute-side we just
  // act as a no-op so nothing gets lost.
  if (feedByKey.size === 0) {
    return { workspace: ws, matched: 0, added: 0, missing: [], zeroed: [] };
  }

  const myTeamIdx = Number.isInteger(ws.settings?.myTeamIdx)
    ? ws.settings.myTeamIdx
    : 0;
  const myTeamNameBefore = existing[myTeamIdx]?.name || "";

  // Default-placeholder detector: a row whose name + initialBudget
  // still match the DEFAULT_TEAMS seed is assumed to be a pre-load
  // placeholder and gets DROPPED rather than zeroed on merge.  That
  // way a fresh workspace doesn't end up with 11 orphan "Ed / Brent /
  // ..." rows at $0 cluttering the panel next to the real feed.  A
  // row that's been customized (either renamed or re-budgeted) is
  // treated as a user assertion and zeroed out rather than dropped.
  const defaultByKey = new Map(
    DEFAULT_TEAMS.map((t) => [
      String(t.name || "").toLowerCase(),
      t.initialBudget,
    ]),
  );

  // Build a team row with feed-aware ``initialSlots``.  When the
  // picks array is present, the slot count is authoritative.  When
  // it's not (no picks opts passed), we keep whatever ``initialSlots``
  // the existing team carried, falling back to the default.
  const buildTeam = (nameOut, budget, prior) => {
    const slotKey = String(nameOut || "").toLowerCase();
    const feedSlots = slotsByKey.get(slotKey);
    const priorSlots = Number.isFinite(Number(prior?.initialSlots))
      ? Math.max(0, Number(prior.initialSlots))
      : DEFAULT_INITIAL_SLOTS;
    const initialSlots = picksArray
      ? Number.isFinite(feedSlots)
        ? feedSlots
        : 0
      : priorSlots;
    return {
      name: nameOut,
      initialBudget: budget,
      initialSlots,
    };
  };

  const usedFeedKeys = new Set();
  const zeroed = [];
  const merged = [];
  for (const t of existing) {
    const key = String(t.name || "").toLowerCase();
    const hit = feedByKey.get(key);
    if (hit) {
      usedFeedKeys.add(key);
      const nameOut = preserveNames && t.name ? t.name : hit.name;
      merged.push(buildTeam(nameOut, hit.auctionDollars, t));
      continue;
    }
    // Drop unmatched default placeholders; zero out unmatched user-
    // customized rows.
    if (
      defaultByKey.has(key) &&
      defaultByKey.get(key) === Number(t.initialBudget)
    ) {
      continue;
    }
    zeroed.push(t.name);
    merged.push(buildTeam(t.name || "", 0, t));
  }

  // Append any feed teams not already on the board.  These are the
  // rows that just showed up in the capital feed — most likely after
  // a Sleeper re-sync.
  const missing = [];
  for (const [key, hit] of feedByKey.entries()) {
    if (usedFeedKeys.has(key)) continue;
    merged.push(buildTeam(hit.name, hit.auctionDollars, null));
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
    zeroed,
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
          initialSlots: Number.isFinite(Number(t?.initialSlots))
            ? Math.max(0, Number(t.initialSlots))
            : DEFAULT_INITIAL_SLOTS,
        }))
      : def.teams,
    players: (() => {
      const src =
        Array.isArray(parsed.players) && parsed.players.length > 0
          ? parsed.players
          : null;
      if (!src) return def.players;
      return src.map((p, i) => ({
        id: String(p?.id || playerSlug(p?.name) || `player-${i}`),
        rank: Number(p?.rank) || i + 1,
        name: String(p?.name || ""),
        preDraft: Math.max(0, Number(p?.preDraft) || 0),
      }));
    })(),
    picks: Array.isArray(parsed.picks)
      ? (() => {
          // Build a playerId → current preDraft fallback map so old
          // localStorage state (pre-Tier-1, no preDraftAtPick snapshot)
          // hydrates with SOMETHING reasonable rather than 0.  Preference
          // order: stored snapshot → current player preDraft → 0.
          const playerSrc =
            Array.isArray(parsed.players) && parsed.players.length > 0
              ? parsed.players
              : def.players;
          const preDraftById = new Map();
          for (const p of playerSrc) {
            const id = String(p?.id || playerSlug(p?.name) || "");
            if (!id) continue;
            preDraftById.set(
              id,
              Math.max(0, Number(p?.preDraft) || 0),
            );
          }
          return parsed.picks
            .map((p) => {
              const pid = String(p?.playerId || "");
              const storedSnap = Number.isFinite(Number(p?.preDraftAtPick))
                ? Math.max(0, Number(p.preDraftAtPick))
                : null;
              const fallback = preDraftById.get(pid) ?? 0;
              return {
                playerId: pid,
                teamIdx: Number.isInteger(p?.teamIdx) ? p.teamIdx : -1,
                amount: Math.max(0, Number(p?.amount) || 0),
                preDraftAtPick: storedSnap != null ? storedSnap : fallback,
                ts: Number(p?.ts) || Date.now(),
              };
            })
            .filter((p) => p.playerId && p.teamIdx >= 0);
        })()
      : [],
  };
}

/**
 * Bid-status classification for UI color coding.
 *
 * Uses ``myWinningBid`` (the competitor-ceiling-capped value) as the
 * PASS threshold.  Bidding above that is strictly wasteful because
 * no rival could match — any $1 above top competitor locks the
 * player.  Falls back to ``myMaxBid`` when winningBid isn't present
 * (old enriched-player shapes without Tier 1 fields).
 */
export function bidStatus(enrichedPlayer, currentBid) {
  if (!enrichedPlayer) return { level: "unknown", label: "" };
  if (enrichedPlayer.drafted) {
    if (enrichedPlayer.mine) return { level: "mine", label: "Mine" };
    return { level: "gone", label: "Gone" };
  }
  const bid = Math.max(0, Number(currentBid) || 0);
  if (bid <= 0) return { level: "idle", label: "Watching" };
  const ceiling = Number.isFinite(enrichedPlayer.myWinningBid)
    ? enrichedPlayer.myWinningBid
    : enrichedPlayer.myMaxBid;
  // Check ceiling FIRST: if the bid would win by more than $1 against
  // the true competitor ceiling, it's overpay territory regardless of
  // where the enforce threshold sits.  This matters when poor
  // competitors push ``myWinningBid`` well below ``enforceUpTo``
  // (rich-vs-bankrupt scenario) — pushing to enforce would
  // overpay by $ you don't need to spend.
  if (bid > ceiling) return { level: "pass", label: "Pass" };
  if (bid <= enrichedPlayer.enforceUpTo) return { level: "push", label: "Push up" };
  return { level: "target", label: "Sweet spot" };
}
