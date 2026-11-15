import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import React from "react";
import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { LEAGUE } from "../fixtures/manager-intel-league";

const nav = { leagueId: "555000111" };
vi.mock("next/navigation", () => ({
  useParams: () => ({ leagueId: nav.leagueId }),
  useRouter: () => ({ push: vi.fn(), replace: vi.fn() }),
  usePathname: () => `/managers/league/${nav.leagueId}`,
  useSearchParams: () => new URLSearchParams(),
}));

import LeagueScoutPage from "@/app/managers/league/[leagueId]/page";

function jsonResponse(status, body) {
  return { ok: status >= 200 && status < 300, status, json: async () => body };
}

beforeEach(() => {
  nav.leagueId = "555000111";
});

afterEach(() => {
  vi.restoreAllMocks();
});

describe("League scouting page (Batch C)", () => {
  it("renders every team with ranks, withheld totals and unknown picks", async () => {
    global.fetch = vi.fn(async () => jsonResponse(200, LEAGUE));
    render(<LeagueScoutPage />);
    await screen.findByRole("heading", { name: "Championship Alleys" });
    expect(global.fetch).toHaveBeenCalledWith(
      "/api/manager-intel/league?leagueId=555000111",
      expect.objectContaining({ cache: "no-store" }),
    );
    const table = screen.getByRole("table", {
      name: /Every team in this league/,
    });
    const rows = within(table).getAllByRole("row");
    expect(rows).toHaveLength(4); // header + 3 teams
    expect(within(rows[1]).getByText("Ann")).toBeTruthy();
    expect(within(rows[1]).getByText("#1 of 2")).toBeTruthy();
    expect(within(rows[1]).getByText("11,000 · 1 unpriced")).toBeTruthy();
    // The open roster: no rank, no total, picks unknown — never 0.
    expect(within(rows[3]).getByText("Open roster")).toBeTruthy();
    expect(within(rows[3]).getByText("— · 1 unpriced")).toBeTruthy();
    expect(within(rows[3]).getByText("Unknown")).toBeTruthy();
    expect(within(rows[3]).getByText("Insufficient sample (n = 0)")).toBeTruthy();
  });

  it("opens a drilldown with position strength and a lookup link", async () => {
    global.fetch = vi.fn(async () => jsonResponse(200, LEAGUE));
    const user = userEvent.setup();
    render(<LeagueScoutPage />);
    await screen.findByRole("heading", { name: "Championship Alleys" });
    await user.click(screen.getByRole("button", { name: "Show details for Ann" }));
    const link = screen.getAllByRole("link", {
      name: /Look up Ann in Manager Intelligence/,
    })[0];
    expect(link.getAttribute("href")).toBe("/managers?username=u1");
    expect(
      screen.getAllByRole("table", { name: /Rostered players by position/ }).length,
    ).toBeGreaterThan(0);
    expect(screen.getAllByText("Tendencies").length).toBeGreaterThan(0);
  });

  it("sorts by a column through the shared sort", async () => {
    global.fetch = vi.fn(async () => jsonResponse(200, LEAGUE));
    const user = userEvent.setup();
    render(<LeagueScoutPage />);
    await screen.findByRole("heading", { name: "Championship Alleys" });
    const table = screen.getByRole("table", { name: /Every team in this league/ });
    await user.click(within(table).getByRole("button", { name: /Manager/ }));
    let rows = within(table).getAllByRole("row");
    expect(within(rows[1]).getByText("Ann")).toBeTruthy();
    await user.click(within(table).getByRole("button", { name: /Manager/ }));
    rows = within(table).getAllByRole("row");
    expect(within(rows[1]).getByText("Open roster")).toBeTruthy();
  });

  it("names partial coverage and the not-Superflex withholding", async () => {
    global.fetch = vi.fn(async () =>
      jsonResponse(200, {
        ...LEAGUE,
        status: "partial",
        coverage: { ...LEAGUE.coverage, transactions: "partial", weeksFailed: 1 },
        ranking: { ...LEAGUE.ranking, withheld: "canonical_board_is_superflex" },
      }),
    );
    render(<LeagueScoutPage />);
    await screen.findByText("Not everything could be read");
    expect(screen.getByText("Transactions partly read (1 week missing).")).toBeTruthy();
    expect(screen.getByText("Ranks withheld")).toBeTruthy();
  });

  it("shows the backend's error and never fetches for a bad id", async () => {
    global.fetch = vi.fn(async () =>
      jsonResponse(404, { error: "not_found", message: "No Sleeper league with that id." }),
    );
    render(<LeagueScoutPage />);
    expect(await screen.findByText("No Sleeper league with that id.")).toBeTruthy();

    nav.leagueId = "not-a-league";
    global.fetch = vi.fn();
    render(<LeagueScoutPage />);
    expect(screen.getByText("That is not a Sleeper league id.")).toBeTruthy();
    expect(global.fetch).not.toHaveBeenCalled();
  });
});
