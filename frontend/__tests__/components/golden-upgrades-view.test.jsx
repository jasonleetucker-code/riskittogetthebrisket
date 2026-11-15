import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import React from "react";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";

vi.mock("@/lib/trade-share", () => ({ buildShareUrl: () => "/trade?share=x" }));

import GoldenUpgradesView from "@/app/arbitrage/GoldenUpgradesView";

const UPGRADE = {
  owned: { name: "Our LB", position: "LB", boardValue: 3000, marketValue: 4000, market: "IDP Trade Calculator" },
  target: { name: "Their LB", position: "LB", boardValue: 3600, marketValue: 3500, market: "IDP Trade Calculator" },
  opponent: "Them",
  market: "IDP Trade Calculator",
  boardGainPct: 20,
  marketInversionPct: 14.29,
  strength: 14.29,
  lineupImpact: { available: false, reason: "player_not_in_lineup_pool" },
  why: "Our board values Their LB 20.0% above Our LB.",
};

function payload(body) {
  return { ok: true, status: 200, json: async () => body };
}

const body = (call) => JSON.parse(call[1].body);

describe("Golden Upgrades view", () => {
  let originalFetch;
  beforeEach(() => {
    originalFetch = global.fetch;
    window.localStorage.clear();
  });
  afterEach(() => {
    global.fetch = originalFetch;
    vi.restoreAllMocks();
  });

  it("renders each upgrade with both edges, the market and no send action", async () => {
    const user = userEvent.setup();
    global.fetch = vi.fn().mockResolvedValue(
      payload({ action: "recommend_only", upgrades: [UPGRADE], criteria: { status: "PRIOR_UNVALIDATED" } }),
    );
    render(<GoldenUpgradesView myTeam="Us" leagueKey="lg" ownerKey="me" />);
    await user.click(screen.getByRole("button", { name: "Find Golden Upgrades" }));
    expect(await screen.findByText("1 Golden Upgrade found.")).toBeInTheDocument();
    expect(screen.getByText("+20.0%")).toBeInTheDocument();
    expect(screen.getByText("14.3%")).toBeInTheDocument();
    expect(screen.getByText("IDP Trade Calculator prefers yours by")).toBeInTheDocument();
    expect(screen.getByText("3,000 board · 4,000 market")).toBeInTheDocument();
    expect(screen.getByText("Lineup impact unavailable")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Open in Trade Calculator" })).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /send/i })).toBeNull();
    expect(body(global.fetch.mock.calls[0])).toMatchObject({ myTeam: "Us", useTeamContext: true });
  });

  it("EXCLUDE regenerates with the refinement and stores it per surface", async () => {
    const user = userEvent.setup();
    global.fetch = vi
      .fn()
      .mockResolvedValueOnce(payload({ upgrades: [UPGRADE] }))
      .mockResolvedValueOnce(payload({ upgrades: [], noResultReason: "no_inversion_meets_the_thresholds", noResultLabel: "No Golden Upgrade found under current constraints" }));
    render(<GoldenUpgradesView myTeam="Us" leagueKey="lg" ownerKey="me" />);
    await user.click(screen.getByRole("button", { name: "Find Golden Upgrades" }));
    await user.click(
      await screen.findByRole("button", {
        name: "Exclude Our LB from outgoing packages in the upgrade to Their LB",
      }),
    );
    await waitFor(() => expect(global.fetch).toHaveBeenCalledTimes(2));
    expect(body(global.fetch.mock.calls[1]).refinement).toEqual({ lock: [], exclude: ["Our LB"] });
    expect(JSON.parse(window.localStorage.getItem("rit.refinement.v1:me:lg:golden-upgrades:Us"))).toEqual({
      lock: [],
      exclude: ["Our LB"],
    });
    expect(await screen.findByText("No Golden Upgrade found under current constraints")).toBeInTheDocument();
  });

  it("explains an empty result with the server's reason", async () => {
    const user = userEvent.setup();
    global.fetch = vi.fn().mockResolvedValue(
      payload({ upgrades: [], noResultReason: "locked_players_exceed_package_size" }),
    );
    render(<GoldenUpgradesView myTeam="Us" leagueKey="lg" ownerKey="me" />);
    await user.click(screen.getByRole("button", { name: "Find Golden Upgrades" }));
    expect(await screen.findByText(/lock at most one/)).toBeInTheDocument();
  });
});
