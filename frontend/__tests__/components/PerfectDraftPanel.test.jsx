/**
 * Perfect Draft panel — what it renders, and what it refuses to render.
 *
 * The panel is an add-on surface on someone else's page, so the most
 * important behaviour is the negative one: on a flag-off, a wrong-league, or
 * a broken response it must VANISH, not render an error banner into the
 * middle of a live draft board.
 *
 * The rest pins that the recommendation is explained in fantasy-football
 * terms — the displaced player by name, a max bid, a net value — rather than
 * as a wall of raw model output.
 */

import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { PerfectDraftPanel, bidStanding, planShape } from "@/components/draft/PerfectDraftPanel";

const CONTEXT = {
  contextVersion: "2026-08-04.v2",
  leagueKey: "pd_main",
  valueScale: "rankDerivedValue",
  team: { name: "Alpha", ownerId: "owner-a", rosterId: 1 },
  rosterSize: 58,
  rosterCount: 57,
  openRosterSpots: 1,
  taxiSize: 0,
  taxiSlotsAvailable: 0,
  waiverValues: { WR: 1200, RB: 1100 },
  waiverLadder: [1200, 1150, 1100, 1050, 1000],
  rosterByPosition: { QB: 5, RB: 1, WR: 9, TE: 7 },
  startersByPosition: { QB: 1, RB: 2, WR: 3, TE: 2, FLEX: 2, SUPER_FLEX: 1 },
  cutLadder: {
    rungs: [
      {
        playerId: "cut1",
        name: "Deep Bench Guy",
        position: "WR",
        effectiveCutCost: 300,
        valueBasis: "board",
      },
      {
        playerId: "cut2",
        name: "Unpriced Body",
        position: "WR",
        effectiveCutCost: 0,
        valueBasis: "assumedWaiver",
      },
    ],
    undroppable: [],
    notes: [],
    unfilledSlotsAtBaseline: 0,
  },
  counts: {},
  unmatchedRosterPlayers: [],
  notes: [],
};

const STATS = {
  myRemaining: 60,
  enrichedPlayers: [
    {
      id: "jeremiyah-love",
      name: "Jeremiyah Love",
      pos: "RB",
      boardValue: 7587,
      inflatedFair: 35,
      preDraft: 35,
      drafted: false,
      tier: "S",
    },
    {
      id: "carnell-tate",
      name: "Carnell Tate",
      pos: "WR",
      boardValue: 5961,
      inflatedFair: 20,
      preDraft: 20,
      drafted: false,
      tier: "A",
    },
    {
      id: "already-gone",
      name: "Already Gone",
      pos: "WR",
      boardValue: 5000,
      inflatedFair: 10,
      preDraft: 10,
      drafted: true,
      tier: "A",
    },
  ],
};

// The REAL workspace shape: `myTeamIdx` lives under `settings`
// (createDefaultWorkspace in lib/draft-logic.js). The fixture used to put it at
// the root, which is the only reason a panel that could never resolve a team in
// the browser passed every test here.
const WORKSPACE = {
  settings: { myTeamIdx: 0 },
  teams: [{ name: "Alpha" }, { name: "Beta" }],
};

function jsonResponse(status, body) {
  return { ok: status >= 200 && status < 300, status, json: async () => body };
}

function okPayload() {
  return {
    teams: [
      { name: "Alpha", ownerId: "owner-a", rosterId: 1, rosterCount: 57 },
      { name: "Beta", ownerId: "owner-b", rosterId: 2, rosterCount: 44 },
    ],
    context: CONTEXT,
    leagueKey: "pd_main",
  };
}

beforeEach(() => {
  vi.stubGlobal("fetch", vi.fn());
  window.localStorage.setItem("next_active_league_v1", "pd_main");
});

afterEach(() => {
  vi.unstubAllGlobals();
  window.localStorage.clear();
});

