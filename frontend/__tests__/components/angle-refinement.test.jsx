import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import React from "react";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";

vi.mock("@/components/useDynastyData", () => ({
  useDynastyData: () => ({
    loading: false,
    error: "",
    rows: [
      { name: "Give Alpha", pos: "WR", rankDerivedValue: 3000, canonicalSites: { ktc: 3100 } },
      { name: "Give Beta", pos: "RB", rankDerivedValue: 2800, canonicalSites: { ktc: 2700 } },
      { name: "Want Zed", pos: "WR", rankDerivedValue: 3500, canonicalSites: { ktc: 3300 } },
    ],
    rawData: {
      sleeper: {
        teams: [
          { name: "My Team", ownerId: "me", players: ["Give Alpha", "Give Beta"] },
          { name: "Other Team", ownerId: "them", players: ["Want Zed"] },
        ],
      },
    },
  }),
}));

vi.mock("@/components/useTeam", () => ({
  useTeam: () => ({ selectedLeagueKey: "dynasty_main", selectedOwnerId: "me" }),
}));

import AnglePage from "@/app/angle/page";

function acquireResponse(players) {
  return {
    ok: true,
    status: 200,
    json: async () => ({
      mode: "acquire",
      acquire: { players: [{ name: "Want Zed", position: "WR" }], size: 1, targets: [] },
      candidates: [
        {
          size: players.length,
          players: players.map((name) => ({ name, position: "WR", my_value: 3000 })),
          my_total: 3000,
          market_total: 3100,
          my_gain_pct: 10,
          market_gain_pct: 1,
          arb_score: 9,
          owner_id: "them",
        },
      ],
      warnings: [],
    }),
  };
}

const body = (call) => JSON.parse(call[1].body);

describe("/angle acquire mode — LOCK / EXCLUDE (C3-CON-03)", () => {
  let originalFetch;
  beforeEach(() => {
    originalFetch = global.fetch;
    window.localStorage.clear();
  });
  afterEach(() => {
    global.fetch = originalFetch;
    vi.restoreAllMocks();
  });

  it("locks an outgoing player and regenerates with the refinement", async () => {
    const user = userEvent.setup();
    global.fetch = vi.fn().mockResolvedValue(acquireResponse(["Give Alpha"]));
    render(<AnglePage />);

    await user.selectOptions(screen.getByLabelText("Your team"), "me");
    await user.selectOptions(screen.getByLabelText("Trade with"), "them");
    await user.click(await screen.findByRole("checkbox", { name: /Want Zed/ }));
    await user.click(screen.getByRole("button", { name: /Find what to give up/ }));
    await waitFor(() => expect(global.fetch).toHaveBeenCalledTimes(1));
    expect(body(global.fetch.mock.calls[0]).refinement).toEqual({ lock: [], exclude: [] });

    await user.click(await screen.findByRole("button", { name: "Lock Give Alpha into every package" }));
    await waitFor(() => expect(global.fetch).toHaveBeenCalledTimes(2));
    expect(body(global.fetch.mock.calls[1])).toMatchObject({
      mode: "acquire",
      refinement: { lock: ["Give Alpha"], exclude: [] },
    });
    expect(await screen.findByRole("button", { name: "Unlock Give Alpha" })).toBeTruthy();

    await user.click(screen.getByRole("button", { name: "Clear refinements" }));
    await waitFor(() => expect(global.fetch).toHaveBeenCalledTimes(3));
    expect(body(global.fetch.mock.calls[2]).refinement).toEqual({ lock: [], exclude: [] });
  });
});
