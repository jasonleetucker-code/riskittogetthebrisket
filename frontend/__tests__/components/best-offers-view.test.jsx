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
      { calculator: "ktc", label: "KTC Market", coverage: "complete" },
      { calculator: "idptc", label: "IDP Trade Calculator", coverage: "incomplete" },
    ],
    whyThisHelpsUs: "A clear win on our board.",
    whyTheyMayAccept: "KTC Market has them ahead.",
    confidence: "moderate",
    caveats: ["Ranking is a declared prior (PRIOR_UNVALIDATED), not a validated model."],
    rankingFactors: {},
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

  it("LOCK on a card regenerates only that opponent with its refinement", async () => {
    const user = userEvent.setup();
    global.fetch = vi
      .fn()
      .mockResolvedValueOnce(payload([QUALIFIED, NO_RESULT]))
      .mockResolvedValueOnce(payload([{ ...QUALIFIED }]));
    render(<BestOffersView myTeam="Us" leagueKey="lg" ownerKey="me" opponentNames={["Them", "Other"]} />);
    await user.click(screen.getByRole("button", { name: "Find the best offer for each team" }));
    await user.click(await screen.findByRole("button", { name: "Lock Our WR into every package" }));
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
});
