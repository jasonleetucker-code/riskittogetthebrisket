/**
 * The sitemap reads the public league through narrow section routes, never
 * the aggregate contract.
 *
 * It needs two lists from the public league: the managers (one franchise
 * URL each) and the rivalry pairs (one rivalry URL each).  It used to pull
 * both from the aggregate `GET /api/public/league` — 2,715,235 bytes of
 * JSON on production (2026-11-08), every section of the contract — which
 * Next's Data Cache refuses to store (2 MB entry cap), so `revalidate: 600`
 * was inert and each regeneration re-fetched it.  The rivalries section
 * payload carries both lists (`league.managers`, `data.rivalries`) at
 * ~77 KB; the backend half of this parity is pinned by
 * tests/public_league/test_server_routes.py
 * ::test_rivalries_section_carries_what_the_sitemap_reads.
 *
 * Expected URLs below are written out by hand from the fixture, not
 * derived from the sitemap's own code.
 */
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

const backend = vi.hoisted(() => ({ responses: {}, calls: [] }));

vi.mock("../lib/server-backend.js", () => ({
  fetchBackendJson: vi.fn(async (path) => {
    backend.calls.push(path);
    return Object.prototype.hasOwnProperty.call(backend.responses, path)
      ? backend.responses[path]
      : null;
  }),
  // Advisor bootstrap: no answer -> "unknown", no advisor-only URL.
  fetchBackendResult: vi.fn(async () => ({ ok: false, status: 0, data: null })),
}));

const ORIGIN = "https://chaseupside.com";

// Shape of GET /api/public/league/rivalries (build_section_payload).
const RIVALRIES_SECTION = {
  contractVersion: "public-league/test",
  leagueKey: "dynasty_main",
  league: {
    leagueName: "Test League",
    seasonsCovered: ["2025", "2026"],
    managers: [
      { ownerId: "111", displayName: "Ann" },
      { ownerId: "222", displayName: "Bo" },
      { ownerId: "333", displayName: "Cy" },
    ],
  },
  section: "rivalries",
  data: {
    rivalries: [
      { ownerIds: ["111", "222"], displayNames: ["Ann", "Bo"] },
      { ownerIds: ["222", "333"], displayNames: ["Bo", "Cy"] },
    ],
  },
};

let sitemap;

beforeEach(async () => {
  backend.responses = {};
  backend.calls = [];
  vi.resetModules();
  ({ default: sitemap } = await import("@/app/sitemap.js"));
});

afterEach(() => {
  vi.restoreAllMocks();
});

function paths(entries) {
  return entries.map((e) => e.url.replace(ORIGIN, ""));
}

describe("sitemap public-league reads", () => {
  it("never requests the aggregate /api/public/league contract", async () => {
    backend.responses["/api/public/league/rivalries"] = RIVALRIES_SECTION;
    await sitemap();
    expect(backend.calls).not.toContain("/api/public/league");
    expect(backend.calls).not.toContain("/api/public/league?refresh=1");
    expect(backend.calls).toContain("/api/public/league/rivalries");
  });

  it("lists one franchise URL per manager and one rivalry URL per pair from the section payload", async () => {
    backend.responses["/api/public/league/rivalries"] = RIVALRIES_SECTION;
    const got = paths(await sitemap());
    const franchise = got.filter((p) => p.startsWith("/league/franchise/"));
    const rivalry = got.filter((p) => p.startsWith("/league/rivalry/"));
    expect(franchise).toEqual([
      "/league/franchise/111",
      "/league/franchise/222",
      "/league/franchise/333",
    ]);
    expect(rivalry).toEqual(["/league/rivalry/111-vs-222", "/league/rivalry/222-vs-333"]);
  });

  it("an aggregate-shaped body is not read for rivalries (the section shape is the contract)", async () => {
    // Guard against a half-migration that reads `sections.rivalries` off a
    // section payload: that key does not exist there, so it would emit no
    // rivalry URLs while every test with an empty backend still passed.
    backend.responses["/api/public/league/rivalries"] = {
      ...RIVALRIES_SECTION,
      data: { rivalries: [] },
      sections: { rivalries: { rivalries: [{ ownerIds: ["9", "8"] }] } },
    };
    const got = paths(await sitemap());
    expect(got.filter((p) => p.startsWith("/league/rivalry/"))).toEqual([]);
    expect(got.filter((p) => p.startsWith("/league/franchise/")).length).toBe(3);
  });

  it("no answer from the section falls back to static routes, with no franchise or rivalry URLs", async () => {
    const got = paths(await sitemap());
    expect(got).toContain("/league");
    expect(got.some((p) => p.startsWith("/league/franchise/"))).toBe(false);
    expect(got.some((p) => p.startsWith("/league/rivalry/"))).toBe(false);
  });

  it("a section payload without rivalry data still lists the managers", async () => {
    backend.responses["/api/public/league/rivalries"] = {
      ...RIVALRIES_SECTION,
      data: {},
    };
    const got = paths(await sitemap());
    expect(got.filter((p) => p.startsWith("/league/franchise/")).length).toBe(3);
    expect(got.some((p) => p.startsWith("/league/rivalry/"))).toBe(false);
  });
});
