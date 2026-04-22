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
  DEFAULT_INITIAL_SLOTS,
  DEFAULT_TEAMS,
  DEFAULT_ROOKIES,
  DRAFT_STORAGE_KEY,
  PHASE_LATE_BOOST,
  TIER_DEFS,
  TIER_CONFIDENCE_MIN_SAMPLES,
  addPlayer,
  bidStatus,
  computeDraftStats,
  createDefaultWorkspace,
  effectiveBudgetFor,
  hydrateWorkspace,
  mergeDraftCapitalTeams,
  playerSlug,
  recordPick,
  removePick,
  removePlayer,
  slotsByTeamFromPicks,
  tierForPreDraft,
  undoLastPick,
  updatePlayerPreDraft,
  updateSettings,
  updateTeam,
  workspaceIsPristine,
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

  it("push when bid is below enforce floor AND below ceiling", () => {
    // Opening Love: enforce=108, winningBid=68 (top competitor is
    // Joel at 68 effective).  Bid of $50 is below both → push.
    expect(bidStatus(love, 50).level).toBe("push");
  });

  it("pass when bid exceeds winning bid (pass-beats-push)", () => {
    // Opening Love winning bid ≈ 68.  Bid of $100 is below the
    // enforce cap (108) but above the ceiling — overpay territory.
    // Pre-Tier-1 this was "target"; post-Tier-1 the competitor
    // ceiling rules.
    expect(bidStatus(love, 100).level).toBe("pass");
  });

  it("pass when bid far above ceiling", () => {
    expect(bidStatus(love, 250).level).toBe("pass");
  });

  it("target when bid between enforce and ceiling (mid-draft, rich rivals)", () => {
    // Force a scenario with a rich rival so ceiling > enforce and
    // "sweet spot" actually has space.  Simulate it by giving every
    // other team the same budget as Russini Panini so competitor
    // ceiling ≈ my own wealth.
    const richWs = createDefaultWorkspace();
    const evenWs = {
      ...richWs,
      teams: richWs.teams.map((t, i) =>
        i === 0 ? t : { ...t, initialBudget: 400 },
      ),
    };
    const evenStats = computeDraftStats(evenWs);
    const loveRich = evenStats.enrichedPlayers.find(
      (p) => p.name === "Jeremiyah Love",
    );
    // With 11 teams at $400 each, ceiling high → enforce=108 and
    // winning ≈ 400+1 competitor reality.  A bid of $120 sits
    // between enforce and ceiling → "target".
    expect(loveRich.myWinningBid).toBeGreaterThan(loveRich.enforceUpTo);
    expect(bidStatus(loveRich, 120).level).toBe("target");
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

// ── mergeDraftCapitalTeams ──────────────────────────────────────────
// Sample matches the exact shape returned by /api/draft-capital:
//   { teamTotals: [{ team: "…", auctionDollars: N }, …] }

describe("mergeDraftCapitalTeams", () => {
  const capitalFeed = [
    { team: "Russini Panini", auctionDollars: 418 },
    { team: "jstuedle", auctionDollars: 171 },
    { team: "Rage Against The Achane ", auctionDollars: 157 },
    { team: "CollinFoz", auctionDollars: 140 },
    { team: "Chargers Team Doctor", auctionDollars: 128 },
    { team: "killaKich00", auctionDollars: 64 },
    { team: "I\u2019m Not Afraid Anymore!", auctionDollars: 50 },
    { team: "TyBWell", auctionDollars: 49 },
    { team: "ughb", auctionDollars: 18 },
    { team: "Still Jason&Brents Team", auctionDollars: 5 },
  ];

  it("matches by case-insensitive name and copies the auction $", () => {
    const ws = createDefaultWorkspace();
    const { workspace, matched, added } = mergeDraftCapitalTeams(
      ws,
      capitalFeed,
    );
    // One of the defaults ("Russini Panini") matches; the other 11
    // defaults are dropped as placeholders, and the feed appends its
    // remaining 9 teams.
    expect(matched).toBe(1);
    expect(added).toBe(capitalFeed.length - 1);
    const russini = workspace.teams.find(
      (t) => t.name === "Russini Panini",
    );
    expect(russini.initialBudget).toBe(418);
  });

  it("drops pristine placeholder defaults rather than zeroing them", () => {
    const ws = createDefaultWorkspace();
    const { workspace } = mergeDraftCapitalTeams(ws, capitalFeed);
    // No "Ed" / "Brent" / "Joey" placeholders should survive a
    // pristine merge — they get replaced entirely by the feed.
    const names = workspace.teams.map((t) => t.name);
    expect(names).not.toContain("Ed");
    expect(names).not.toContain("Brent");
    expect(names).not.toContain("Joey");
    // Final size = matched (1) + added (9) = 10.
    expect(workspace.teams.length).toBe(10);
  });

  it("zeroes out manually-edited rows that aren't in the feed", () => {
    // User renamed "Ed" to "Dynasty Danglers" but left the budget
    // alone.  The rename signals user intent, so the row stays —
    // but zeroed, because the feed is authoritative for budgets.
    const ws = createDefaultWorkspace();
    const withRename = updateTeam(ws, 1, { name: "Dynasty Danglers" });
    const { workspace, zeroed } = mergeDraftCapitalTeams(
      withRename,
      capitalFeed,
    );
    const dd = workspace.teams.find((t) => t.name === "Dynasty Danglers");
    expect(dd).toBeTruthy();
    expect(dd.initialBudget).toBe(0);
    expect(zeroed).toContain("Dynasty Danglers");
  });

  it("appends feed teams that aren't already on the board", () => {
    const ws = createDefaultWorkspace();
    const { workspace } = mergeDraftCapitalTeams(ws, capitalFeed);
    const names = workspace.teams.map((t) => t.name);
    expect(names).toContain("jstuedle");
    expect(names).toContain("CollinFoz");
    expect(names).toContain("ughb");
  });

  it("preserves the user's myTeamIdx by name across the merge", () => {
    const ws = createDefaultWorkspace();
    // Pretend the user picked team index 2 ("Brent") as theirs.
    const picked = updateSettings(ws, { myTeamIdx: 0 });
    const { workspace } = mergeDraftCapitalTeams(picked, capitalFeed);
    // Russini Panini was at idx 0 before; it should still be the
    // "mine" team after merge.
    expect(workspace.teams[workspace.settings.myTeamIdx].name).toBe(
      "Russini Panini",
    );
  });

  it("keeps custom team names when preserveCustomNames=true (default)", () => {
    const ws = createDefaultWorkspace();
    // Simulate: user renamed "Russini Panini" to "My Squad" before
    // hitting the Draft Capital button.
    const renamed = updateTeam(ws, 0, { name: "My Squad" });
    const { workspace, matched } = mergeDraftCapitalTeams(
      renamed,
      capitalFeed,
    );
    // The rename means we miss the match against "Russini Panini"
    // and just append the feed's version.
    expect(matched).toBe(0);
    expect(
      workspace.teams.find((t) => t.name === "Russini Panini").initialBudget,
    ).toBe(418);
    expect(workspace.teams.find((t) => t.name === "My Squad")).toBeTruthy();
  });

  it("empty feed is a safe no-op", () => {
    const ws = createDefaultWorkspace();
    const { workspace, matched, added } = mergeDraftCapitalTeams(ws, []);
    expect(matched).toBe(0);
    expect(added).toBe(0);
    expect(workspace.teams).toEqual(ws.teams);
  });

  it("merged budgets sum to exactly the feed's total budget", () => {
    // With placeholder defaults dropped, the board should sum to
    // exactly $1200 — no phantom default budget left over.
    const ws = createDefaultWorkspace();
    const { workspace } = mergeDraftCapitalTeams(ws, capitalFeed);
    const feedTotal = capitalFeed.reduce((s, t) => s + t.auctionDollars, 0);
    expect(feedTotal).toBe(1200);
    const mergedTotal = workspace.teams.reduce(
      (s, t) => s + t.initialBudget,
      0,
    );
    expect(mergedTotal).toBe(1200);
  });

  it("a feed with a $0 team carries that $0 onto the board", () => {
    // Backend change (2026-04-23) seeds every Sleeper roster at $0
    // so teams that traded every rookie pick still appear in the
    // feed.  Confirm those rows land on the board with $0.
    const feedWithZero = [
      ...capitalFeed,
      { team: "Jason&Brent Future Team", auctionDollars: 0 },
    ];
    const { workspace } = mergeDraftCapitalTeams(
      createDefaultWorkspace(),
      feedWithZero,
    );
    const zero = workspace.teams.find(
      (t) => t.name === "Jason&Brent Future Team",
    );
    expect(zero).toBeTruthy();
    expect(zero.initialBudget).toBe(0);
  });
});

// ── workspaceIsPristine ─────────────────────────────────────────────

describe("workspaceIsPristine", () => {
  it("returns true for a freshly created workspace", () => {
    expect(workspaceIsPristine(createDefaultWorkspace())).toBe(true);
  });

  it("returns false once a pick is recorded", () => {
    const ws = createDefaultWorkspace();
    const next = recordPick(ws, {
      playerId: ws.players[0].id,
      teamIdx: 0,
      amount: 100,
    });
    expect(workspaceIsPristine(next)).toBe(false);
  });

  it("returns false once a team name or budget is edited", () => {
    const renamed = updateTeam(createDefaultWorkspace(), 0, {
      name: "Changed",
    });
    expect(workspaceIsPristine(renamed)).toBe(false);
    const rebudgeted = updateTeam(createDefaultWorkspace(), 1, {
      initialBudget: 999,
    });
    expect(workspaceIsPristine(rebudgeted)).toBe(false);
  });

  it("returns false when the team count differs from the default", () => {
    const ws = createDefaultWorkspace();
    const fewer = { ...ws, teams: ws.teams.slice(0, 10) };
    expect(workspaceIsPristine(fewer)).toBe(false);
  });

  it("gracefully handles null / undefined input", () => {
    expect(workspaceIsPristine(null)).toBe(false);
    expect(workspaceIsPristine(undefined)).toBe(false);
  });
});

// ── Tier 1 upgrades ─────────────────────────────────────────────────────

describe("tierForPreDraft", () => {
  it("classifies by PreDraft $ thresholds", () => {
    expect(tierForPreDraft(135)).toBe("S");
    expect(tierForPreDraft(60)).toBe("S");
    expect(tierForPreDraft(59)).toBe("A");
    expect(tierForPreDraft(25)).toBe("A");
    expect(tierForPreDraft(24)).toBe("B");
    expect(tierForPreDraft(8)).toBe("B");
    expect(tierForPreDraft(7)).toBe("C");
    expect(tierForPreDraft(3)).toBe("C");
    expect(tierForPreDraft(2)).toBe("D");
    expect(tierForPreDraft(1)).toBe("D");
    expect(tierForPreDraft(0)).toBe("D");
  });

  it("coerces bad input to D", () => {
    expect(tierForPreDraft(null)).toBe("D");
    expect(tierForPreDraft(undefined)).toBe("D");
    expect(tierForPreDraft("garbage")).toBe("D");
    expect(tierForPreDraft(-5)).toBe("D");
  });

  it("TIER_DEFS exports 5 tiers in descending price order", () => {
    expect(TIER_DEFS.map((t) => t.key)).toEqual(["S", "A", "B", "C", "D"]);
    for (let i = 1; i < TIER_DEFS.length; i++) {
      expect(TIER_DEFS[i].min).toBeLessThan(TIER_DEFS[i - 1].min);
    }
  });
});

describe("effectiveBudgetFor", () => {
  it("reserves $1 per remaining slot beyond the current bid", () => {
    expect(effectiveBudgetFor(100, 3)).toBe(98); // $1 × 2 reserved
    expect(effectiveBudgetFor(100, 1)).toBe(100); // last slot: full budget
    expect(effectiveBudgetFor(5, 5)).toBe(1); // $1 × 4 reserved
  });

  it("returns 0 when slots are 0 (team has no roster space)", () => {
    expect(effectiveBudgetFor(50, 0)).toBe(0);
  });

  it("returns 0 when team is over-committed (more slots than $)", () => {
    expect(effectiveBudgetFor(10, 11)).toBe(0);
  });

  it("handles bad input gracefully", () => {
    expect(effectiveBudgetFor(null, 3)).toBe(0);
    expect(effectiveBudgetFor(100, null)).toBe(0);
    expect(effectiveBudgetFor(-5, 3)).toBe(0);
  });
});

describe("slotsByTeamFromPicks", () => {
  it("counts picks per currentOwner (case-insensitive)", () => {
    const picks = [
      { currentOwner: "Russini Panini" },
      { currentOwner: "Russini Panini" },
      { currentOwner: "jstuedle" },
      { currentOwner: "RUSSINI PANINI" }, // different casing
    ];
    const counts = slotsByTeamFromPicks(picks);
    expect(counts.get("russini panini")).toBe(3);
    expect(counts.get("jstuedle")).toBe(1);
  });

  it("handles null / non-array input", () => {
    expect(slotsByTeamFromPicks(null).size).toBe(0);
    expect(slotsByTeamFromPicks(undefined).size).toBe(0);
    expect(slotsByTeamFromPicks("bad").size).toBe(0);
  });

  it("ignores picks with missing owner", () => {
    const picks = [
      { currentOwner: "Russini Panini" },
      { currentOwner: "" },
      { currentOwner: null },
      {},
    ];
    expect(slotsByTeamFromPicks(picks).get("russini panini")).toBe(1);
  });
});

// ── computeDraftStats: Tier 1 derivations ───────────────────────────────

describe("computeDraftStats — Tier 1 new fields", () => {
  const ws = createDefaultWorkspace();
  const stats = computeDraftStats(ws);

  it("exposes initialSlots / slotsRemaining / effectiveBudget per team", () => {
    for (const t of stats.teamStats) {
      expect(t.initialSlots).toBe(DEFAULT_INITIAL_SLOTS);
      expect(t.slotsDrafted).toBe(0);
      expect(t.slotsRemaining).toBe(DEFAULT_INITIAL_SLOTS);
      // effectiveBudget = max(0, remaining − (slots − 1))
      expect(t.effectiveBudget).toBe(
        Math.max(0, t.remaining - (DEFAULT_INITIAL_SLOTS - 1)),
      );
    }
  });

  it("slotPressure is 0 at draft start", () => {
    expect(stats.slotPressure).toBe(0);
    expect(stats.phaseMultiplier).toBe(1);
  });

  it("topCompetitorMax is the max OTHER slot-adjusted budget", () => {
    // Teams 1-10 have $71, Joel has $73.  All with 6 slots.
    // Effective: 71-5=66, 73-5=68.  Top competitor = 68 (Joel).
    expect(stats.topCompetitorMax).toBe(68);
  });

  it("enrichedPlayers carry tier + myWinningBid", () => {
    const love = stats.enrichedPlayers.find(
      (p) => p.name === "Jeremiyah Love",
    );
    expect(love.tier).toBe("S");
    // Love's theoretical max at opening is 193; competitor ceiling
    // caps winning bid at 68+1=69.
    expect(love.theoreticalMaxBid).toBe(193);
    expect(love.myWinningBid).toBe(69);
  });

  it("myWinningBid ≤ theoreticalMaxBid for every undrafted player", () => {
    for (const p of stats.enrichedPlayers) {
      if (p.drafted) continue;
      expect(p.myWinningBid).toBeLessThanOrEqual(p.theoreticalMaxBid);
    }
  });

  it("tier heat is null at draft start (no samples)", () => {
    for (const key of ["S", "A", "B", "C", "D"]) {
      expect(stats.tierHeat[key]).toBeNull();
      expect(stats.tierConfidence[key]).toBe(0);
      expect(stats.tierSampleCount[key]).toBe(0);
    }
  });
});

describe("computeDraftStats — preDraftAtPick snapshot", () => {
  it("recordPick stores the current preDraft at the moment of the pick", () => {
    const ws = createDefaultWorkspace();
    const love = ws.players.find((p) => p.name === "Jeremiyah Love");
    const next = recordPick(ws, {
      playerId: love.id,
      teamIdx: 0,
      amount: 120,
    });
    expect(next.picks[0].preDraftAtPick).toBe(135);
  });

  it("retroactive preDraft edit does NOT change tier heat (snapshot wins)", () => {
    const ws = createDefaultWorkspace();
    const love = ws.players.find((p) => p.name === "Jeremiyah Love");
    const withPick = recordPick(ws, {
      playerId: love.id,
      teamIdx: 5,
      amount: 200,
    });
    const before = computeDraftStats(withPick);
    // Now the user decides Love is actually worth 80 (retroactive).
    const withEdit = updatePlayerPreDraft(withPick, love.id, 80);
    const after = computeDraftStats(withEdit);
    // tierHeat for S should be unchanged because preDraftAtPick
    // snapshot is what's used, not the current player.preDraft.
    expect(after.tierHeat.S).toBeCloseTo(before.tierHeat.S, 4);
    // And the inflation denominator is the same (also uses snapshot).
    expect(after.inflation).toBeCloseTo(before.inflation, 4);
  });
});

describe("computeDraftStats — tier heat / inflation blend", () => {
  it("one S-tier overpay pushes tier heat > 1 with low confidence", () => {
    const ws = createDefaultWorkspace();
    const love = ws.players.find((p) => p.name === "Jeremiyah Love");
    const stats = computeDraftStats(
      recordPick(ws, { playerId: love.id, teamIdx: 5, amount: 200 }),
    );
    expect(stats.tierHeat.S).toBeCloseTo(200 / 135, 4);
    // 1 sample / 3-sample min = 0.333 confidence
    expect(stats.tierConfidence.S).toBeCloseTo(1 / 3, 4);
    expect(stats.tierSampleCount.S).toBe(1);
  });

  it("three S-tier picks hits full confidence", () => {
    const ws = createDefaultWorkspace();
    const love = ws.players.find((p) => p.name === "Jeremiyah Love");
    const mendoza = ws.players.find(
      (p) => p.name === "Fernando Mendoza",
    );
    const lemon = ws.players.find((p) => p.name === "Makai Lemon");
    let next = recordPick(ws, { playerId: love.id, teamIdx: 5, amount: 135 });
    next = recordPick(next, { playerId: mendoza.id, teamIdx: 4, amount: 102 });
    next = recordPick(next, { playerId: lemon.id, teamIdx: 3, amount: 90 });
    const stats = computeDraftStats(next);
    expect(stats.tierSampleCount.S).toBe(3);
    expect(stats.tierConfidence.S).toBe(1);
    // Paid exactly fair each time → heat = 1.0
    expect(stats.tierHeat.S).toBeCloseTo(1.0, 4);
  });

  it("tier heat is unaffected by picks in other tiers", () => {
    const ws = createDefaultWorkspace();
    // Draft a $1 D-tier player at $10 (massive overpay, but for D).
    const caleb = ws.players.find((p) => p.name === "Caleb Douglas");
    const next = recordPick(ws, {
      playerId: caleb.id,
      teamIdx: 3,
      amount: 10,
    });
    const stats = computeDraftStats(next);
    expect(stats.tierHeat.D).toBeGreaterThan(1);
    expect(stats.tierHeat.S).toBeNull();
    expect(stats.tierHeat.A).toBeNull();
    expect(stats.tierHeat.B).toBeNull();
    expect(stats.tierHeat.C).toBeNull();
  });
});

describe("computeDraftStats — phase multiplier (slot pressure)", () => {
  it("ramps up as my slots drain", () => {
    // Simulate me (team 0) drafting 5 of 6 picks at $1 each so we
    // move slotPressure from 0 → 5/6 without blowing the budget
    // (and without disturbing tier S heat).
    const ws = createDefaultWorkspace();
    const picks = [
      "Caleb Douglas",
      "De'Zhaun Stribling",
      "Drew Allar",
      "Roman Hemby",
      "Jeff Caldwell",
    ];
    let next = ws;
    for (const name of picks) {
      const p = next.players.find((pl) => pl.name === name);
      next = recordPick(next, {
        playerId: p.id,
        teamIdx: 0,
        amount: 1,
      });
    }
    const stats = computeDraftStats(next);
    expect(stats.mySlotsRemaining).toBe(1);
    expect(stats.slotPressure).toBeCloseTo(5 / 6, 4);
    // phaseMultiplier = 1 + (5/6) × 0.5 ≈ 1.417
    expect(stats.phaseMultiplier).toBeCloseTo(1 + (5 / 6) * PHASE_LATE_BOOST, 4);
  });

  it("phase multiplier stays at 1 when no slots drafted", () => {
    const stats = computeDraftStats(createDefaultWorkspace());
    expect(stats.phaseMultiplier).toBe(1);
  });
});

describe("computeDraftStats — top competitor ceiling capping", () => {
  it("winning bid collapses to 1 when every other team is bankrupt", () => {
    const ws = createDefaultWorkspace();
    // Zero every other team's budget.
    const bankruptWs = {
      ...ws,
      teams: ws.teams.map((t, i) =>
        i === 0 ? t : { ...t, initialBudget: 0 },
      ),
    };
    const stats = computeDraftStats(bankruptWs);
    expect(stats.topCompetitorMax).toBe(0);
    const love = stats.enrichedPlayers.find(
      (p) => p.name === "Jeremiyah Love",
    );
    // myWinningBid = max(1, 0+1) = 1 — I lock any player for $1.
    expect(love.myWinningBid).toBe(1);
  });

  it("winning bid uncapped (up to theoretical max) with wealthy rivals", () => {
    const ws = createDefaultWorkspace();
    // Set every rival to my budget so competitor ceiling is high.
    const evenWs = {
      ...ws,
      teams: ws.teams.map((t, i) =>
        i === 0 ? t : { ...t, initialBudget: 417 },
      ),
    };
    const stats = computeDraftStats(evenWs);
    expect(stats.topCompetitorMax).toBeGreaterThan(400);
    const love = stats.enrichedPlayers.find(
      (p) => p.name === "Jeremiyah Love",
    );
    // Budget advantage ≈ 1.0 now, so theoretical max ≈ preDraft ×
    // (1 + 0.09 × 0) = preDraft.  Winning bid doesn't cap below it.
    expect(love.myWinningBid).toBeCloseTo(love.theoreticalMaxBid, 0);
  });
});

describe("mergeDraftCapitalTeams — with picks array", () => {
  const teamTotals = [
    { team: "Russini Panini", auctionDollars: 418 },
    { team: "jstuedle", auctionDollars: 171 },
    { team: "Pop Trunk", auctionDollars: 0 },
  ];
  const picks = [
    // Russini owns 8 picks, jstuedle 3, Pop Trunk 0
    ...Array(8).fill({ currentOwner: "Russini Panini" }),
    ...Array(3).fill({ currentOwner: "jstuedle" }),
  ];

  it("sets initialSlots from the picks array when supplied", () => {
    const ws = createDefaultWorkspace();
    const { workspace } = mergeDraftCapitalTeams(ws, teamTotals, { picks });
    const russini = workspace.teams.find((t) => t.name === "Russini Panini");
    const jstu = workspace.teams.find((t) => t.name === "jstuedle");
    const pop = workspace.teams.find((t) => t.name === "Pop Trunk");
    expect(russini.initialSlots).toBe(8);
    expect(jstu.initialSlots).toBe(3);
    expect(pop.initialSlots).toBe(0);
  });

  it("without picks array, initialSlots falls back to DEFAULT_INITIAL_SLOTS", () => {
    const ws = createDefaultWorkspace();
    const { workspace } = mergeDraftCapitalTeams(ws, teamTotals);
    const russini = workspace.teams.find((t) => t.name === "Russini Panini");
    expect(russini.initialSlots).toBe(DEFAULT_INITIAL_SLOTS);
  });
});

describe("hydrateWorkspace — Tier 1 field backfill", () => {
  it("backfills preDraftAtPick from current player when missing", () => {
    const parsed = {
      version: 1,
      settings: { myTeamIdx: 0 },
      teams: DEFAULT_TEAMS,
      players: DEFAULT_ROOKIES.map((p) => ({
        id: playerSlug(p.name),
        rank: p.rank,
        name: p.name,
        preDraft: p.preDraft,
      })),
      picks: [
        // Old-format pick: no preDraftAtPick field
        {
          playerId: playerSlug("Jeremiyah Love"),
          teamIdx: 0,
          amount: 120,
          ts: 1000,
        },
      ],
    };
    const ws = hydrateWorkspace(parsed);
    expect(ws.picks[0].preDraftAtPick).toBe(135); // from player.preDraft
  });

  it("preserves preDraftAtPick when present (no retroactive rewrite)", () => {
    const parsed = {
      version: 1,
      settings: { myTeamIdx: 0 },
      teams: DEFAULT_TEAMS,
      players: DEFAULT_ROOKIES.map((p) => ({
        id: playerSlug(p.name),
        rank: p.rank,
        name: p.name,
        preDraft: p.preDraft,
      })),
      picks: [
        {
          playerId: playerSlug("Jeremiyah Love"),
          teamIdx: 0,
          amount: 120,
          preDraftAtPick: 999, // user edited preDraft after pick
          ts: 1000,
        },
      ],
    };
    const ws = hydrateWorkspace(parsed);
    expect(ws.picks[0].preDraftAtPick).toBe(999);
  });

  it("backfills initialSlots to DEFAULT_INITIAL_SLOTS when missing", () => {
    const parsed = {
      version: 1,
      settings: { myTeamIdx: 0 },
      teams: [{ name: "A", initialBudget: 100 }], // no initialSlots
      players: [],
      picks: [],
    };
    const ws = hydrateWorkspace(parsed);
    expect(ws.teams[0].initialSlots).toBe(DEFAULT_INITIAL_SLOTS);
  });
});
