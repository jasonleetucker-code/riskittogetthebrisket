// The /waivers bid desk (FaabRecommendation) — two verified defects from the
// 2026-11-16 sweep, pinned at the render level against the real wire shape
// of POST /api/waiver/faab-recommend.
//
// 1. MISSING IS NEVER ZERO (or another number): the "Your remaining FAAB"
//    tile in the league-history disclosure printed the LEAGUE BUDGET when
//    the team's balance was unknown ("$100 · league budget" reads as "you
//    have $100").  It now follows FaabHeaderStat's rule — "—" + "balance not
//    reported" — and prefers the desk's own `faabBudget` block
//    (src/trade/waiver.py::faab_budget_block), the balance every bid on the
//    desk was capped at.
// 2. The rival table dropped the backend's `contestProbability` and
//    re-sorted by the estimated bid alone, so a rival who rarely bids read
//    as the top threat.  The live engine
//    (src/trade/faab_engine.py::rival_expected_bids) already returns rivals
//    in its threat order (bid x chance they bid); the table now keeps that
//    order and shows the chance.

import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { render, screen, within } from "@testing-library/react";

import FaabRecommendation, { yourFaabTile } from "@/components/waivers/FaabRecommendation";

function mockDesk(json) {
  vi.stubGlobal(
    "fetch",
    vi.fn().mockResolvedValue({ ok: true, json: async () => json }),
  );
}

beforeEach(() => vi.restoreAllMocks());
afterEach(() => vi.unstubAllGlobals());

const BASE = {
  bids: { recommended: 6, conservative: 3, aggressive: 9, maxRational: 30, clearing: 5 },
  confidence: "medium",
  factors: [],
  warnings: [],
};

const ANALYTICS = {
  leagueBudget: 100,
  leagueAvgWinningBid: 4,
  leagueMedianWinningBid: 1,
  totalBidsAnalyzed: 300,
};

function renderDesk({ selectedTeam = { ownerId: "me", name: "Me" }, leagueFaab = ANALYTICS } = {}) {
  return render(
    <FaabRecommendation
      addPlayer={{ name: "Jaylen Waddle", pos: "WR" }}
      dropPlayer={null}
      leagueKey="dynasty_main"
      ownerId="me"
      selectedTeam={selectedTeam}
      leagueFaab={leagueFaab}
    />,
  );
}

async function yourFaab() {
  const el = (await screen.findByText("Your remaining FAAB")).closest(".ds-stat");
  return {
    value: el.querySelector(".ds-stat__value").textContent,
    meta: el.querySelector(".ds-stat__meta")?.textContent ?? null,
  };
}

describe("Your remaining FAAB — an unknown balance is never the league budget", () => {
  it("desk says the balance is unknown: '—' + 'balance not reported', not $100", async () => {
    mockDesk({
      ...BASE,
      bids: { ...BASE.bids, recommended: null, conservative: null, aggressive: null, maxRational: null },
      faabBudget: { state: "unknown", balance: null, originalBudget: 100, bidsWithheld: true },
    });
    renderDesk();
    const tile = await yourFaab();
    expect(tile.value).toBe("—");
    expect(tile.meta).toBe("balance not reported");
    expect(tile.value).not.toBe("$100");
    expect(tile.meta).not.toMatch(/league budget/);
  });

  it("no faabBudget and no roster balance: still unknown, never the budget", async () => {
    mockDesk(BASE);
    renderDesk({ selectedTeam: { ownerId: "me", name: "Me" } });
    const tile = await yourFaab();
    expect(tile.value).toBe("—");
    expect(tile.meta).toBe("balance not reported");
  });

  it("the desk's known balance wins and is shown against its original budget", async () => {
    mockDesk({
      ...BASE,
      faabBudget: { state: "known", balance: 37, originalBudget: 100, bidsWithheld: false, source: "roster" },
    });
    // A stale client-side figure must not override what the bids were capped at.
    renderDesk({ selectedTeam: { ownerId: "me", name: "Me", faabRemaining: 63 } });
    const tile = await yourFaab();
    expect(tile.value).toBe("$37");
    expect(tile.meta).toBe("37% of $100");
  });

  it("the desk's 'unknown' wins over a client-side balance", async () => {
    mockDesk({ ...BASE, faabBudget: { state: "unknown", balance: null, originalBudget: 100 } });
    renderDesk({ selectedTeam: { ownerId: "me", name: "Me", faabRemaining: 63 } });
    const tile = await yourFaab();
    expect(tile.value).toBe("—");
    expect(tile.meta).toBe("balance not reported");
  });

  it("an older desk without faabBudget falls back to the roster balance (regression)", async () => {
    mockDesk(BASE);
    renderDesk({ selectedTeam: { ownerId: "me", name: "Me", faabRemaining: 63 } });
    const tile = await yourFaab();
    expect(tile.value).toBe("$63");
    expect(tile.meta).toBe("63% of $100");
  });

  it("a known $0 balance is a measured $0, not unknown", async () => {
    mockDesk({ ...BASE, faabBudget: { state: "known", balance: 0, originalBudget: 100 } });
    renderDesk();
    const tile = await yourFaab();
    expect(tile.value).toBe("$0");
    expect(tile.meta).toBe("0% of $100");
  });
});

