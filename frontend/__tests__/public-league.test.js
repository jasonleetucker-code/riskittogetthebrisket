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
const pageSource = fs.readFileSync(
  path.resolve(__dirname, "..", "app", "league", "page.jsx"),
  "utf8",
);

describe("public /league page isolation", () => {
  it("does not import useApp / AppShell", () => {
    expect(pageSource).not.toMatch(/from\s+["']@\/components\/AppShell["']/);
    expect(pageSource).not.toMatch(/import\s+\{[^}]*useApp[^}]*\}/);
  });

  it("does not import useDynastyData", () => {
    expect(pageSource).not.toMatch(/from\s+["']@\/components\/useDynastyData["']/);
  });

  it("does not import the private league-analysis module", () => {
    expect(pageSource).not.toMatch(/from\s+["']@\/lib\/league-analysis["']/);
  });

  it("does not import private dynasty-data / trade-logic / edge-helpers", () => {
    expect(pageSource).not.toMatch(/from\s+["']@\/lib\/dynasty-data["']/);
    expect(pageSource).not.toMatch(/from\s+["']@\/lib\/trade-logic["']/);
    expect(pageSource).not.toMatch(/from\s+["']@\/lib\/edge-helpers["']/);
  });

  it("pulls data from the public contract fetcher", () => {
    expect(pageSource).toMatch(/fetchPublicLeague/);
    expect(pageSource).toMatch(/@\/lib\/public-league-data/);
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

  it("refuses to hydrate useDynastyData inside the public shell", () => {
    // PublicAppShell must explicitly not call useDynastyData.
    const publicShellMatch = appShellSource.match(/function PublicAppShell[\s\S]*?^}/m);
    expect(publicShellMatch).toBeTruthy();
    expect(publicShellMatch[0]).not.toMatch(/useDynastyData\(/);
  });
});
