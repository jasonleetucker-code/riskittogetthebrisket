/**
 * PerfectWaiversPanel (C7-WAIV-01) — display of the server-solved plan.
 *
 * The plan is solved by src/trade/perfect_waivers.py; this panel formats it.
 * These pin: the request it sends (league + team, never guessed), the plan
 * table with each add beside the release it replaces, the stop explanation,
 * the unknown-budget and not-proven-optimal states, unpriced/protected
 * disclosure, failures as stated states, and the /waivers wiring (lazy,
 * per-panel Suspense, ResilientSection recovery="reload", not next/dynamic).
 */
import { readFileSync } from "node:fs";
import path from "node:path";
import { afterEach, describe, expect, it, vi } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";

import PerfectWaiversPanel from "@/components/waivers/PerfectWaiversPanel";

function plan(overrides = {}) {
  return {
    version: "perfect-waivers/2026-10-08.v1",
    leagueKey: "main",
    advisoryOnly: true,
    team: { ownerId: "me", name: "Mine" },
    plan: {
      moves: [
        {
          add: {
            playerId: "fa1",
            name: "Free TE",
            position: "TE",
            value: 2600,
            bid: { recommended: 12 },
          },
          release: { kind: "drop", playerId: "te1", name: "Weak TE", position: "TE", value: 900 },
          gain: 1700,
          relativeGap: 0.9714,
          material: true,
          standsAlone: true,
        },
        {
          add: { playerId: "fa2", name: "Free WR", position: "WR", value: 600, bid: { recommended: 0 } },
          release: { kind: "openSpot" },
          gain: 600,
          relativeGap: null,
          material: true,
          standsAlone: true,
        },
      ],
      addCount: 2,
      dropCount: 1,
      openSpotsUsed: 1,
      netValueGain: 2300,
      totalRecommendedBid: 12,
      startersFilledBefore: 2,
      startersFilledAfter: 2,
      starterSlots: 2,
    },
    stopRule: {
      agreementRatio: 0.15,
      nextBestMove: {
        add: { name: "Close WR", value: 2100 },
        release: { kind: "drop", name: "Bench WR", value: 2000 },
        gain: 100,
        relativeGap: 0.0488,
        reason: "within_uncertainty",
      },
    },
    solver: { status: "optimal", provenOptimal: true },
    budget: { state: "known", balance: 60 },
    constraints: { resolutionFailed: false, protectedOnRoster: [{ name: "Fav WR" }] },
    unpriced: { rosterPlayers: [{ name: "Ghost" }], freeAgents: 3, freeAgentSample: [] },
    notes: [],
    ...overrides,
  };
}

function mockFetch(status, body) {
  const fn = vi.fn(async () => ({ ok: status >= 200 && status < 300, status, json: async () => body }));
  vi.stubGlobal("fetch", fn);
  return fn;
}

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("PerfectWaiversPanel — request", () => {
  it("posts the league and the selected team", async () => {
    const fn = mockFetch(200, plan());
    render(<PerfectWaiversPanel leagueKey="main" ownerId="me" />);
    await screen.findByText("Free TE");
    const [url, init] = fn.mock.calls[0];
    expect(url).toBe("/api/waiver/perfect");
    expect(JSON.parse(init.body)).toEqual({ leagueKey: "main", teamOwnerId: "me" });
  });

  it("asks for nothing without a team", () => {
    const fn = mockFetch(200, plan());
    render(<PerfectWaiversPanel leagueKey="main" ownerId="" />);
    expect(fn).not.toHaveBeenCalled();
  });
});

