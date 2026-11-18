// /arbitrage trade tools — 2026-11-16 verified frontend sweep:
//  * Best Offers and Package Builder show the forced roster release(s) each
//    generated trade carries (`rosterCapacity`, src/trade/roster_capacity.py)
//    with their value; unpriced reads "value unknown", missing reads
//    "not checked" — never hidden, never zero.
//  * Package Scan, Golden Upgrades and Best Offers show a sentence for a
//    failed request, with the backend code only as a detail.
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import React from "react";
import { fireEvent, render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";

vi.mock("@/components/useDynastyData", () => ({
  useDynastyData: () => ({
    loading: false,
    error: "",
    rows: [],
    rawData: {
      sleeper: {
        teams: [
          { name: "My Team", ownerId: "me", players: ["Send Alpha"] },
          { name: "Other Team", ownerId: "them", players: ["Target Bob"] },
        ],
      },
    },
  }),
}));

vi.mock("@/components/useTeam", () => ({
  useTeam: () => ({ selectedLeagueKey: "dynasty_main", selectedOwnerId: "me" }),
}));

vi.mock("@/lib/market-arbitrage", async (importOriginal) => ({
  ...(await importOriginal()),
  buildArbitrageRows: () => [],
}));

vi.mock("@/lib/trade-share", () => ({ buildShareUrl: () => "/trade?share=x" }));

import ArbitragePage from "@/app/arbitrage/page";
import BestOffersView from "@/app/arbitrage/BestOffersView";
import GoldenUpgradesView from "@/app/arbitrage/GoldenUpgradesView";
import PackageBuilderView from "@/app/arbitrage/PackageBuilderView";

const ok = (body) => ({ ok: true, status: 200, json: async () => body });
const failure = (status, body) => ({ ok: false, status, json: async () => body });

const FORCED = {
  rosterLimit: 58,
  requiresDrops: true,
  forcedDropsAreUpperBound: false,
  forcedDrops: [
    { playerId: "9", name: "Bench RB", position: "RB", value: 1210.2 },
    { playerId: "Nobody", name: "Nobody", position: "DB", value: null },
  ],
  forcedDropValue: 1210.2,
  unpricedForcedDrops: 1,
};

function bestOffer(rosterCapacity) {
  return {
    team: "Them",
    status: "qualified",
    offer: {
      send: [{ name: "Our WR", position: "WR" }],
      receive: [{ name: "Their RB", position: "RB" }, { name: "Their TE", position: "TE" }],
      packageSize: "1-for-2",
      canonical: { vaAdjustedGap: 700, magnitude: "lean" },
      external: null,
      externalAll: [],
      whyThisHelpsUs: "Helps.",
      whyTheyMayAccept: "Maybe.",
      rankingFactors: {},
      rankingImputations: {},
      score: 0.5,
      rosterCapacity,
    },
  };
}

const PKG = {
  opponent: "Them",
  packageSize: "1-for-2",
  send: [{ name: "Our WR", position: "WR", isPick: false }],
  receive: [
    { name: "Their QB", position: "QB", isPick: false },
    { name: "Their TE", position: "TE", isPick: false },
  ],
  canonical: { vaAdjustedGap: 300, magnitude: "lean" },
  external: null,
  externalAll: [],
  lineupImpact: null,
};

describe("forced roster releases on generated trades", () => {
  let originalFetch;
  beforeEach(() => {
    originalFetch = global.fetch;
    window.localStorage.clear();
  });
  afterEach(() => {
    global.fetch = originalFetch;
    vi.restoreAllMocks();
  });

  it("Best Offers names each forced release and its value", async () => {
    const user = userEvent.setup();
    global.fetch = vi.fn().mockResolvedValue(ok({ opponents: [bestOffer(FORCED)] }));
    render(<BestOffersView myTeam="Us" leagueKey="lg" ownerKey="me" opponentNames={["Them"]} />);
    await user.click(screen.getByRole("button", { name: "Find the best offer for each team" }));
    const note = await screen.findByRole("note", { name: "Roster capacity" });
    expect(note).toHaveTextContent(
      "Forces 2 releases to fit the 58-man limit — 1,210 value released (plus 1 with value unknown, not counted).",
    );
    expect(within(note).getByText("Bench RB (RB) — 1,210 value")).toBeInTheDocument();
    expect(within(note).getByText("Nobody (DB) — value unknown")).toBeInTheDocument();
  });

  it("Best Offers: an unknown requirement reads 'may require a release'", async () => {
    const user = userEvent.setup();
    global.fetch = vi.fn().mockResolvedValue(
      ok({ opponents: [bestOffer({ rosterLimit: 58, requiresDrops: null, forcedDrops: [] })] }),
    );
    render(<BestOffersView myTeam="Us" leagueKey="lg" ownerKey="me" opponentNames={["Them"]} />);
    await user.click(screen.getByRole("button", { name: "Find the best offer for each team" }));
    expect(await screen.findByRole("note", { name: "Roster capacity" })).toHaveTextContent(
      "May require a release (taxi occupancy unknown).",
    );
  });

  it("Best Offers: no capacity block (Asset only) reads 'not checked', never 'fits'", async () => {
    const user = userEvent.setup();
    global.fetch = vi.fn().mockResolvedValue(ok({ opponents: [bestOffer(null)] }));
    render(<BestOffersView myTeam="Us" leagueKey="lg" ownerKey="me" opponentNames={["Them"]} />);
    await user.click(screen.getByRole("button", { name: "Find the best offer for each team" }));
    const note = await screen.findByRole("note", { name: "Roster capacity" });
    expect(note).toHaveTextContent(/not checked/);
    expect(note).not.toHaveTextContent(/no release needed/);
  });

  it("Package Builder names each forced release and its value", async () => {
    const user = userEvent.setup();
    global.fetch = vi.fn().mockResolvedValue(ok({ packages: [{ ...PKG, rosterCapacity: FORCED }] }));
    render(
      <PackageBuilderView
        myTeam="Us"
        leagueKey="lg"
        ownerKey="me"
        teams={[{ name: "Us", players: ["Our WR"] }, { name: "Them", players: ["Their QB", "Their TE"] }]}
      />,
    );
    await user.click(screen.getByRole("button", { name: "Build packages" }));
    const note = await screen.findByRole("note", { name: "Roster capacity" });
    expect(within(note).getByText("Bench RB (RB) — 1,210 value")).toBeInTheDocument();
    expect(within(note).getByText("Nobody (DB) — value unknown")).toBeInTheDocument();
  });

  it("Best Offers: no priced release (forcedDropValue 0.0) is 'released value unknown', never 0", async () => {
    const user = userEvent.setup();
    global.fetch = vi.fn().mockResolvedValue(
      ok({
        opponents: [
          bestOffer({
            ...FORCED,
            forcedDrops: [FORCED.forcedDrops[1]],
            forcedDropValue: 0.0,
            unpricedForcedDrops: 1,
          }),
        ],
      }),
    );
    render(<BestOffersView myTeam="Us" leagueKey="lg" ownerKey="me" opponentNames={["Them"]} />);
    await user.click(screen.getByRole("button", { name: "Find the best offer for each team" }));
    const note = await screen.findByRole("note", { name: "Roster capacity" });
    expect(note).toHaveTextContent(
      "Forces 1 release to fit the 58-man limit — released value unknown (the release is not priced).",
    );
    expect(note).not.toHaveTextContent(/\b0 value released/);
    expect(within(note).getByText("Released")).toBeVisible();
  });

  it("Package Builder: an existing overage is stated, not blamed on the trade", async () => {
    const user = userEvent.setup();
    global.fetch = vi.fn().mockResolvedValue(
      ok({
        packages: [
          {
            ...PKG,
            rosterCapacity: { ...FORCED, certainty: "exact", overLimitBefore: 1, overLimitAfter: 2 },
          },
        ],
      }),
    );
    render(
      <PackageBuilderView
        myTeam="Us"
        leagueKey="lg"
        ownerKey="me"
        teams={[{ name: "Us", players: ["Our WR"] }, { name: "Them", players: ["Their QB", "Their TE"] }]}
      />,
    );
    await user.click(screen.getByRole("button", { name: "Build packages" }));
    const note = await screen.findByRole("note", { name: "Roster capacity" });
    expect(note).toHaveTextContent(/^Needs 2 releases to fit the 58-man limit/);
    expect(note).toHaveTextContent(
      "Your roster is already 1 over the 58-man limit before this trade — 1 release owed with or without it; after it, 2 over.",
    );
  });

  it("Package Scan cards use the same rule, with each release's value", async () => {
    const user = userEvent.setup();
    const trade = {
      give: [{ name: "Send Alpha", position: "WR", modelValue: 3000, ktcValue: 3200 }],
      receive: [
        { name: "Target Bob", position: "RB", modelValue: 2000, ktcValue: 1900 },
        { name: "Target Cy", position: "TE", modelValue: 1500, ktcValue: 1400 },
      ],
      boardDelta: 500,
      ktcDelta: 100,
      arbitrageScore: 9,
      packageSize: "1-for-2",
      marketsUsed: ["ktc"],
      mixedMarket: false,
      counterparty: "Other Team",
      rosterCapacity: FORCED,
      counterpartyRosterCapacity: { rosterLimit: 58, requiresDrops: false, forcedDrops: [], forcedDropValue: 0 },
    };
    global.fetch = vi.fn().mockResolvedValue(ok({ trades: [trade], warnings: [], metadata: {} }));
    render(<ArbitragePage />);
    fireEvent.click(screen.getByRole("tab", { name: "Package Scan" }));
    await user.click(screen.getByRole("button", { name: "Find trade packages" }));
    const mine = await screen.findByRole("note", { name: "Your roster capacity" });
    expect(mine).toHaveTextContent(
      "Your roster: Forces 2 releases to fit the 58-man limit — 1,210 value released (plus 1 with value unknown, not counted).",
    );
    expect(within(mine).getByText("Bench RB (RB) — 1,210 value")).toBeInTheDocument();
    expect(within(mine).getByText("Nobody (DB) — value unknown")).toBeInTheDocument();
    expect(screen.getByRole("note", { name: "Other Team's roster capacity" })).toHaveTextContent(
      "Other Team's roster: Fits Other Team's roster — no release needed.",
    );
    // The retired wording ("must release N: names") is gone.
    expect(screen.queryByText(/must release/)).toBeNull();
  });

  it("Package Scan: a missing capacity block reads 'not checked', never silence", async () => {
    const user = userEvent.setup();
    const trade = {
      give: [{ name: "Send Alpha", position: "WR", modelValue: 3000, ktcValue: 3200 }],
      receive: [{ name: "Target Bob", position: "RB", modelValue: 3400, ktcValue: 3000 }],
      boardDelta: 400,
      ktcDelta: 200,
      arbitrageScore: 12,
      packageSize: "1-for-1",
      marketsUsed: ["ktc"],
      mixedMarket: false,
    };
    global.fetch = vi.fn().mockResolvedValue(ok({ trades: [trade], warnings: [], metadata: {} }));
    render(<ArbitragePage />);
    fireEvent.click(screen.getByRole("tab", { name: "Package Scan" }));
    await user.click(screen.getByRole("button", { name: "Find trade packages" }));
    const mine = await screen.findByRole("note", { name: "Your roster capacity" });
    expect(mine).toHaveTextContent(/not checked/);
    expect(mine).not.toHaveTextContent(/no release needed/);
  });

  it("Package Builder: an unavailable capacity read is said, never 'fits'", async () => {
    const user = userEvent.setup();
    global.fetch = vi.fn().mockResolvedValue(
      ok({ packages: [{ ...PKG, rosterCapacity: { unavailable: "assessment_failed" } }] }),
    );
    render(
      <PackageBuilderView
        myTeam="Us"
        leagueKey="lg"
        ownerKey="me"
        teams={[{ name: "Us", players: ["Our WR"] }, { name: "Them", players: ["Their QB"] }]}
      />,
    );
    await user.click(screen.getByRole("button", { name: "Build packages" }));
    expect(await screen.findByRole("note", { name: "Roster capacity" })).toHaveTextContent(
      /could not be checked .* unknown, not zero/,
    );
  });
});

describe("trade-tool request failures read as sentences", () => {
  let originalFetch;
  beforeEach(() => {
    originalFetch = global.fetch;
    window.localStorage.clear();
  });
  afterEach(() => {
    global.fetch = originalFetch;
    vi.restoreAllMocks();
  });

  async function expectSentence(code, text) {
    const alert = await screen.findByRole("alert");
    expect(alert).toHaveTextContent(text);
    expect(within(alert).getByText(code).tagName).toBe("CODE");
  }

  it("Best Offers: unknown_team", async () => {
    const user = userEvent.setup();
    global.fetch = vi.fn().mockResolvedValue(failure(400, { error: "unknown_team", myTeam: "Us" }));
    render(<BestOffersView myTeam="Us" leagueKey="lg" ownerKey="me" opponentNames={["Them"]} />);
    await user.click(screen.getByRole("button", { name: "Find the best offer for each team" }));
    await expectSentence("unknown_team", "That team is not in this league's rosters — choose your team again.");
  });

  it("Golden Upgrades: data_not_ready", async () => {
    const user = userEvent.setup();
    global.fetch = vi.fn().mockResolvedValue(failure(503, { error: "data_not_ready" }));
    render(<GoldenUpgradesView myTeam="Us" leagueKey="lg" ownerKey="me" />);
    await user.click(screen.getByRole("button", { name: "Find Golden Upgrades" }));
    await expectSentence(
      "data_not_ready",
      "This league's rosters and values are not loaded on the server yet — try again in a moment.",
    );
  });

  it("Package Scan: auth_required", async () => {
    const user = userEvent.setup();
    global.fetch = vi.fn().mockResolvedValue(failure(401, { error: "auth_required" }));
    render(<ArbitragePage />);
    fireEvent.click(screen.getByRole("tab", { name: "Package Scan" }));
    await user.click(screen.getByRole("button", { name: "Find trade packages" }));
    await expectSentence("auth_required", "Sign in to use the trade tools.");
  });

  it("Best Offers: a bridge 503 reads temporarily unavailable, transport text only as detail", async () => {
    const user = userEvent.setup();
    global.fetch = vi.fn().mockResolvedValue(
      failure(503, { error: "Best-offers service unavailable", detail: "This operation was aborted" }),
    );
    render(<BestOffersView myTeam="Us" leagueKey="lg" ownerKey="me" opponentNames={["Them"]} />);
    await user.click(screen.getByRole("button", { name: "Find the best offer for each team" }));
    const alert = await screen.findByRole("alert");
    expect(alert).toHaveTextContent(
      "Best Offers is temporarily unavailable — the server is restarting or did not answer in time. Try again shortly.",
    );
    expect(within(alert).getByTestId("trade-tool-error-detail")).toHaveTextContent(
      "Best-offers service unavailable: This operation was aborted",
    );
  });

  it("Package Scan: a bridge 503 reads temporarily unavailable", async () => {
    const user = userEvent.setup();
    global.fetch = vi.fn().mockResolvedValue(
      failure(503, { error: "Trade finder service unavailable", detail: "fetch failed" }),
    );
    render(<ArbitragePage />);
    fireEvent.click(screen.getByRole("tab", { name: "Package Scan" }));
    await user.click(screen.getByRole("button", { name: "Find trade packages" }));
    const alert = await screen.findByRole("alert");
    expect(alert).toHaveTextContent("Package Scan is temporarily unavailable");
    expect(within(alert).getByTestId("trade-tool-error-detail")).toHaveTextContent("fetch failed");
  });

  it("Golden Upgrades: a request the browser could not send reads unreachable", async () => {
    const user = userEvent.setup();
    global.fetch = vi.fn().mockRejectedValue(new TypeError("Failed to fetch"));
    render(<GoldenUpgradesView myTeam="Us" leagueKey="lg" ownerKey="me" />);
    await user.click(screen.getByRole("button", { name: "Find Golden Upgrades" }));
    const alert = await screen.findByRole("alert");
    expect(alert).toHaveTextContent(
      "Golden Upgrades could not reach the server. Check your connection and try again shortly.",
    );
    expect(within(alert).getByTestId("trade-tool-error-detail")).toHaveTextContent("Failed to fetch");
  });

  it.each(["invalid_refinement", "invalid_numbers"])(
    "Best Offers: an unrecognised 4xx %s says not accepted, never 'Try again'",
    async (code) => {
      const user = userEvent.setup();
      global.fetch = vi.fn().mockResolvedValue(failure(400, { error: code }));
      render(<BestOffersView myTeam="Us" leagueKey="lg" ownerKey="me" opponentNames={["Them"]} />);
      await user.click(screen.getByRole("button", { name: "Find the best offer for each team" }));
      const alert = await screen.findByRole("alert");
      expect(alert).toHaveTextContent("Best Offers did not accept this request (HTTP 400).");
      expect(alert).not.toHaveTextContent(/try again/i);
      expect(within(alert).getByText(code).tagName).toBe("CODE");
    },
  );

  it("Package Scan: an unrecognised 4xx says not accepted, never 'Try again'", async () => {
    const user = userEvent.setup();
    global.fetch = vi.fn().mockResolvedValue(failure(400, { error: "invalid_refinement" }));
    render(<ArbitragePage />);
    fireEvent.click(screen.getByRole("tab", { name: "Package Scan" }));
    await user.click(screen.getByRole("button", { name: "Find trade packages" }));
    const alert = await screen.findByRole("alert");
    expect(alert).toHaveTextContent("Package Scan did not accept this request (HTTP 400).");
    expect(alert).not.toHaveTextContent(/try again/i);
  });

  it("a server sentence is shown as-is with no code detail", async () => {
    const user = userEvent.setup();
    global.fetch = vi.fn().mockResolvedValue(failure(503, { error: "No data loaded." }));
    render(<GoldenUpgradesView myTeam="Us" leagueKey="lg" ownerKey="me" />);
    await user.click(screen.getByRole("button", { name: "Find Golden Upgrades" }));
    const alert = await screen.findByRole("alert");
    expect(alert).toHaveTextContent("No data loaded.");
    expect(alert.querySelector("code")).toBeNull();
  });
});
