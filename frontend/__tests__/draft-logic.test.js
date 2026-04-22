/**
 * Tests for lib/draft-logic.js — pure inflation math for the draft
 * dashboard.  Spot-checks every derived value against known-good
 * numbers from Jason's Inflation Google Sheet so a formula tweak
 * here gets caught before shipping.
 */
import { describe, expect, it } from "vitest";
import {
  DEFAULT_AGGRESSION,
  DEFAULT_ENFORCE_PCT,
  DEFAULT_TEAMS,
  DEFAULT_ROOKIES,
  DRAFT_STORAGE_KEY,
  addPlayer,
  bidStatus,
  computeDraftStats,
  createDefaultWorkspace,
  hydrateWorkspace,
  playerSlug,
  recordPick,
  removePick,
  removePlayer,
  undoLastPick,
  updatePlayerPreDraft,
  updateSettings,
  updateTeam,
} from "@/lib/draft-logic";

// ── Constants / seed data ────────────────────────────────────────────

describe("seed data", () => {
  it("72 rookies totaling $1211 of PreDraft value (CSV verbatim)", () => {
    // The sheet's raw PreDraft column sums to $1211 — slightly more
    // than the $1200 total budget because the column is tuned for
    // *relative* player worth, not absolute budget allocation.  The
    // inflation formula handles this by using ``totalBudget`` as the
    // baseline rather than the column sum.
    expect(DEFAULT_ROOKIES.length).toBe(72);
    const total = DEFAULT_ROOKIES.reduce((s, r) => s + r.preDraft, 0);
    expect(total).toBe(1211);
  });

  it("ranks are 1..72 contiguous", () => {
    const ranks = DEFAULT_ROOKIES.map((r) => r.rank);
    expect(ranks).toEqual(Array.from({ length: 72 }, (_, i) => i + 1));
  });

  it("defaults include 12 teams with Russini Panini at idx 0", () => {
    expect(DEFAULT_TEAMS.length).toBe(12);
    expect(DEFAULT_TEAMS[0].name).toBe("Russini Panini");
    expect(DEFAULT_TEAMS[0].initialBudget).toBe(417);
  });

  it("storage key is stable", () => {
    expect(DRAFT_STORAGE_KEY).toBe("next_draft_board_v1");
  });
});

// ── playerSlug ───────────────────────────────────────────────────────

describe("playerSlug", () => {
  it("lowercases, dashes, and strips punctuation", () => {
    expect(playerSlug("Ja'Marr Chase")).toBe("ja-marr-chase");
    expect(playerSlug("A.J. Haulcy")).toBe("a-j-haulcy");
    expect(playerSlug("   ")).toBe("");
    expect(playerSlug("Emmanuel McNeil-Warren")).toBe(
      "emmanuel-mcneil-warren",
    );
  });
});

// ── createDefaultWorkspace ───────────────────────────────────────────

describe("createDefaultWorkspace", () => {
  it("matches the sheet's opening state", () => {
    const ws = createDefaultWorkspace();
    expect(ws.version).toBe(1);
    expect(ws.settings.myTeamIdx).toBe(0);
    expect(ws.settings.aggression).toBe(DEFAULT_AGGRESSION);
    expect(ws.settings.enforcePct).toBe(DEFAULT_ENFORCE_PCT);
    expect(ws.teams.length).toBe(12);
    expect(ws.players.length).toBe(72);
    expect(ws.picks).toEqual([]);
  });

  it("every player has a slug id", () => {
    const ws = createDefaultWorkspace();
    for (const p of ws.players) {
      expect(p.id).toMatch(/^[a-z0-9-]+$/);
      expect(p.id.length).toBeGreaterThan(0);
    }
  });
});

// ── computeDraftStats: opening state ────────────────────────────────
// Anchor numbers pulled directly from the sheet at draft-start:
//   Total Auction $        1200
//   My Starting $          417
//   Other Teams Remaining  784   (rounded up from 783 in the sheet)
//   Avg $ per Other Team   71
//   Budget Advantage       5.85
//   Inflation Factor       1.00