describe("PerfectWaiversPanel — the plan", () => {
  it("renders each add beside the release it replaces, with the bid", async () => {
    mockFetch(200, plan());
    render(<PerfectWaiversPanel leagueKey="main" ownerId="me" />);
    expect(await screen.findByText("Free TE")).toBeInTheDocument();
    expect(screen.getByText("Weak TE")).toBeInTheDocument();
    expect(screen.getByText("Open roster spot")).toBeInTheDocument();
    expect(screen.getByText("+1,700")).toBeInTheDocument();
    expect(screen.getByText("$12")).toBeInTheDocument();
    expect(screen.getByText("Proven optimal")).toBeInTheDocument();
    expect(screen.getByTestId("perfect-waivers-summary")).toHaveTextContent("$12 of $60 FAAB");
  });

  it("explains the stop with the next move it declined", async () => {
    mockFetch(200, plan());
    render(<PerfectWaiversPanel leagueKey="main" ownerId="me" />);
    expect(
      await screen.findByText(/next best move — add Close WR for Bench WR — gains \+100/),
    ).toHaveTextContent("4.9% apart, inside the 15% band");
  });

  it("discloses protected and unpriced players instead of hiding them", async () => {
    mockFetch(200, plan());
    render(<PerfectWaiversPanel leagueKey="main" ownerId="me" />);
    expect(await screen.findByText(/Protected, never proposed as drops: Fav WR/)).toBeInTheDocument();
    expect(screen.getByText(/never proposed as drops:\s*Ghost/)).toBeInTheDocument();
    expect(screen.getByText(/3 free agents the board has not priced/)).toBeInTheDocument();
    expect(screen.getByText(/Advice only — no claim is submitted/)).toBeInTheDocument();
  });

  it("states an unknown balance rather than showing $0", async () => {
    mockFetch(200, plan({ budget: { state: "unknown", balance: null } }));
    render(<PerfectWaiversPanel leagueKey="main" ownerId="me" />);
    expect(await screen.findByTestId("perfect-waivers-summary")).toHaveTextContent(
      "FAAB balance unknown — paid claims withheld",
    );
  });

  it("labels a search that hit its limit", async () => {
    mockFetch(200, plan({ solver: { status: "node_limit", provenOptimal: false } }));
    render(<PerfectWaiversPanel leagueKey="main" ownerId="me" />);
    expect(await screen.findByText("Best plan found, not proven optimal")).toBeInTheDocument();
    expect(screen.queryByText("Proven optimal")).not.toBeInTheDocument();
  });

  it("an empty plan says no move clears the bar", async () => {
    mockFetch(200, plan({ plan: { ...plan().plan, moves: [], addCount: 0, dropCount: 0 } }));
    render(<PerfectWaiversPanel leagueKey="main" ownerId="me" />);
    expect(await screen.findByText("No move clears the bar")).toBeInTheDocument();
  });
});

describe("PerfectWaiversPanel — failures are stated", () => {
  it("league not ready", async () => {
    mockFetch(503, { error: "data_not_ready" });
    render(<PerfectWaiversPanel leagueKey="main" ownerId="me" />);
    expect(await screen.findByText(/rosters haven't loaded yet/)).toBeInTheDocument();
  });

  it("network failure", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn(async () => {
        throw new TypeError("network");
      }),
    );
    render(<PerfectWaiversPanel leagueKey="main" ownerId="me" />);
    await waitFor(() =>
      expect(screen.getByText(/Couldn't reach the waiver optimizer/)).toBeInTheDocument(),
    );
  });
});

describe("/waivers wiring", () => {
  const page = readFileSync(
    path.resolve(__dirname, "../../app/waivers/page.jsx"),
    "utf8",
  );

  it("loads the panel with React.lazy, never next/dynamic", () => {
    expect(page).toMatch(/lazy\(\(\) => import\("@\/components\/waivers\/PerfectWaiversPanel"\)\)/);
    expect(page).not.toMatch(/from "next\/dynamic"/);
    expect(page).not.toMatch(/^import PerfectWaiversPanel/m);
  });

  it("wraps it in its own Suspense inside a reload-recovering ResilientSection", () => {
    expect(page).toMatch(
      /<ResilientSection name="Perfect Waivers" recovery="reload">\s*<Suspense fallback=\{null\}>\s*<PerfectWaiversPanel/,
    );
  });
});
