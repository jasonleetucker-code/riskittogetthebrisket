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

// ── Player tags (TARGET / AVOID / neutral) ──────────────────────────────
// Tags drive the recommendation engine.  A player defaults to neutral
// (no entry in ``workspace.tags``); the UI cycles TARGET → AVOID →
// neutral via clickable chips.  Stored in a separate map keyed by
// player id so it survives player renames + is trivially JSON-
// serializable.
export const TAG_TARGET = "target";
export const TAG_AVOID = "avoid";
export const TAG_VALUES = [TAG_TARGET, TAG_AVOID];

/**
 * Cycle helper: neutral → target → avoid → neutral.  Used by the
 * row-level "click to retag" button.
 */
export function cycleTag(current) {
  if (current === TAG_TARGET) return TAG_AVOID;
  if (current === TAG_AVOID) return null;
  return TAG_TARGET;
}

/**
 * Tier scarcity thresholds.  When ``remaining / initial < THRESHOLD``
 * the tier is "drying up" and recommendations urge extra aggression.
 */
export const TIER_SCARCITY_URGENT = 0.3;

/**
 * Slot-pressure gate for the "Spend up" recommendation — only trigger
 * past this fraction of the draft (i.e. late-draft mode).  At 0.6
 * that's after ~60% of my picks are drafted.
 */
export const SPEND_UP_PRESSURE_MIN = 0.6;
/**
 * $-per-slot floor for the "Spend up" recommendation — only trigger
 * when my remaining $ exceeds my remaining slots × this floor.
 * Prevents the surplus-alert from firing when my per-slot budget is
 * already normal-sized.
 */
export const SPEND_UP_MDV_FLOOR = 10;

/** Max slots on the user's explicit Target Board. */
export const TARGET_BOARD_MAX = 6;

/**
 * Per-nomination decay on a rival's tier-interest prior.  0.8 means
 * every nomination a team makes in tier T reduces their prior on
 * wanting ANOTHER player in that tier by 20% (multiplicative).  Tuned
 * to: 1 nom → 0.80, 2 noms → 0.64, 3 noms → 0.51, 4 noms → 0.41.
 * Floored at ``TIER_INTEREST_MIN`` so a team is never fully excluded.
 */
export const NOMINATION_DECAY = 0.8;
/**
 * Minimum tier-interest prior a team can have after nominations.
 * Keeps the Bayesian competitor ceiling from collapsing to zero for
 * a rival that has nominated many in a single tier — they MIGHT
 * still want another one, just less likely.
 */
