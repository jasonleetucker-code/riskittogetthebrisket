/**
 * TC-B / TCM-O11, O12, O13, L01 — /trade "Next steps".
 *
 * Deep links into the EXISTING engines carry this trade's team and partner;
 * partner evidence is Manager Scout's own answer for THIS package, fetched
 * only when asked; Save to Trade Desk records exactly what is on the
 * calculator.  Nothing here values a trade or computes a verdict.
 */
import { afterEach, describe, expect, it, vi } from "vitest";
import React from "react";
import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";

import TradeNextActions from "@/components/trade/TradeNextActions";

const P = (name, pos, playerId) => ({ name, pos, assetClass: "offense", playerId });
const SIDES = [
  { label: "A", assets: [P("Give WR", "WR", "11")] },
  { label: "B", assets: [P("Get RB", "RB", "22"), { name: "2027 Mid 1st", pos: "PICK", assetClass: "pick" }] },
];
const BASE = {
  sides: SIDES,
  leagueKey: "dynasty_main",
  myTeam: "Jason",
  mySideIdx: 0,
  sideTeamNames: ["Jason", "Joey"],
  evalState: "complete",
  isFair: false,
  balancerSideLabel: "A",
};

afterEach(() => {
  vi.restoreAllMocks();
});

const hrefOf = (testId) => within(screen.getByTestId(testId)).getByRole("link").getAttribute("href");

describe("TradeNextActions", () => {
  it("links every engine for this team and partner", () => {
    render(<TradeNextActions {...BASE} />);
    expect(hrefOf("trade-next-scan")).toBe("/arbitrage?tool=scan&team=Jason&opponent=Joey");
    expect(hrefOf("trade-next-builder")).toBe("/arbitrage?tool=builder&team=Jason");
    expect(hrefOf("trade-next-best")).toBe("/arbitrage?tool=best&team=Jason");
    expect(hrefOf("trade-next-golden")).toBe("/arbitrage?tool=golden&team=Jason");
    expect(hrefOf("trade-next-scout")).toBe("/trades");
    expect(hrefOf("trade-next-managers")).toBe("/managers");
    expect(hrefOf("trade-next-database")).toBe(
      "/market/trade-database?players=11%2C22&picks=2027+Mid+1st",
    );
    const balance = screen.getByTestId("trade-next-balance");
    expect(balance.getAttribute("data-state")).toBe("suggested");
    expect(within(balance).getByRole("link").getAttribute("href")).toBe("#trade-side-A-balancers");
  });

  it("says what is missing instead of linking a guess", () => {
    render(<TradeNextActions {...BASE} myTeam="" mySideIdx={null} sideTeamNames={[null, null]} />);
    expect(within(screen.getByTestId("trade-next-scan")).queryByRole("link")).toBeNull();
    expect(within(screen.getByTestId("trade-next-builder")).queryByRole("link")).toBeNull();
    expect(screen.getByTestId("trade-next-desk").textContent).toMatch(/Pick your team first/);
    expect(screen.getByTestId("trade-partner-unavailable").textContent).toMatch(/Pick your team first/);
  });

  it("saves exactly this trade to the Trade Desk, source calculator", async () => {
    const fetchMock = vi.fn(async () => ({ ok: true, status: 200, json: async () => ({ items: [] }) }));
    vi.stubGlobal("fetch", fetchMock);
    render(<TradeNextActions {...BASE} />);
    await userEvent.click(screen.getByRole("button", { name: "Save to Trade Desk" }));
    await waitFor(() => expect(screen.getByText("Saved to your Trade Desk")).toBeInTheDocument());
    const [url, init] = fetchMock.mock.calls[0];
    expect(url).toBe("/api/user/trade-desk");
    expect(JSON.parse(init.body)).toEqual({
      leagueKey: "dynasty_main",
      myTeam: "Jason",
      opponent: "Joey",
      source: "calculator",
      send: [{ name: "Give WR", isPick: false, position: "WR" }],
      receive: [
        { name: "Get RB", isPick: false, position: "RB" },
        { name: "2027 Mid 1st", isPick: true },
      ],
    });
    vi.unstubAllGlobals();
  });

  it("fetches partner evidence only when asked, and renders the owner's counts", async () => {
    const evidence = {
      state: "measured",
      tradeCount: 6,
      positionsTheyWouldReceive: [{ position: "WR", receivedBefore: 2, ofPlayersReceived: 9 }],
      picksTheyWouldReceive: null,
      offerShapeForThem: "1-for-2",
      sameShapeBefore: 1,
      tradesWithRequester: 0,
    };
    const fetchMock = vi.fn(async () => ({ ok: true, status: 200, json: async () => evidence }));
    vi.stubGlobal("fetch", fetchMock);
    render(<TradeNextActions {...BASE} />);
    expect(fetchMock).not.toHaveBeenCalled();
    await userEvent.click(screen.getByRole("button", { name: /Show Joey's trade history/ }));
    await waitFor(() => expect(screen.getByText(/Received 2 WR of 9 players acquired by trade/)).toBeInTheDocument());
    // Asked for explicitly, so it is shown open — "in the document" alone also
    // passes for a collapsed <details>, which hid the answer behind a second click.
    expect(screen.getByText(/Received 2 WR of 9 players acquired by trade/).closest("details")).toHaveAttribute("open");
    const [url, init] = fetchMock.mock.calls[0];
    expect(url).toBe("/api/manager-scout/offer-evidence?leagueKey=dynasty_main");
    expect(init.method).toBe("POST");
    expect(JSON.parse(init.body)).toEqual({
      myTeam: "Jason",
      opponent: "Joey",
      theyReceive: [{ name: "Give WR", isPick: false, position: "WR" }],
      theySend: [
        { name: "Get RB", isPick: false, position: "RB" },
        { name: "2027 Mid 1st", isPick: true },
      ],
    });
    expect(screen.getByTestId("trade-partner-evidence").textContent).toMatch(/never a\s+likelihood/);
    vi.unstubAllGlobals();
  });

  it("an unmeasured partner history reads as why, never as zero", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn(async () => ({
        ok: true,
        status: 200,
        json: async () => ({ state: "unavailable", reason: "acquisition_store_missing" }),
      })),
    );
    render(<TradeNextActions {...BASE} />);
    await userEvent.click(screen.getByRole("button", { name: /Show Joey's trade history/ }));
    await waitFor(() =>
      expect(screen.getByText(/trade history is not collected on this server/)).toBeInTheDocument(),
    );
    vi.unstubAllGlobals();
  });
});

describe("ManagerEvidence disclosure default", () => {
  const evidence = {
    state: "measured",
    tradeCount: 6,
    positionsTheyWouldReceive: [{ position: "WR", receivedBefore: 2, ofPlayersReceived: 9 }],
    picksTheyWouldReceive: null,
    offerShapeForThem: "1-for-2",
    sameShapeBefore: 1,
    tradesWithRequester: 0,
  };

  it("stays collapsed on generated-trade cards", async () => {
    const { default: ManagerEvidence } = await import("@/components/trade/ManagerEvidence");
    const { container } = render(<ManagerEvidence evidence={evidence} team="Ed" />);
    const details = container.querySelector("details");
    expect(details).not.toBeNull();
    expect(details).not.toHaveAttribute("open");
  });

  it("opens when the caller rendered it on an explicit request", async () => {
    const { default: ManagerEvidence } = await import("@/components/trade/ManagerEvidence");
    const { container } = render(<ManagerEvidence evidence={evidence} team="Ed" defaultOpen />);
    expect(container.querySelector("details")).toHaveAttribute("open");
  });
});
