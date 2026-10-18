// Manager Intelligence Batch D — the Trade tools section of a scouted roster,
// the league page opened on one manager, and the Package Builder applying a
// seed from the link.
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import React from "react";
import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { parseShareParam } from "@/lib/trade-share";
import { parseBuilderSeed } from "@/lib/package-builder";
import { LEAGUE } from "../fixtures/manager-intel-league";
import {
  EXTERNAL_TOOLS,
  SCOPED_TOOLS,
  scoutedManager,
} from "../fixtures/manager-trade-tools";

const nav = { leagueId: "555000111" };
vi.mock("next/navigation", () => ({
  useParams: () => ({ leagueId: nav.leagueId }),
  useRouter: () => ({ push: vi.fn(), replace: vi.fn() }),
  usePathname: () => `/managers/league/${nav.leagueId}`,
  useSearchParams: () => new URLSearchParams(),
}));

import TradeTools from "@/app/managers/TradeTools";
import LeagueScoutPage from "@/app/managers/league/[leagueId]/page";
import PackageBuilderView from "@/app/arbitrage/PackageBuilderView";

const decodeHref = (href) => parseShareParam(href.slice("/trade".length));

afterEach(() => {
  vi.restoreAllMocks();
  window.history.replaceState(null, "", "/");
});