describe("yourFaabTile (display parts only)", () => {
  it("covers every state without inventing a number", () => {
    expect(yourFaabTile({ faabBudget: null, selectedTeam: null, leagueBudget: 100 })).toEqual({
      value: "—",
      meta: "select a team",
    });
    expect(
      yourFaabTile({ faabBudget: { state: "known", balance: 25 }, selectedTeam: null, leagueBudget: null }),
    ).toEqual({ value: "$25", meta: null });
    // A "known" block that carries no number is still not a number.
    expect(
      yourFaabTile({ faabBudget: { state: "known", balance: null }, selectedTeam: {}, leagueBudget: 100 }),
    ).toEqual({ value: "—", meta: "balance not reported" });
    // An unrecognised block is ignored, not trusted.
    expect(
      yourFaabTile({ faabBudget: { state: "maybe" }, selectedTeam: { faabRemaining: 40 }, leagueBudget: 100 }),
    ).toEqual({ value: "$40", meta: "40% of $100" });
  });
});

// ── Rivals ──────────────────────────────────────────────────────────

function rival(o) {
  return {
    faabRemaining: 80,
    needLevel: "neutral",
    aggression: 1,
    lowSample: false,
    balanceUnknown: false,
    ...o,
  };
}

function contention(perOpponent) {
  return {
    ...BASE,
    contention: { clearing: 5, topRival: 60, perOpponent, estimateOnly: true, notes: [], skipped: false },
  };
}

// The engine's own order: expBid x contestProbability = 27, 16, 6.
const THREAT_ORDERED = [
  rival({ ownerId: "a", teamName: "Always Bids", expBid: 30, contestProbability: 0.9 }),
  rival({ ownerId: "c", teamName: "Often Bids", expBid: 20, contestProbability: 0.8 }),
  rival({ ownerId: "b", teamName: "Rarely Bids", expBid: 60, contestProbability: 0.1 }),
];

async function rivalTable() {
  return screen.findByRole("table", { name: /Estimated rival bids/i });
}

function bodyRows(table) {
  return within(table).getAllByRole("row").slice(1);
}

describe("rival contention — the backend's contest probability and order", () => {
  it("keeps the recommender's threat order instead of re-sorting by the bid", async () => {
    mockDesk(contention(THREAT_ORDERED));
    renderDesk();
    const table = await rivalTable();
    const names = bodyRows(table).map((r) => within(r).getAllByRole("cell")[0].textContent);
    expect(names[0]).toMatch(/Always Bids/);
    expect(names[1]).toMatch(/Often Bids/);
    // The big-but-rare bidder is NOT first.
    expect(names[2]).toMatch(/Rarely Bids/);
  });

  it("shows the chance each rival bids beside the estimated bid", async () => {
    mockDesk(contention(THREAT_ORDERED));
    renderDesk();
    const table = await rivalTable();
    expect(within(table).getByRole("columnheader", { name: /Chance they bid/ })).toBeInTheDocument();
    const rare = bodyRows(table).find((r) => r.textContent.includes("Rarely Bids"));
    expect(rare.textContent).toContain("$60");
    expect(rare.textContent).toContain("10%");
    const always = bodyRows(table).find((r) => r.textContent.includes("Always Bids"));
    expect(always.textContent).toContain("90%");
  });

  it("names the order it keeps, and the top-rival tile says it is a bid IF they bid", async () => {
    mockDesk(contention(THREAT_ORDERED));
    renderDesk();
    const table = await rivalTable();
    expect(table).toHaveAccessibleName(/threat order/i);
    const tile = screen.getByText("Projected top rival").closest(".ds-stat");
    expect(within(tile).getByText("$60")).toBeInTheDocument();
    expect(within(tile).getByText("highest bid if they bid, of 3 rivals")).toBeInTheDocument();
  });

  it("a row missing its probability shows '—', never 0%", async () => {
    mockDesk(
      contention([
        THREAT_ORDERED[0],
        rival({ ownerId: "x", teamName: "No Read", expBid: 12, contestProbability: null }),
      ]),
    );
    renderDesk();
    const table = await rivalTable();
    const row = bodyRows(table).find((r) => r.textContent.includes("No Read"));
    expect(row.textContent).not.toContain("0%");
    expect(within(row).getAllByRole("cell")[2].textContent).toBe("—");
  });

  it("an unstated aggression is '—', never the neutral 1.00×", async () => {
    mockDesk(
      contention([rival({ ownerId: "a", teamName: "Agg Unknown", expBid: 10, contestProbability: 0.5, aggression: null })]),
    );
    renderDesk();
    const table = await rivalTable();
    const row = bodyRows(table).find((r) => r.textContent.includes("Agg Unknown"));
    expect(row.textContent).not.toContain("1.00×");
  });

  it("a legacy payload without the probability keeps highest-bid-first (regression)", async () => {
    mockDesk(
      contention([
        rival({ ownerId: "l", teamName: "Low", expBid: 12 }),
        rival({ ownerId: "t", teamName: "Top", expBid: 40 }),
      ]),
    );
    renderDesk();
    const table = await rivalTable();
    expect(within(table).queryByRole("columnheader", { name: /Chance they bid/ })).toBeNull();
    const names = bodyRows(table).map((r) => within(r).getAllByRole("cell")[0].textContent);
    expect(names[0]).toMatch(/Top/);
    expect(names[1]).toMatch(/Low/);
  });
});
