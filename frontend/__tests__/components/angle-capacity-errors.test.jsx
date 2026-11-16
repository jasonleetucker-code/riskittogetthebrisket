// /angle (Package Builder): forced roster releases are shown per candidate,
// request failures read as sentences (code only as a detail), and the results
// copy states the SERVER's applied thresholds with the market gate as a
// ceiling.  2026-11-16 verified frontend sweep.
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import React from "react";
import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";

vi.mock("@/components/useDynastyData", () => ({
  useDynastyData: () => ({
    loading: false,
    error: "",
    rows: [
      { name: "Give Alpha", pos: "WR", rankDerivedValue: 3000, canonicalSites: { ktc: 3100 } },
      { name: "Want Zed", pos: "WR", rankDerivedValue: 3500, canonicalSites: { ktc: 3300 } },
    ],
    rawData: {
      sleeper: {
        teams: [
          { name: "My Team", ownerId: "me", players: ["Give Alpha"] },
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

function candidate(name, rosterCapacity) {
  const c = {
    team: "Other Team",
    owner_id: "them",
    size: 1,
    players: [{ name, position: "WR", my_value: 3500, market_value: 3300, market_source: "ktcCrowdTradesSfTep" }],
    my_total: 3500,
    market_total: 3300,
    my_gain_pct: 12,
    market_gain_pct: -1,
    arb_score: 13,
  };
  if (rosterCapacity !== undefined) c.rosterCapacity = rosterCapacity;
  return c;
}

const offerResponse = (candidates, thresholds = { min_my_gain_pct: 5, max_market_gain_pct: 5 }) => ({
  ok: true,
  status: 200,
  json: async () => ({
    mode: "offer",
    offer: { team: "My Team", size: 1, players: [], my_total: 0, market_total: 0 },
    candidates,
    // `null` = the server reported no thresholds block.
    ...(thresholds === null ? {} : { thresholds }),
    warnings: [],
  }),
});

const failure = (status, body) => ({ ok: false, status, json: async () => body });

async function search(user) {
  render(<AnglePage />);
  await user.click(await screen.findByRole("checkbox", { name: /Give Alpha/ }));
  await user.click(screen.getByRole("button", { name: /Find return options/ }));
}

describe("/angle — forced roster releases per candidate", () => {
  let originalFetch;
  beforeEach(() => {
    originalFetch = global.fetch;
    window.localStorage.clear();
  });
  afterEach(() => {
    global.fetch = originalFetch;
    vi.restoreAllMocks();
  });

  it("shows each forced release and its value; an unpriced one reads 'value unknown'", async () => {
    const user = userEvent.setup();
    global.fetch = vi.fn().mockResolvedValue(
      offerResponse([
        candidate("Want Zed", {
          rosterLimit: 58,
          requiresDrops: true,
          forcedDropsAreUpperBound: false,
          forcedDrops: [
            { playerId: "1", name: "Bench WR", position: "WR", value: 812.4 },
            { playerId: "Mystery DL", name: "Mystery DL", position: "DL", value: null },
          ],
          forcedDropValue: 812.4,
          unpricedForcedDrops: 1,
        }),
      ]),
    );
    await search(user);
    const note = await screen.findByRole("note", { name: "Roster capacity" });
    expect(note).toHaveTextContent(
      "Forces 2 releases to fit the 58-man limit — 812 value released (plus 1 with value unknown, not counted).",
    );
    expect(within(note).getByText("Bench WR (WR) — 812 value")).toBeInTheDocument();
    expect(within(note).getByText("Mystery DL (DL) — value unknown")).toBeInTheDocument();
  });

  it("an unknown requirement reads 'may require a release'; a missing block reads 'not checked'", async () => {
    const user = userEvent.setup();
    global.fetch = vi.fn().mockResolvedValue(
      offerResponse([
        candidate("Want Zed", { rosterLimit: 58, requiresDrops: null, forcedDrops: [] }),
        { ...candidate("Want Zed", undefined), players: [{ name: "Other Guy", position: "RB", my_value: 3400, market_value: 3200 }] },
      ]),
    );
    await search(user);
    const notes = await screen.findAllByRole("note", { name: "Roster capacity" });
    const text = notes.map((n) => n.textContent);
    expect(text).toContain("May require a release (taxi occupancy unknown).");
    expect(text.some((t) => /not checked/.test(t))).toBe(true);
    // Neither unknown state may read as "fits".
    expect(text.some((t) => /no release needed/.test(t))).toBe(false);
  });

  it("labels the release list visibly: 'Released' for a determined set, 'Worst case' for a bound", async () => {
    const user = userEvent.setup();
    const drops = [{ playerId: "1", name: "Bench WR", position: "WR", value: 812.4 }];
    global.fetch = vi.fn().mockResolvedValue(
      offerResponse([
        candidate("Want Zed", {
          rosterLimit: 58,
          requiresDrops: true,
          forcedDropsAreUpperBound: false,
          forcedDrops: drops,
          forcedDropValue: 812.4,
          unpricedForcedDrops: 0,
        }),
        {
          ...candidate("Want Zed", {
            rosterLimit: 58,
            requiresDrops: null,
            certainty: "partial",
            forcedDropsAreUpperBound: true,
            forcedDrops: drops,
          }),
          players: [{ name: "Other Guy", position: "RB", my_value: 3400, market_value: 3200 }],
        },
      ]),
    );
    await search(user);
    const notes = await screen.findAllByRole("note", { name: "Roster capacity" });
    // Visible text, not only an accessible name.
    expect(within(notes[0]).getByText("Released")).toBeVisible();
    expect(within(notes[0]).getByRole("list", { name: "Released" })).toBeInTheDocument();
    expect(within(notes[1]).getByText("Worst case")).toBeVisible();
    expect(within(notes[1]).getByRole("list", { name: "Worst case" })).toBeInTheDocument();
  });

  it("no priced release on the real payload (forcedDropValue 0.0) reads 'released value unknown', never 0", async () => {
    const user = userEvent.setup();
    global.fetch = vi.fn().mockResolvedValue(
      offerResponse([
        candidate("Want Zed", {
          rosterLimit: 58,
          requiresDrops: true,
          forcedDropsAreUpperBound: false,
          forcedDrops: [{ playerId: "Mystery DL", name: "Mystery DL", position: "DL", value: null }],
          // roster_capacity.py: `float(sum(priced)) if priced else 0.0`
          forcedDropValue: 0.0,
          unpricedForcedDrops: 1,
        }),
      ]),
    );
    await search(user);
    const note = await screen.findByRole("note", { name: "Roster capacity" });
    expect(note).toHaveTextContent("released value unknown (the release is not priced)");
    expect(note).not.toHaveTextContent(/0 value released/);
  });

  it("an overage the roster owed before the trade is stated, not blamed on the trade", async () => {
    const user = userEvent.setup();
    global.fetch = vi.fn().mockResolvedValue(
      offerResponse([
        candidate("Want Zed", {
          rosterLimit: 58,
          requiresDrops: true,
          certainty: "exact",
          forcedDropsAreUpperBound: false,
          overLimitBefore: 1,
          overLimitAfter: 2,
          forcedDrops: [
            { playerId: "1", name: "Bench WR", position: "WR", value: 812.4 },
            { playerId: "2", name: "Bench TE", position: "TE", value: 400 },
          ],
          forcedDropValue: 1212.4,
          unpricedForcedDrops: 0,
        }),
      ]),
    );
    await search(user);
    const note = await screen.findByRole("note", { name: "Roster capacity" });
    expect(note).toHaveTextContent("Needs 2 releases to fit the 58-man limit — 1,212 value released.");
    expect(note).toHaveTextContent(
      "Your roster is already 1 over the 58-man limit before this trade — 1 release owed with or without it; after it, 2 over.",
    );
    expect(note).not.toHaveTextContent(/Forces 2 releases/);
  });

  it("a trade that fits says so", async () => {
    const user = userEvent.setup();
    global.fetch = vi.fn().mockResolvedValue(
      offerResponse([candidate("Want Zed", { rosterLimit: 58, requiresDrops: false, forcedDrops: [], forcedDropValue: 0 })]),
    );
    await search(user);
    expect(await screen.findByRole("note", { name: "Roster capacity" })).toHaveTextContent(
      "Fits your roster — no release needed.",
    );
  });
});

describe("/angle — request failures read as sentences", () => {
  let originalFetch;
  beforeEach(() => {
    originalFetch = global.fetch;
    window.localStorage.clear();
  });
  afterEach(() => {
    global.fetch = originalFetch;
    vi.restoreAllMocks();
  });

  it.each([
    [401, "auth_required", "Sign in to use the trade tools."],
    [400, "unknown_team", "That team is not in this league's rosters — choose your team again."],
    [503, "data_not_ready", "This league's rosters and values are not loaded on the server yet — try again in a moment."],
  ])("HTTP %s %s shows a message with the code only as a detail", async (status, code, text) => {
    const user = userEvent.setup();
    global.fetch = vi.fn().mockResolvedValue(failure(status, { error: code }));
    await search(user);
    const alert = await screen.findByRole("alert");
    expect(alert).toHaveTextContent("Couldn't find packages");
    expect(alert).toHaveTextContent(text);
    // The code survives only inside the detail element, never as the message.
    expect(within(alert).getByText(code).tagName).toBe("CODE");
  });

  it("a bridge 503 (backend restarting / timed out) reads temporarily unavailable, transport text as detail", async () => {
    const user = userEvent.setup();
    global.fetch = vi.fn().mockResolvedValue(
      failure(503, { error: "Angle packages service unavailable", detail: "fetch failed" }),
    );
    await search(user);
    const alert = await screen.findByRole("alert");
    expect(alert).toHaveTextContent(
      "Package Builder is temporarily unavailable — the server is restarting or did not answer in time. Try again shortly.",
    );
    // The technical text survives only as the detail.
    expect(within(alert).getByTestId("trade-tool-error-detail")).toHaveTextContent(
      "(details: Angle packages service unavailable: fetch failed)",
    );
  });

  it("a request the browser could not send reads unreachable, not 'Failed to fetch'", async () => {
    const user = userEvent.setup();
    global.fetch = vi.fn().mockRejectedValue(new TypeError("Failed to fetch"));
    await search(user);
    const alert = await screen.findByRole("alert");
    expect(alert).toHaveTextContent(
      "Package Builder could not reach the server. Check your connection and try again shortly.",
    );
    expect(within(alert).getByTestId("trade-tool-error-detail")).toHaveTextContent("Failed to fetch");
  });

  it("an unrecognised deterministic 4xx says the request was not accepted, never 'Try again'", async () => {
    const user = userEvent.setup();
    global.fetch = vi.fn().mockResolvedValue(failure(400, { error: "invalid_numbers" }));
    await search(user);
    const alert = await screen.findByRole("alert");
    expect(alert).toHaveTextContent("Package Builder did not accept this request (HTTP 400).");
    expect(alert).not.toHaveTextContent(/try again/i);
    expect(within(alert).getByText("invalid_numbers").tagName).toBe("CODE");
  });

  it("the server's own sentence is shown as-is", async () => {
    const user = userEvent.setup();
    global.fetch = vi.fn().mockResolvedValue(
      failure(503, { error: "No data loaded. Angle requires live player data." }),
    );
    await search(user);
    expect(await screen.findByRole("alert")).toHaveTextContent("No data loaded. Angle requires live player data.");
  });
});

describe("/angle — thresholds are the server's, the market gate a ceiling", () => {
  let originalFetch;
  beforeEach(() => {
    originalFetch = global.fetch;
    window.localStorage.clear();
  });
  afterEach(() => {
    global.fetch = originalFetch;
    vi.restoreAllMocks();
  });

  it("states the applied thresholds, not the live inputs, and never '±'", async () => {
    const user = userEvent.setup();
    // The form still holds its defaults (5 / 5); the server reports 8 / 2.
    global.fetch = vi.fn().mockResolvedValue(
      offerResponse([candidate("Want Zed", { rosterLimit: 58, requiresDrops: false, forcedDrops: [] })], {
        min_my_gain_pct: 8,
        max_market_gain_pct: 2,
      }),
    );
    await search(user);
    expect(
      await screen.findByText(
        "Each package gains at least +8% on your board, and on the market the other side consults you receive at most +2% more than you give (a ceiling only — the market gap can be lower).",
      ),
    ).toBeInTheDocument();
    expect(screen.queryByText(/±/)).toBeNull();
    expect(screen.queryByText(/stays within/)).toBeNull();
  });

  it("the empty state also uses the applied thresholds", async () => {
    const user = userEvent.setup();
    global.fetch = vi.fn().mockResolvedValue(offerResponse([], { min_my_gain_pct: 9, max_market_gain_pct: 1 }));
    await search(user);
    expect(
      await screen.findByText(/^Nothing gains at least \+9% on your board with a market gap of at most \+1%/),
    ).toBeInTheDocument();
  });

  it("missing thresholds name no number rather than the form's", async () => {
    const user = userEvent.setup();
    global.fetch = vi.fn().mockResolvedValue(offerResponse([], null));
    await search(user);
    expect(await screen.findByText(/the server did not report their values/)).toBeInTheDocument();
    expect(screen.queryByText(/clears \+5%/)).toBeNull();
  });
});
