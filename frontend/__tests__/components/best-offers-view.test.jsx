import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import React from "react";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";

vi.mock("@/lib/trade-share", () => ({ buildShareUrl: () => "/trade?share=x" }));

import BestOffersView from "@/app/arbitrage/BestOffersView";

function payload(cards) {
  return {
    ok: true,
    status: 200,
    json: async () => ({
      action: "recommend_only",
      rankingMethod: { status: "PRIOR_UNVALIDATED" },
      opponents: cards,
    }),
  };
}

const QUALIFIED = {
  team: "Them",
  status: "qualified",
  posture: "PUSH",
  offer: {
    send: [{ name: "Our WR", position: "WR" }],
    receive: [{ name: "Their RB", position: "RB" }],
    packageSize: "1-for-1",
    canonical: { vaAdjustedGap: 1000, magnitude: "stretch" },
    external: { label: "KTC Market", opponentMarginPct: 4.17, result: "win" },
    externalAll: [
      {
        calculator: "ktc",
        label: "KTC Market",
        coverage: "complete",
        opponentMarginPct: 4.17,
        result: "win",
        qualifies: true,
      },
      { calculator: "idptc", label: "IDP Trade Calculator", coverage: "incomplete" },
    ],
    whyThisHelpsUs: "A clear win on our board.",
    whyTheyMayAccept: "KTC Market has them ahead.",
    confidence: "moderate",
    caveats: ["Ranking is a declared prior (PRIOR_UNVALIDATED), not a validated model."],
    rankingFactors: { mutualBalance: 0.42, calculatorDivergence: 0.1, lineupImpact: null },
    rankingImputations: { lineupImpact: -0.25 },
    score: 0.6,
    outgoingAlsoOfferedTo: { "Our WR": 3 },
  },
};

const NO_RESULT = {
  team: "Other",
  status: "no_result",
  noResultLabel: "No qualifying trade found",
  noResultDetail: "No package is a clear win for you on the canonical board.",
};

const body = (call) => JSON.parse(call[1].body);