describe("Trade tools (Batch D)", () => {
  it("seeds every tool for the loaded league from the chosen assets", async () => {
    const user = userEvent.setup();
    render(<TradeTools manager={scoutedManager()} tradeTools={SCOPED_TOOLS} />);
    // Nothing chosen yet: no calculator link, tools named but inert.
    expect(
      screen.queryByRole("link", { name: "Open in Trade Calculator" }),
    ).toBeNull();
    expect(
      screen.getByText(/Select at least one priced asset/),
    ).toBeInTheDocument();

    // Unresolved assets are listed, unselectable, and never shown as 0.
    const veteran = screen.getByLabelText(/Deep Veteran/);
    expect(veteran).toBeDisabled();
    expect(
      screen.getByText(/Unresolved: the canonical board does not price him/),
    ).toBeInTheDocument();
    expect(screen.getByLabelText(/Zed Unranked/)).toBeDisabled();
    expect(screen.queryByText(/^0$/)).toBeNull();

    await user.click(screen.getByLabelText(/Alpha Back/));
    await user.click(screen.getByLabelText(/^2027 Round 1/));
    const calc = screen.getByRole("link", { name: "Open in Trade Calculator" });
    const state = decodeHref(calc.getAttribute("href"));
    expect(state.sides[1].players).toEqual(["Alpha Back", "2027 Round 1"]);
    expect(state.sides[1].assetIds).toEqual([
      null,
      "pick:dynasty_main:2027:r1:o4",
    ]);
    expect(state.packageModel).toBe(SCOPED_TOOLS.packageModel.id);
    expect(
      screen.getByRole("link", { name: "Analyze Trade" }).getAttribute("href"),
    ).toBe(calc.getAttribute("href"));
    const builder = screen.getByRole("link", { name: "Package Builder" });
    expect(
      parseBuilderSeed(builder.getAttribute("href").split("?")[1]),
    ).toEqual({
      opponentOwner: "735693375101108224",
      leagueKey: "dynasty_main",
      target: "",
    });

    await user.click(screen.getByRole("button", { name: "Clear" }));
    await user.click(screen.getByLabelText(/Alpha Back/));
    expect(
      parseBuilderSeed(
        screen
          .getByRole("link", { name: "Package Builder" })
          .getAttribute("href")
          .split("?")[1],
      ).target,
    ).toBe("Alpha Back");

    await user.click(screen.getByRole("button", { name: "Select all priced" }));
    expect(screen.getByText(/4 selected · 3 unresolved/)).toBeInTheDocument();
  });

  it("an external league offers only the generic calculator seed", async () => {
    const user = userEvent.setup();
    render(
      <TradeTools
        manager={scoutedManager("sleeper-555")}
        tradeTools={EXTERNAL_TOOLS}
      />,
    );
    expect(
      screen.getByText(/not one of the site's leagues/),
    ).toBeInTheDocument();
    await user.click(screen.getByLabelText(/^2027 Round 1/));
    const state = decodeHref(
      screen
        .getByRole("link", { name: "Open in Trade Calculator" })
        .getAttribute("href"),
    );
    expect(state.sides[1].players).toEqual(["2027 Round 1"]);
    expect(state.sides[1].assetIds).toEqual([null]);
    expect(screen.queryByRole("link", { name: "Analyze Trade" })).toBeNull();
    expect(screen.queryByRole("link", { name: "Package Builder" })).toBeNull();
    expect(screen.queryByText("Analyze Trade")).toBeNull();
  });
});

describe("League scouting opened on one manager", () => {
  it("?manager= expands that manager's row and shows its trade tools", async () => {
    const payload = {
      ...LEAGUE,
      tradeTools: EXTERNAL_TOOLS,
      managers: LEAGUE.managers.map((m) =>
        m.rosterId === 2 ? { ...m, ownerUserId: "735693375101108224" } : m,
      ),
    };
    global.fetch = vi.fn(async () => ({
      ok: true,
      status: 200,
      json: async () => payload,
    }));
    window.history.replaceState(
      null,
      "",
      "/managers/league/555000111?manager=735693375101108224",
    );
    render(<LeagueScoutPage />);
    await screen.findByRole("heading", { name: "Championship Alleys" });
    const bob = payload.managers.find((m) => m.rosterId === 2).displayName;
    const toggle = await screen.findByRole("button", {
      name: `Hide details for ${bob}`,
    });
    expect(toggle).toHaveAttribute("aria-expanded", "true");
    const sections = screen.getAllByRole("region", {
      name: `Trade tools for ${bob}`,
    });
    expect(sections.length).toBeGreaterThan(0);
    expect(
      within(sections[0]).getByText(/only the Trade Calculator can be seeded/),
    ).toBeInTheDocument();
    // The drilldown renders in the table AND the phone stack: every checkbox
    // id is unique, so each label binds to its own copy's checkbox.
    const ids = [...document.querySelectorAll('input[type="checkbox"]')].map((el) => el.id);
    expect(ids.length).toBeGreaterThan(0);
    expect(new Set(ids).size).toBe(ids.length);
    // Other managers stay collapsed.
    expect(
      screen.getByRole("button", { name: "Show details for Ann" }),
    ).toBeInTheDocument();
  });
});

describe("Package Builder applies a seed from the link", () => {
  let originalFetch;
  beforeEach(() => {
    originalFetch = global.fetch;
    window.localStorage.clear();
  });
  afterEach(() => {
    global.fetch = originalFetch;
  });

  const TEAMS = [
    { name: "Us", ownerId: "111", players: ["Our WR"] },
    {
      name: "Dana's Team",
      ownerId: "735693375101108224",
      players: ["Alpha Back"],
    },
  ];

  it("chooses the counterparty and target and builds with them", async () => {
    const user = userEvent.setup();
    global.fetch = vi.fn().mockResolvedValue({
      ok: true,
      status: 200,
      json: async () => ({
        packages: [],
        request: { opponent: "Dana's Team" },
      }),
    });
    const seed = parseBuilderSeed(
      "?tool=builder&league=dynasty_main&opponent=735693375101108224&target=Alpha%20Back",
    );
    render(
      <PackageBuilderView
        myTeam="Us"
        leagueKey="dynasty_main"
        ownerKey="111"
        teams={TEAMS}
        seed={seed}
      />,
    );
    expect(
      await screen.findByText(
        /Pre-filled from Manager Intelligence: trading with Dana's Team, acquiring Alpha Back/,
      ),
    ).toBeInTheDocument();
    expect(screen.getByLabelText("Player or pick you want")).toHaveValue(
      "Alpha Back",
    );
    expect(screen.getByLabelText("From team")).toHaveValue("Dana's Team");
    await user.click(screen.getByRole("button", { name: "Build packages" }));
    expect(JSON.parse(global.fetch.mock.calls[0][1].body)).toMatchObject({
      myTeam: "Us",
      leagueKey: "dynasty_main",
      target: "Alpha Back",
      opponent: "Dana's Team",
    });
  });

  it("says so when the seeded manager is not in the selected league", async () => {
    const seed = parseBuilderSeed(
      "?tool=builder&league=dynasty_main&opponent=999",
    );
    render(
      <PackageBuilderView
        myTeam="Us"
        leagueKey="dynasty_new"
        ownerKey="111"
        teams={TEAMS}
        seed={seed}
      />,
    );
    expect(await screen.findByText(/different league/)).toBeInTheDocument();
    expect(screen.getByLabelText("From team")).toHaveValue("");
  });
});
