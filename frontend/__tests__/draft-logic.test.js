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

  it("sync mode updates every row when none have been manually edited", () => {
    // First pull seeds feedBudget on every row.  A second pull with
    // different numbers should flow through freely because no row's
    // initialBudget has diverged from its feedBudget yet.
    const ws = createDefaultWorkspace();
    const { workspace: first } = mergeDraftCapitalTeams(ws, capitalFeed, {
      mode: "sync",
    });
    const bumpedFeed = capitalFeed.map((e) => ({
      ...e,
      auctionDollars: e.auctionDollars + 1,
    }));
    const { workspace: second } = mergeDraftCapitalTeams(first, bumpedFeed, {
      mode: "sync",
    });
    const russini = second.teams.find((t) => t.name === "Russini Panini");
    expect(russini.initialBudget).toBe(419);
    expect(russini.feedBudget).toBe(419);
  });

  it("sync mode preserves a user-edited row and still advances feedBudget", () => {
    const ws = createDefaultWorkspace();
    const { workspace: seeded } = mergeDraftCapitalTeams(ws, capitalFeed, {
      mode: "sync",
    });
    // User overrides Russini Panini to 500.
    const edited = updateTeam(
      seeded,
      seeded.teams.findIndex((t) => t.name === "Russini Panini"),
      { initialBudget: 500 },
    );
    // Draft capital re-pulls with a new value.
    const newFeed = capitalFeed.map((e) =>
      e.team === "Russini Panini" ? { ...e, auctionDollars: 420 } : e,
    );
    const { workspace: after } = mergeDraftCapitalTeams(edited, newFeed, {
      mode: "sync",
    });
    const russini = after.teams.find((t) => t.name === "Russini Panini");
    // User's 500 is preserved; feedBudget tracks the latest feed.
    expect(russini.initialBudget).toBe(500);
    expect(russini.feedBudget).toBe(420);
  });

  it("force mode overwrites user edits (the Load-from-Draft-Capital button)", () => {
    const ws = createDefaultWorkspace();
    const { workspace: seeded } = mergeDraftCapitalTeams(ws, capitalFeed, {
      mode: "sync",
    });
    const edited = updateTeam(
      seeded,
      seeded.teams.findIndex((t) => t.name === "Russini Panini"),
      { initialBudget: 500 },
    );
    const { workspace: forced } = mergeDraftCapitalTeams(edited, capitalFeed, {
      mode: "force",
    });
    const russini = forced.teams.find((t) => t.name === "Russini Panini");
    expect(russini.initialBudget).toBe(418);
    expect(russini.feedBudget).toBe(418);
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

// ── Tier 2 ──────────────────────────────────────────────────────────────

import {
  TAG_TARGET,
  TAG_AVOID,
  TIER_SCARCITY_URGENT,
  cycleTag,
  nextBestTargets,
  playerRecommendation,
  setPlayerTag,
} from "@/lib/draft-logic";

describe("cycleTag", () => {
  it("cycles neutral → target → avoid → neutral", () => {
    expect(cycleTag(null)).toBe(TAG_TARGET);
    expect(cycleTag(undefined)).toBe(TAG_TARGET);
    expect(cycleTag(TAG_TARGET)).toBe(TAG_AVOID);
    expect(cycleTag(TAG_AVOID)).toBe(null);
  });
});

describe("setPlayerTag", () => {
  it("writes target/avoid and clears on anything else", () => {
    const ws = createDefaultWorkspace();
    const love = ws.players.find((p) => p.name === "Jeremiyah Love");
    const tagged = setPlayerTag(ws, love.id, TAG_TARGET);
    expect(tagged.tags[love.id]).toBe(TAG_TARGET);
    const cleared = setPlayerTag(tagged, love.id, null);
    expect(cleared.tags[love.id]).toBeUndefined();
    const avoided = setPlayerTag(ws, love.id, TAG_AVOID);
    expect(avoided.tags[love.id]).toBe(TAG_AVOID);
  });

  it("does not mutate the input workspace", () => {
    const ws = createDefaultWorkspace();
    const love = ws.players.find((p) => p.name === "Jeremiyah Love");
    const result = setPlayerTag(ws, love.id, TAG_TARGET);
    expect(ws.tags[love.id]).toBeUndefined();
    expect(result.tags[love.id]).toBe(TAG_TARGET);
  });

  it("no-op when playerId is empty", () => {
    const ws = createDefaultWorkspace();
    expect(setPlayerTag(ws, "", TAG_TARGET)).toBe(ws);
  });
});

describe("hydrateWorkspace — tags roundtrip", () => {
  it("preserves valid target/avoid tags", () => {
    const ws = createDefaultWorkspace();
    const tagged = setPlayerTag(
      setPlayerTag(ws, "jeremiyah-love", TAG_TARGET),
      "drew-allar",
      TAG_AVOID,
    );
    const roundtripped = hydrateWorkspace(
      JSON.parse(JSON.stringify(tagged)),
    );
    expect(roundtripped.tags["jeremiyah-love"]).toBe(TAG_TARGET);
    expect(roundtripped.tags["drew-allar"]).toBe(TAG_AVOID);
  });

  it("drops invalid tag values", () => {
    const parsed = {
      version: 1,
      settings: {},
      teams: DEFAULT_TEAMS,
      players: DEFAULT_ROOKIES.map((p) => ({
        id: playerSlug(p.name),
        rank: p.rank,
        name: p.name,
        preDraft: p.preDraft,
      })),
      picks: [],
      tags: {
        "jeremiyah-love": "target",
        "carnell-tate": "bogus",
        "makai-lemon": null,
      },
    };
    const ws = hydrateWorkspace(parsed);
    expect(ws.tags["jeremiyah-love"]).toBe(TAG_TARGET);
    expect(ws.tags["carnell-tate"]).toBeUndefined();
    expect(ws.tags["makai-lemon"]).toBeUndefined();
  });
});

// ── tierStats ───────────────────────────────────────────────────────────

describe("computeDraftStats — tierStats", () => {
  it("reports totals per tier at draft start", () => {
    const stats = computeDraftStats(createDefaultWorkspace());
    // DEFAULT_ROOKIES distribution:
    //   S (≥60): Love(135), Mendoza(102), Lemon(90), Tate(83),
    //            Tyson(73), Styles(66), Downs(61) → 7
    //   A (25-59): Sadiq, McNeil-Warren, Thieneman, Bailey,
    //              Reese, CJ Allen, Concepcion, Cooper → 8 (sanity via ≥25 && <60)
    //   ...
    // Just sanity-check shape + totals sum to 72.
    const totalAcrossTiers = Object.values(stats.tierStats).reduce(
      (s, t) => s + t.total,
      0,
    );
    expect(totalAcrossTiers).toBe(72);
    expect(stats.tierStats.S.total).toBeGreaterThan(0);
    expect(stats.tierStats.S.remaining).toBe(stats.tierStats.S.total);
    expect(stats.tierStats.S.remainingRatio).toBe(1);
  });

  it("tracks drafted / remaining as picks land", () => {
    const ws = createDefaultWorkspace();
    const love = ws.players.find((p) => p.name === "Jeremiyah Love");
    const withPick = recordPick(ws, {
      playerId: love.id,
      teamIdx: 5,
      amount: 135,
    });
    const stats = computeDraftStats(withPick);
    const sBefore = computeDraftStats(ws).tierStats.S;
    expect(stats.tierStats.S.drafted).toBe(1);
    expect(stats.tierStats.S.remaining).toBe(sBefore.total - 1);
    expect(stats.tierStats.S.remainingRatio).toBeCloseTo(
      (sBefore.total - 1) / sBefore.total,
      4,
    );
  });
});

describe("computeDraftStats — draftProgress", () => {
  it("starts at 0 and climbs with picks", () => {
    const ws = createDefaultWorkspace();
    const s0 = computeDraftStats(ws);
    expect(s0.draftProgress).toBe(0);
    expect(s0.totalInitialSlots).toBe(12 * DEFAULT_INITIAL_SLOTS);

    const love = ws.players.find((p) => p.name === "Jeremiyah Love");
    const withPick = recordPick(ws, {
      playerId: love.id,
      teamIdx: 0,
      amount: 135,
    });
    const s1 = computeDraftStats(withPick);
    expect(s1.totalPicksMade).toBe(1);
    expect(s1.draftProgress).toBeCloseTo(1 / 72, 4);
  });
});

describe("enrichedPlayers carry userTag", () => {
  it("reflects target/avoid/null per player", () => {
    let ws = createDefaultWorkspace();
    ws = setPlayerTag(ws, "jeremiyah-love", TAG_TARGET);
    ws = setPlayerTag(ws, "drew-allar", TAG_AVOID);
    const stats = computeDraftStats(ws);
    const love = stats.enrichedPlayers.find(
      (p) => p.name === "Jeremiyah Love",
    );
    const allar = stats.enrichedPlayers.find(
      (p) => p.name === "Drew Allar",
    );
    const tate = stats.enrichedPlayers.find(
      (p) => p.name === "Carnell Tate",
    );
    expect(love.userTag).toBe(TAG_TARGET);
    expect(allar.userTag).toBe(TAG_AVOID);
    expect(tate.userTag).toBeNull();
  });
});

// ── playerRecommendation ────────────────────────────────────────────────

describe("playerRecommendation", () => {
  it("returns null for drafted players", () => {
    const ws = createDefaultWorkspace();
    const love = ws.players.find((p) => p.name === "Jeremiyah Love");
    const withPick = recordPick(ws, {
      playerId: love.id,
      teamIdx: 0,
      amount: 120,
    });
    const stats = computeDraftStats(withPick);
    const lovePost = stats.enrichedPlayers.find(
      (p) => p.name === "Jeremiyah Love",
    );
    expect(playerRecommendation(lovePost, stats)).toBeNull();
  });

  it("AVOID tag always returns level 'avoid'", () => {
    let ws = createDefaultWorkspace();
    ws = setPlayerTag(ws, "jeremiyah-love", TAG_AVOID);
    const stats = computeDraftStats(ws);
    const love = stats.enrichedPlayers.find(
      (p) => p.name === "Jeremiyah Love",
    );
    const rec = playerRecommendation(love, stats);
    expect(rec.level).toBe("avoid");
  });

  it("neutral tag = no recommendation (level 'neutral')", () => {
    const stats = computeDraftStats(createDefaultWorkspace());
    const tate = stats.enrichedPlayers.find(
      (p) => p.name === "Carnell Tate",
    );
    const rec = playerRecommendation(tate, stats);
    expect(rec.level).toBe("neutral");
  });

  it("LOCK when rivals are bankrupt and player is a target", () => {
    let ws = createDefaultWorkspace();
    // Zero every rival's budget so topCompetitorMax == 0.
    ws = {
      ...ws,
      teams: ws.teams.map((t, i) =>
        i === 0 ? t : { ...t, initialBudget: 0 },
      ),
    };
    ws = setPlayerTag(ws, "jeremiyah-love", TAG_TARGET);
    const stats = computeDraftStats(ws);
    const love = stats.enrichedPlayers.find(
      (p) => p.name === "Jeremiyah Love",
    );
    expect(stats.topCompetitorMax).toBe(0);
    expect(playerRecommendation(love, stats).level).toBe("lock");
  });

  it("STEAL when rivals are bankrupt but player is untagged", () => {
    const bankrupt = {
      ...createDefaultWorkspace(),
    };
    bankrupt.teams = bankrupt.teams.map((t, i) =>
      i === 0 ? t : { ...t, initialBudget: 0 },
    );
    const stats = computeDraftStats(bankrupt);
    const tate = stats.enrichedPlayers.find(
      (p) => p.name === "Carnell Tate",
    );
    expect(playerRecommendation(tate, stats).level).toBe("steal");
  });

  it("PUSH when target is in a drying-up tier", () => {
    // Force S-tier scarcity by drafting most S players.
    let ws = createDefaultWorkspace();
    const sPlayers = ws.players.filter(
      (p) => p.preDraft >= 60,
    );
    // Draft all but the first S-tier player.
    for (const p of sPlayers.slice(1)) {
      ws = recordPick(ws, {
        playerId: p.id,
        teamIdx: 5,
        amount: Math.max(1, Math.floor(p.preDraft * 0.5)),
      });
    }
    ws = setPlayerTag(ws, sPlayers[0].id, TAG_TARGET);
    const stats = computeDraftStats(ws);
    expect(stats.tierStats.S.remainingRatio).toBeLessThan(
      TIER_SCARCITY_URGENT,
    );
    const p = stats.enrichedPlayers.find((pl) => pl.id === sPlayers[0].id);
    const rec = playerRecommendation(p, stats);
    expect(rec.level).toBe("push");
  });

  it("BUY is the default for a target in a normal market", () => {
    // All defaults except target flag on Love.  No picks yet, so
    // rivals still wealthy, no tier scarcity, no slot pressure.
    let ws = createDefaultWorkspace();
    ws = setPlayerTag(ws, "jeremiyah-love", TAG_TARGET);
    const stats = computeDraftStats(ws);
    const love = stats.enrichedPlayers.find(
      (p) => p.name === "Jeremiyah Love",
    );
    const rec = playerRecommendation(love, stats);
    // Opening-state competitor ceiling is $68 (Joel).  preDraft 135;
    // collapse floor = 0.3 × 135 = 40.  68 > 40 so no lock/steal.
    // No tier scarcity on S at opening.  Slot pressure 0 so no
    // spend-up.  → "buy".
    expect(rec.level).toBe("buy");
  });
});

// ── nextBestTargets ─────────────────────────────────────────────────────

describe("nextBestTargets", () => {
  it("returns an array capped at the limit", () => {
    const stats = computeDraftStats(createDefaultWorkspace());
    const top = nextBestTargets(stats, { limit: 5 });
    expect(top.length).toBeLessThanOrEqual(5);
    for (const entry of top) {
      expect(entry.player).toBeTruthy();
      expect(entry.rec).toBeTruthy();
      expect(entry.ev).toBeGreaterThanOrEqual(0);
    }
  });

  it("excludes drafted players", () => {
    const ws = createDefaultWorkspace();
    const love = ws.players.find((p) => p.name === "Jeremiyah Love");
    const withPick = recordPick(ws, {
      playerId: love.id,
      teamIdx: 0,
      amount: 120,
    });
    const stats = computeDraftStats(withPick);
    const top = nextBestTargets(stats, { limit: 10 });
    expect(top.find((e) => e.player.name === "Jeremiyah Love")).toBeUndefined();
  });

  it("excludes AVOID-tagged players entirely", () => {
    let ws = createDefaultWorkspace();
    ws = setPlayerTag(ws, "jeremiyah-love", TAG_AVOID);
    const stats = computeDraftStats(ws);
    const top = nextBestTargets(stats, { limit: 72 });
    expect(top.find((e) => e.player.name === "Jeremiyah Love")).toBeUndefined();
  });

  it("ranks TARGET-tagged players above untagged at similar value", () => {
    let ws = createDefaultWorkspace();
    // Tag Tate (PreDraft 83) as a target; Tyson (73) stays neutral.
    ws = setPlayerTag(ws, "carnell-tate", TAG_TARGET);
    const stats = computeDraftStats(ws);
    const top = nextBestTargets(stats, { limit: 5 });
    const tateIdx = top.findIndex((e) => e.player.name === "Carnell Tate");
    const tysonIdx = top.findIndex(
      (e) => e.player.name === "Jordyn Tyson",
    );
    // Tate should be at or above Tyson after the tag boost.
    expect(tateIdx).toBeGreaterThanOrEqual(0);
    if (tysonIdx >= 0) {
      expect(tateIdx).toBeLessThan(tysonIdx);
    }
  });

  it("falls back gracefully when stats is null", () => {
    expect(nextBestTargets(null)).toEqual([]);
  });
});

// ── Tier 3 ──────────────────────────────────────────────────────────────

import {
  computeHistorySeries,
  nominationCandidates,
} from "@/lib/draft-logic";

describe("teamStats — Tier 3 per-team signals", () => {
  it("mdv = remaining / slotsRemaining; 0 when no slots left", () => {
    const ws = createDefaultWorkspace();
    const stats = computeDraftStats(ws);
    const mine = stats.teamStats[0];
    // Russini: 417 / 6 ≈ 69.5
    expect(mine.mdv).toBeCloseTo(417 / 6, 4);
  });

  it("overpayIndex is null before any picks", () => {
    const ws = createDefaultWorkspace();
    const stats = computeDraftStats(ws);
    for (const t of stats.teamStats) {
      expect(t.overpayIndex).toBeNull();
      expect(t.preDraftSum).toBe(0);
    }
  });

  it("overpayIndex > 0 when a team pays over PreDraft", () => {
    const ws = createDefaultWorkspace();
    const love = ws.players.find((p) => p.name === "Jeremiyah Love");
    const withPick = recordPick(ws, {
      playerId: love.id,
      teamIdx: 5,
      amount: 200, // $65 over fair
    });
    const stats = computeDraftStats(withPick);
    const overpayer = stats.teamStats[5];
    expect(overpayer.overpayIndex).toBeCloseTo((200 - 135) / 135, 4);
  });

  it("overpayIndex < 0 for a value hunter", () => {
    const ws = createDefaultWorkspace();
    const mendoza = ws.players.find((p) => p.name === "Fernando Mendoza");
    const withPick = recordPick(ws, {
      playerId: mendoza.id,
      teamIdx: 4,
      amount: 50, // $52 under fair
    });
    const stats = computeDraftStats(withPick);
    const hunter = stats.teamStats[4];
    expect(hunter.overpayIndex).toBeCloseTo((50 - 102) / 102, 4);
    expect(hunter.overpayIndex).toBeLessThan(0);
  });

  it("overpayIndex aggregates across multiple picks", () => {
    const ws = createDefaultWorkspace();
    const love = ws.players.find((p) => p.name === "Jeremiyah Love");
    const mendoza = ws.players.find((p) => p.name === "Fernando Mendoza");
    let next = recordPick(ws, {
      playerId: love.id,
      teamIdx: 5,
      amount: 200,
    });
    next = recordPick(next, {
      playerId: mendoza.id,
      teamIdx: 5,
      amount: 120,
    });
    const stats = computeDraftStats(next);
    const t = stats.teamStats[5];
    // Paid 320, preDraft 237 → overpayIndex = (320 - 237) / 237
    expect(t.preDraftSum).toBe(135 + 102);
    expect(t.overpayIndex).toBeCloseTo((320 - 237) / 237, 4);
    expect(t.picksCount).toBe(2);
  });
});

describe("nominationCandidates", () => {
  it("returns empty when stats is null or missing", () => {
    expect(nominationCandidates(null)).toEqual([]);
    expect(nominationCandidates({})).toEqual([]);
  });

  it("excludes drafted players", () => {
    const ws = createDefaultWorkspace();
    const love = ws.players.find((p) => p.name === "Jeremiyah Love");
    const withPick = recordPick(ws, {
      playerId: love.id,
      teamIdx: 0,
      amount: 120,
    });
    const stats = computeDraftStats(withPick);
    const list = nominationCandidates(stats, { limit: 72 });
    expect(list.find((n) => n.player.name === "Jeremiyah Love")).toBeUndefined();
  });

  it("excludes target-tagged players (never nominate my own targets)", () => {
    let ws = createDefaultWorkspace();
    ws = setPlayerTag(ws, "jeremiyah-love", TAG_TARGET);
    const stats = computeDraftStats(ws);
    const list = nominationCandidates(stats, { limit: 72 });
    expect(list.find((n) => n.player.name === "Jeremiyah Love")).toBeUndefined();
  });

  it("score is capped by top competitor affordability (drain floor)", () => {
    // Strip all other teams' budgets so drain potential = 0.
    const ws = createDefaultWorkspace();
    const bankrupt = {
      ...ws,
      teams: ws.teams.map((t, i) =>
        i === 0 ? t : { ...t, initialBudget: 0 },
      ),
    };
    const stats = computeDraftStats(bankrupt);
    expect(stats.topCompetitorMax).toBe(0);
    // drain < 1 → player skipped entirely
    const list = nominationCandidates(stats, { limit: 72 });
    expect(list.length).toBe(0);
  });

  it("carries a rationale on every entry", () => {
    const stats = computeDraftStats(createDefaultWorkspace());
    const list = nominationCandidates(stats, { limit: 3 });
    for (const entry of list) {
      expect(typeof entry.rationale).toBe("string");
      expect(entry.rationale.length).toBeGreaterThan(0);
    }
  });
});

describe("computeHistorySeries", () => {
  it("returns baseline + one entry per pick in ts order", () => {
    const ws = createDefaultWorkspace();
    const love = ws.players.find((p) => p.name === "Jeremiyah Love");
    const mendoza = ws.players.find((p) => p.name === "Fernando Mendoza");
    const p1 = recordPick(ws, {
      playerId: love.id,
      teamIdx: 5,
      amount: 135,
    });
    // Mutate the second pick's ts so it's strictly later (recordPick
    // uses Date.now(), which may collide within a single tick).
    const p2 = recordPick(p1, {
      playerId: mendoza.id,
      teamIdx: 4,
      amount: 102,
    });
    p2.picks[1].ts = p2.picks[0].ts + 1000;

    const series = computeHistorySeries(p2);
    expect(series.length).toBe(3); // baseline + 2 picks
    expect(series[0].picksCount).toBe(0);
    expect(series[1].picksCount).toBe(1);
    expect(series[2].picksCount).toBe(2);
    expect(series[0].inflation).toBeCloseTo(1.0, 4);
  });

  it("reflects inflation shifts as picks accumulate", () => {
    const ws = createDefaultWorkspace();
    const love = ws.players.find((p) => p.name === "Jeremiyah Love");
    // Massive overpay → inflation drops.
    const withPick = recordPick(ws, {
      playerId: love.id,
      teamIdx: 5,
      amount: 300,
    });
    const series = computeHistorySeries(withPick);
    expect(series[0].inflation).toBeCloseTo(1.0, 4);
    expect(series[1].inflation).toBeLessThan(series[0].inflation);
  });

  it("empty workspace yields just the baseline entry", () => {
    const series = computeHistorySeries(createDefaultWorkspace());
    expect(series.length).toBe(1);
    expect(series[0].picksCount).toBe(0);
  });

  it("handles null input gracefully", () => {
    const series = computeHistorySeries(null);
    expect(series.length).toBe(1);
  });
});

// ── Target Board + Nominations + Bayesian ceiling (post-Tier-3 follow-on) ──

import {
  NOMINATION_DECAY,
  TARGET_BOARD_MAX,
  TIER_INTEREST_MIN,
  addToTargetBoard,
  clearTargetBoard,
  moveTargetInBoard,
  recordNomination,
  removeFromTargetBoard,
  removeNomination,
  undoLastNomination,
} from "@/lib/draft-logic";

describe("addToTargetBoard", () => {
  it("appends player and auto-applies target tag", () => {
    const ws = createDefaultWorkspace();
    const next = addToTargetBoard(ws, "jeremiyah-love");
    expect(next.targetBoard).toEqual(["jeremiyah-love"]);
    expect(next.tags["jeremiyah-love"]).toBe(TAG_TARGET);
  });

  it("no-op if already on the board", () => {
    const ws = addToTargetBoard(
      createDefaultWorkspace(),
      "jeremiyah-love",
    );
    const again = addToTargetBoard(ws, "jeremiyah-love");
    expect(again.targetBoard.length).toBe(1);
  });

  it("capped at TARGET_BOARD_MAX (6)", () => {
    let ws = createDefaultWorkspace();
    for (let i = 0; i < 8; i++) {
      ws = addToTargetBoard(ws, ws.players[i].id);
    }
    expect(ws.targetBoard.length).toBe(TARGET_BOARD_MAX);
    expect(TARGET_BOARD_MAX).toBe(6);
  });

  it("preserves order in the board array", () => {
    let ws = createDefaultWorkspace();
    ws = addToTargetBoard(ws, "jeremiyah-love");
    ws = addToTargetBoard(ws, "makai-lemon");
    ws = addToTargetBoard(ws, "carnell-tate");
    expect(ws.targetBoard).toEqual([
      "jeremiyah-love",
      "makai-lemon",
      "carnell-tate",
    ]);
  });

  it("empty playerId is a no-op", () => {
    const ws = createDefaultWorkspace();
    expect(addToTargetBoard(ws, "").targetBoard).toEqual([]);
  });
});

describe("removeFromTargetBoard", () => {
  it("removes the player but keeps the target tag", () => {
    let ws = addToTargetBoard(createDefaultWorkspace(), "jeremiyah-love");
    const next = removeFromTargetBoard(ws, "jeremiyah-love");
    expect(next.targetBoard).toEqual([]);
    // Tag stays — the two concepts are independent.
    expect(next.tags["jeremiyah-love"]).toBe(TAG_TARGET);
  });
});

describe("clearTargetBoard", () => {
  it("empties the board but leaves tags alone", () => {
    let ws = addToTargetBoard(createDefaultWorkspace(), "jeremiyah-love");
    ws = addToTargetBoard(ws, "makai-lemon");
    const cleared = clearTargetBoard(ws);
    expect(cleared.targetBoard).toEqual([]);
    expect(cleared.tags["jeremiyah-love"]).toBe(TAG_TARGET);
    expect(cleared.tags["makai-lemon"]).toBe(TAG_TARGET);
  });
});

describe("moveTargetInBoard", () => {
  const build = () => {
    let ws = createDefaultWorkspace();
    ws = addToTargetBoard(ws, "jeremiyah-love");
    ws = addToTargetBoard(ws, "makai-lemon");
    ws = addToTargetBoard(ws, "carnell-tate");
    return ws;
  };

  it("moves a slot up", () => {
    const ws = build();
    const next = moveTargetInBoard(ws, "carnell-tate", "up");
    expect(next.targetBoard).toEqual([
      "jeremiyah-love",
      "carnell-tate",
      "makai-lemon",
    ]);
  });

  it("moves a slot down", () => {
    const ws = build();
    const next = moveTargetInBoard(ws, "jeremiyah-love", "down");
    expect(next.targetBoard).toEqual([
      "makai-lemon",
      "jeremiyah-love",
      "carnell-tate",
    ]);
  });

  it("no-op at boundaries", () => {
    const ws = build();
    expect(moveTargetInBoard(ws, "jeremiyah-love", "up")).toBe(ws);
    expect(moveTargetInBoard(ws, "carnell-tate", "down")).toBe(ws);
  });

  it("no-op for unknown player", () => {
    const ws = build();
    expect(moveTargetInBoard(ws, "ghost", "up")).toBe(ws);
  });
});

describe("computeDraftStats — targetBoardStats", () => {
  it("empty board yields empty totals + idle status", () => {
    const stats = computeDraftStats(createDefaultWorkspace());
    expect(stats.targetBoardStats.slots).toEqual([]);
    expect(stats.targetBoardStats.portfolioStatus).toBe("idle");
  });

  it("sums fair + winBid across undrafted targets", () => {
    let ws = createDefaultWorkspace();
    ws = addToTargetBoard(ws, "jeremiyah-love");
    ws = addToTargetBoard(ws, "makai-lemon");
    const stats = computeDraftStats(ws);
    const tb = stats.targetBoardStats;
    expect(tb.slots.length).toBe(2);
    // At opening: Love fair 135, Lemon fair 90
    expect(tb.totals.fairSum).toBe(225);
    expect(tb.totals.remainingCount).toBe(2);
  });

  it("paid sum only counts targets drafted to me", () => {
    let ws = createDefaultWorkspace();
    ws = addToTargetBoard(ws, "jeremiyah-love");
    ws = addToTargetBoard(ws, "makai-lemon");
    // I grab Love at $60; rival grabs Lemon at $50.
    ws = recordPick(ws, {
      playerId: "jeremiyah-love",
      teamIdx: 0,
      amount: 60,
    });
    ws = recordPick(ws, {
      playerId: "makai-lemon",
      teamIdx: 4,
      amount: 50,
    });
    const stats = computeDraftStats(ws);
    const tb = stats.targetBoardStats;
    expect(tb.totals.mineCount).toBe(1);
    expect(tb.totals.otherCount).toBe(1);
    expect(tb.totals.paidSum).toBe(60);
    expect(tb.totals.remainingCount).toBe(0);
  });

  it("portfolioBuffer = myRemaining − remainingWinBid − nonTargetSlotsLeft × $1", () => {
    let ws = createDefaultWorkspace();
    ws = addToTargetBoard(ws, "jeremiyah-love");
    ws = addToTargetBoard(ws, "makai-lemon");
    const stats = computeDraftStats(ws);
    const tb = stats.targetBoardStats;
    // myRemaining=417, slotsRemaining=6, target count=2, so
    // nonTargetSlotsLeft = 4.  winBids capped by competitor ceiling
    // ~$68 each → winBidSum ~ 2×69 = 138.  Buffer ≈ 417 − ~138 − 4.
    const expected = 417 - tb.totals.remainingWinBid - 4;
    expect(tb.portfolioBuffer).toBe(expected);
    expect(tb.portfolioStatus).toBe("on_track");
  });

  it("flags 'short' when remaining targets exceed remaining $", () => {
    let ws = createDefaultWorkspace();
    // Make myRemaining tiny by starting the user with a $20 budget.
    ws = updateTeam(ws, 0, { initialBudget: 20 });
    ws = addToTargetBoard(ws, "jeremiyah-love");
    ws = addToTargetBoard(ws, "makai-lemon");
    const stats = computeDraftStats(ws);
    expect(stats.targetBoardStats.portfolioStatus).toBe("short");
    expect(stats.targetBoardStats.portfolioBuffer).toBeLessThan(0);
  });
});

// ── Nominations ─────────────────────────────────────────────────────────

describe("recordNomination", () => {
  it("stores playerId + team + snapshot preDraft", () => {
    const ws = createDefaultWorkspace();
    const next = recordNomination(ws, {
      playerId: "jeremiyah-love",
      nominatingTeamIdx: 4,
    });
    expect(next.nominations.length).toBe(1);
    const n = next.nominations[0];
    expect(n.playerId).toBe("jeremiyah-love");
    expect(n.nominatingTeamIdx).toBe(4);
    expect(n.preDraftAtNomination).toBe(135);
    expect(typeof n.ts).toBe("number");
  });

  it("replaces an existing nomination for the same player", () => {
    let ws = recordNomination(createDefaultWorkspace(), {
      playerId: "jeremiyah-love",
      nominatingTeamIdx: 4,
    });
    ws = recordNomination(ws, {
      playerId: "jeremiyah-love",
      nominatingTeamIdx: 5,
    });
    expect(ws.nominations.length).toBe(1);
    expect(ws.nominations[0].nominatingTeamIdx).toBe(5);
  });

  it("no-op with invalid inputs", () => {
    const ws = createDefaultWorkspace();
    expect(
      recordNomination(ws, { playerId: "", nominatingTeamIdx: 0 }).nominations,
    ).toEqual([]);
    expect(
      recordNomination(ws, {
        playerId: "jeremiyah-love",
        nominatingTeamIdx: "bad",
      }).nominations,
    ).toEqual([]);
  });
});

describe("removeNomination / undoLastNomination", () => {
  it("removes a specific logged nomination", () => {
    let ws = recordNomination(createDefaultWorkspace(), {
      playerId: "jeremiyah-love",
      nominatingTeamIdx: 4,
    });
    ws = removeNomination(ws, "jeremiyah-love");
    expect(ws.nominations).toEqual([]);
  });

  it("undoLastNomination pops the newest by ts", async () => {
    let ws = recordNomination(createDefaultWorkspace(), {
      playerId: "jeremiyah-love",
      nominatingTeamIdx: 4,
    });
    await new Promise((r) => setTimeout(r, 2));
    ws = recordNomination(ws, {
      playerId: "makai-lemon",
      nominatingTeamIdx: 5,
    });
    expect(ws.nominations.length).toBe(2);
    const undone = undoLastNomination(ws);
    expect(undone.nominations.length).toBe(1);
    expect(undone.nominations[0].playerId).toBe("jeremiyah-love");
  });
});

describe("computeDraftStats — Bayesian tier interest", () => {
  it("no nominations → every team tierInterest is 1.0 on every tier", () => {
    const stats = computeDraftStats(createDefaultWorkspace());
    for (const t of stats.teamStats) {
      for (const def of TIER_DEFS) {
        expect(t.tierInterest[def.key]).toBe(1);
      }
      expect(t.nominationsLogged).toBe(0);
    }
  });

  it("one S nomination decays the nominator's S-tier interest once", () => {
    const ws = recordNomination(createDefaultWorkspace(), {
      playerId: "jeremiyah-love", // tier S
      nominatingTeamIdx: 4,
    });
    const stats = computeDraftStats(ws);
    expect(stats.teamStats[4].tierInterest.S).toBeCloseTo(
      NOMINATION_DECAY,
      4,
    );
    // Other tiers untouched.
    expect(stats.teamStats[4].tierInterest.A).toBe(1);
    // Other teams untouched.
    expect(stats.teamStats[5].tierInterest.S).toBe(1);
    expect(stats.teamStats[4].nominationsLogged).toBe(1);
  });

  it("multiple nominations stack multiplicatively", () => {
    let ws = createDefaultWorkspace();
    // 3 S-tier noms from team 4: 0.8^3 ≈ 0.512.
    const sPlayers = ws.players.filter((p) => p.preDraft >= 60);
    for (const p of sPlayers.slice(0, 3)) {
      ws = recordNomination(ws, {
        playerId: p.id,
        nominatingTeamIdx: 4,
      });
    }
    const stats = computeDraftStats(ws);
    expect(stats.teamStats[4].tierInterest.S).toBeCloseTo(
      Math.pow(NOMINATION_DECAY, 3),
      4,
    );
  });

  it("tierInterest is floored at TIER_INTEREST_MIN with enough noms", () => {
    // D tier has 28+ players; 0.8^28 ≈ 0.002 which would dip well
    // below the floor without clamping.
    let ws = createDefaultWorkspace();
    const dPlayers = ws.players.filter((p) => p.preDraft <= 2);
    expect(dPlayers.length).toBeGreaterThan(20);
    for (const p of dPlayers) {
      ws = recordNomination(ws, {
        playerId: p.id,
        nominatingTeamIdx: 4,
      });
    }
    const stats = computeDraftStats(ws);
    expect(stats.teamStats[4].tierInterest.D).toBe(TIER_INTEREST_MIN);
  });

  it("bayesianTopCompetitor per player reflects tierInterest", () => {
    // Only ONE rival is wealthy (team 1); the rest are broke.  That
    // makes team 1 the exclusive ceiling-setter, so their decayed
    // tier interest directly drops the Bayesian ceiling.
    let ws = createDefaultWorkspace();
    ws = {
      ...ws,
      teams: ws.teams.map((t, i) => {
        if (i === 0) return t;
        if (i === 1) return { ...t, initialBudget: 400 };
        return { ...t, initialBudget: 0 };
      }),
    };
    ws = recordNomination(ws, {
      playerId: "jeremiyah-love",
      nominatingTeamIdx: 1,
    });
    ws = recordNomination(ws, {
      playerId: "fernando-mendoza",
      nominatingTeamIdx: 1,
    });
    const stats = computeDraftStats(ws);
    const makai = stats.enrichedPlayers.find(
      (p) => p.name === "Makai Lemon",
    );
    expect(stats.topCompetitorMax).toBeGreaterThan(300);
    // Team 1 nominated 2 S players → S interest ≈ 0.64 → Bayesian
    // ceiling ≈ 0.64 × topCompetitorMax.
    expect(makai.bayesianTopCompetitor).toBeLessThan(
      stats.topCompetitorMax,
    );
    expect(makai.bayesianTopCompetitor).toBeCloseTo(
      Math.floor(stats.topCompetitorMax * NOMINATION_DECAY * NOMINATION_DECAY),
      0,
    );
  });

  it("bayesianWinningBid ≤ myWinningBid (tighter ceiling)", () => {
    const ws = recordNomination(createDefaultWorkspace(), {
      playerId: "jeremiyah-love",
      nominatingTeamIdx: 4,
    });
    const stats = computeDraftStats(ws);
    for (const p of stats.enrichedPlayers) {
      if (p.drafted) continue;
      expect(p.bayesianWinningBid).toBeLessThanOrEqual(p.myWinningBid);
    }
  });
});

describe("hydrateWorkspace — targetBoard + nominations roundtrip", () => {
  it("preserves targetBoard order", () => {
    let ws = createDefaultWorkspace();
    ws = addToTargetBoard(ws, "jeremiyah-love");
    ws = addToTargetBoard(ws, "makai-lemon");
    const round = hydrateWorkspace(JSON.parse(JSON.stringify(ws)));
    expect(round.targetBoard).toEqual(["jeremiyah-love", "makai-lemon"]);
  });

  it("truncates targetBoard to TARGET_BOARD_MAX", () => {
    const parsed = {
      version: 1,
      settings: {},
      teams: DEFAULT_TEAMS,
      players: DEFAULT_ROOKIES.map((p) => ({
        id: playerSlug(p.name),
        rank: p.rank,
        name: p.name,
        preDraft: p.preDraft,
      })),
      picks: [],
      targetBoard: [
        "a", "b", "c", "d", "e", "f", "g", "h", // 8 > 6
      ],
    };
    expect(hydrateWorkspace(parsed).targetBoard.length).toBe(
      TARGET_BOARD_MAX,
    );
  });

  it("preserves valid nominations and drops malformed ones", () => {
    const parsed = {
      version: 1,
      settings: {},
      teams: DEFAULT_TEAMS,
      players: DEFAULT_ROOKIES.map((p) => ({
        id: playerSlug(p.name),
        rank: p.rank,
        name: p.name,
        preDraft: p.preDraft,
      })),
      picks: [],
      nominations: [
        { playerId: "jeremiyah-love", nominatingTeamIdx: 4, ts: 1 },
        { playerId: "", nominatingTeamIdx: 4 }, // drop: empty id
        { playerId: "makai-lemon", nominatingTeamIdx: "bad" }, // drop
      ],
    };
    const ws = hydrateWorkspace(parsed);
    expect(ws.nominations.length).toBe(1);
    expect(ws.nominations[0].playerId).toBe("jeremiyah-love");
  });
});

// ── replacePlayerPool / rescaleValuesToBudget ──────────────────────────

import {
  DEFAULT_POSITION_MINS,
  computeDraftReview,
  computeRosterBreakdown,
  draftReviewToCsv,
  replacePlayerPool,
  rescaleValuesToBudget,
} from "@/lib/draft-logic";

describe("rescaleValuesToBudget", () => {
  it("scales a raw value array so its sum matches the target", () => {
    const out = rescaleValuesToBudget([100, 50, 25, 10, 5], 1200);
    expect(out.reduce((s, v) => s + v, 0)).toBeCloseTo(1200, -1);
  });

  it("floors every scaled value at 1 (no unbiddable fillers)", () => {
    const out = rescaleValuesToBudget([1000, 1, 1, 1], 100);
    // Raw #1 dominates; without a floor the 1's would scale to tiny.
    for (const v of out) expect(v).toBeGreaterThanOrEqual(1);
  });

  it("no-op on empty / zero-total input", () => {
    expect(rescaleValuesToBudget([], 1200)).toEqual([]);
    const out = rescaleValuesToBudget([0, 0, 0], 1200);
    expect(out).toEqual([1, 1, 1]);
  });
});

describe("replacePlayerPool", () => {
  it("replaces players and preserves tags that still have a home", () => {
    let ws = createDefaultWorkspace();
    ws = setPlayerTag(ws, "jeremiyah-love", TAG_TARGET);
    ws = setPlayerTag(ws, "drew-allar", TAG_AVOID);
    const { workspace: next, kept, added, dropped } = replacePlayerPool(ws, [
      { name: "Jeremiyah Love", preDraft: 200, pos: "RB" },
      { name: "New Player X", preDraft: 40, pos: "WR" },
      // Note: Drew Allar dropped from the list
    ]);
    expect(next.players.length).toBe(2);
    expect(next.tags["jeremiyah-love"]).toBe(TAG_TARGET);
    // Drew Allar dropped → tag removed.
    expect(next.tags["drew-allar"]).toBeUndefined();
    expect(kept).toBe(1); // Love carried over
    expect(added).toBe(1); // New Player X
    expect(dropped).toBeGreaterThan(0);
  });

  it("preserves Target Board order when players survive", () => {
    let ws = createDefaultWorkspace();
    ws = addToTargetBoard(ws, "jeremiyah-love");
    ws = addToTargetBoard(ws, "makai-lemon");
    ws = addToTargetBoard(ws, "drew-allar");
    const { workspace: next } = replacePlayerPool(ws, [
      { name: "Jeremiyah Love", preDraft: 100 },
      { name: "Makai Lemon", preDraft: 90 },
      // Allar dropped
      { name: "Caleb Douglas", preDraft: 2 },
    ]);
    expect(next.targetBoard).toEqual([
      "jeremiyah-love",
      "makai-lemon",
      // drew-allar dropped
    ]);
  });

  it("retains picks whose player survived + reports orphans", () => {
    let ws = createDefaultWorkspace();
    ws = recordPick(ws, {
      playerId: "jeremiyah-love",
      teamIdx: 0,
      amount: 120,
    });
    ws = recordPick(ws, {
      playerId: "drew-allar",
      teamIdx: 2,
      amount: 1,
    });
    const { workspace: next, orphanedPicks } = replacePlayerPool(ws, [
      { name: "Jeremiyah Love", preDraft: 100 },
    ]);
    expect(next.picks.length).toBe(1);
    expect(next.picks[0].playerId).toBe("jeremiyah-love");
    expect(orphanedPicks.length).toBe(1);
    expect(orphanedPicks[0].playerId).toBe("drew-allar");
  });

  it("carries pos through from the incoming list", () => {
    const ws = createDefaultWorkspace();
    const { workspace: next } = replacePlayerPool(ws, [
      { name: "Jeremiyah Love", preDraft: 100, pos: "RB" },
    ]);
    expect(next.players[0].pos).toBe("RB");
  });

  it("null / empty input returns an empty player list", () => {
    const ws = createDefaultWorkspace();
    const { workspace: next } = replacePlayerPool(ws, null);
    expect(next.players).toEqual([]);
  });

  it("preserves ktcDollar and idpTradeCalcDollar through the field strip", () => {
    const ws = createDefaultWorkspace();
    const { workspace: next } = replacePlayerPool(ws, [
      { name: "WR Rook", preDraft: 30, pos: "WR", ktcDollar: 55 },
      { name: "LB Rook", preDraft: 25, pos: "LB", idpTradeCalcDollar: 48 },
      { name: "Both Vendors", preDraft: 20, pos: "RB", ktcDollar: 35, idpTradeCalcDollar: 12 },
    ]);
    const wr = next.players.find((p) => p.name === "WR Rook");
    const lb = next.players.find((p) => p.name === "LB Rook");
    const both = next.players.find((p) => p.name === "Both Vendors");
    expect(wr.ktcDollar).toBe(55);
    expect(wr.idpTradeCalcDollar).toBeUndefined();
    expect(lb.idpTradeCalcDollar).toBe(48);
    expect(lb.ktcDollar).toBeUndefined();
    expect(both.ktcDollar).toBe(35);
    expect(both.idpTradeCalcDollar).toBe(12);
  });
});

describe("nominationCandidates — vendor split (offense=KTC, IDP=IDPTC)", () => {
  function statsWith(players) {
    // Minimal stats stub — nominationCandidates only reads
    // `enrichedPlayers` and `topCompetitorMax` from stats.
    return { enrichedPlayers: players, topCompetitorMax: 100 };
  }

  it("offense rookie surfaces when KTC overrates vs our board", () => {
    const list = nominationCandidates(
      statsWith([
        { id: "wr-rook", name: "WR Rook", pos: "WR", preDraft: 30, ktcDollar: 50 },
      ]),
    );
    expect(list.length).toBe(1);
    expect(list[0].vendorLabel).toBe("KTC");
    expect(list[0].vendorDollar).toBe(50);
    expect(list[0].gap).toBe(20);
  });

  it("IDP rookie surfaces when IDPTradeCalc overrates vs our board", () => {
    const list = nominationCandidates(
      statsWith([
        { id: "lb-rook", name: "LB Rook", pos: "LB", preDraft: 25, idpTradeCalcDollar: 48 },
      ]),
    );
    expect(list.length).toBe(1);
    expect(list[0].vendorLabel).toBe("IDPTC");
    expect(list[0].vendorDollar).toBe(48);
    expect(list[0].gap).toBe(23);
  });

  it("IDP rookie with only KTC dollar (no IDPTradeCalc) is skipped", () => {
    const list = nominationCandidates(
      statsWith([
        { id: "lb-rook", name: "LB Rook", pos: "LB", preDraft: 25, ktcDollar: 60 },
      ]),
    );
    expect(list.length).toBe(0);
  });

  it("offense rookie with only IDPTradeCalc dollar (no KTC) is skipped", () => {
    const list = nominationCandidates(
      statsWith([
        { id: "wr-rook", name: "WR Rook", pos: "WR", preDraft: 30, idpTradeCalcDollar: 90 },
      ]),
    );
    expect(list.length).toBe(0);
  });

  it("rationale uses the per-row vendor label", () => {
    const list = nominationCandidates(
      statsWith([
        { id: "wr-rook", name: "WR Rook", pos: "WR", preDraft: 30, ktcDollar: 50 },
        { id: "lb-rook", name: "LB Rook", pos: "LB", preDraft: 25, idpTradeCalcDollar: 48 },
      ]),
    );
    const wr = list.find((e) => e.player.name === "WR Rook");
    const lb = list.find((e) => e.player.name === "LB Rook");
    expect(wr.rationale).toContain("KTC values");
    expect(lb.rationale).toContain("IDPTC values");
  });
});

// ── computeDraftReview / draftReviewToCsv ──────────────────────────────

describe("computeDraftReview", () => {
  it("aggregates MY picks + computes portfolio ratio + steals", async () => {
    let ws = createDefaultWorkspace();
    // I snipe Love at a bargain, overpay on Lemon.
    ws = recordPick(ws, {
      playerId: "jeremiyah-love",
      teamIdx: 0,
      amount: 60, // fair is 135 at opening → steal
    });
    // Force a ts gap between picks.
    ws.picks[0].ts = 1;
    ws = recordPick(ws, {
      playerId: "makai-lemon",
      teamIdx: 0,
      amount: 200, // fair is 90 at opening → overpay
    });
    ws.picks[1].ts = 2;
    const review = computeDraftReview(ws);

    expect(review.myPicks.length).toBe(2);
    expect(review.portfolio.paid).toBe(260);
    // portfolio.fairValue uses CURRENT inflatedFair which shifts
    // with inflation, but for this check we just verify ordering:
    expect(review.bestSteal.playerName).toBe("Jeremiyah Love");
    expect(review.worstOverpay.playerName).toBe("Makai Lemon");
  });

  it("per-team rankings include every team with picks, sorted by ratio", () => {
    let ws = createDefaultWorkspace();
    ws = recordPick(ws, {
      playerId: "jeremiyah-love",
      teamIdx: 0,
      amount: 100,
    });
    ws = recordPick(ws, {
      playerId: "makai-lemon",
      teamIdx: 3,
      amount: 150,
    });
    const review = computeDraftReview(ws);
    expect(review.teamRankings.length).toBe(2);
    for (let i = 1; i < review.teamRankings.length; i++) {
      expect(review.teamRankings[i - 1].ratio).toBeGreaterThanOrEqual(
        review.teamRankings[i].ratio,
      );
    }
    expect(review.teamRankings.find((t) => t.isMine)).toBeTruthy();
  });

  it("empty workspace produces safe empties", () => {
    const review = computeDraftReview(createDefaultWorkspace());
    expect(review.myPicks).toEqual([]);
    expect(review.bestSteal).toBeNull();
    expect(review.worstOverpay).toBeNull();
    expect(review.portfolio.paid).toBe(0);
  });

  it("CSV header + body shape; quoting works on commas + quotes", () => {
    let ws = createDefaultWorkspace();
    ws = recordPick(ws, {
      playerId: "jeremiyah-love",
      teamIdx: 0,
      amount: 100,
    });
    const review = computeDraftReview(ws);
    const csv = draftReviewToCsv(review);
    expect(csv.split("\n")[0]).toBe(review.csvHeader.join(","));
    expect(csv).toContain("Jeremiyah Love");
  });

  it("draftReviewToCsv escapes commas/quotes in cells", () => {
    const review = {
      csvHeader: ["Name"],
      csvBody: [['Say "hi"'], ["a,b,c"]],
    };
    const csv = draftReviewToCsv(review);
    expect(csv).toContain('"Say ""hi"""');
    expect(csv).toContain('"a,b,c"');
  });
});

// ── computeRosterBreakdown ─────────────────────────────────────────────

describe("computeRosterBreakdown", () => {
  const playersArray = [
    { displayName: "Josh Allen", position: "QB" },
    { displayName: "Bijan Robinson", position: "RB" },
    { displayName: "Ja'Marr Chase", position: "WR" },
    { displayName: "Travis Kelce", position: "TE" },
    { displayName: "Micah Parsons", position: "LB" },
  ];

  it("counts by position and flags shortages", () => {
    const roster = ["Josh Allen", "Bijan Robinson", "Ja'Marr Chase"];
    const br = computeRosterBreakdown(roster, playersArray);
    expect(br.counts.QB).toBe(1);
    expect(br.counts.RB).toBe(1);
    expect(br.counts.WR).toBe(1);
    // QB min is 3 → short 2; TE min 2 → short 2; etc.
    expect(br.shortages.QB).toBe(2);
    expect(br.shortages.TE).toBe(2);
    expect(br.needPositions).toContain("QB");
    expect(br.needPositions).toContain("TE");
  });

  it("need positions sorted by largest shortage first", () => {
    const roster = [
      "Josh Allen",
      "Bijan Robinson",
      "Ja'Marr Chase",
      "Travis Kelce",
      "Travis Kelce",
    ];
    const br = computeRosterBreakdown(roster, playersArray);
    // Sorted by biggest shortage first.
    const [first, ...rest] = br.needPositions;
    for (const pos of rest) {
      expect(br.shortages[first]).toBeGreaterThanOrEqual(
        br.shortages[pos],
      );
    }
  });

  it("unknown names silently skipped", () => {
    const roster = ["Nobody Real", "Ghost McGhost", "Josh Allen"];
    const br = computeRosterBreakdown(roster, playersArray);
    expect(br.counts.QB).toBe(1);
    expect(br.counts.RB).toBe(0);
  });

  it("uses default position mins when not overridden", () => {
    const br = computeRosterBreakdown([], []);
    expect(br.positionMins).toEqual(DEFAULT_POSITION_MINS);
  });

  it("custom thresholds override defaults", () => {
    const roster = ["Josh Allen"];
    const custom = { QB: 1, RB: 2 };
    const br = computeRosterBreakdown(roster, playersArray, custom);
    // QB is met (1/1), RB is short (0/2).
    expect(br.needPositions).toEqual(["RB"]);
    expect(br.counts.TE).toBeUndefined(); // TE not in custom mins
  });
});
