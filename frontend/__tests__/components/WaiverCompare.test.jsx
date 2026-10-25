/**
 * Waiver Wire Comparison page — rendered against a mocked API payload.
 */
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import WaiverCompareClient from "@/app/waiver-wire/r7k4q9m2/WaiverCompareClient";
import { WAIVER_COMPARE_PATH } from "@/lib/public-routes";

vi.mock("../../lib/server-backend.js", () => ({
  fetchBackendJson: vi.fn(async () => null),
  fetchBackendResult: vi.fn(async () => ({ ok: false, status: 0, data: null })),
}));

const rec = (id, name, pos, age, ktc, idptc, value) => ({
  id,
  name,
  pos,
  team: "DET",
  age,
  ktc,
  idptc,
  value,
});

function payload() {
  const players = {
    r1: rec("r1", "Roster Star", "WR", 25, 8000, 9000, 8500),
    r2: rec("r2", "Roster Linebacker", "LB", 27, null, 2000, 2000),
    r3: rec("r3", "Roster Unranked", "DL", 29, null, null, null),
  };
  const waiverIds = [];
  for (let i = 0; i < 75; i += 1) {
    const id = `w${i}`;
    players[id] = rec(id, `Waiver ${i}`, i % 2 ? "WR" : "LB", i < 10 ? 21 : 30, 3000 - i, null, 3000 - i);
    waiverIds.push(id);
  }
  return {
    ok: true,
    league: { key: "dynasty_main", name: "Risk It To Get The Brisket" },
    values: {
      asOf: "2026-10-21T18:58:55Z",
      sources: {
        ktc: { label: "KeepTradeCut", settings: "Dynasty · Crowd+Trades · Superflex · TE++", staleness: "fresh" },
        idptc: { label: "IDP Trade Calculator", settings: "Superflex · TE Premium", staleness: "fresh" },
      },
    },
    rosters: { fetchedAt: "2026-10-21T19:00:00Z", state: "live" },
    teams: [
      { rosterId: 1, teamName: "Alpha", ownerName: "Al", playerIds: ["r1", "r2", "r3"] },
      { rosterId: 2, teamName: "Bravo", ownerName: "Bo", playerIds: [] },
    ],
    waiverIds,
    players,
  };
}

beforeEach(() => {
  window.history.replaceState(null, "", WAIVER_COMPARE_PATH);
  global.fetch = vi.fn(async (url) => {
    if (String(url).includes("/api/public/waiver-compare")) {
      return { ok: true, status: 200, json: async () => payload() };
    }
    throw new Error(`unexpected fetch: ${url}`);
  });
});

afterEach(() => {
  vi.restoreAllMocks();
});

describe("WaiverCompareClient", () => {
  it("lists every team and shows the selected roster with N/A for unranked", async () => {
    render(<WaiverCompareClient />);
    const select = await screen.findByLabelText("Select your team");
    await waitFor(() => expect(within(select).getAllByRole("option")).toHaveLength(3));
    expect(within(select).getByRole("option", { name: "Alpha (Al)" })).toBeTruthy();
    expect(within(select).getByRole("option", { name: "Bravo (Bo)" })).toBeTruthy();

    fireEvent.change(select, { target: { value: "1" } });
    expect(await screen.findByText("Roster Star")).toBeTruthy();
    expect(screen.getByText("Roster Unranked")).toBeTruthy();
    expect(screen.getAllByText("N/A").length).toBeGreaterThan(0);
    expect(screen.getByText("8,500")).toBeTruthy();
    expect(window.location.search).toContain("team=1");
  });

  it("shows the top 50 waivers and loads 50 more", async () => {
    render(<WaiverCompareClient />);
    expect(await screen.findByText("Waiver 0")).toBeTruthy();
    expect(screen.getByText("Waiver 49")).toBeTruthy();
    expect(screen.queryByText("Waiver 50")).toBeNull();
    fireEvent.click(screen.getByRole("button", { name: "Load 50 more" }));
    expect(await screen.findByText("Waiver 74")).toBeTruthy();
    expect(screen.queryByRole("button", { name: "Load 50 more" })).toBeNull();
  });

  it("the age slider filters the whole waiver pool, not the visible page", async () => {
    render(<WaiverCompareClient />);
    await screen.findByText("Waiver 0");
    fireEvent.change(screen.getByLabelText(/Waiver max age/), { target: { value: "21" } });
    await waitFor(() => expect(screen.queryByText("Waiver 49")).toBeNull());
    expect(screen.getByText("Waiver 9")).toBeTruthy();
    expect(screen.getAllByText(/21 and younger/).length).toBeGreaterThan(0);
  });

  it("the position filter applies to both lists", async () => {
    render(<WaiverCompareClient />);
    const select = await screen.findByLabelText("Select your team");
    await waitFor(() => expect(within(select).getAllByRole("option")).toHaveLength(3));
    fireEvent.change(select, { target: { value: "1" } });
    await screen.findByText("Roster Star");
    fireEvent.change(screen.getByLabelText("Position"), { target: { value: "LB" } });
    await waitFor(() => expect(screen.queryByText("Roster Star")).toBeNull());
    expect(screen.getByText("Roster Linebacker")).toBeTruthy();
    expect(screen.queryByText("Waiver 1")).toBeNull(); // WR
    expect(screen.getByText("Waiver 0")).toBeTruthy(); // LB
  });

  it("tapping a player reveals the per-source values", async () => {
    render(<WaiverCompareClient />);
    const select = await screen.findByLabelText("Select your team");
    await waitFor(() => expect(within(select).getAllByRole("option")).toHaveLength(3));
    fireEvent.change(select, { target: { value: "1" } });
    fireEvent.click(await screen.findByText("Roster Linebacker"));
    expect(await screen.findByText("Not listed")).toBeTruthy();
    expect(screen.getAllByText("2,000").length).toBeGreaterThan(1);
  });

  it("renders an explicit error when rosters are unavailable", async () => {
    global.fetch = vi.fn(async () => ({
      ok: false,
      status: 503,
      json: async () => ({ ok: false, error: "rosters_unavailable" }),
    }));
    render(<WaiverCompareClient />);
    expect(await screen.findByText(/Sleeper rosters are unavailable/)).toBeTruthy();
  });
});

describe("sitemap", () => {
  it("never lists the unlisted page", async () => {
    const { default: sitemap } = await import("@/app/sitemap.js");
    const urls = (await sitemap()).map((e) => e.url);
    expect(urls.some((u) => u.includes(WAIVER_COMPARE_PATH))).toBe(false);
  });
});