describe("the recommendation", () => {
  beforeEach(() => {
    fetch.mockResolvedValue(jsonResponse(200, okPayload()));
  });

  it("names the rookies it recommends", async () => {
    render(<PerfectDraftPanel stats={STATS} workspace={WORKSPACE} />);
    const table = await screen.findByRole("table");
    expect(within(table).getByText("Jeremiyah Love")).toBeInTheDocument();
  });

  it("never recommends a rookie another team already bought", async () => {
    render(<PerfectDraftPanel stats={STATS} workspace={WORKSPACE} />);
    await screen.findByRole("table");
    expect(screen.queryByText("Already Gone")).not.toBeInTheDocument();
  });

  it("names the roster player each rookie would displace", async () => {
    render(<PerfectDraftPanel stats={STATS} workspace={WORKSPACE} />);
    // One open roster spot, so the first rookie displaces nobody and the
    // second takes the cheapest rung.
    const table = await screen.findByRole("table");
    expect(within(table).getByText("open spot")).toBeInTheDocument();
    expect(within(table).getByText("Deep Bench Guy")).toBeInTheDocument();
  });

  it("flags a cut whose value the board could not price", async () => {
    const ctx = {
      ...CONTEXT,
      openRosterSpots: 0,
      cutLadder: {
        ...CONTEXT.cutLadder,
        rungs: [CONTEXT.cutLadder.rungs[1], CONTEXT.cutLadder.rungs[0]],
      },
    };
    fetch.mockResolvedValue(jsonResponse(200, { ...okPayload(), context: ctx }));
    render(<PerfectDraftPanel stats={STATS} workspace={WORKSPACE} />);
    const table = await screen.findByRole("table");
    expect(within(table).getByText("Unpriced Body")).toBeInTheDocument();
    expect(within(table).getAllByText("unpriced").length).toBeGreaterThan(0);
  });

  it("shows a max bid and how the live price sits against it", async () => {
    render(<PerfectDraftPanel stats={STATS} workspace={WORKSPACE} />);
    await screen.findByRole("table");
    expect(screen.getByRole("columnheader", { name: /max bid/i })).toBeInTheDocument();
    const badges = screen.getAllByText(/below max|near max|above max/i);
    expect(badges.length).toBeGreaterThan(0);
  });

  it("explains the model in plain language", async () => {
    render(<PerfectDraftPanel stats={STATS} workspace={WORKSPACE} />);
    await screen.findByRole("table");
    expect(
      screen.getByText(/value of the roster player you would likely have to release/i),
    ).toBeInTheDocument();
  });

  it("offers a team selector when the league has more than one team", async () => {
    render(<PerfectDraftPanel stats={STATS} workspace={WORKSPACE} />);
    await screen.findByRole("table");
    const select = screen.getByLabelText("Team to optimize");
    expect(within(select).getByRole("option", { name: "Beta" })).toBeInTheDocument();
  });

  it("offers the three strategy modes", async () => {
    render(<PerfectDraftPanel stats={STATS} workspace={WORKSPACE} />);
    await screen.findByRole("table");
    for (const label of ["Balanced", "Win now", "Long-term"]) {
      expect(screen.getByRole("radio", { name: label })).toBeInTheDocument();
    }
  });
});

describe("it vanishes rather than erroring", () => {
  it("renders nothing when the feature flag is off", async () => {
    fetch.mockResolvedValue(
      jsonResponse(503, { error: "feature_disabled", flag: "perfect_draft" }),
    );
    const { container } = render(<PerfectDraftPanel stats={STATS} workspace={WORKSPACE} />);
    await waitFor(() => expect(container).toBeEmptyDOMElement());
  });

  it("renders nothing when the league's rosters are not loaded", async () => {
    fetch.mockResolvedValue(jsonResponse(503, { error: "data_not_ready" }));
    const { container } = render(<PerfectDraftPanel stats={STATS} workspace={WORKSPACE} />);
    await waitFor(() => expect(container).toBeEmptyDOMElement());
  });

  it("renders nothing when the request fails outright", async () => {
    fetch.mockRejectedValue(new Error("network down"));
    const { container } = render(<PerfectDraftPanel stats={STATS} workspace={WORKSPACE} />);
    await waitFor(() => expect(container).toBeEmptyDOMElement());
  });

  it("never leaks the environment variable name", async () => {
    fetch.mockResolvedValue(
      jsonResponse(503, { error: "feature_disabled", flag: "perfect_draft" }),
    );
    const { container } = render(<PerfectDraftPanel stats={STATS} workspace={WORKSPACE} />);
    await waitFor(() => expect(container).toBeEmptyDOMElement());
    expect(container.textContent).not.toMatch(/RISKIT_FEATURE/);
  });
});

