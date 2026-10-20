/**
 * League Hub — the Brisket Trade Advisor flag gates EVERY routing change.
 *
 * Safe-rollout norm: with `brisket_trade_advisor` OFF (the server's teams
 * bootstrap classifies as "disabled") /league must render and behave
 * exactly as it did on main before the advisor:
 *   - the Overview section's MARKUP is in the server-rendered HTML (first
 *     paint / SEO), not a lazy-chunk placeholder;
 *   - the tab is labelled "Home" and no advisor tab is offered;
 *   - tab clicks REPLACE the URL (no history entries) and Home writes a
 *     bare `/league`;
 *   - a missing public-league contract blanks the hub (main's early
 *     returns), with no nav.
 * With the flag ON ("ready") the new routing applies: advisor first,
 * "Overview" label, pushed history entries.
 *
 * The server render uses react-dom/server (waiting for Suspense), so "in
 * the SSR HTML" is tested directly.  `next/dynamic` is mocked on its real
 * contract: `ssr: false` renders only a placeholder on the server, so only
 * a static or `ssr: true` section can put its markup in the HTML.
 */
import fs from "node:fs";
import path from "node:path";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { renderToReadableStream } from "react-dom/server";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";

const nav = vi.hoisted(() => ({ search: "", push: vi.fn(), replace: vi.fn() }));
vi.mock("next/navigation", () => ({
  useRouter: () => ({ push: nav.push, replace: nav.replace }),
  useSearchParams: () => new URLSearchParams(nav.search),
}));
// next/dynamic modelled on its real contract: an `ssr: false` section
// renders only a placeholder on the server (its data label on the client,
// so non-overview tabs stay observable); an `ssr: true` section is a
// React.lazy the server render waits for, so its markup reaches the HTML.
vi.mock("next/dynamic", async () => {
  const React = await import("react");
  return {
    default: (loader, opts = {}) => {
      if (opts.ssr === false) {
        return function LazySection({ data }) {
          return <div data-lazy-section="">{data?.label || "lazy-section"}</div>;
        };
      }
      const Lazy = React.lazy(() => loader().then((m) => ({ default: m.default ?? m })));
      return function SsrSection(props) {
        return (
          <React.Suspense fallback={<div data-lazy-section="">loading-section</div>}>
            <Lazy {...props} />
          </React.Suspense>
        );
      };
    },
  };
});
vi.mock("@/app/league/sections/overview.jsx", () => ({
  default: ({ data }) => <div data-testid="overview-markup">At a glance: {data?.label}</div>,
}));
vi.mock("@/app/league/shared.jsx", () => ({ buildManagerLookup: () => ({}) }));
vi.mock("@/components/ds", () => ({
  PageHeader: ({ title, eyebrow }) => (
    <header>
      <p>{eyebrow}</p>
      <h1>{title}</h1>
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
  sections: {
    overview: { label: "Overview loaded" },
    awards: { label: "Awards loaded" },
  },
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

// Server render that waits for every Suspense boundary, like Next's SSR of
// an `ssr: true` dynamic section.
async function ssr(element) {
  const stream = await renderToReadableStream(element);
  await stream.allReady;
  return new Response(stream).text();
}

const tabLabels = () => screen.getAllByRole("tab").map((t) => t.textContent);

describe("advisor flag OFF — /league is exactly main", () => {
  it("server-renders the Overview markup and the 'Home' label", async () => {
    const html = await ssr(<LeagueClient initialContract={contract} initialAdvisor={DISABLED} />);
    expect(html).toContain('data-testid="overview-markup"');
    expect(html).toContain("At a glance: <!-- -->Overview loaded");
    expect(html).toMatch(/role="tab"[^>]*>Home</);
    expect(html).not.toMatch(/role="tab"[^>]*>Overview</);
    expect(html).not.toContain("Trade Advisor");
    expect(html).not.toContain("data-lazy-section");
  });

  it("?tab=overview server-renders the same Overview markup", async () => {
    nav.search = "tab=overview";
    const html = await ssr(
      <LeagueClient initialContract={contract} initialTab="overview" initialAdvisor={DISABLED} />,
    );
    expect(html).toContain('data-testid="overview-markup"');
  });

  it("tab clicks replace the URL and push no history; Home writes a bare /league", async () => {
    const user = userEvent.setup();
    render(<LeagueClient initialContract={contract} initialAdvisor={DISABLED} />);
    expect(tabLabels()).toContain("Home");
    expect(tabLabels()).not.toContain("Overview");
    expect(tabLabels()).not.toContain("Trade Advisor");

    await user.click(screen.getByRole("tab", { name: "Awards" }));
    expect(nav.replace).toHaveBeenLastCalledWith("/league?tab=awards", { scroll: false });
    expect(await screen.findByText("Awards loaded")).toBeInTheDocument();

    await user.click(screen.getByRole("tab", { name: "Home" }));
    expect(nav.replace).toHaveBeenLastCalledWith("/league", { scroll: false });
    expect(await screen.findByTestId("overview-markup")).toBeInTheDocument();

    expect(nav.push).not.toHaveBeenCalled();
  });

  it("a missing public-league contract blanks the hub as on main (no nav)", () => {
    render(<LeagueClient initialContract={null} initialAdvisor={DISABLED} />);
    expect(screen.getByText("Loading league data...")).toBeInTheDocument();
    expect(screen.queryByRole("tablist")).toBeNull();
  });
});

describe("advisor flag ON — the new hub routing", () => {
  it("server-renders the advisor landing, advisor tab first, Overview labelled 'Overview'", async () => {
    const html = await ssr(<LeagueClient initialContract={contract} initialAdvisor={READY} />);
    expect(html).toContain("Brisket Trade Advisor");
    expect(html).toContain("Which team are you evaluating for?");
    expect(html).toMatch(/role="tab"[^>]*>Trade Advisor</);
    expect(html).toMatch(/role="tab"[^>]*>Overview</);
    expect(html).not.toMatch(/role="tab"[^>]*>Home</);
  });

  it("tab clicks push history entries; Overview gets an explicit ?tab=", async () => {
    const user = userEvent.setup();
    render(<LeagueClient initialContract={contract} initialAdvisor={READY} />);
    await user.click(screen.getByRole("tab", { name: "Overview" }));
    expect(nav.push).toHaveBeenLastCalledWith("/league?tab=overview", { scroll: false });
    expect(await screen.findByTestId("overview-markup")).toBeInTheDocument();
    await user.click(screen.getByRole("tab", { name: "Awards" }));
    expect(nav.push).toHaveBeenLastCalledWith("/league?tab=awards", { scroll: false });
    expect(nav.replace).not.toHaveBeenCalled();
  });
});
