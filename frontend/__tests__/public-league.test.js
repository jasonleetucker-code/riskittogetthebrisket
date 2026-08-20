import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import fs from "node:fs";
import path from "node:path";

import {
  PUBLIC_SECTION_KEYS,
  fetchPublicLeague,
  fetchPublicSection,
} from "../lib/public-league-data.js";

// ── Section keys ────────────────────────────────────────────────────────────
describe("PUBLIC_SECTION_KEYS", () => {
  it("starts with overview so the front door is always first", () => {
    expect(PUBLIC_SECTION_KEYS[0]).toBe("overview");
  });

  it("includes every required public section", () => {
    const required = [
      "overview", "history", "rivalries", "awards", "records",
      "franchise", "activity", "draft", "weekly", "superlatives", "archives",
    ];
    for (const key of required) {
      expect(PUBLIC_SECTION_KEYS).toContain(key);
    }
  });

  it("is frozen so accidental mutation throws", () => {
    expect(Object.isFrozen(PUBLIC_SECTION_KEYS)).toBe(true);
  });
});

// ── Data-fetcher behavior ──────────────────────────────────────────────────
describe("fetchPublicLeague", () => {
  let origFetch;
  beforeEach(() => {
    origFetch = global.fetch;
  });
  afterEach(() => {
    global.fetch = origFetch;
    vi.resetAllMocks();
  });

  it("calls /api/public/league and returns parsed JSON", async () => {
    const payload = { contractVersion: "x", league: {}, sections: {} };
    global.fetch = vi.fn().mockResolvedValue({
      ok: true,
      json: async () => payload,
    });
    const result = await fetchPublicLeague();
    expect(result).toEqual(payload);
    expect(global.fetch).toHaveBeenCalledWith(
      "/api/public/league",
      expect.objectContaining({ method: "GET", credentials: "omit" }),
    );
  });

  it("propagates refresh=1 when requested", async () => {
    global.fetch = vi.fn().mockResolvedValue({
      ok: true,
      json: async () => ({}),
    });
    await fetchPublicLeague({ refresh: true });
    expect(global.fetch).toHaveBeenCalledWith(
      "/api/public/league?refresh=1",
      expect.any(Object),
    );
  });

  it("throws a descriptive error on non-OK response", async () => {
    global.fetch = vi.fn().mockResolvedValue({
      ok: false,
      status: 503,
      json: async () => ({}),
    });
    await expect(fetchPublicLeague()).rejects.toThrow(/503/);
  });
});

describe("fetchPublicSection", () => {
  let origFetch;
  beforeEach(() => {
    origFetch = global.fetch;
  });
  afterEach(() => {
    global.fetch = origFetch;
  });

  it("rejects unknown section names up front", async () => {
    await expect(fetchPublicSection("not-a-section")).rejects.toThrow(/Unknown public section/);
  });

  it("targets /api/public/league/{section}", async () => {
    global.fetch = vi.fn().mockResolvedValue({
      ok: true,
      json: async () => ({}),
    });
    await fetchPublicSection("awards");
    expect(global.fetch).toHaveBeenCalledWith(
      "/api/public/league/awards",
      expect.any(Object),
    );
  });

  it("threads owner + refresh through the query string", async () => {
    global.fetch = vi.fn().mockResolvedValue({
      ok: true,
      json: async () => ({}),
    });
    await fetchPublicSection("franchise", { owner: "owner-1", refresh: true });
    const [url] = global.fetch.mock.calls[0];
    expect(url).toMatch(/\/api\/public\/league\/franchise\?/);
    expect(url).toMatch(/owner=owner-1/);
    expect(url).toMatch(/refresh=1/);
  });
});

