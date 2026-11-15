// /arbitrage restores a Package Builder seed from its own query
// (Manager Intelligence Batch D): `?tool=builder&league=…&opponent=<owner id>
// [&target=…]` opens the builder tab with that team chosen; anything else
// leaves the page exactly as before.
import { afterEach, describe, expect, it, vi } from "vitest";
import React from "react";
import { render, screen } from "@testing-library/react";

vi.mock("@/components/useDynastyData", () => ({
  useDynastyData: () => ({
    loading: false,
    error: "",
    rows: [],
    rawData: {
      sleeper: {
        teams: [
          { name: "My Team", ownerId: "111", players: ["Send Alpha"] },
          {
            name: "Dana's Team",
            ownerId: "735693375101108224",
            players: ["Alpha Back"],
          },
        ],
      },
    },
  }),
}));
vi.mock("@/components/useTeam", () => ({
  useTeam: () => ({
    selectedLeagueKey: "dynasty_main",
    selectedOwnerId: "111",
  }),
}));

import ArbitragePage from "@/app/arbitrage/page";

afterEach(() => {
  window.history.replaceState(null, "", "/");
  window.localStorage.clear();
});

describe("/arbitrage Package Builder seed", () => {
  it("opens the builder with the seeded counterparty and target", async () => {
    window.history.replaceState(
      null,
      "",
      "/arbitrage?tool=builder&league=dynasty_main&opponent=735693375101108224&target=Alpha%20Back",
    );
    render(<ArbitragePage />);
    expect(
      await screen.findByRole("tab", { name: "Package Builder" }),
    ).toHaveAttribute("aria-selected", "true");
    expect(
      await screen.findByText(/trading with Dana's Team, acquiring Alpha Back/),
    ).toBeInTheDocument();
    expect(screen.getByLabelText("From team")).toHaveValue("Dana's Team");
  });

  it("no seed: the default tool, untouched", () => {
    window.history.replaceState(null, "", "/arbitrage");
    render(<ArbitragePage />);
    expect(
      screen.getByRole("tab", { name: "Golden Upgrades" }),
    ).toHaveAttribute("aria-selected", "true");
    expect(
      screen.queryByText(/Pre-filled from Manager Intelligence/),
    ).toBeNull();
  });
});