describe("degenerate inputs", () => {
  beforeEach(() => {
    fetch.mockResolvedValue(jsonResponse(200, okPayload()));
  });

  it("says so plainly when no rookie is worth buying", async () => {
    const broke = { ...STATS, myRemaining: 0 };
    render(<PerfectDraftPanel stats={broke} workspace={WORKSPACE} />);
    expect(
      await screen.findByText(/Holding the budget is the better play/i),
    ).toBeInTheDocument();
  });

  it("survives an empty rookie pool", async () => {
    const empty = { ...STATS, enrichedPlayers: [] };
    render(<PerfectDraftPanel stats={empty} workspace={WORKSPACE} />);
    expect(
      await screen.findByText(/Holding the budget is the better play/i),
    ).toBeInTheDocument();
  });
});

describe("mobile rendering", () => {
  beforeEach(() => {
    fetch.mockResolvedValue(jsonResponse(200, okPayload()));
  });

  it("marks the secondary columns to collapse at narrow widths", async () => {
    // jsdom evaluates no media queries, so this asserts the CSS CONTRACT the
    // DataTable emits — the ds-col-hide-* classes the stylesheet acts on.
    render(<PerfectDraftPanel stats={STATS} workspace={WORKSPACE} />);
    await screen.findByRole("table");
    const table = screen.getByRole("table");
    const hidden = table.querySelectorAll(
      "th.ds-col-hide-sm, th.ds-col-hide-md, th.ds-col-hide-lg",
    );
    expect(hidden.length).toBeGreaterThanOrEqual(3);
  });

  it("keeps the decision-critical columns at every width", async () => {
    render(<PerfectDraftPanel stats={STATS} workspace={WORKSPACE} />);
    await screen.findByRole("table");
    for (const name of [/rookie/i, /exp\. cost/i, /max bid/i, /net added/i]) {
      const th = screen.getByRole("columnheader", { name });
      expect(th.className).not.toMatch(/ds-col-hide/);
    }
  });
});

describe("pure helpers", () => {
  it("classifies a live price against the model ceiling", () => {
    expect(bidStanding(10, 20).label).toBe("Below max");
    expect(bidStanding(19, 20).label).toBe("Near max");
    expect(bidStanding(25, 20).label).toBe("Above max");
    expect(bidStanding(10, 0)).toBeNull();
  });

  it("describes a plan's shape in ordinary language", () => {
    expect(planShape({ players: [] })).toBe("no rookies");
    expect(planShape({ players: [{ price: 40 }] })).toBe("a single target");
    expect(planShape({ players: [{ price: 40 }, { price: 5 }] })).toBe("star-focused");
    expect(
      planShape({ players: [{ price: 5 }, { price: 5 }, { price: 5 }, { price: 5 }] }),
    ).toBe("depth-focused");
  });
});