export const TIER_INTEREST_MIN = 0.2;

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
    teams: DEFAULT_TEAMS.map((t) => ({ ...t, feedBudget: t.initialBudget })),
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
    // tags: { [playerId]: "target" | "avoid" }  — neutral = absent
    tags: {},
    // targetBoard: ordered array of playerId slots (up to TARGET_BOARD_MAX).
    //   The user's explicit "these are my 6" short-list.  Independent of
    //   the general target tag system so the user can keep a wide target
    //   list (20+) but still focus the board on 6 specific picks.  A
    //   player can be on both (common) or one or the other.
    targetBoard: [],
    // nominations: chronological log of who nominated whom.  Drives the
    // Bayesian per-team tier-interest priors that refine the competitor
    // ceiling on any given undrafted player.
    //   { playerId, nominatingTeamIdx, preDraftAtNomination, ts }
    nominations: [],
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

  // ── Bayesian tier-interest priors per team ─────────────────────────
  // Nominations are a negative signal: teams typically nominate
  // players they DON'T want (to drain rivals or price-anchor).  Decay
  // each team's "wants a player of tier T" prior by NOMINATION_DECAY
  // per nomination they've made in tier T, floored at
  // TIER_INTEREST_MIN so they're never fully excluded.  No
  // nominations logged → priors stay 1.0 and Bayesian ceiling
  // collapses to the naive topCompetitorMax.
  const nominations = Array.isArray(ws.nominations) ? ws.nominations : [];
  // tierInterest[teamIdx][tierKey] ∈ [TIER_INTEREST_MIN, 1]
  const tierInterestByTeam = teams.map(() => {
    const m = {};
    for (const def of TIER_DEFS) m[def.key] = 1;
    return m;
  });
  // Build a quick playerId → current preDraft map for the fallback
  // when a nomination predates the preDraftAtNomination snapshot
  // (old localStorage data).  Fresh nominations always snapshot, so
  // the fallback is rare.
  const nominationPreDraftFallback = new Map(
    players.map((p) => [p.id, Math.max(0, Number(p.preDraft) || 0)]),
  );
  for (const n of nominations) {
    const idx = n?.nominatingTeamIdx;
    if (!Number.isInteger(idx) || idx < 0 || idx >= teams.length) continue;
    const snap = Number.isFinite(Number(n?.preDraftAtNomination))
      ? Math.max(0, Number(n.preDraftAtNomination))
      : nominationPreDraftFallback.get(n?.playerId) || 0;
    const tierKey = tierForPreDraft(snap);
    const cur = tierInterestByTeam[idx][tierKey] ?? 1;
    tierInterestByTeam[idx][tierKey] = Math.max(
      TIER_INTEREST_MIN,
      cur * NOMINATION_DECAY,
    );
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

  // ── Per-tier scarcity stats ───────────────────────────────────────
  // Total players in each tier at draft START vs still on the board,
  // so the recommendation engine can flag "tier drying up" on the
  // remaining targets.  Tier is determined from ``player.preDraft``
  // (the current value) because scarcity is about what's LEFT, not
  // what WAS — retroactive PreDraft edits intentionally reshape this.
  const tierStats = {};
  for (const def of TIER_DEFS) {
    tierStats[def.key] = {
      key: def.key,
      label: def.label,
      total: 0,
      drafted: 0,
      remaining: 0,
      remainingRatio: 1,
      heat: tierHeat[def.key],
      confidence: tierConfidence[def.key],
      sampleCount: tierSampleCount[def.key],
    };
  }
  for (const p of players) {
    const key = tierForPreDraft(p.preDraft);
    if (!tierStats[key]) continue;
    tierStats[key].total += 1;
    if (pickedPlayerIds.has(p.id)) tierStats[key].drafted += 1;
  }
  for (const key of Object.keys(tierStats)) {
    const t = tierStats[key];
    t.remaining = Math.max(0, t.total - t.drafted);
    t.remainingRatio = t.total > 0 ? t.remaining / t.total : 0;
  }

  // Lookup for user tags.
  const tagMap = (ws.tags && typeof ws.tags === "object") ? ws.tags : {};

  // Per-team stats (name, initial, spent, remaining, slots, eff$).
  //
  // Tier 3 additions per team:
  //   mdv           — marginal dollar value (remaining / slots left).
  //                   Used in the budget-pressure heatmap.
  //   overpayIndex  — (Σ paid − Σ preDraftAtPick) / Σ preDraftAtPick
  //                   across all picks.  Null when no picks yet.
  //                   > 0: overpayer.  < 0: value hunter.  ~0: rational.
  //                   Surfaces in the Teams panel so "who's running hot
  //                   and will likely overpay again" is visible at a
  //                   glance.
  const teamStats = teams.map((t, idx) => {
    const teamPicks = picksByTeam[idx];
    const spent = teamPicks.reduce(
      (s, p) => s + (Number(p.amount) || 0),
      0,
    );
    const initial = Number(t.initialBudget) || 0;
    const remaining = remainingByIdx[idx];
    const picksCount = teamPicks.length;
    const preDraftSum = teamPicks.reduce((s, pk) => {
      const snap = Number.isFinite(Number(pk.preDraftAtPick))
        ? Math.max(0, Number(pk.preDraftAtPick))
        : playerPreDraftById.get(pk.playerId) || 0;
      return s + snap;
    }, 0);
    const overpayIndex =
      preDraftSum > 0 ? (spent - preDraftSum) / preDraftSum : null;
    const slotsLeft = slotsRemainingByIdx[idx];
    const mdv = slotsLeft > 0 ? remaining / slotsLeft : 0;
    // Count this team's logged nominations for the UI badge.
    const nominationsLogged = nominations.filter(
      (n) => n.nominatingTeamIdx === idx,
    ).length;
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
      slotsRemaining: slotsLeft,
      effectiveBudget: effectiveBudgetByIdx[idx],
      mdv,
      preDraftSum,
      overpayIndex,
      tierInterest: tierInterestByTeam[idx],
      nominationsLogged,
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
    // Bayesian competitor ceiling: reweight each rival's effective
    // budget by their tierInterest for THIS player's tier.  Less
    // interest (more nominations in this tier) → lower effective
    // ceiling for this player → lower bayesianWinningBid → I might
    // pay less than the naive topCompetitorMax suggests.  Only
    // diverges from topCompetitorMax once at least one nomination
    // has been logged; otherwise every tier-interest is 1.0 and the
    // numbers match.
    let bayesianTopCompetitor = 0;
    for (let i = 0; i < effectiveBudgetByIdx.length; i++) {
      if (i === myTeamIdx) continue;
      const interest = tierInterestByTeam[i]?.[tier] ?? 1;
      const weighted = effectiveBudgetByIdx[i] * interest;
      if (weighted > bayesianTopCompetitor) {
        bayesianTopCompetitor = weighted;
      }
    }
    const bayesianWinningBid = Math.max(
      0,
      Math.min(theoreticalMaxBid, Math.max(1, Math.floor(bayesianTopCompetitor) + 1)),
    );
    const enforceUpTo = Math.floor(inflatedFair * enforcePct);
    const drafted = !!pick;
    const mine = drafted && pick.teamIdx === myTeamIdx;
    const valueVsFair =
      drafted && Number.isFinite(Number(pick.amount))
        ? inflatedFair - Number(pick.amount)
        : null;
    const userTag = tagMap[p.id] || null;
    return {
      ...p,
      preDraft,
      tier,
      tierInflation: combinedInflation,
      pick,
      drafted,
      mine,
      userTag,
      inflatedFair: Math.max(0, inflatedFair),
      myMaxBid: Math.max(0, theoreticalMaxBid),
      theoreticalMaxBid: Math.max(0, theoreticalMaxBid),
      myWinningBid,
      bayesianTopCompetitor: Math.max(0, Math.floor(bayesianTopCompetitor)),
      bayesianWinningBid,
      enforceUpTo: Math.max(0, enforceUpTo),
      valueVsFair,
    };
  });

  // Total picks in the draft = sum of initial slots across all teams.
  // Used for the UI progress bar; typically 72 (12 × 6) for our
  // league but differs when teams trade picks between leagues.
  const totalInitialSlots = initialSlotsByIdx.reduce((s, n) => s + n, 0);
  const totalPicksMade = picks.length;
  const draftProgress =
    totalInitialSlots > 0 ? totalPicksMade / totalInitialSlots : 0;

  // ── Target Board rollup ─────────────────────────────────────────────
  // Aggregated view of the user's explicit short-list.  Each slot
  // carries a reference to the enriched player row so the UI can
  // render live "fair now" / "win now" numbers that update as other
  // picks land.  Totals handle three states per slot:
  //
  //   drafted to me:    +paid           (green; locked in)
  //   drafted to other: NOT in totals   (greyed out on the UI)
  //   undrafted:        +myWinningBid   (the realistic buy price)
  //
  // ``portfolioCost`` is what it would cost to get every remaining
  // target at current winning-bid prices, plus what I already spent
  // on targets.  ``portfolioBuffer`` = my remaining $ − cost of
  // remaining targets, i.e. what's left if I hit everything I still
  // want at today's prices.  Negative buffer means I can't afford
  // all six — the UI surfaces this as a red warning.
  const enrichedPlayerById = new Map(
    enrichedPlayers.map((p) => [p.id, p]),
  );
  const boardIds = Array.isArray(ws.targetBoard) ? ws.targetBoard : [];
  const targetBoardSlots = boardIds
    .map((id) => enrichedPlayerById.get(id))
    .filter(Boolean);
  const tbTotals = {
    preDraftSum: 0,
    fairSum: 0,
    winBidSum: 0,
    paidSum: 0,
    mineCount: 0,
    otherCount: 0,
    remainingCount: 0,
    remainingFair: 0,
    remainingWinBid: 0,
  };
  for (const p of targetBoardSlots) {
    tbTotals.preDraftSum += p.preDraft || 0;
    tbTotals.fairSum += p.inflatedFair || 0;
    tbTotals.winBidSum += p.myWinningBid || 0;
    if (p.drafted) {
      if (p.mine) {
        tbTotals.mineCount += 1;
        tbTotals.paidSum += p.pick?.amount || 0;
      } else {
        tbTotals.otherCount += 1;
      }
    } else {
      tbTotals.remainingCount += 1;
      tbTotals.remainingFair += p.inflatedFair || 0;
      tbTotals.remainingWinBid += p.myWinningBid || 0;
    }
  }
  // Buffer: what's left of my budget after buying every remaining
  // target at winning-bid prices, reserving $1 per additional slot
  // beyond the targets.  If I have 6 slots but only 4 targets, I
  // need $1 each for the other 2 so I can still fill my roster.
  const nonTargetSlotsLeft = Math.max(
    0,
    mySlotsRemaining - tbTotals.remainingCount,
  );
  const portfolioBuffer =
    myRemaining - tbTotals.remainingWinBid - nonTargetSlotsLeft;
  let portfolioStatus = "idle";
  let portfolioStatusLabel = "Add targets to your board";
  if (targetBoardSlots.length > 0) {
    if (portfolioBuffer < 0) {
      portfolioStatus = "short";
      portfolioStatusLabel = `Short $${Math.abs(Math.round(portfolioBuffer))} — trim a target or lower your ceiling`;
    } else if (portfolioBuffer < 10) {
      portfolioStatus = "tight";
      portfolioStatusLabel = `Tight — $${Math.round(portfolioBuffer)} of slack`;
    } else {
      portfolioStatus = "on_track";
      portfolioStatusLabel = `On track — $${Math.round(portfolioBuffer)} of headroom`;
    }
  }
  const targetBoardStats = {
    slots: targetBoardSlots,
    totals: tbTotals,
    portfolioBuffer,
    portfolioStatus,
    portfolioStatusLabel,
    nonTargetSlotsLeft,
  };

  // ── Nominations summary ────────────────────────────────────────────
  // Surface the raw nominations plus a per-tier count so the UI can
  // show "Joel has logged 3 S-tier noms" as a quick-read signal.
  const nominationsEnriched = nominations.map((n) => ({
    ...n,
    player: enrichedPlayerById.get(n.playerId) || null,
    nominatingTeamName:
      teams[n.nominatingTeamIdx]?.name || `Team ${n.nominatingTeamIdx + 1}`,
  }));
  const nominationsByTier = {};
  for (const def of TIER_DEFS) nominationsByTier[def.key] = 0;
  for (const n of nominations) {
    const snap = Number.isFinite(Number(n.preDraftAtNomination))
      ? n.preDraftAtNomination
      : nominationPreDraftFallback.get(n.playerId) || 0;
    const k = tierForPreDraft(snap);
    nominationsByTier[k] = (nominationsByTier[k] || 0) + 1;
  }

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
    tierStats,
    totalInitialSlots,
    totalPicksMade,
    draftProgress,
    teamStats,
    enrichedPlayers,
    targetBoardStats,
    nominationsCount: nominations.length,
    nominationsByTier,
    nominationsEnriched,
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

/**
 * Set (or clear) the TARGET / AVOID tag on a player.
 *
 * Pass ``null`` / ``undefined`` / anything unrecognized to clear the
 * tag back to neutral (i.e. remove from the tags map).  Returns a
 * new workspace; does not mutate.
 */
export function setPlayerTag(workspace, playerId, tag) {
  if (!playerId) return workspace;
  const next = { ...(workspace.tags || {}) };
  if (tag === TAG_TARGET || tag === TAG_AVOID) {
    next[playerId] = tag;
  } else {
    delete next[playerId];
  }
  return { ...workspace, tags: next };
}

// ── Target Board mutators ──────────────────────────────────────────────
/**
 * Append a player to the explicit Target Board if there's a free slot
 * and they're not already on it.  Cap at ``TARGET_BOARD_MAX``.  Also
 * auto-applies the ``target`` tag so the rec engine picks them up.
 */
export function addToTargetBoard(workspace, playerId) {
  if (!playerId) return workspace;
  const board = Array.isArray(workspace.targetBoard)
    ? workspace.targetBoard
    : [];
  if (board.includes(playerId)) return workspace;
  if (board.length >= TARGET_BOARD_MAX) return workspace;
  const next = setPlayerTag(workspace, playerId, TAG_TARGET);
  return { ...next, targetBoard: [...board, playerId] };
}

/**
 * Remove a player from the Target Board.  Does NOT clear their
 * target tag — the tag is a broader concept than board membership,
 * so a user who removes from the board while keeping the tag is
 * signalling "still interested, just not top-6 focus."
 */
export function removeFromTargetBoard(workspace, playerId) {
  const board = (workspace.targetBoard || []).filter(
    (id) => id !== playerId,
  );
  return { ...workspace, targetBoard: board };
}

/** Reset the Target Board to empty.  Tags are untouched. */
export function clearTargetBoard(workspace) {
  return { ...workspace, targetBoard: [] };
}

/**
 * Reorder the Target Board by moving one player one slot up or down.
 * Used for the row-reorder buttons on the Target Board UI.  No-op if
 * the player is missing, or already at the boundary.
 */
export function moveTargetInBoard(workspace, playerId, direction) {
  const board = [...(workspace.targetBoard || [])];
  const idx = board.indexOf(playerId);
  if (idx < 0) return workspace;
  const to = direction === "up" ? idx - 1 : idx + 1;
  if (to < 0 || to >= board.length) return workspace;
  const [moved] = board.splice(idx, 1);
  board.splice(to, 0, moved);
  return { ...workspace, targetBoard: board };
}

// ── Nomination mutators ────────────────────────────────────────────────
/**
 * Log a rival nomination.  Nominations are one per player (re-logging
 * replaces the prior entry so a miscue can be corrected in place).
 * ``preDraftAtNomination`` snapshots the PreDraft $ at log time, same
 * as ``preDraftAtPick`` on picks — retroactive edits can't corrupt
 * tier-interest decay.
 */
export function recordNomination(workspace, { playerId, nominatingTeamIdx }) {
  if (!playerId || !Number.isInteger(nominatingTeamIdx)) return workspace;
  const nominations = (workspace.nominations || []).filter(
    (n) => n.playerId !== playerId,
  );
  const player = (workspace.players || []).find((p) => p.id === playerId);
  const preDraftAtNomination = Math.max(0, Number(player?.preDraft) || 0);
  nominations.push({
    playerId,
    nominatingTeamIdx,
    preDraftAtNomination,
    ts: Date.now(),
  });
  return { ...workspace, nominations };
}

/** Remove a single logged nomination (undo a mis-click). */
export function removeNomination(workspace, playerId) {
  return {
    ...workspace,
    nominations: (workspace.nominations || []).filter(
      (n) => n.playerId !== playerId,
    ),
  };
}

/** Undo the most recent nomination log entry (by ts). */
export function undoLastNomination(workspace) {
  const noms = workspace.nominations || [];
  if (noms.length === 0) return workspace;
  const sorted = [...noms].sort((a, b) => (b.ts || 0) - (a.ts || 0));
  const toRemove = sorted[0];
  return {
    ...workspace,
    nominations: noms.filter((n) => n !== toRemove),
  };
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
  // ``mode === "sync"`` preserves user-edited budgets: a row is only
  // rewritten when its ``initialBudget`` still equals its last-seen
  // ``feedBudget`` (i.e. the user hasn't typed a custom value).
  // ``mode === "force"`` (default) is the "Load from Draft Capital"
  // semantics — overwrite everything.
  const mode = opts.mode === "sync" ? "sync" : "force";
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
  const buildTeam = (nameOut, feedBudget, prior) => {
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
    // In sync mode, preserve the user's typed initialBudget when it
    // diverges from the last-seen feed value.  In force mode (or when
    // no prior feedBudget exists), snap initialBudget to the new feed
    // value.  Either way, feedBudget always tracks the latest feed.
    let initialBudget = feedBudget;
    if (mode === "sync" && prior) {
      const priorFeed = Number.isFinite(Number(prior.feedBudget))
        ? Number(prior.feedBudget)
        : null;
      const priorInitial = Number.isFinite(Number(prior.initialBudget))
        ? Number(prior.initialBudget)
        : null;
      if (priorFeed != null && priorInitial != null && priorInitial !== priorFeed) {
        // User has edited the budget since the last feed pull —
        // preserve their value, but still advance the feedBudget
        // cursor so future edits re-match the user's intent.
        initialBudget = priorInitial;
      }
    }
    return {
      name: nameOut,
      initialBudget,
      initialSlots,
      feedBudget,
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

/**
 * Replace the rookie player pool with a new list (e.g. from the
 * live /api/data rookie rankings) while preserving the user's
 * tags, Target Board, and already-recorded picks wherever the
 * player id carries over.
 *
 * Input shape: ``newPlayers`` is ``[{ name, preDraft, pos? }, ...]``.
 * Each entry's id is generated via ``playerSlug(name)`` (same rule
 * used in ``createDefaultWorkspace``) so previous state that was
 * keyed by the same slug lines back up automatically.
 *
 *   - Players on the new list keep their old tag/board-membership
 *     if the slug matches anything from the old list.
 *   - Players previously drafted (picks) are preserved when their
 *     slug still exists in the new list.  Orphaned picks (the
 *     player dropped off the new list entirely) are DROPPED — the
 *     caller should preview this and confirm before committing.
 *   - Rank is 1..N in input order (caller decides sort).
 *
 * Returns ``{ workspace, kept, added, dropped, orphanedPicks }``
 * so the UI can report exactly what the sync did.
 */
export function replacePlayerPool(workspace, newPlayers) {
  const prev = workspace || createDefaultWorkspace();
  const prevPlayers = Array.isArray(prev.players) ? prev.players : [];
  const prevTags = prev.tags || {};
  const prevBoard = Array.isArray(prev.targetBoard) ? prev.targetBoard : [];
  const prevPicks = Array.isArray(prev.picks) ? prev.picks : [];
  const prevIds = new Set(prevPlayers.map((p) => p.id));

  const incoming = (Array.isArray(newPlayers) ? newPlayers : [])
    .filter((p) => p && p.name)
    .map((p, i) => ({
      id: playerSlug(p.name),
      rank: Number.isFinite(Number(p.rank)) ? Number(p.rank) : i + 1,
      name: String(p.name),
      preDraft: Math.max(0, Number(p.preDraft) || 0),
      ...(p.pos ? { pos: String(p.pos) } : {}),
    }))
    .filter((p) => p.id);

  const incomingIds = new Set(incoming.map((p) => p.id));

  // Preserve tags ONLY for players still on the board.
  const nextTags = {};
  for (const [id, tag] of Object.entries(prevTags)) {
    if (incomingIds.has(id) && (tag === TAG_TARGET || tag === TAG_AVOID)) {
      nextTags[id] = tag;
    }
  }

  // Preserve Target Board order, drop any slot whose player left.
  const nextBoard = prevBoard.filter((id) => incomingIds.has(id));

  // Preserve picks; drop any whose player is gone (they'll be
  // reported in ``orphanedPicks`` so the caller can warn / undo).
  const orphanedPicks = [];
  const nextPicks = [];
  for (const pk of prevPicks) {
    if (incomingIds.has(pk.playerId)) {
      nextPicks.push(pk);
    } else {
      orphanedPicks.push(pk);
    }
  }

  // Diagnostic counts.
  const kept = incoming.filter((p) => prevIds.has(p.id)).length;
  const added = incoming.length - kept;
  const dropped = prevPlayers.filter((p) => !incomingIds.has(p.id)).length;

  return {
    workspace: {
      ...prev,
      players: incoming,
      tags: nextTags,
      targetBoard: nextBoard,
      picks: nextPicks,
    },
    kept,
    added,
    dropped,
    orphanedPicks,
  };
}

/**
 * Rescale raw value numbers onto a $N total budget.  Used when
 * syncing from an external ranking source whose values aren't on
 * the $1200-total scale our dashboard uses.
 *
 *   scale        = targetTotal / Σ rawValues
 *   scaled[i]    = max(1, round(raw[i] × scale))
 *
 * Every scaled value is floored at $1 so the tail of the curve
 * doesn't round to 0 and turn into unbiddable filler.  Small
 * rounding drift against the exact targetTotal is fine — the
 * inflation math handles non-exact totals via ``totalBudget`` as
 * the inflation denominator rather than the column sum.
 */
export function rescaleValuesToBudget(rawValues, targetTotal) {
  const total = (Array.isArray(rawValues) ? rawValues : []).reduce(
    (s, v) => s + Math.max(0, Number(v) || 0),
    0,
  );
  if (total <= 0) return (rawValues || []).map(() => 1);
  const scale = Number(targetTotal) / total;
  return rawValues.map((v) => Math.max(1, Math.round(Math.max(0, Number(v) || 0) * scale)));
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
      ? parsed.teams.map((t, i) => {
          const initialBudget = Math.max(0, Number(t?.initialBudget) || 0);
          // Legacy workspaces (pre-feedBudget tracking) are treated as
          // in-sync so the next /api/draft-capital fetch freely updates
          // them.  Once the user edits a row post-hydration, the
          // diverging feedBudget will protect that edit on subsequent
          // auto-syncs.
          const feedBudget = Number.isFinite(Number(t?.feedBudget))
            ? Math.max(0, Number(t.feedBudget))
            : initialBudget;
          return {
            name: String(t?.name || `Team ${i + 1}`),
            initialBudget,
            initialSlots: Number.isFinite(Number(t?.initialSlots))
              ? Math.max(0, Number(t.initialSlots))
              : DEFAULT_INITIAL_SLOTS,
            feedBudget,
          };
        })
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
    tags: (() => {
      // Tags are optional; silently drop any value that isn't
      // exactly "target" or "avoid".  This keeps the map tight
      // even if localStorage gets hand-edited to something weird.
      const src = parsed.tags && typeof parsed.tags === "object" ? parsed.tags : {};
      const out = {};
      for (const [k, v] of Object.entries(src)) {
        if (v === TAG_TARGET || v === TAG_AVOID) out[String(k)] = v;
      }
      return out;
    })(),
    targetBoard: Array.isArray(parsed.targetBoard)
      ? parsed.targetBoard
          .filter((id) => typeof id === "string" && id.length > 0)
          .slice(0, TARGET_BOARD_MAX)
      : [],
    nominations: Array.isArray(parsed.nominations)
      ? parsed.nominations
          .map((n) => ({
            playerId: String(n?.playerId || ""),
            nominatingTeamIdx: Number.isInteger(n?.nominatingTeamIdx)
              ? n.nominatingTeamIdx
              : -1,
            preDraftAtNomination: Math.max(
              0,
              Number(n?.preDraftAtNomination) || 0,
            ),
            ts: Number(n?.ts) || Date.now(),
          }))
          .filter((n) => n.playerId && n.nominatingTeamIdx >= 0)
      : [],
  };
}

// ── Recommendation engine ──────────────────────────────────────────────
/**
 * Classify a single undrafted player's draft-time stance given the
 * current workspace state.  Returns null for drafted players or
 * missing input.  The classification is INDEPENDENT of any live bid
 * (use ``bidStatus`` for that).  It answers: "all else equal, what
 * should my posture be on this guy right now?"
 *
 * Levels (ordered by priority):
 *
 *   - ``avoid``   — user flagged AVOID
 *   - ``lock``    — target AND competitor ceiling collapses
 *                  (rivals can't afford past a modest bid)
 *   - ``steal``   — NEUTRAL AND competitor ceiling collapses
 *                  (opportunistic grab at fire-sale price)
 *   - ``spend``   — target AND late-draft surplus (slot pressure
 *                   high, remaining $ outpaces remaining slots)
 *   - ``push``    — target AND tier drying up
 *   - ``buy``     — target, normal market
 *   - ``neutral`` — nothing noteworthy
 *
 * Every level carries a short ``label`` + ``rationale`` so the UI
 * can render the label as a chip and the rationale as a tooltip.
 */
export function playerRecommendation(enrichedPlayer, stats) {
  if (!enrichedPlayer || enrichedPlayer.drafted || !stats) return null;
  const p = enrichedPlayer;
  const tag = p.userTag;

  // Explicit AVOID flag — user knows better than any signal.
  if (tag === TAG_AVOID) {
    return {
      level: "avoid",
      label: "Avoid",
      rationale: "You flagged this player as avoid.",
    };
  }

  // Competitor ceiling collapse: bid ``topCompetitorMax + 1`` wins.
  // Floor the threshold at max(1, preDraft × 0.3) so a borderline
  // "my rivals can afford $10 and the player's PreDraft is $30"
  // scenario doesn't register as collapse (rivals might push to $15,
  // still much below my ceiling).
  const collapseFloor = Math.max(1, Math.floor(p.preDraft * 0.3));
  if (stats.topCompetitorMax <= collapseFloor) {
    if (tag === TAG_TARGET) {
      return {
        level: "lock",
        label: "Lock now",
        rationale: `Rivals maxed at $${stats.topCompetitorMax}; bid $${
          stats.topCompetitorMax + 1
        } to lock.`,
      };
    }
    return {
      level: "steal",
      label: "Steal candidate",
      rationale: `Rivals maxed at $${stats.topCompetitorMax}; any bid above wins.`,
    };
  }

  // Late-draft surplus $ on a target → spend up.
  const mdv =
    stats.mySlotsRemaining > 0
      ? stats.myRemaining / stats.mySlotsRemaining
      : 0;
  if (
    tag === TAG_TARGET &&
    stats.slotPressure >= SPEND_UP_PRESSURE_MIN &&
    mdv > SPEND_UP_MDV_FLOOR
  ) {
    return {
      level: "spend",
      label: "Spend up",
      rationale: `Late draft (${Math.round(
        stats.slotPressure * 100,
      )}% pressure), ~$${Math.round(mdv)}/slot surplus — don't let $ go unused.`,
    };
  }

  // Tier scarcity on a target.
  if (tag === TAG_TARGET) {
    const tierInfo = stats.tierStats?.[p.tier];
    if (
      tierInfo &&
      tierInfo.remainingRatio < TIER_SCARCITY_URGENT &&
      tierInfo.remaining > 0
    ) {
      return {
        level: "push",
        label: "Push aggressively",
        rationale: `Only ${tierInfo.remaining} of ${tierInfo.total} ${p.tier}-tier players left.`,
      };
    }
    return {
      level: "buy",
      label: "Buy at fair",
      rationale: `Target; bid up to $${p.myWinningBid} to win.`,
    };
  }

  return {
    level: "neutral",
    label: "Neutral",
    rationale: null,
  };
}

/**
 * Rank undrafted players by expected value and return the top N.
 *
 * EV model (per player p):
 *
 *   surplus(p) = max(0, inflatedFair − myWinningBid)
 *   tagWeight(p) = 1.5 (target)  1.0 (neutral)  0 (avoid)
 *   ev(p) = surplus × tagWeight + tierScarcityBoost(p, stats)
 *
 * Where ``tierScarcityBoost`` adds a small bump when the player
 * sits in a drying-up tier, nudging those to the front.  Avoid-
 * tagged players are forced to 0 so they never surface as
 * recommendations.  Ties are broken by tier (S > A > B > C > D)
 * then by ``preDraft`` descending.
 *
 * Returns an array of ``{ player, ev, rec }`` objects, sorted
 * descending by ev, capped at ``limit`` entries (default 5).
 */
export function nextBestTargets(stats, { limit = 5 } = {}) {
  if (!stats || !Array.isArray(stats.enrichedPlayers)) return [];
  const tierOrder = { S: 5, A: 4, B: 3, C: 2, D: 1 };
  const candidates = [];
  for (const p of stats.enrichedPlayers) {
    if (p.drafted) continue;
    if (p.userTag === TAG_AVOID) continue;

    const surplus = Math.max(0, p.inflatedFair - p.myWinningBid);
    const tagWeight = p.userTag === TAG_TARGET ? 1.5 : 1.0;
    const tierInfo = stats.tierStats?.[p.tier];
    const scarcityBoost =
      tierInfo && tierInfo.remainingRatio < TIER_SCARCITY_URGENT
        ? Math.max(0, 10 * (TIER_SCARCITY_URGENT - tierInfo.remainingRatio))
        : 0;

    const ev = surplus * tagWeight + scarcityBoost;
    if (ev <= 0 && p.userTag !== TAG_TARGET) continue;

    candidates.push({
      player: p,
      ev,
      rec: playerRecommendation(p, stats),
    });
  }

  candidates.sort((a, b) => {
    if (b.ev !== a.ev) return b.ev - a.ev;
    const at = tierOrder[a.player.tier] || 0;
    const bt = tierOrder[b.player.tier] || 0;
    if (bt !== at) return bt - at;
    return b.player.preDraft - a.player.preDraft;
  });

  return candidates.slice(0, limit);
}

// ── Nomination optimizer ───────────────────────────────────────────────
/**
 * Rank undrafted players by "good nomination" score.  A good
 * nomination is a player the user DOESN'T want, whose expected
 * clearing price is high enough to drain rival budgets, without
 * creating significant risk of the user being stuck with them.
 *
 * Score model:
 *
 *   expected_price(p) = p.inflatedFair
 *   affordable(p)     = min(expected_price, topCompetitorMax)
 *     — rivals can't pay more than their effective ceiling; a
 *       player with fair $50 facing $20-max rivals drains at most $20.
 *   tag_weight(p):
 *     avoid    → 1.8    // I actively want them off the board
 *     neutral  → 1.0
 *     target   → 0      // never nominate my own targets
 *   risk_of_winning(p) = if my_winning_bid exceeds expected_price by
 *     a wide margin, I might accidentally win them.  For neutrals we
 *     dampen the score by this risk factor; avoid-tagged players are
 *     assumed acceptable to win (user chose the tag).
 *
 *   score(p) = affordable × tag_weight × (1 − risk_factor)
 *
 * Excludes drafted players and my targets.  Returns top ``limit``
 * candidates sorted descending by score.
 */
export function nominationCandidates(stats, { limit = 10 } = {}) {
  if (!stats || !Array.isArray(stats.enrichedPlayers)) return [];

  // Re-purposed 2026-04-26: instead of a drain-by-affordability
  // ranker, this now surfaces rookies KTC values MUCH HIGHER than
  // our board.  Rationale: if KTC says a rookie is worth $50 and
  // our board says $30, leaguemates who reference KTC will bid up
  // to $50 — draining their budget on a player our model considers
  // overpriced.  Largest gap = biggest tax on rivals.
  //
  // Selection:
  //   1. Not yet drafted
  //   2. Not target-tagged (don't undermine your own pursuit)
  //   3. Has both a board ``preDraft`` AND a KTC dollar value
  //   4. ``ktcDollar > preDraft`` (KTC overrates relative to us)
  //
  // Sort: ``ktcDollar - preDraft`` descending.  Cap at ``limit``
  // (default 10).
  const out = [];
  for (const p of stats.enrichedPlayers) {
    if (p.drafted) continue;
    if (p.userTag === TAG_TARGET) continue;
    const ourDollar = Math.max(0, p.preDraft || 0);
    const ktcDollar = Math.max(0, Number(p.ktcDollar) || 0);
    if (ourDollar <= 0 || ktcDollar <= 0) continue;
    const gap = ktcDollar - ourDollar;
    if (gap < 1) continue;  // KTC must overrate by at least $1
    const drain = Math.min(ktcDollar, Math.max(0, stats.topCompetitorMax || 0));
    out.push({
      player: p,
      score: gap,
      drain,
      gap,
      ourDollar,
      ktcDollar,
      expectedPrice: ktcDollar,
      rationale:
        `KTC values $${Math.round(ktcDollar)} vs our $${Math.round(ourDollar)} ` +
        `· $${Math.round(gap)} gap — leaguemates following KTC will ` +
        `bid past your board's fair price`,
    });
  }

  out.sort((a, b) => b.gap - a.gap);
  return out.slice(0, limit);
}

// ── Inflation history series ───────────────────────────────────────────
/**
 * Re-simulate the draft pick-by-pick to produce a time series of
 * ``{picksCount, timestamp, inflation, topCompetitorMax, leagueSpentPct,
 * budgetAdvantage}`` snapshots — one per pick plus the draft-start
 * zeroed baseline.
 *
 * Used for the inflation sparkline and any other "how did we get
 * here?" retrospective UI.  Runs ``computeDraftStats`` N+1 times
 * (N = number of picks) so O(N²) relative to the pick list, but N
 * caps at 72 in our league and each computeDraftStats call is
 * cheap, so total cost is negligible even mid-draft.
 *
 * Picks are sorted by ``ts`` ascending so the series reflects
 * actual draft order regardless of any edit-then-re-record churn.
 */
export function computeHistorySeries(workspace) {
  const ws = workspace || createDefaultWorkspace();
  const picks = Array.isArray(ws.picks) ? [...ws.picks] : [];
  picks.sort((a, b) => (a.ts || 0) - (b.ts || 0));

  const series = [];
  // Baseline (no picks).
  const base = computeDraftStats({ ...ws, picks: [] });
  series.push({
    picksCount: 0,
    timestamp: null,
    inflation: base.inflation,
    topCompetitorMax: base.topCompetitorMax,
    leagueSpentPct: base.leagueSpentPct,
    budgetAdvantage: base.budgetAdvantage,
  });

  for (let i = 0; i < picks.length; i++) {
    const cumulative = picks.slice(0, i + 1);
    const s = computeDraftStats({ ...ws, picks: cumulative });
    series.push({
      picksCount: i + 1,
      timestamp: picks[i].ts || null,
      inflation: s.inflation,
      topCompetitorMax: s.topCompetitorMax,
      leagueSpentPct: s.leagueSpentPct,
      budgetAdvantage: s.budgetAdvantage,
    });
  }

  return series;
}

// ── Post-draft review ──────────────────────────────────────────────────
/**
 * Build the "how did the draft go" review bundle from a completed
 * (or in-progress) workspace.
 *
 * Uses CURRENT inflated fair as the fair-value yardstick, not the
 * fair price at the moment of the pick.  Rationale: inflated fair is
 * the end-state market consensus — the best retrospective number for
 * "was my roster a good ROI?".  ``valueVsFair`` on each row still
 * carries this delta (positive = steal, negative = overpay).
 *
 * Returns:
 *   myPicks      — enriched rows for every pick MY team made
 *   bestSteal    — my pick with largest positive valueVsFair (or null)
 *   worstOverpay — my pick with largest negative valueVsFair (or null)
 *   portfolio    — { paid, fairValue, ratio } for MY picks
 *   teamRankings — every team { idx, name, paid, fair, ratio }
 *                  sorted descending by ratio (best drafter first)
 *   csvRows      — array-of-arrays ready for CSV export (mine + all)
 *
 * Falls back to sane empties when no picks are recorded yet so the
 * UI can render skeleton state without special-casing.
 */
export function computeDraftReview(workspace, stats) {
  const ws = workspace || createDefaultWorkspace();
  const s = stats || computeDraftStats(ws);
  const picks = Array.isArray(ws.picks) ? ws.picks : [];
  const myIdx = Number.isInteger(ws.settings?.myTeamIdx)
    ? ws.settings.myTeamIdx
    : 0;
  const playerById = new Map(s.enrichedPlayers.map((p) => [p.id, p]));
  const teamIdxName = (i) =>
    ws.teams?.[i]?.name || `Team ${i + 1}`;

  // Build rows per pick.
  const rows = picks.map((pk) => {
    const player = playerById.get(pk.playerId);
    return {
      playerId: pk.playerId,
      playerName: player?.name || pk.playerId,
      tier: player?.tier || "?",
      teamIdx: pk.teamIdx,
      teamName: teamIdxName(pk.teamIdx),
      paid: Number(pk.amount) || 0,
      fair: player?.inflatedFair ?? 0,
      preDraft: player?.preDraft ?? pk.preDraftAtPick ?? 0,
      valueVsFair: player
        ? (player.inflatedFair || 0) - (Number(pk.amount) || 0)
        : 0,
      pos: player?.pos || null,
      mine: pk.teamIdx === myIdx,
      ts: pk.ts,
    };
  });

  const myRows = rows.filter((r) => r.mine).sort((a, b) => b.valueVsFair - a.valueVsFair);
  const bestSteal = myRows.length > 0 ? myRows[0] : null;
  const worstOverpay =
    myRows.length > 0 ? myRows[myRows.length - 1] : null;

  const portfolioPaid = myRows.reduce((sum, r) => sum + r.paid, 0);
  const portfolioFair = myRows.reduce((sum, r) => sum + r.fair, 0);
  const portfolioRatio = portfolioPaid > 0 ? portfolioFair / portfolioPaid : 0;

  // Per-team aggregation.
  const byTeam = new Map();
  for (const r of rows) {
    const key = r.teamIdx;
    const bucket = byTeam.get(key) || {
      idx: key,
      name: r.teamName,
      paid: 0,
      fair: 0,
      count: 0,
    };
    bucket.paid += r.paid;
    bucket.fair += r.fair;
    bucket.count += 1;
    byTeam.set(key, bucket);
  }
  const teamRankings = [...byTeam.values()]
    .map((t) => ({
      ...t,
      ratio: t.paid > 0 ? t.fair / t.paid : 0,
      delta: t.fair - t.paid,
      isMine: t.idx === myIdx,
    }))
    .sort((a, b) => b.ratio - a.ratio);

  // CSV shape: header row + one row per pick, chronological.
  const csvHeader = [
    "Team",
    "Player",
    "Tier",
    "Pos",
    "Paid",
    "PreDraft",
    "Fair",
    "Delta (fair - paid)",
    "Mine",
  ];
  const csvBody = [...rows]
    .sort((a, b) => (a.ts || 0) - (b.ts || 0))
    .map((r) => [
      r.teamName,
      r.playerName,
      r.tier,
      r.pos || "",
      r.paid,
      r.preDraft,
      r.fair,
      r.valueVsFair,
      r.mine ? "yes" : "",
    ]);

  return {
    rows,
    myPicks: myRows.sort((a, b) => (a.ts || 0) - (b.ts || 0)),
    bestSteal,
    worstOverpay,
    portfolio: {
      paid: portfolioPaid,
      fairValue: portfolioFair,
      ratio: portfolioRatio,
      delta: portfolioFair - portfolioPaid,
    },
    teamRankings,
    csvHeader,
    csvBody,
  };
}

/**
 * Serialize a draft review into a CSV string ready for
 * ``Blob`` download.  Quote only cells that contain commas or
 * quotes — everything else stays bare for readability when
 * opened in a spreadsheet app.
 */
export function draftReviewToCsv(review) {
  if (!review) return "";
  const esc = (v) => {
    const s = String(v ?? "");
    if (/[",\n]/.test(s)) return `"${s.replace(/"/g, '""')}"`;
    return s;
  };
  const lines = [review.csvHeader.join(",")];
  for (const row of review.csvBody) {
    lines.push(row.map(esc).join(","));
  }
  return lines.join("\n");
}

// ── Roster-gap awareness ───────────────────────────────────────────────
/**
 * Default positional thresholds for "need".  When the user's
 * current Sleeper roster has FEWER of a position than the
 * threshold, that position is flagged as a need.  Values chosen
 * to fit a 2-QB/2-RB/3-WR/1-TE + flex IDP starter shape common
 * in SF leagues — adjust via options when a league's shape
 * differs significantly.
 */
export const DEFAULT_POSITION_MINS = {
  QB: 3,
  RB: 4,
  WR: 5,
  TE: 2,
  DL: 3,
  LB: 3,
  DB: 3,
};

/**
 * Count how many players on my current Sleeper roster fall into
 * each position bucket, and diff that against ``positionMins`` to
 * flag positions where I'm short.
 *
 * ``sleeperTeamPlayers`` — array of player names from the Sleeper
 * roster feed.  ``allPlayersArray`` — the playersArray from
 * /api/data (full rankings, used to map name → position).
 *
 * Returns:
 *   counts         { QB: 3, RB: 4, ... }  — how many I have
 *   needPositions  ["TE", "DB"]           — positions below min
 *   shortages      { TE: 1, DB: 2 }       — how many short per pos
 *
 * Unmatched names (free-agent pickups, preseason adds, etc) are
 * simply skipped — they don't contribute to counts either way.
 */
export function computeRosterBreakdown(
  sleeperTeamPlayers,
  allPlayersArray,
  positionMins = DEFAULT_POSITION_MINS,
) {
  const counts = {};
  for (const key of Object.keys(positionMins)) counts[key] = 0;

  const playerNames = Array.isArray(sleeperTeamPlayers)
    ? sleeperTeamPlayers
    : [];
  const byName = new Map();
  if (Array.isArray(allPlayersArray)) {
    for (const p of allPlayersArray) {
      const name = p?.displayName || p?.canonicalName || p?.name;
      if (name) byName.set(String(name), p);
    }
  }

  for (const name of playerNames) {
    const row = byName.get(String(name));
    if (!row) continue;
    const pos = String(row.position || row.pos || "").toUpperCase();
    if (counts[pos] != null) counts[pos] += 1;
  }

  const shortages = {};
  const needPositions = [];
  for (const [key, min] of Object.entries(positionMins)) {
    const have = counts[key] || 0;
    const short = Math.max(0, min - have);
    if (short > 0) {
      shortages[key] = short;
      needPositions.push(key);
    }
  }
  // Sort need positions by biggest shortage first for UI priority.
  needPositions.sort((a, b) => (shortages[b] || 0) - (shortages[a] || 0));

  return { counts, needPositions, shortages, positionMins };
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
