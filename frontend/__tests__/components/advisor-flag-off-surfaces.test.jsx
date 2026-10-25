/**
 * Brisket Trade Advisor — the surfaces OUTSIDE the hub also equal main
 * while `brisket_trade_advisor` is off.
 *
 * The flag is read the way the hub reads it: the server's cached read of
 * /api/public/league/trade-advisor/teams, classified by
 * `classifyTeamsResult` ("ready" = served; "disabled"/"unknown" = not
 * confirmed, which renders as main).  Covered here:
 *   - the landing card on `/` (logged-out): "League" + main's copy when
 *     off, "Go to League Hub" + the advisor mention only when served;
 *   - the sitemap: no advisor-only URL (`/league?tab=overview`) when off;
 *   - the nav model's Hub entry: main's hint, no advisor keywords;
 *   - /league/activity's back-link, decided on the server — no browser
 *     teams request at all.
 */
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import fs from "node:fs";
import path from "node:path";
import { render, screen, waitFor } from "@testing-library/react";

const TEAMS_PATH = "/api/public/league/trade-advisor/teams";
const FIX = path.resolve(__dirname, "..", "fixtures", "trade-advisor");
const fixture = (name) => JSON.parse(fs.readFileSync(path.join(FIX, `${name}.json`), "utf8"));

const backend = vi.hoisted(() => ({ teams: null }));
vi.mock("@/lib/server-backend", () => ({
  fetchBackendResult: vi.fn(async (p) => (p === "/api/public/league/trade-advisor/teams" ? backend.teams : { ok: false, status: 404, data: null })),
  fetchBackendJson: vi.fn(async () => null),
  backendOrigin: () => "http://backend.test",
}));
vi.mock("@/app/AppShellWrapper", () => ({ useAuthContext: () => ({ authenticated: false }) }));
vi.mock("@/components/terminal/TerminalLayout", () => ({ default: () => <div data-testid="terminal" /> }));
vi.mock("@/components/useUserState", () => ({ useUserState: () => ({ state: {} }) }));
vi.mock("@/components/useNews", () => ({
  useNews: () => ({ loading: false, error: null, items: [], unavailable: false, reason: null, scored: [], byPlayer: new Map() }),
}));
vi.mock("@/lib/public-league-data", () => ({ fetchPublicSection: vi.fn(async () => ({ data: { feed: [] } })) }));

import HomePage from "@/app/page.jsx";
import ActivityPage from "@/app/league/activity/page";
import sitemap from "@/app/sitemap";
import { NAV_MODEL, paletteTargets } from "@/lib/nav-model";

const OFF = { ok: false, status: 503, data: fixture("error.disabled") };
const ON = { ok: true, status: 200, data: fixture("teams.success") };

// Render a route the way Next would: an async server page is awaited
// first; a client page renders directly.
async function renderRoute(Page) {
  const el = Page.constructor.name === "AsyncFunction" ? await Page({}) : <Page />;
  return render(el);
}

beforeEach(() => {
  backend.teams = OFF;
  vi.stubGlobal("fetch", vi.fn(() => new Promise(() => {})));
});
afterEach(() => vi.unstubAllGlobals());

const MAIN_LANDING_COPY = "Open to everyone: champions, records, rivalries, weekly recaps and every trade in league history.";
const browserTeamsRequests = () => fetch.mock.calls.filter(([u]) => String(u).includes(TEAMS_PATH));

describe("advisor flag OFF — outside the hub, exactly main", () => {
  it("landing card: 'League' and main's copy, no advisor mention", async () => {
    await renderRoute(HomePage);
    expect(screen.getByRole("link", { name: "League" })).toHaveAttribute("href", "/league");
    expect(screen.getByText(MAIN_LANDING_COPY)).toBeInTheDocument();
    expect(screen.queryByText(/Go to League Hub/)).toBeNull();
    expect(screen.queryByText(/Brisket Trade Advisor/)).toBeNull();
    expect(browserTeamsRequests()).toEqual([]);
  });

  it("sitemap carries no advisor-only URL", async () => {
    const urls = (await sitemap()).map((e) => e.url);
    expect(urls.some((u) => /\/league$/.test(u))).toBe(true);
    expect(urls.some((u) => u.endsWith("/league?tab=overview"))).toBe(false);
  });

  it("nav: the Hub entry is main's (hint, no advisor keywords)", () => {
    const hub = NAV_MODEL.find((g) => g.key === "league").items.find((i) => i.href === "/league");
    expect(hub.hint).toBe("Champions, records, power, draft capital, recaps");
    expect(hub.keywords).toBeUndefined();
    expect(JSON.stringify(paletteTargets())).not.toMatch(/advisor/i);
  });

  it("activity back-link is /league, decided on the server with no browser teams request", async () => {
    await renderRoute(ActivityPage);
    expect(await screen.findByRole("link", { name: "← League home" })).toHaveAttribute("href", "/league");
    await new Promise((r) => setTimeout(r, 0));
    expect(browserTeamsRequests()).toEqual([]);
  });
});

describe("advisor flag ON (confirmed served) — the advisor wording applies", () => {
  beforeEach(() => {
    backend.teams = ON;
  });

  it("landing card: 'Go to League Hub' and the advisor mention", async () => {
    await renderRoute(HomePage);
    expect(screen.getByRole("link", { name: "Go to League Hub" })).toHaveAttribute("href", "/league");
    expect(screen.getByText(/the Brisket Trade Advisor, plus champions/)).toBeInTheDocument();
  });

  it("sitemap lists /league?tab=overview", async () => {
    const urls = (await sitemap()).map((e) => e.url);
    expect(urls.some((u) => u.endsWith("/league?tab=overview"))).toBe(true);
  });

  it("activity back-link names Overview, still with no browser teams request", async () => {
    await renderRoute(ActivityPage);
    await waitFor(() =>
      expect(screen.getByRole("link", { name: "← League home" })).toHaveAttribute("href", "/league?tab=overview"),
    );
    expect(browserTeamsRequests()).toEqual([]);
  });
});
