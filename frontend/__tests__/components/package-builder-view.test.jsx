import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import React from "react";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";

vi.mock("@/lib/trade-share", () => ({ buildShareUrl: () => "/trade?share=x" }));

import PackageBuilderView from "@/app/arbitrage/PackageBuilderView";
import { buildRequest } from "@/lib/package-builder";

const TEAMS = [
  { name: "Us", players: ["Our WR", "Our RB"] },
  { name: "Them", players: ["Their QB", "Their WR"] },
];

const PKG = {
  opponent: "Them",
  packageSize: "1-for-1",
  send: [{ name: "Our WR", position: "WR", isPick: false }],
  receive: [{ name: "Their QB", position: "QB", isPick: false }],
  canonical: { vaAdjustedGap: 300, magnitude: "lean" },
  external: null,
  externalAll: [
    { calculator: "k", label: "KTC Market", coverage: "complete", opponentMarginPct: -2.5, result: "loss" },
  ],
  confidence: "moderate",
  lineupImpact: null,
};

const ok = (body) => ({ ok: true, status: 200, json: async () => body });
const body = (call) => JSON.parse(call[1].body);

describe("Package Builder view", () => {
  let originalFetch;
  beforeEach(() => {
    originalFetch = global.fetch;
    window.localStorage.clear();
  });
  afterEach(() => {
    global.fetch = originalFetch;
    vi.restoreAllMocks();
  });

  it("sends the request the user described and renders packages without a send action", async () => {
    const user = userEvent.setup();
    global.fetch = vi.fn().mockResolvedValue(
      ok({ action: "recommend_only", request: { opponent: "Them" }, packages: [PKG] }),
    );
    render(<PackageBuilderView myTeam="Us" leagueKey="lg" ownerKey="me" teams={TEAMS} />);
    await user.type(screen.getByLabelText("Player or pick you want (optional)"), "Their QB");
    await user.click(screen.getByRole("button", { name: "QB" }));
    await user.click(screen.getByLabelText("Allow draft picks"));
    await user.click(screen.getByRole("button", { name: "Build packages" }));
    expect(await screen.findByText("1 package found with Them.")).toBeInTheDocument();
    expect(body(global.fetch.mock.calls[0])).toMatchObject({
      myTeam: "Us",
      target: "Their QB",
      returnPositions: ["QB"],
      allowPicks: true,
      evidence: "any",
      maxPlayersPerSide: 3,
    });
    expect(screen.getByText("No calculator shows them even")).toBeInTheDocument();
    expect(screen.getByText("KTC Market: them -2.5% (loss for them)")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Open in Trade Calculator" })).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /^send/i })).toBeNull();
    expect(screen.getByRole("button", { name: "QB" })).toHaveAttribute("aria-pressed", "true");
  });

  it("EXCLUDE on a package asset regenerates with the refinement", async () => {
    const user = userEvent.setup();
    global.fetch = vi
      .fn()
      .mockResolvedValueOnce(ok({ packages: [PKG] }))
      .mockResolvedValueOnce(
        ok({ packages: [], noResultReason: "all_outgoing_assets_constrained", noResultLabel: "No package found under current constraints" }),
      );
    render(<PackageBuilderView myTeam="Us" leagueKey="lg" ownerKey="me" teams={TEAMS} />);
    await user.click(screen.getByRole("button", { name: "Build packages" }));
    await user.click(
      await screen.findByRole("button", { name: "Exclude Our WR from outgoing packages in package 1" }),
    );
    await waitFor(() => expect(global.fetch).toHaveBeenCalledTimes(2));
    expect(body(global.fetch.mock.calls[1]).refinement).toEqual({ lock: [], exclude: ["Our WR"] });
    expect(await screen.findByText("No package found under current constraints")).toBeInTheDocument();
    expect(screen.getByText("Every asset you offered is protected or excluded.")).toBeInTheDocument();
  });

  it("omits empty choices so the server reads them as any", () => {
    const req = buildRequest({
      myTeam: "Us",
      leagueKey: "",
      target: "  ",
      opponent: "",
      outgoing: [],
      positions: [],
      maxSide: 2,
      allowPicks: false,
      evidence: "external",
      useTeamContext: false,
      refinement: { lock: [], exclude: [], skip: ["x"] },
    });
    expect(req).toEqual({
      myTeam: "Us",
      maxPlayersPerSide: 2,
      allowPicks: false,
      evidence: "external",
      useTeamContext: false,
      refinement: { lock: [], exclude: [] },
    });
  });
});