describe("Best offer by opponent view", () => {
  let originalFetch;
  beforeEach(() => {
    originalFetch = global.fetch;
    window.localStorage.clear();
  });
  afterEach(() => {
    global.fetch = originalFetch;
    vi.restoreAllMocks();
  });

  it("renders one card per opponent with both verdicts, reasons and no send action", async () => {
    const user = userEvent.setup();
    global.fetch = vi.fn().mockResolvedValue(payload([QUALIFIED, NO_RESULT]));
    render(<BestOffersView myTeam="Us" leagueKey="lg" ownerKey="me" opponentNames={["Them", "Other"]} />);
    await user.click(screen.getByRole("button", { name: "Find the best offer for each team" }));

    expect(await screen.findByRole("heading", { name: "Them" })).toBeInTheDocument();
    expect(screen.getByText("1 of 2 teams have a qualifying offer.")).toBeInTheDocument();
    expect(screen.getByText("+1,000")).toBeInTheDocument();
    expect(screen.getByText("+4.2%")).toBeInTheDocument();
    expect(screen.getByText("IDP Trade Calculator: does not price every asset")).toBeInTheDocument();
    expect(screen.getByText("Our WR also headlines 3 other offers")).toBeInTheDocument();
    expect(screen.getByText("No qualifying trade found")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Open in Trade Calculator" })).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /send/i })).toBeNull();
    expect(body(global.fetch.mock.calls[0])).toMatchObject({ myTeam: "Us", useTeamContext: true });
  });

  it("shows the opponent's trade history as counts, or why it is missing", async () => {
    const user = userEvent.setup();
    const withHistory = {
      ...QUALIFIED,
      offer: {
        ...QUALIFIED.offer,
        managerEvidence: {
          state: "measured",
          tradeCount: 5,
          positionsTheyWouldReceive: [{ position: "WR", receivedBefore: 2, ofPlayersReceived: 6 }],
          picksTheyWouldReceive: null,
          offerShapeForThem: "even",
          sameShapeBefore: 3,
          tradesWithRequester: 0,
          unresolvedPositionReceived: 0,
        },
      },
    };
    const noHistory = {
      ...QUALIFIED,
      team: "Other",
      offer: {
        ...QUALIFIED.offer,
        managerEvidence: { state: "insufficient_sample", reason: "no_completed_trades_observed" },
      },
    };
    global.fetch = vi.fn().mockResolvedValue(payload([withHistory, noHistory]));
    render(<BestOffersView myTeam="Us" leagueKey="lg" ownerKey="me" opponentNames={["Them", "Other"]} />);
    await user.click(screen.getByRole("button", { name: "Find the best offer for each team" }));

    expect(await screen.findByText("Them: trade history")).toBeInTheDocument();
    expect(screen.getByText("Received 2 WR of 6 players acquired by trade")).toBeInTheDocument();
    expect(screen.getByText("3 of 5 trades had this shape for them (even)")).toBeInTheDocument();
    expect(screen.getByText("0 trades completed with you")).toBeInTheDocument();
    expect(screen.getByText("Manager history: no completed trades on record.")).toBeInTheDocument();
  });

  it("LOCK on a card regenerates only that opponent with its refinement", async () => {
    const user = userEvent.setup();
    global.fetch = vi
      .fn()
      .mockResolvedValueOnce(payload([QUALIFIED, NO_RESULT]))
      .mockResolvedValueOnce(payload([{ ...QUALIFIED }]));
    render(<BestOffersView myTeam="Us" leagueKey="lg" ownerKey="me" opponentNames={["Them", "Other"]} />);
    await user.click(screen.getByRole("button", { name: "Find the best offer for each team" }));
    await user.click(await screen.findByRole("button", { name: "Lock Our WR into every package in the Them offer" }));
    await waitFor(() => expect(global.fetch).toHaveBeenCalledTimes(2));
    expect(body(global.fetch.mock.calls[1])).toMatchObject({
      opponents: ["Them"],
      refinementByOpponent: { Them: { lock: ["Our WR"], exclude: [] } },
    });
    expect(
      JSON.parse(window.localStorage.getItem("rit.refinement.v1:me:lg:best-offers:Us|Them")),
    ).toEqual({ lock: ["Our WR"], exclude: [] });
  });

  it("a saved card refinement travels with the full scan", async () => {
    const user = userEvent.setup();
    window.localStorage.setItem(
      "rit.refinement.v1:me:lg:best-offers:Us|Them",
      JSON.stringify({ lock: [], exclude: ["Our WR"] }),
    );
    global.fetch = vi.fn().mockResolvedValue(payload([NO_RESULT]));
    render(<BestOffersView myTeam="Us" leagueKey="lg" ownerKey="me" opponentNames={["Them", "Other"]} />);
    await user.click(screen.getByRole("button", { name: "Find the best offer for each team" }));
    await waitFor(() => expect(global.fetch).toHaveBeenCalledTimes(1));
    expect(body(global.fetch.mock.calls[0]).refinementByOpponent).toEqual({
      Them: { lock: [], exclude: ["Our WR"] },
    });
  });

  it("switching to Asset only re-scans in that mode", async () => {
    const user = userEvent.setup();
    global.fetch = vi.fn().mockResolvedValue(payload([QUALIFIED]));
    render(<BestOffersView myTeam="Us" leagueKey="lg" ownerKey="me" opponentNames={["Them"]} />);
    await user.click(screen.getByRole("button", { name: "Find the best offer for each team" }));
    await screen.findByRole("heading", { name: "Them" });
    await user.click(screen.getByRole("radio", { name: "Asset only" }));
    await waitFor(() => expect(global.fetch).toHaveBeenCalledTimes(2));
    expect(body(global.fetch.mock.calls[1]).useTeamContext).toBe(false);
  });

  it("shows a contrary complete verdict and every ranking factor", async () => {
    const user = userEvent.setup();
    const contrary = {
      ...QUALIFIED,
      offer: {
        ...QUALIFIED.offer,
        externalAll: [
          {
            calculator: "ktc",
            label: "KTC Market",
            coverage: "complete",
            opponentMarginPct: -8.7,
            result: "loss",
          },
          {
            calculator: "idptc",
            label: "IDP Trade Calculator",
            coverage: "complete",
            opponentMarginPct: 32.5,
            result: "win",
            qualifies: true,
          },
        ],
      },
    };
    global.fetch = vi.fn().mockResolvedValue(payload([contrary]));
    render(<BestOffersView myTeam="Us" leagueKey="lg" ownerKey="me" opponentNames={["Them"]} />);
    await user.click(screen.getByRole("button", { name: "Find the best offer for each team" }));
    expect(await screen.findByText("KTC Market: them -8.7% (loss for them)")).toBeInTheDocument();
    expect(screen.getByText("IDP Trade Calculator: them +32.5% (win for them)")).toBeInTheDocument();
    expect(screen.getByText("How this offer ranked")).toBeInTheDocument();
    expect(screen.getByText("Board vs calculator disagreement (cost)")).toBeInTheDocument();
    expect(screen.getByText(/ranked as -0.25, the worst known/)).toBeInTheDocument();
    expect(screen.getByText("0.600")).toBeInTheDocument();
  });

  it("a team name with spaces still labels its card", async () => {
    const user = userEvent.setup();
    global.fetch = vi.fn().mockResolvedValue(payload([{ ...QUALIFIED, team: "The Big Team" }]));
    render(<BestOffersView myTeam="Us" leagueKey="lg" ownerKey="me" opponentNames={["The Big Team"]} />);
    await user.click(screen.getByRole("button", { name: "Find the best offer for each team" }));
    expect(await screen.findByRole("article", { name: "The Big Team" })).toBeInTheDocument();
  });

  it("a response for the previous team never lands after the team changes", async () => {
    const user = userEvent.setup();
    let resolveFirst;
    global.fetch = vi.fn().mockImplementationOnce(
      () => new Promise((resolve) => { resolveFirst = resolve; }),
    );
    const { rerender } = render(
      <BestOffersView myTeam="Us" leagueKey="lg" ownerKey="me" opponentNames={["Them"]} />,
    );
    await user.click(screen.getByRole("button", { name: "Find the best offer for each team" }));
    rerender(<BestOffersView myTeam="Other" leagueKey="lg" ownerKey="me" opponentNames={["Them"]} />);
    resolveFirst(payload([QUALIFIED]));
    await new Promise((r) => setTimeout(r, 20));
    expect(screen.queryByRole("heading", { name: "Them" })).toBeNull();
  });
});
