// Manager Intelligence Batch F — saved managers on /managers and the scoped
// leaderboards page.
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import React from "react";
import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import ManagersPage from "@/app/managers/page";
import LeaderboardsPage from "@/app/managers/leaderboards/page";
import { PROFILE } from "../fixtures/manager-intel-profile";

function jsonResponse(status, body) {
  return { ok: status >= 200 && status < 300, status, json: async () => body };
}

const ENTRY = {
  userId: PROFILE.manager.userId,
  username: "dynastyfan",
  displayName: "Dynasty Fan",
  previousUsernames: ["oldfan"],
  nameState: "current",
  alerts: true,
  alertState: { seeded: false },
};

function savedPayload(managers) {
  return { managers, count: managers.length, limit: 50 };
}

beforeEach(() => {
  window.localStorage.clear();
  window.history.replaceState(null, "", "/managers");
});

afterEach(() => {
  vi.restoreAllMocks();
});

function backend({ saved = savedPayload([]), onWrite } = {}) {
  let current = saved;
  return vi.fn(async (url, init = {}) => {
    const u = String(url);
    if (u.startsWith("/api/manager-intel/saved/refresh")) {
      return jsonResponse(200, {
        checked: [
          {
            userId: ENTRY.userId,
            displayName: "Dynasty Fan",
            mode: "ok",
            newEvents: [
              { id: "tx:1", kind: "trade", leagueName: "Alpha Dynasty", added: ["Joe"], dropped: [] },
            ],
          },
        ],
        remaining: 0,
      });
    }
    if (u.startsWith("/api/manager-intel/saved")) {
      if (init.method === "POST" || init.method === "DELETE") {
        const out = onWrite ? onWrite(u, init) : null;
        if (out) {
          if (out.status < 300) current = out.body;
          return jsonResponse(out.status, out.body);
        }
      }
      return jsonResponse(200, current);
    }
    return jsonResponse(200, PROFILE);
  });
}

async function lookUp(user) {
  await user.type(screen.getByLabelText("Sleeper username"), "dynastyfan");
  await user.click(screen.getByRole("button", { name: "Look up" }));
  await screen.findByRole("heading", { name: "Dynasty Fan" });
}

describe("Saved managers on /managers", () => {
  it("shows an explicit empty state", async () => {
    global.fetch = backend();
    render(<ManagersPage />);
    expect(await screen.findByText("No saved managers yet")).toBeTruthy();
  });

  it("shows an explicit unavailable state", async () => {
    global.fetch = vi.fn(async () =>
      jsonResponse(503, { error: "feature_disabled", message: "Manager Intelligence is switched off." }),
    );
    render(<ManagersPage />);
    expect(await screen.findByText("Saved managers unavailable")).toBeTruthy();
    expect(screen.getByText("Manager Intelligence is switched off.")).toBeTruthy();
  });

  it("saves the looked-up manager by user id and toggles to Saved", async () => {
    const writes = [];
    global.fetch = backend({
      onWrite: (url, init) => {
        writes.push([init.method, url, init.body]);
        return { status: 201, body: { ...savedPayload([ENTRY]), saved: ENTRY, created: true } };
      },
    });
    const user = userEvent.setup();
    render(<ManagersPage />);
    await lookUp(user);
    const save = await screen.findByRole("button", { name: /^Save manager/ });
    expect(save.getAttribute("aria-pressed")).toBe("false");
    await user.click(save);
    expect(writes).toEqual([
      ["POST", "/api/manager-intel/saved", JSON.stringify({ userId: ENTRY.userId })],
    ]);
    const saved = await screen.findByRole("button", { name: /^Saved/ });
    expect(saved.getAttribute("aria-pressed")).toBe("true");
    // The panel lists it with the former username (a rename keeps the entry).
    expect(screen.getByText(/formerly @oldfan/)).toBeTruthy();
  });

  it("removes a saved manager by id", async () => {
    const writes = [];
    global.fetch = backend({
      saved: savedPayload([ENTRY]),
      onWrite: (url, init) => {
        writes.push([init.method, url]);
        return { status: 200, body: { ...savedPayload([]), removed: true } };
      },
    });
    const user = userEvent.setup();
    render(<ManagersPage />);
    await user.click(await screen.findByRole("button", { name: /^Remove/ }));
    expect(writes).toEqual([
      ["DELETE", `/api/manager-intel/saved?userId=${ENTRY.userId}`],
    ]);
    expect(await screen.findByText("No saved managers yet")).toBeTruthy();
  });

  it("refuses to add past the cap and says why", async () => {
    const full = { managers: [{ ...ENTRY, userId: "999", username: "x" }], count: 50, limit: 50 };
    global.fetch = backend({ saved: full });
    const user = userEvent.setup();
    render(<ManagersPage />);
    await lookUp(user);
    const save = await screen.findByRole("button", { name: /^Save manager/ });
    await waitFor(() => expect(save.disabled).toBe(true));
    expect(screen.getByText(/Saved list full \(50 of 50 saved\)/)).toBeTruthy();
  });

  it("runs the in-app new-activity check and lists what is new", async () => {
    global.fetch = backend({ saved: savedPayload([ENTRY]) });
    const user = userEvent.setup();
    render(<ManagersPage />);
    await user.click(await screen.findByRole("button", { name: "Check for new activity" }));
    const region = await screen.findByRole("region", { name: "New activity" });
    expect(within(region).getByText("Trade in Alpha Dynasty — added Joe")).toBeTruthy();
    const link = screen.getByRole("link", { name: "Leaderboards" });
    expect(link.getAttribute("href")).toBe("/managers/leaderboards?population=saved");
  });

  it("links each readable league to its leaderboard", async () => {
    const profile = {
      ...PROFILE,
      leagues: PROFILE.leagues.map((l, i) => ({
        ...l,
        leagueId: i === 0 ? "1312006700437352448" : l.leagueId,
      })),
    };
    global.fetch = vi.fn(async (url) =>
      jsonResponse(200, String(url).startsWith("/api/manager-intel/saved") ? savedPayload([]) : profile),
    );
    const user = userEvent.setup();
    render(<ManagersPage />);
    await lookUp(user);
    const links = screen.getAllByRole("link", { name: /League leaderboard/ });
    expect(links[0].getAttribute("href")).toBe(
      "/managers/leaderboards?population=league&league=1312006700437352448",
    );
  });
});

