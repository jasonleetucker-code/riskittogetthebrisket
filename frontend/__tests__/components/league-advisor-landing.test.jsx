/**
 * League Hub routing with the Brisket Trade Advisor as DEFAULT_TAB (design
 * §8.1, unit F1).
 *
 *   - no ?tab= (or an unknown one) lands on the advisor, server-rendered
 *     team step, h1 "Brisket Trade Advisor";
 *   - flag off (bootstrap "disabled") → the hub behaves as before the
 *     advisor: Overview lands, no advisor tab, nothing broken (the full
 *     flag-off = main contract is league-advisor-flag-gate.test.jsx);
 *   - a failed public-league contract no longer blanks the hub: the advisor
 *     still renders, other tabs show an in-panel state;
 *   - tab clicks PUSH a history entry; Back (URL loses ?tab=) returns to the
 *     advisor.
 */
import fs from "node:fs";
import path from "node:path";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";

const nav = vi.hoisted(() => ({ search: "", push: vi.fn(), replace: vi.fn() }));
vi.mock("next/navigation", () => ({
  useRouter: () => ({ push: nav.push, replace: nav.replace }),
  useSearchParams: () => new URLSearchParams(nav.search),
}));
vi.mock("next/dynamic", () => ({ default: () => ({ data }) => <div>{data?.label || "section-ready"}</div> }));
vi.mock("@/app/league/shared.jsx", () => ({ buildManagerLookup: () => ({}) }));
vi.mock("@/components/ds", () => ({
  PageHeader: ({ title, eyebrow, description }) => (
    <header>
      <p>{eyebrow}</p>
      <h1>{title}</h1>
      <p>{description}</p>
    </header>
  ),
  Tabs: ({ tabs, onChange }) => (
    <div role="tablist">
      {tabs.map((t) => (
        <button key={t.id} role="tab" onClick={() => onChange(t.id)}>
          {t.label}
        </button>
      ))}
    </div>
  ),
  Select: ({ options }) => (
    <select aria-label="Select league section">
      {options.map((o) => (
        <option key={o.value} value={o.value}>
          {o.label}
        </option>
      ))}
    </select>
  ),
  tabId: (_, tab) => `tab-${tab}`,
  tabPanelId: (_, tab) => `panel-${tab}`,
}));
vi.mock("@/components/ui", () => ({
  LoadingState: ({ message }) => <div>{message}</div>,
  EmptyState: ({ title, message }) => (
    <div>
      {title}: {message}
    </div>
  ),
}));

import LeagueClient from "@/app/league/LeagueClient";
import { classifyTeamsResult } from "@/lib/trade-advisor-client";

const FIX = path.resolve(__dirname, "..", "fixtures", "trade-advisor");
const fixture = (name) => JSON.parse(fs.readFileSync(path.join(FIX, `${name}.json`), "utf8"));
const READY = classifyTeamsResult({ status: 200, data: fixture("teams.success") });
const DISABLED = classifyTeamsResult({ status: 503, data: fixture("error.disabled") });
const contract = {
  league: { leagueName: "Public League", managers: [], seasonsCovered: [] },
  sections: { overview: { label: "Overview loaded" } },
};

beforeEach(() => {
  nav.search = "";
  nav.push = vi.fn((href) => {
    nav.search = href.split("?")[1] || "";
  });
  nav.replace = vi.fn((href) => {
    nav.search = href.split("?")[1] || "";
  });
  vi.stubGlobal("fetch", vi.fn(() => new Promise(() => {})));
});
afterEach(() => vi.unstubAllGlobals());

const tabLabels = () => screen.getAllByRole("tab").map((t) => t.textContent);

it("lands on the advisor with its own h1 and the team step server-rendered", () => {
  render(<LeagueClient initialContract={contract} initialAdvisor={READY} />);
  expect(screen.getByRole("heading", { level: 1, name: "Brisket Trade Advisor" })).toBeInTheDocument();
  expect(screen.getByText("Evaluate trades using our league's scoring, roster construction, and dynasty market.")).toBeInTheDocument();
  expect(screen.getByText("Public League")).toBeInTheDocument();
  expect(screen.getByRole("combobox", { name: "Your team" })).toBeInTheDocument();
  expect(tabLabels()[0]).toBe("Trade Advisor");
  expect(tabLabels()).toContain("Overview");
  expect(fetch).not.toHaveBeenCalled();
});

it("an unknown ?tab= also lands on the advisor", () => {
  nav.search = "tab=not-a-tab";
  render(<LeagueClient initialContract={contract} initialTab="not-a-tab" initialAdvisor={READY} />);
  expect(screen.getByRole("heading", { level: 1, name: "Brisket Trade Advisor" })).toBeInTheDocument();
});

it("flag off: Overview lands, the advisor tab is not offered, nothing is broken", () => {
  render(<LeagueClient initialContract={contract} initialAdvisor={DISABLED} />);
  expect(screen.getByRole("heading", { level: 1, name: "Public League" })).toBeInTheDocument();
  expect(screen.getByText("Overview loaded")).toBeInTheDocument();
  expect(tabLabels()).not.toContain("Trade Advisor");
  expect(screen.queryByRole("combobox", { name: "Your team" })).toBeNull();
});

it("flag off: a deep link to the advisor falls back to Overview", () => {
  nav.search = "tab=trade-advisor";
  render(<LeagueClient initialContract={contract} initialTab="trade-advisor" initialAdvisor={DISABLED} />);
  expect(screen.getByText("Overview loaded")).toBeInTheDocument();
});

it("a deep link to another tab still works", () => {
  nav.search = "tab=awards";
  render(<LeagueClient initialContract={{ ...contract, sections: { ...contract.sections, awards: { label: "Awards loaded" } } }} initialTab="awards" initialAdvisor={READY} />);
  expect(screen.getByText("Awards loaded")).toBeInTheDocument();
});

it("a failed public-league contract does not blank the advisor", () => {
  render(<LeagueClient initialContract={null} initialAdvisor={READY} />);
  expect(screen.getByRole("heading", { level: 1, name: "Brisket Trade Advisor" })).toBeInTheDocument();
  expect(screen.getByRole("combobox", { name: "Your team" })).toBeInTheDocument();
});

it("tab clicks push history; Back to no ?tab= returns to the advisor", async () => {
  const user = userEvent.setup();
  const view = render(<LeagueClient initialContract={contract} initialAdvisor={READY} />);
  await user.click(screen.getByRole("tab", { name: "Overview" }));
  expect(nav.push).toHaveBeenCalledWith("/league?tab=overview", { scroll: false });
  expect(screen.getByText("Overview loaded")).toBeInTheDocument();
  nav.search = ""; // browser Back
  view.rerender(<LeagueClient initialContract={contract} initialAdvisor={READY} />);
  expect(await screen.findByRole("heading", { level: 1, name: "Brisket Trade Advisor" })).toBeInTheDocument();
});
