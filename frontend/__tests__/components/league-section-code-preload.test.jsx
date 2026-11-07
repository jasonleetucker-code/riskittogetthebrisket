// /league tab switch (Workstream H, 2026-10-27).  Measured on production before
// the change: clicking "Records" fetched /api/public/league/records (~450 ms),
// only then asked for the section chunk (~135 ms more), and then sat on
// "Loading section..." for a further ~300 ms because the React.lazy boundary
// inside next/dynamic suspends on its first render and React throttles the
// reveal.  These tests pin:
//   * the code request starts while the data request is still pending;
//   * a section whose code is already loaded when it first renders does not
//     suspend (no lazy fallback), while the hydration / first-paint path
//     (nothing preloaded) still loads through next/dynamic as before;
//   * the data/loading behaviour is unchanged (a section renders only once
//     its data is present).
import fs from "node:fs";
import path from "node:path";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import { act, cleanup, render, screen } from "@testing-library/react";

const nav = vi.hoisted(() => ({ tab: "overview", replace: vi.fn() }));
const imported = vi.hoisted(() => []);
const fallbacks = vi.hoisted(() => ({ count: 0 }));
vi.mock("next/navigation", () => ({
  useRouter: () => ({ replace: nav.replace, push: nav.replace }),
  useSearchParams: () => new URLSearchParams({ tab: nav.tab }),
}));
// next/dynamic on its real client contract: React.lazy over
// `loader().then(convertModule)` inside a Suspense boundary.  The fallback
// counts every time the boundary actually suspended.
vi.mock("next/dynamic", async () => {
  const React = await import("react");
  function Fallback() {
    fallbacks.count += 1;
    return <div>lazy-fallback</div>;
  }
  return {
    default: (loader) => {
      const Lazy = React.lazy(() => loader().then((m) => ({ default: m.default ?? m })));
      return function DynamicSection(props) {
        return (
          <React.Suspense fallback={<Fallback />}>
            <Lazy {...props} />
          </React.Suspense>
        );
      };
    },
  };
});
vi.mock("@/app/league/sections/overview.jsx", () => ({ default: ({ data }) => <div>{data?.label || "overview-ready"}</div> }));
vi.mock("@/app/league/sections/records.jsx", () => {
  imported.push("records");
  return { default: ({ data }) => <div>section:{data?.label}</div> };
});
vi.mock("@/app/league/sections/streaks.jsx", () => {
  imported.push("streaks");
  return { default: ({ data }) => <div>section:{data?.label}</div> };
});
vi.mock("@/app/league/sections/history.jsx", () => {
  imported.push("history");
  return { default: () => null };
});
vi.mock("@/app/league/shared.jsx", () => ({ buildManagerLookup: () => ({}) }));
vi.mock("@/components/ds", () => ({
  PageHeader: ({ title }) => <h1>{title}</h1>,
  Tabs: () => null,
  Select: () => null,
  tabId: (_, tab) => `tab-${tab}`,
  tabPanelId: (_, tab) => `panel-${tab}`,
}));
vi.mock("@/components/ui", () => ({
  LoadingState: ({ message }) => <div>{message}</div>,
  EmptyState: ({ title, message }) => <div>{title}: {message}</div>,
}));

import LeagueClient, { preloadSectionCode } from "@/app/league/LeagueClient";

const initial = {
  league: { leagueName: "Public League", managers: [], seasonsCovered: [] },
  sections: { overview: { label: "Overview loaded" } },
};
let pending;
beforeEach(() => {
  nav.tab = "overview";
  pending = [];
  fallbacks.count = 0;
  vi.stubGlobal("fetch", vi.fn((url, options) => new Promise((resolve) => pending.push({ url, options, resolve }))));
});
afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});

it("first paint of a tab whose code is not loaded still goes through next/dynamic", async () => {
  // Nothing preloaded for `streaks` yet: the first render suspends exactly
  // as before (the server rendered the same fallback, so hydration agrees).
  nav.tab = "streaks";
  const contract = { ...initial, sections: { ...initial.sections, streaks: { label: "Streaks loaded" } } };
  render(<LeagueClient initialContract={contract} initialTab="streaks" />);
  expect(screen.getByText("lazy-fallback")).toBeTruthy();
  expect(await screen.findByText("section:Streaks loaded")).toBeTruthy();
  expect(fallbacks.count).toBeGreaterThan(0);
});

it("requests the section code while its data request is still pending, then renders without suspending", async () => {
  const view = render(<LeagueClient initialContract={initial} />);
  expect(imported).not.toContain("records");
  nav.tab = "records";
  view.rerender(<LeagueClient initialContract={initial} />);
  // Data requested, not yet answered: the shell's loading state is unchanged...
  expect(pending).toHaveLength(1);
  expect(pending[0].url).toBe("/api/public/league/records");
  expect(screen.getByText("Loading section...")).toBeTruthy();
  // ...and the code request has already gone out alongside it.
  await vi.waitFor(() => expect(imported).toContain("records"));
  await act(async () => {
    await preloadSectionCode("records"); // the effect's own request, settled
  });
  expect(screen.getByText("Loading section...")).toBeTruthy();
  fallbacks.count = 0;
  await act(async () =>
    pending[0].resolve(new Response(JSON.stringify({ league: initial.league, data: { label: "Records loaded" } }))),
  );
  // Code landed before the data: the lazy boundary resolves during the
  // render — the content is there in the same commit, no fallback shown.
  expect(screen.getByText("section:Records loaded")).toBeTruthy();
  expect(fallbacks.count).toBe(0);
  expect(fetch).toHaveBeenCalledTimes(1);
});

it("is best effort: tabs without lazily-loaded code are a no-op", async () => {
  expect(preloadSectionCode("overview")).toBeNull();
  expect(preloadSectionCode("not-a-tab")).toBeNull();
  const p = preloadSectionCode("history");
  expect(p).toBeTruthy();
  await p;
  expect(imported).toContain("history");
});

it("loads every lazy section through the loader map the preload uses", () => {
  const src = fs.readFileSync(path.join(__dirname, "../../app/league/LeagueClient.jsx"), "utf8");
  // No section keeps a private inline loader the preload cannot reach.
  expect(src).not.toMatch(/lazySection\(\s*\(\)\s*=>\s*import\(/);
  const keys = [...src.matchAll(/= lazySection\(("([^"]+)"|PIECE_OF_SHIT_RANKINGS_TAB)\)/g)].map((m) => m[2] || m[1]);
  expect((src.match(/= lazySection\(/g) || []).length).toBe(keys.length);
  expect(keys.length).toBeGreaterThan(15);
  const start = src.indexOf("const SECTION_CODE_FOR_TAB = {");
  const mapBody = src.slice(start, src.indexOf("};", start));
  for (const key of keys) {
    const entries =
      key === "PIECE_OF_SHIT_RANKINGS_TAB" ? ["[PIECE_OF_SHIT_RANKINGS_TAB]:"] : [`"${key}":`, ` ${key}:`];
    expect(entries.some((entry) => mapBody.includes(entry))).toBe(true);
  }
});