const SAVED_BOARDS = {
  population: {
    kind: "saved",
    label: "Your saved managers",
    n: 2,
    withData: 1,
    window: "7d",
  },
  status: "ok",
  rankingRule: "Competition ranking, highest first.",
  note: "Built from each saved manager's last activity read.",
  boards: [
    {
      key: "trades",
      label: "Completed trades (last 7 days)",
      n: 1,
      rows: [{ id: "111", userId: "111", rank: 1, displayName: "Alpha", username: "alpha", value: 0, asOf: Date.UTC(2026, 9, 1, 12) }],
      unranked: [{ id: "222", userId: "222", displayName: "Beta", username: "beta", value: null, reason: "not_yet_read" }],
    },
  ],
};

describe("/managers/leaderboards", () => {
  beforeEach(() => {
    window.history.replaceState(null, "", "/managers/leaderboards");
  });

  it("ranks saved managers and names the population and n", async () => {
    global.fetch = vi.fn(async () => jsonResponse(200, SAVED_BOARDS));
    render(<LeaderboardsPage />);
    expect(
      await screen.findByRole("heading", {
        name: "Your saved managers · 2 managers (1 with recent data)",
      }),
    ).toBeTruthy();
    expect(global.fetch.mock.calls[0][0]).toBe("/api/manager-intel/leaderboard?population=saved");
    const list = screen.getByRole("list", {
      name: "Completed trades (last 7 days) — Your saved managers",
    });
    const items = within(list).getAllByRole("listitem");
    // A real zero is a value; a never-read manager is unranked, not last at 0.
    expect(within(items[0]).getByText("0")).toBeTruthy();
    expect(within(items[1]).getByText("Unranked: not read yet")).toBeTruthy();
    expect(within(items[1]).getAllByText("—")).toHaveLength(2); // no rank, no value
    expect(screen.getByText("1 of 2 ranked")).toBeTruthy();
  });

  it("asks for a league id and reads that league's boards", async () => {
    const leagueBoards = {
      ...SAVED_BOARDS,
      population: {
        kind: "league",
        label: "Current teams in Alleys",
        leagueId: "42",
        season: "2026",
        window: "30d",
        n: 12,
      },
      note: null,
    };
    global.fetch = vi.fn(async (url) =>
      jsonResponse(200, String(url).includes("population=league") ? leagueBoards : SAVED_BOARDS),
    );
    const user = userEvent.setup();
    render(<LeaderboardsPage />);
    await screen.findByRole("heading", { name: /Your saved managers/ });
    await user.click(screen.getByRole("radio", { name: "A league" }));
    expect(screen.getByText("Pick a league")).toBeTruthy();
    await user.type(screen.getByLabelText("Sleeper league id"), "42");
    await user.click(screen.getByRole("button", { name: "Rank this league" }));
    expect(
      await screen.findByRole("heading", { name: "Current teams in Alleys · 12 teams" }),
    ).toBeTruthy();
    expect(global.fetch.mock.calls.at(-1)[0]).toBe(
      "/api/manager-intel/leaderboard?population=league&leagueId=42&window=30d",
    );
    expect(window.location.search).toBe("?population=league&league=42");
  });

  it("deep-links a league population", async () => {
    window.history.replaceState(null, "", "/managers/leaderboards?population=league&league=42");
    global.fetch = vi.fn(async () => jsonResponse(404, { error: "not_found", message: "No Sleeper league with that id." }));
    render(<LeaderboardsPage />);
    expect(await screen.findByText("No Sleeper league with that id.")).toBeTruthy();
    expect(global.fetch.mock.calls[0][0]).toBe(
      "/api/manager-intel/leaderboard?population=league&leagueId=42",
    );
  });

  it("shows an explicit empty population", async () => {
    global.fetch = vi.fn(async () =>
      jsonResponse(200, { ...SAVED_BOARDS, population: { ...SAVED_BOARDS.population, n: 0, withData: 0 } }),
    );
    render(<LeaderboardsPage />);
    expect(await screen.findByText("No saved managers")).toBeTruthy();
  });
});
