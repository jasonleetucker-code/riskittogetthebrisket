// TC-B / TCM-O11 — /trade "Next steps" deep-links into /arbitrage with
// ?tool=&team=&opponent=.  The link and this page's reader share ONE owner
// (lib/trade-next-actions.js): a valid tool opens that tab, a known team is
// selected, a team this league does not have is dropped, never guessed.
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import React from "react";
import { render, screen, waitFor } from "@testing-library/react";

vi.mock("@/components/useDynastyData", () => ({
  useDynastyData: () => ({
    loading: false,
    error: "",
    rows: [],
    rawData: {
      sleeper: {
        teams: [
          { name: "My Team", ownerId: "me", players: [] },
          { name: "Other Team", ownerId: "them", players: [] },
        ],
      },
    },
  }),
}));
vi.mock("@/components/useTeam", () => ({
  useTeam: () => ({ selectedLeagueKey: "dynasty_main", selectedOwnerId: "me" }),
}));
vi.mock("@/lib/trade-share", () => ({ buildShareUrl: () => "/trade" }));

import ArbitragePage, { TOOL_TABS } from "@/app/arbitrage/page";
import { ARBITRAGE_TOOL_IDS, arbitrageHref } from "@/lib/trade-next-actions";

function visit(href) {
  window.history.pushState(null, "", href);
}

describe("/arbitrage deep links from /trade", () => {
  beforeEach(() => {
    window.localStorage.clear();
    global.fetch = vi.fn(async () => ({ ok: false, status: 404, json: async () => ({}) }));
  });
  afterEach(() => {
    window.history.pushState(null, "", "/");
    vi.restoreAllMocks();
  });

  it("the link owner knows exactly this page's tools", () => {
    expect(ARBITRAGE_TOOL_IDS).toEqual(TOOL_TABS.map((t) => t.id));
  });

  it("opens the linked tool for the linked team", async () => {
    visit(arbitrageHref("builder", { team: "Other Team" }));
    render(<ArbitragePage />);
    await waitFor(() =>
      expect(screen.getByRole("tab", { name: "Package Builder" })).toHaveAttribute(
        "aria-selected",
        "true",
      ),
    );
    expect(screen.getByRole("combobox", { name: /Your team/i })).toHaveValue("Other Team");
  });

  it("selects the linked opponent on Package Scan", async () => {
    visit(arbitrageHref("scan", { team: "My Team", opponent: "Other Team" }));
    render(<ArbitragePage />);
    await waitFor(() =>
      expect(screen.getByRole("tab", { name: "Package Scan" })).toHaveAttribute(
        "aria-selected",
        "true",
      ),
    );
    expect(screen.getByRole("combobox", { name: /Opponent/i })).toHaveValue("Other Team");
  });

  it("drops a team this league does not have and an unknown tool", async () => {
    visit("/arbitrage?tool=nonsense&team=Nobody");
    render(<ArbitragePage />);
    expect(screen.getByRole("tab", { name: "Golden Upgrades" })).toHaveAttribute(
      "aria-selected",
      "true",
    );
    // Falls back to the user's own team, never the unknown name.
    expect(screen.getByRole("combobox", { name: /Your team/i })).toHaveValue("My Team");
  });
});