describe("computeDraftStats — opening state (matches Inflation sheet)", () => {
  const ws = createDefaultWorkspace();
  const stats = computeDraftStats(ws);

  it("total budget is 1200", () => {
    expect(stats.totalBudget).toBe(1200);
  });

  it("my starting / my remaining is 417", () => {
    expect(stats.myStarting).toBe(417);
    expect(stats.myRemaining).toBe(417);
  });

  it("other teams hold 783 (1200 - 417)", () => {
    expect(stats.otherTeamsRemaining).toBe(783);
  });

  it("avg per other team is ~71.2", () => {
    expect(stats.avgPerOtherTeam).toBeCloseTo(71.18, 1);
  });

  it("budget advantage is ~5.86", () => {
    // sheet rounds to 5.85; we preserve one more digit.
    expect(stats.budgetAdvantage).toBeCloseTo(5.86, 1);
  });

  it("inflation is exactly 1.00 when nothing is drafted", () => {
    expect(stats.inflation).toBeCloseTo(1.0, 5);
  });

  it("undrafted pre-draft pool reflects the column sum (1211)", () => {
    // The UI shows this in the "Board $ left" card; it's the literal
    // sum of still-on-board preDraft values, not the inflation
    // baseline.
    expect(stats.undraftedPreDraft).toBe(1211);
  });

  it("Jeremiyah Love opens at Fair 135 / Enforce 108 / Max 193", () => {
    // Sheet row 2: PreDraft 135, Fair 135, Enforce 108, Max 193.
    const love = stats.enrichedPlayers.find(
      (p) => p.name === "Jeremiyah Love",
    );
    expect(love.preDraft).toBe(135);
    expect(love.inflatedFair).toBe(135);
    expect(love.enforceUpTo).toBe(108);
    expect(love.myMaxBid).toBe(193);
  });

  it("Fernando Mendoza opens at Fair 102 / Enforce 81 / Max 146", () => {
    // Sheet row 3 (Enforce 81 is the FLOOR of 102 × 0.8 = 81.6).
    const mendoza = stats.enrichedPlayers.find(
      (p) => p.name === "Fernando Mendoza",
    );
    expect(mendoza.inflatedFair).toBe(102);
    expect(mendoza.enforceUpTo).toBe(81);
    expect(mendoza.myMaxBid).toBe(146);
  });
});

// ── computeDraftStats: mid-draft inflation behaviour ────────────────

describe("computeDraftStats — inflation response to picks", () => {
  // Sheet formula: inflation = remainingLeague / (totalBudget − soldPreDraft).
  // totalBudget = 1200 throughout this block.

  it("overpays push inflation < 1.0", () => {
    const ws = createDefaultWorkspace();
    // Someone else pays $200 for a $135 player — $65 over fair.
    const love = ws.players.find((p) => p.name === "Jeremiyah Love");
    const withPick = recordPick(ws, {
      playerId: love.id,
      teamIdx: 5,
      amount: 200,
    });
    const stats = computeDraftStats(withPick);
    expect(stats.inflation).toBeLessThan(1.0);
    // remainingLeague = 1200 − 200 = 1000
    // expectedPool    = 1200 − 135 = 1065
    // inflation       = 1000 / 1065
    expect(stats.inflation).toBeCloseTo(1000 / 1065, 4);
  });

  it("bargains push inflation > 1.0", () => {
    const ws = createDefaultWorkspace();
    const mendoza = ws.players.find((p) => p.name === "Fernando Mendoza");
    const withPick = recordPick(ws, {
      playerId: mendoza.id,
      teamIdx: 4,
      amount: 50, // $52 under fair
    });
    const stats = computeDraftStats(withPick);
    expect(stats.inflation).toBeGreaterThan(1.0);
    // 1150 / (1200 − 102) = 1150 / 1098
    expect(stats.inflation).toBeCloseTo(1150 / 1098, 4);
  });

  it("pay exactly fair keeps inflation at 1.0", () => {
    const ws = createDefaultWorkspace();
    const tate = ws.players.find((p) => p.name === "Carnell Tate");
    const withPick = recordPick(ws, {
      playerId: tate.id,
      teamIdx: 3,
      amount: 83, // fair == preDraft at opening
    });
    const stats = computeDraftStats(withPick);
    // (1200 − 83) / (1200 − 83) = 1117 / 1117 = 1.0
    expect(stats.inflation).toBeCloseTo(1.0, 5);
  });

  it("my spent / remaining tracks only my picks", () => {
    const ws = createDefaultWorkspace();
    const lemon = ws.players.find((p) => p.name === "Makai Lemon");
    const love = ws.players.find((p) => p.name === "Jeremiyah Love");
    let next = recordPick(ws, { playerId: lemon.id, teamIdx: 0, amount: 90 });
    next = recordPick(next, { playerId: love.id, teamIdx: 4, amount: 140 });
    const stats = computeDraftStats(next);
    expect(stats.mySpent).toBe(90);
    expect(stats.myRemaining).toBe(417 - 90);
    expect(stats.totalSpent).toBe(230);
  });

  it("my overpays shrink MyMaxBid on remaining players", () => {
    // When *I* overspend, my remaining budget drops faster than my
    // opponents', so my budget-advantage factor collapses → MaxBid
    // drops for everyone else on the board.  (When someone ELSE
    // overpays, my advantage actually GROWS — the remaining money
    // pool shifts toward me.)
    const ws = createDefaultWorkspace();
    const love = ws.players.find((p) => p.name === "Jeremiyah Love");
    const before = computeDraftStats(ws).enrichedPlayers.find(
      (p) => p.name === "Makai Lemon",
    );
    const after = computeDraftStats(
      recordPick(ws, { playerId: love.id, teamIdx: 0, amount: 300 }),
    ).enrichedPlayers.find((p) => p.name === "Makai Lemon");
    expect(after.myMaxBid).toBeLessThan(before.myMaxBid);
  });

  it("other teams' overpays GROW MyMaxBid (my advantage increases)", () => {
    const ws = createDefaultWorkspace();
    const love = ws.players.find((p) => p.name === "Jeremiyah Love");
    const before = computeDraftStats(ws).enrichedPlayers.find(
      (p) => p.name === "Makai Lemon",
    );
    const after = computeDraftStats(
      recordPick(ws, { playerId: love.id, teamIdx: 5, amount: 300 }),
    ).enrichedPlayers.find((p) => p.name === "Makai Lemon");
    // The budget-advantage jump outruns the inflation drop, so MaxBid
    // should be at least as large (typically strictly larger).
    expect(after.myMaxBid).toBeGreaterThanOrEqual(before.myMaxBid);
  });

  it("drafted rows carry valueVsFair = fair - price", () => {
    const ws = createDefaultWorkspace();
    const love = ws.players.find((p) => p.name === "Jeremiyah Love");
    const withPick = recordPick(ws, {
      playerId: love.id,
      teamIdx: 0,
      amount: 120, // I got a $15 bargain at inflation 1.0 post-clamp
    });
    const stats = computeDraftStats(withPick);
    const lovePost = stats.enrichedPlayers.find(
      (p) => p.name === "Jeremiyah Love",
    );
    expect(lovePost.drafted).toBe(true);
    expect(lovePost.mine).toBe(true);
    expect(lovePost.valueVsFair).toBeGreaterThan(0);
  });
});

