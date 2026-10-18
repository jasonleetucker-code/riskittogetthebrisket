// /arbitrage page order and shared discovery request (owner directive
// 2026-10-18): tools first with Golden Upgrades the default, the research
// table below them (collapsed), one discovery request reused by every view.
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import React from "react";
import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";

vi.mock("@/components/useDynastyData", () => ({
  useDynastyData: () => ({
    loading: false,
    error: "",
    rows: [
      {
        name: "Deep LB",
        pos: "LB",
        assetClass: "idp",
        canonicalConsensusRank: 400,
        rank: 400,
        rankDerivedValue: 1800,
        canonicalSites: { idpTradeCalc: 800 },
      },
      {
        name: "Good LB",
        pos: "LB",
        assetClass: "idp",
        canonicalConsensusRank: 90,
        rank: 90,
        rankDerivedValue: 4200,
        canonicalSites: { idpTradeCalc: 2000 },
      },
    ],
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
vi.mock("@/lib/trade-share", () => ({ buildShareUrl: () => "/trade" }));

import ArbitragePage, { DEFAULT_TOOL, TOOL_TABS } from "@/app/arbitrage/page";

const ok = (body) => ({ ok: true, status: 200, json: async () => body });
const body = (call) => JSON.parse(call[1].body);
const DEFAULT_DISCOVERY = {
  targetQuality: "top250",
  playersToTarget: "both",
  sort: "most_impactful",
};

describe("/arbitrage page order", () => {
  let originalFetch;
  beforeEach(() => {
    originalFetch = global.fetch;
    window.localStorage.clear();
  });
  afterEach(() => {
    global.fetch = originalFetch;
    vi.restoreAllMocks();
  });

  it("puts the five tools first, in the owner's order, with Golden Upgrades selected", () => {
    render(<ArbitragePage />);
    const tabs = screen.getAllByRole("tab").map((t) => t.textContent);
    expect(tabs).toEqual([
      "Golden Upgrades",
      "Package Scan",
      "Best Offer by Opponent",
      "Package Builder",
      "Trade Desk",
    ]);
    expect(TOOL_TABS[0].id).toBe(DEFAULT_TOOL);
    expect(screen.getByRole("tab", { name: "Golden Upgrades" })).toHaveAttribute(
      "aria-selected",
      "true",
    );
    expect(screen.getByRole("button", { name: "Find Golden Upgrades" })).toBeInTheDocument();
  });

  it("renders no research table before the tools; it sits below, collapsed", () => {
    render(<ArbitragePage />);
    expect(screen.queryByRole("table")).toBeNull();
    const tablist = screen.getByRole("tablist");
    const research = screen.getByRole("button", { name: /Player-level market research/ });
    // The tool navigation precedes the research section in document order.
    expect(tablist.compareDocumentPosition(research) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
  });

  it("keeps Package Scan reachable with its existing controls", () => {
    render(<ArbitragePage />);
    fireEvent.click(screen.getByRole("tab", { name: "Package Scan" }));
    expect(screen.getByRole("button", { name: "Find trade packages" })).toBeInTheDocument();
    expect(screen.getByText("Package scan ready")).toBeInTheDocument();
  });

  it("sends the same default discovery request from Golden Upgrades and Package Scan", async () => {
    const user = userEvent.setup();
    global.fetch = vi
      .fn()
      .mockResolvedValueOnce(ok({ upgrades: [] }))
      .mockResolvedValueOnce(ok({ trades: [], metadata: {} }));
    render(<ArbitragePage />);
    await user.click(screen.getByRole("button", { name: "Find Golden Upgrades" }));
    await waitFor(() => expect(global.fetch).toHaveBeenCalledTimes(1));
    expect(body(global.fetch.mock.calls[0]).discovery).toEqual(DEFAULT_DISCOVERY);
    fireEvent.click(screen.getByRole("tab", { name: "Package Scan" }));
    await user.click(screen.getByRole("button", { name: "Find trade packages" }));
    await waitFor(() => expect(global.fetch).toHaveBeenCalledTimes(2));
    expect(global.fetch.mock.calls[1][0]).toBe("/api/trade/finder");
    expect(body(global.fetch.mock.calls[1]).discovery).toEqual(DEFAULT_DISCOVERY);
  });

  it("a filter change re-runs Golden Upgrades with the new Target Quality", async () => {
    const user = userEvent.setup();
    global.fetch = vi.fn().mockResolvedValue(ok({ upgrades: [] }));
    render(<ArbitragePage />);
    await user.click(screen.getByRole("button", { name: "Find Golden Upgrades" }));
    await waitFor(() => expect(global.fetch).toHaveBeenCalledTimes(1));
    await user.selectOptions(screen.getByLabelText("Target quality"), "top100");
    await waitFor(() => expect(global.fetch).toHaveBeenCalledTimes(2));
    expect(body(global.fetch.mock.calls[1]).discovery.targetQuality).toBe("top100");
  });

  it("an empty filtered Golden result says so and expands in one click", async () => {
    const user = userEvent.setup();
    global.fetch = vi
      .fn()
      .mockResolvedValueOnce(
        ok({
          upgrades: [],
          noResultReason: "no_upgrade_within_target_quality",
          noResultLabel: "No Golden Upgrade found",
          noResultDetail: "No legitimate Golden Upgrade brings back a Top 250 player. 3 at Top 500; 9 at All Players.",
          discovery: { broaderAvailability: { top500: 3, all: 9 } },
        }),
      )
      .mockResolvedValueOnce(ok({ upgrades: [] }));
    render(<ArbitragePage />);
    await user.click(screen.getByRole("button", { name: "Find Golden Upgrades" }));
    expect(await screen.findByText(/brings back a Top 250 player/)).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Search Top 500 (3 found)" }));
    await waitFor(() => expect(global.fetch).toHaveBeenCalledTimes(2));
    expect(body(global.fetch.mock.calls[1]).discovery.targetQuality).toBe("top500");
  });

  it("the research table defaults to Top 250 and absolute opportunity", async () => {
    const user = userEvent.setup();
    render(<ArbitragePage />);
    await user.click(screen.getByRole("button", { name: /Player-level market research/ }));
    const table = await screen.findByRole("table");
    expect(within(table).getByText("Good LB")).toBeInTheDocument();
    expect(within(table).queryByText("Deep LB")).toBeNull();
    // The wide table scrolls inside its own region, never the page.
    expect(table.parentElement.className).toMatch(/tableScroll/);
  });
});