describe("live updating as the auction proceeds", () => {
  // The regression these guard is invisible from the outside unless you check
  // the rendered cut: the roster context is a pre-draft snapshot, so a panel
  // that reads it raw keeps offering the same roster player for release after
  // every purchase, and keeps believing a used-up open spot is free.
  beforeEach(() => {
    fetch.mockResolvedValue(jsonResponse(200, okPayload()));
  });

  // `realizedResults` reads the drafted+mine rows, so a fixture that only bumps
  // the counter would not exercise the "bought so far" line. Add real purchases.
  const withBought = (n, spent) => ({
    ...STATS,
    myRookiesBought: n,
    mySpent: spent,
    totalPicksMade: n,
    rookiePoolSize: 72,
    enrichedPlayers: [
      ...STATS.enrichedPlayers,
      ...Array.from({ length: n }, (_, i) => ({
        id: `bought-${i}`,
        name: `Bought ${i}`,
        pos: "WR",
        boardValue: 4000,
        drafted: true,
        mine: true,
        pick: { amount: Math.round(spent / Math.max(1, n)) },
      })),
    ],
  });

  it("advances the named cut once purchases consume the open spot", async () => {
    // One open spot. With nothing bought, the first recommendation displaces
    // nobody. With one bought, the spot is gone and the cheapest rung is next.
    const { unmount } = render(
      <PerfectDraftPanel stats={withBought(0, 0)} workspace={WORKSPACE} />,
    );
    let table = await screen.findByRole("table");
    expect(within(table).getByText("open spot")).toBeInTheDocument();
    unmount();

    render(<PerfectDraftPanel stats={withBought(1, 20)} workspace={WORKSPACE} />);
    table = await screen.findByRole("table");
    expect(within(table).queryByText("open spot")).not.toBeInTheDocument();
    expect(within(table).getByText("Deep Bench Guy")).toBeInTheDocument();
  });

  it("does not offer a roster player who was already displaced", async () => {
    // Two bought against one open spot: the first rung is spent, so the panel
    // must name the SECOND rung, never "Deep Bench Guy" again.
    render(<PerfectDraftPanel stats={withBought(2, 40)} workspace={WORKSPACE} />);
    const table = await screen.findByRole("table");
    expect(within(table).queryByText("Deep Bench Guy")).not.toBeInTheDocument();
    expect(within(table).getByText("Unpriced Body")).toBeInTheDocument();
  });

  it("reports what has already been bought alongside the remaining plan", async () => {
    render(<PerfectDraftPanel stats={withBought(1, 20)} workspace={WORKSPACE} />);
    await screen.findByRole("table");
    expect(screen.getByText(/Bought so far:/i)).toBeInTheDocument();
    expect(screen.getByText(/The plan below covers what is left/i)).toBeInTheDocument();
  });

  it("labels which phase of the draft the plan describes", async () => {
    const { unmount } = render(
      <PerfectDraftPanel stats={withBought(0, 0)} workspace={WORKSPACE} />,
    );
    await screen.findByRole("table");
    expect(screen.getByText("Opening plan")).toBeInTheDocument();
    unmount();

    // One bought: the open spot is consumed but the ladder is intact, so a
    // remaining plan still renders.
    render(<PerfectDraftPanel stats={withBought(1, 20)} workspace={WORKSPACE} />);
    await screen.findByRole("table");
    expect(screen.getByText("Live — remaining plan")).toBeInTheDocument();
  });

  it("says it updates automatically, with the live spend", async () => {
    render(<PerfectDraftPanel stats={withBought(2, 45)} workspace={WORKSPACE} />);
    await screen.findByRole("table");
    expect(screen.getByText(/Updates automatically/i)).toBeInTheDocument();
    expect(screen.getByText(/2 bought · \$45 spent/i)).toBeInTheDocument();
  });

  it("warns explicitly when there is no modelled roster room left", async () => {
    // Purchases have eaten the open spot and both rungs. "No room" and "nothing
    // is worth buying" read identically to a user and mean opposite things.
    render(<PerfectDraftPanel stats={withBought(5, 90)} workspace={WORKSPACE} />);
    expect(
      await screen.findByText(/No modelled roster room left/i),
    ).toBeInTheDocument();
  });

  it("offers a manual roster refresh for mid-draft trades", async () => {
    render(<PerfectDraftPanel stats={withBought(1, 20)} workspace={WORKSPACE} />);
    await screen.findByRole("table");
    expect(screen.getByRole("button", { name: /refresh roster/i })).toBeInTheDocument();
  });
});

describe("price uncertainty is shown for what it is", () => {
  beforeEach(() => {
    fetch.mockResolvedValue(jsonResponse(200, okPayload()));
  });

  /** The explainer lives behind an InfoTip, which renders its children lazily. */
  async function openExplainer() {
    await screen.findByRole("table");
    fireEvent.click(screen.getByRole("button", { name: /how this is calculated/i }));
  }

  it("says the range is an assumption before any sale is recorded", async () => {
    render(<PerfectDraftPanel stats={STATS} workspace={WORKSPACE} />);
    await openExplainer();
    expect(
      screen.getByText(/price range is a starting assumption/i),
    ).toBeInTheDocument();
  });

  it("says it is measured once this draft has sales to learn from", async () => {
    const withSales = {
      ...STATS,
      tierPriceRatios: { S: [1.1, 0.95, 1.05], A: [] },
      allPriceRatios: [1.1, 0.95, 1.05],
    };
    render(<PerfectDraftPanel stats={withSales} workspace={WORKSPACE} />);
    await openExplainer();
    expect(screen.getByText(/from the 3 sales recorded so far/i)).toBeInTheDocument();
  });

  it("reports what the plan costs if bids run high", async () => {
    render(<PerfectDraftPanel stats={STATS} workspace={WORKSPACE} />);
    await screen.findByRole("table");
    // Spare or short, but never silent — a plan's exposure to bidding above
    // expectation is the number a live bidder actually needs.
    expect(screen.getByText(/if bids run high/i)).toBeInTheDocument();
  });

  it("narrows the band as the room proves itself calm", async () => {
    const bandWidth = (table) => {
      const cell = within(table)
        .getAllByTitle(/Likely range/i)
        .map((el) => el.getAttribute("title"))[0];
      const [lo, hi] = cell.match(/\d+/g).map(Number);
      return hi - lo;
    };

    const { unmount } = render(<PerfectDraftPanel stats={STATS} workspace={WORKSPACE} />);
    const priorWidth = bandWidth(await screen.findByRole("table"));
    unmount();

    const calm = [1.0, 1.01, 0.99, 1.0, 1.02, 0.98];
    render(
      <PerfectDraftPanel
        stats={{ ...STATS, tierPriceRatios: { S: calm }, allPriceRatios: calm }}
        workspace={WORKSPACE}
      />,
    );
    expect(bandWidth(await screen.findByRole("table"))).toBeLessThan(priorWidth);
  });
});