// ── Import-surface guardrails for the page ─────────────────────────────────
// The /league route is a server component (page.jsx) that wraps a client
// component (LeagueClient.jsx).  Both must honor the isolation contract.
const pageSource = fs.readFileSync(
  path.resolve(__dirname, "..", "app", "league", "page.jsx"),
  "utf8",
);
const clientSource = fs.readFileSync(
  path.resolve(__dirname, "..", "app", "league", "LeagueClient.jsx"),
  "utf8",
);
// tabs.js is the third file in the route's server graph — page.jsx
// imports it to decide which sections to server-render — so the
// isolation guardrails below have to cover it too.
const tabsSource = fs.readFileSync(
  path.resolve(__dirname, "..", "app", "league", "tabs.js"),
  "utf8",
);
const combinedSource = pageSource + "\n" + clientSource + "\n" + tabsSource;

describe("public /league page isolation", () => {
  it("does not import useApp / AppShell", () => {
    expect(combinedSource).not.toMatch(/from\s+["']@\/components\/AppShell["']/);
    expect(combinedSource).not.toMatch(/import\s+\{[^}]*useApp[^}]*\}/);
  });

  it("does not import useDynastyData", () => {
    expect(combinedSource).not.toMatch(/from\s+["']@\/components\/useDynastyData["']/);
  });

  it("does not import the private league-analysis module", () => {
    expect(combinedSource).not.toMatch(/from\s+["']@\/lib\/league-analysis["']/);
  });

  it("does not import private dynasty-data / trade-logic / edge-helpers", () => {
    expect(combinedSource).not.toMatch(/from\s+["']@\/lib\/dynasty-data["']/);
    expect(combinedSource).not.toMatch(/from\s+["']@\/lib\/trade-logic["']/);
    expect(combinedSource).not.toMatch(/from\s+["']@\/lib\/edge-helpers["']/);
  });

  it("pulls data from the public contract — either via server fetch of /api/public/league or via fetchPublicLeague on the client", () => {
    const serverFetch = /\/api\/public\/league/.test(pageSource);
    const clientFetch = /fetchPublicLeague/.test(clientSource)
      && /@\/lib\/public-league-data/.test(clientSource);
    expect(serverFetch || clientFetch).toBe(true);
  });

  it("page.jsx is a server component (does not declare \"use client\")", () => {
    expect(pageSource.trim().startsWith('"use client"')).toBe(false);
  });

  it("LeagueClient.jsx is a client component", () => {
    expect(clientSource.trim().startsWith('"use client"')).toBe(true);
  });
});

// ── AppShell gating sanity ─────────────────────────────────────────────────
const appShellSource = fs.readFileSync(
  path.resolve(__dirname, "..", "components", "AppShell.jsx"),
  "utf8",
);

describe("AppShell public-route gating", () => {
  it("includes /league in PUBLIC_ONLY_ROUTE_PREFIXES", () => {
    expect(appShellSource).toMatch(/PUBLIC_ONLY_ROUTE_PREFIXES[^\n]*\/league/);
  });

  it("refuses to hydrate useDynastyData inside the dataless shell", () => {
    // Renamed from PublicAppShell to NoPlayerDataAppShell when private
    // routes with no player data (/login, /more, /admin, …) started
    // taking the same branch. The privacy invariant this test guards is
    // unchanged: whichever shell serves /league must never call
    // useDynastyData, because /api/data carries private rankings, edge
    // signals and trade targets.
    //
    // toBeTruthy() on the match is load-bearing — if this component is
    // renamed again the regex stops matching, and without that assertion
    // `not.toMatch` on an empty string would PASS and the guard would
    // silently stop guarding.
    const shellMatch = appShellSource.match(/function NoPlayerDataAppShell[\s\S]*?^}/m);
    expect(shellMatch).toBeTruthy();
    expect(shellMatch[0]).not.toMatch(/useDynastyData\(/);
  });

  it("routes /league to the dataless shell, not the private one", () => {
    // The rename above is only safe if the branch still sends /league
    // there. Pin the composition, so a future edit that gates /league
    // into PrivateAppShell fails here rather than in production.
    expect(appShellSource).toMatch(
      /!isPublicOnlyRoute\(pathname\)\s*&&\s*!isNoPlayerDataRoute\(pathname\)/,
    );
  });
});
