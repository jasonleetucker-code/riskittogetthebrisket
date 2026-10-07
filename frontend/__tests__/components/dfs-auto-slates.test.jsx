import React from "react";
import { cleanup, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import AutoSlates from "@/components/dfs/AutoSlates";

function jsonResponse(status, body) {
  return { ok: status >= 200 && status < 300, status, json: async () => body };
}

beforeEach(() => {
  vi.stubGlobal("fetch", vi.fn());
});

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});

describe("AutoSlates — daily sports (DFS-AUTO-19)", () => {
  it("asks for the selected sport and opens its listed slate with no upload", async () => {
    const calls = [];
    const LIST = {
      sport: "nhl",
      state: "AVAILABLE",
      derivationNote: "Game set is the NHL slate Daily Fantasy Fuel lists for each platform.",
      slates: [
        {
          autoSlateId: "draftkings:nhl:2026:d20261007:listed",
          platform: "draftkings",
          sport: "nhl",
          slateKey: "listed",
          slateDate: "2026-10-07",
          week: null,
          label: "DraftKings NHL · Wed Oct 7 · 3 games",
          lockAt: "2026-10-07T23:30:00+00:00",
          contentHash: "nhlhash",
          summary: { games: 3, players: 66, projected: 64 },
          freshness: { state: "CURRENT", locked: false, ageMinutes: 2, degraded: [] },
        },
      ],
    };
    fetch.mockImplementation(async (url, init) => {
      const u = String(url);
      calls.push({ u, body: init?.body ? JSON.parse(init.body) : null });
      if (u.includes("/auto/slates?")) return jsonResponse(200, LIST);
      if (u.endsWith("/auto/slates/select")) return jsonResponse(201, { snapshotId: "s1", contentHash: "nhlhash" });
      return jsonResponse(404, {});
    });
    const onSelected = vi.fn();
    render(<AutoSlates sport="nhl" platform="draftkings" selectedHash={null} onSelected={onSelected} />);
    expect(await screen.findByText("DraftKings NHL · Wed Oct 7 · 3 games")).toBeInTheDocument();
    expect(calls[0].u).toContain("sport=nhl");
    // No "main" key on a daily sport: the next unlocked listed slate opens by default.
    await waitFor(() => expect(onSelected).toHaveBeenCalledWith({ snapshotId: "s1", contentHash: "nhlhash" }));
    const select = calls.find((c) => c.u.endsWith("/auto/slates/select"));
    expect(select.body).toEqual({ autoSlateId: "draftkings:nhl:2026:d20261007:listed" });
    expect(screen.getByText(/Daily Fantasy Fuel lists/)).toBeInTheDocument();
  });

  it("says plainly when a sport has no automatic path", async () => {
    fetch.mockImplementation(async () =>
      jsonResponse(200, {
        sport: "mma",
        state: "UNAVAILABLE",
        slates: [],
        reason: "Automatic slates are live for NFL, NBA and NHL; this sport still needs its platform file (Advanced).",
      }),
    );
    render(<AutoSlates sport="mma" platform="draftkings" selectedHash={null} onSelected={() => {}} />);
    expect(await screen.findByText(/live for NFL, NBA and NHL/)).toBeInTheDocument();
  });
});