describe("the workspace shape it actually receives", () => {
  beforeEach(() => {
    fetch.mockResolvedValue(jsonResponse(200, okPayload()));
  });

  it("resolves the user's team from settings.myTeamIdx", async () => {
    // The bug this pins: reading `workspace.myTeamIdx` off the root returns
    // undefined, so no team reaches the roster-context request, the server
    // answers `context: null`, and the panel silent-vanishes BEFORE its own
    // team selector renders — unreachable in the browser, green in tests.
    render(
      <PerfectDraftPanel
        stats={STATS}
        workspace={{ settings: { myTeamIdx: 1 }, teams: [{ name: "Alpha" }, { name: "Beta" }] }}
      />,
    );
    await screen.findByRole("table");
    const url = fetch.mock.calls[0][0];
    expect(String(url)).toContain("teamName=Beta");
  });

  it("still renders when a workspace has no settings block at all", async () => {
    render(<PerfectDraftPanel stats={STATS} workspace={{ teams: [{ name: "Alpha" }] }} />);
    expect(await screen.findByRole("table")).toBeInTheDocument();
  });
});

describe("the waiver ladder reaches the solve", () => {
  beforeEach(() => {
    fetch.mockResolvedValue(jsonResponse(200, okPayload()));
  });

  it("shows what the plan gives up on waivers, not just what it releases", async () => {
    render(<PerfectDraftPanel stats={STATS} workspace={WORKSPACE} />);
    await screen.findByRole("table");
    expect(screen.getByText(/off waivers/i)).toBeInTheDocument();
  });
});


describe("positional balance and opponent-aware pricing", () => {
  beforeEach(() => {
    fetch.mockResolvedValue(jsonResponse(200, okPayload()));
  });

  it("names the starting slots this roster cannot fill", async () => {
    // The context has 1 RB against 2 RB starters.
    render(<PerfectDraftPanel stats={STATS} workspace={WORKSPACE} />);
    await screen.findByRole("table");
    expect(screen.getByText(/Short of starters at/i)).toBeInTheDocument();
    expect(screen.getByText(/RB \(1\)/)).toBeInTheDocument();
  });

  it("does not invent a need for a FLEX slot", async () => {
    // FLEX and SUPER_FLEX are slots several positions can fill, not positions
    // anybody can be short of.
    render(<PerfectDraftPanel stats={STATS} workspace={WORKSPACE} />);
    await screen.findByRole("table");
    const line = screen.getByText(/Short of starters at/i).textContent;
    expect(line).not.toMatch(/FLEX/);
  });

  it("says plainly when the roster already covers every slot", async () => {
    const ctx = {
      ...CONTEXT,
      rosterByPosition: { QB: 5, RB: 4, WR: 9, TE: 7 },
    };
    fetch.mockResolvedValue(jsonResponse(200, { ...okPayload(), context: ctx }));
    render(<PerfectDraftPanel stats={STATS} workspace={WORKSPACE} />);
    await screen.findByRole("table");
    expect(screen.getByText(/already covers every starting slot/i)).toBeInTheDocument();
  });

  it("offers a price basis and defaults to fair value", async () => {
    render(<PerfectDraftPanel stats={STATS} workspace={WORKSPACE} />);
    await screen.findByRole("table");
    expect(screen.getByText("Fair value")).toBeInTheDocument();
    expect(screen.getByText("Beat the room")).toBeInTheDocument();
  });
});
