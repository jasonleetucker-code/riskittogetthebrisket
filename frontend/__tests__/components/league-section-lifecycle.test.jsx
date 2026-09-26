import { afterEach, beforeEach, expect, it, vi } from "vitest";
import { act, cleanup, render, screen } from "@testing-library/react";
import { StrictMode } from "react";
const nav = vi.hoisted(() => ({ tab: "overview", replace: vi.fn() }));
vi.mock("next/navigation", () => ({ useRouter: () => ({ replace: nav.replace }), useSearchParams: () => new URLSearchParams({ tab: nav.tab }) }));
vi.mock("next/dynamic", () => ({ default: () => ({ data }) => <div>{data?.label || "section-ready"}</div> }));
vi.mock("@/app/league/sections/overview.jsx", () => ({ default: ({ data }) => <div>{data?.label || "overview-ready"}</div> }));
vi.mock("@/app/league/shared.jsx", () => ({ buildManagerLookup: () => ({}) }));
vi.mock("@/components/ds", () => ({ PageHeader: ({ title }) => <h1>{title}</h1>, Tabs: () => null, Select: () => null, tabId: (_, tab) => `tab-${tab}`, tabPanelId: (_, tab) => `panel-${tab}` }));
vi.mock("@/components/ui", () => ({ LoadingState: ({ message }) => <div>{message}</div>, EmptyState: ({ title, message }) => <div>{title}: {message}</div> }));
import LeagueClient from "@/app/league/LeagueClient";
const initial = { league: { leagueName: "Public League", managers: [], seasonsCovered: [] }, sections: { overview: { label: "Overview loaded" } } };
let pending;
beforeEach(() => {
  nav.tab = "overview";
  pending = [];
  vi.stubGlobal("fetch", vi.fn((url, options) => new Promise((resolve) => pending.push({ url, options, resolve }))));
});
afterEach(() => { cleanup(); vi.unstubAllGlobals(); });
function switchTab(view, tab) {
  nav.tab = tab;
  view.rerender(<LeagueClient initialContract={initial} />);
}
async function finish(index, label, status = 200) {
  await act(async () => pending[index].resolve(new Response(JSON.stringify({ league: initial.league, data: { label } }), { status })));
}

it("loads once and caches completed public sections without credentials", async () => {
  const view = render(<LeagueClient initialContract={initial} />);
  expect(fetch).not.toHaveBeenCalled();
  switchTab(view, "history");
  expect(pending[0].options.credentials).toBe("omit");
  expect(pending[0].url).toBe("/api/public/league/history");
  await finish(0, "History loaded");
  expect(screen.getByText("History loaded")).toBeTruthy();
  switchTab(view, "overview");
  switchTab(view, "history");
  expect(fetch).toHaveBeenCalledTimes(1);
  expect(screen.getByText("History loaded")).toBeTruthy();
});
it("reuses a pending section after visiting a cached tab then returning", async () => {
  const view = render(<LeagueClient initialContract={initial} />);
  switchTab(view, "history");
  switchTab(view, "overview");
  switchTab(view, "history");
  expect(fetch).toHaveBeenCalledTimes(1);
  await finish(0, "History loaded");
  expect(screen.getByText("History loaded")).toBeTruthy();
  expect(screen.queryByText("Loading section...")).toBeNull();
});
it("merges two overlapping section completions without cancelling the other", async () => {
  const view = render(<LeagueClient initialContract={initial} />);
  switchTab(view, "history");
  switchTab(view, "rivalries");
  await finish(0, "History loaded");
  await finish(1, "Rivalries loaded");
  expect(screen.getByText("Rivalries loaded")).toBeTruthy();
  switchTab(view, "history");
  expect(screen.getByText("History loaded")).toBeTruthy();
  expect(fetch).toHaveBeenCalledTimes(2);
});
it("scopes a failed section to its tab and retries after leaving and returning", async () => {
  const view = render(<LeagueClient initialContract={initial} />);
  switchTab(view, "history");
  await finish(0, "ignored", 503);
  expect(screen.getByText(/Section unavailable/)).toBeTruthy();
  switchTab(view, "rivalries");
  expect(screen.queryByText(/Section unavailable/)).toBeNull();
  await finish(1, "Rivalries loaded");
  switchTab(view, "history");
  await finish(2, "History recovered");
  expect(screen.getByText("History recovered")).toBeTruthy();
});
it("does not update an unmounted shell when a section completes", async () => {
  const view = render(<LeagueClient initialContract={initial} />);
  switchTab(view, "history");
  view.unmount();
  await finish(0, "History loaded");
  expect(screen.queryByText("History loaded")).toBeNull();
});
it("keeps a late background failure off the current section", async () => {
  const view = render(<LeagueClient initialContract={initial} />);
  switchTab(view, "history");
  switchTab(view, "rivalries");
  await finish(0, "ignored", 503);
  expect(screen.queryByText(/Section unavailable/)).toBeNull();
  await finish(1, "Rivalries loaded");
  expect(screen.getByText("Rivalries loaded")).toBeTruthy();
});
it("coalesces section loading across StrictMode effect replay", async () => {
  nav.tab = "history";
  render(<StrictMode><LeagueClient initialContract={initial} /></StrictMode>);
  expect(fetch).toHaveBeenCalledTimes(1);
  await finish(0, "History loaded");
  expect(screen.getByText("History loaded")).toBeTruthy();
});