// ── State mutators ──────────────────────────────────────────────────

describe("state mutators", () => {
  it("recordPick replaces a prior pick for the same player (edit flow)", () => {
    const ws = createDefaultWorkspace();
    const love = ws.players[0];
    const once = recordPick(ws, { playerId: love.id, teamIdx: 0, amount: 120 });
    const twice = recordPick(once, { playerId: love.id, teamIdx: 3, amount: 150 });
    expect(twice.picks.length).toBe(1);
    expect(twice.picks[0].teamIdx).toBe(3);
    expect(twice.picks[0].amount).toBe(150);
  });

  it("undoLastPick removes the newest by timestamp", async () => {
    const ws = createDefaultWorkspace();
    let next = recordPick(ws, {
      playerId: ws.players[0].id,
      teamIdx: 0,
      amount: 100,
    });
    // Tiny wait so the second pick gets a strictly greater timestamp.
    await new Promise((r) => setTimeout(r, 2));
    next = recordPick(next, {
      playerId: ws.players[1].id,
      teamIdx: 1,
      amount: 80,
    });
    expect(next.picks.length).toBe(2);
    const afterUndo = undoLastPick(next);
    expect(afterUndo.picks.length).toBe(1);
    expect(afterUndo.picks[0].playerId).toBe(ws.players[0].id);
  });

  it("undoLastPick on empty picks is a no-op", () => {
    const ws = createDefaultWorkspace();
    expect(undoLastPick(ws).picks).toEqual([]);
  });

  it("removePick clears a single draft", () => {
    const ws = createDefaultWorkspace();
    const next = recordPick(ws, {
      playerId: ws.players[0].id,
      teamIdx: 0,
      amount: 100,
    });
    const cleared = removePick(next, ws.players[0].id);
    expect(cleared.picks).toEqual([]);
  });

  it("updatePlayerPreDraft changes only the target player", () => {
    const ws = createDefaultWorkspace();
    const target = ws.players[0];
    const next = updatePlayerPreDraft(ws, target.id, 200);
    expect(next.players[0].preDraft).toBe(200);
    expect(next.players[1].preDraft).toBe(ws.players[1].preDraft);
  });

  it("updateTeam patches name and budget", () => {
    const ws = createDefaultWorkspace();
    const next = updateTeam(ws, 0, {
      name: "Brisket Bidders",
      initialBudget: 500,
    });
    expect(next.teams[0].name).toBe("Brisket Bidders");
    expect(next.teams[0].initialBudget).toBe(500);
  });

  it("updateSettings patches aggression without losing enforcePct", () => {
    const ws = createDefaultWorkspace();
    const next = updateSettings(ws, { aggression: 0.2 });
    expect(next.settings.aggression).toBe(0.2);
    expect(next.settings.enforcePct).toBe(DEFAULT_ENFORCE_PCT);
  });

  it("addPlayer appends with next-available rank", () => {
    const ws = createDefaultWorkspace();
    const next = addPlayer(ws, { name: "Unlisted Prospect", preDraft: 4 });
    expect(next.players.length).toBe(73);
    expect(next.players[72].name).toBe("Unlisted Prospect");
    expect(next.players[72].rank).toBe(73);
  });

  it("addPlayer refuses duplicates", () => {
    const ws = createDefaultWorkspace();
    const same = addPlayer(ws, { name: "Jeremiyah Love", preDraft: 999 });
    expect(same.players.length).toBe(72);
  });

  it("removePlayer drops the row AND any pick that references it", () => {
    const ws = createDefaultWorkspace();
    const target = ws.players[0];
    let next = recordPick(ws, {
      playerId: target.id,
      teamIdx: 0,
      amount: 100,
    });
    expect(next.picks.length).toBe(1);
    next = removePlayer(next, target.id);
    expect(next.players.find((p) => p.id === target.id)).toBeUndefined();
    expect(next.picks).toEqual([]);
  });
});

