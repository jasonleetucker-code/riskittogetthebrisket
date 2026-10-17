/**
 * TC-A — the ROS Fit panel on /trade reads the ACTIVE league, never the
 * default one.  It fetched /api/public/league/rosTradeDeadline with no
 * leagueKey (the route then answers for the registry default) and cached one
 * answer for every league (feature matrix TCM-K13).
 */
import { describe, it, expect, vi, afterEach } from "vitest";
import React from "react";
import { cleanup, render, waitFor } from "@testing-library/react";

const mod = await import("@/components/RosTradeFitPanel");
const RosTradeFitPanel = mod.default;

afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
});

describe("RosTradeFitPanel league scoping", () => {
  it("builds the league-scoped URL", () => {
    expect(mod.rosTradeDeadlineUrl("dynasty_new")).toBe(
      "/api/public/league/rosTradeDeadline?leagueKey=dynasty_new",
    );
    expect(mod.rosTradeDeadlineUrl("")).toBe("/api/public/league/rosTradeDeadline");
  });

  it("fetches directions for the league it is given, one cache per league", async () => {
    const spy = vi
      .spyOn(globalThis, "fetch")
      .mockResolvedValue({ ok: true, json: async () => ({ teams: [], players: [] }) });
    const sides = [{ label: "A", assets: [] }, { label: "B", assets: [] }];
    render(<RosTradeFitPanel sides={sides} settings={{}} leagueKey="league_x" />);
    await waitFor(() =>
      expect(spy.mock.calls.map((c) => c[0])).toContain(
        "/api/public/league/rosTradeDeadline?leagueKey=league_x",
      ),
    );
    cleanup();
    render(<RosTradeFitPanel sides={sides} settings={{}} leagueKey="league_y" />);
    await waitFor(() =>
      expect(spy.mock.calls.map((c) => c[0])).toContain(
        "/api/public/league/rosTradeDeadline?leagueKey=league_y",
      ),
    );
  });

  it("/trade passes the active league", async () => {
    const fs = await import("node:fs");
    const path = await import("node:path");
    const src = fs.readFileSync(path.resolve(__dirname, "../../app/trade/page.jsx"), "utf8");
    expect(src).toMatch(/<RosTradeFitPanel[^>]*leagueKey=\{selectedLeagueKey \|\| ""\}/);
  });
});
