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

import { render, screen, waitFor, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { PerfectDraftPanel, bidStanding, planShape } from "@/components/draft/PerfectDraftPanel";

const CONTEXT = {
  contextVersion: "2026-07-30.v1",
  leagueKey: "pd_main",
  valueScale: "rankDerivedValue",
  team: { name: "Alpha", ownerId: "owner-a", rosterId: 1 },
  rosterSize: 58,
  rosterCount: 57,
  openRosterSpots: 1,
  taxiSize: 0,
  taxiSlotsAvailable: 0,
  waiverValues: { WR: 1200, RB: 1100 },
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

const WORKSPACE = { myTeamIdx: 0, teams: [{ name: "Alpha" }, { name: "Beta" }] };

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