// ── bidStatus ───────────────────────────────────────────────────────

describe("bidStatus", () => {
  const ws = createDefaultWorkspace();
  const stats = computeDraftStats(ws);
  const love = stats.enrichedPlayers.find(
    (p) => p.name === "Jeremiyah Love",
  );

  it("watching when no bid yet", () => {
    expect(bidStatus(love, 0).level).toBe("idle");
  });

  it("push when bid is below enforce floor", () => {
    expect(bidStatus(love, 50).level).toBe("push");
  });

  it("target (sweet spot) when between enforce and max", () => {
    // enforce=108, max=193 → 150 should be target.
    expect(bidStatus(love, 150).level).toBe("target");
  });

  it("pass when bid exceeds max", () => {
    expect(bidStatus(love, 250).level).toBe("pass");
  });

  it("mine/gone labels when already drafted", () => {
    const mine = { ...love, drafted: true, mine: true };
    const gone = { ...love, drafted: true, mine: false };
    expect(bidStatus(mine, 100).level).toBe("mine");
    expect(bidStatus(gone, 100).level).toBe("gone");
  });
});

// ── hydrateWorkspace ────────────────────────────────────────────────

describe("hydrateWorkspace", () => {
  it("returns defaults for null / non-object / wrong version", () => {
    expect(hydrateWorkspace(null).version).toBe(1);
    expect(hydrateWorkspace("bad").version).toBe(1);
    expect(hydrateWorkspace({ version: 99 }).players.length).toBe(72);
  });

  it("preserves valid state", () => {
    const ws = createDefaultWorkspace();
    const mutated = recordPick(ws, {
      playerId: ws.players[0].id,
      teamIdx: 0,
      amount: 120,
    });
    const serialized = JSON.parse(JSON.stringify(mutated));
    const restored = hydrateWorkspace(serialized);
    expect(restored.picks.length).toBe(1);
    expect(restored.picks[0].amount).toBe(120);
  });

  it("drops malformed picks rather than crashing", () => {
    const bad = {
      version: 1,
      settings: { myTeamIdx: 0 },
      teams: [{ name: "x", initialBudget: 100 }],
      players: [{ id: "p1", rank: 1, name: "X", preDraft: 10 }],
      picks: [
        { playerId: "", teamIdx: 0, amount: 5 }, // empty id → drop
        { playerId: "p1", teamIdx: "x", amount: 5 }, // bad teamIdx → drop
        { playerId: "p1", teamIdx: 0, amount: 5 }, // keep
      ],
    };
    expect(hydrateWorkspace(bad).picks.length).toBe(1);
  });
});
