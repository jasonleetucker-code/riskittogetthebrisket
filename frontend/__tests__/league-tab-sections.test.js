/**
 * /league section-scoped SSR spec.
 *
 * The page used to server-render the aggregate public contract — 2.01 MB
 * of JSON across 17 sections — and pass the whole thing to a client
 * component, which serialized it into the RSC flight payload and made
 * the /league document 2.38 MB.  It now ships only the sections the
 * landing tab actually reads, and the client fetches the rest on open.
 *
 * These tests pin the two things that make that safe: the tab→section
 * map stays in lockstep with the sections the backend will actually
 * serve, and the server component never goes back to the aggregate.
 */
import fs from "node:fs";
import path from "node:path";
import { describe, expect, it } from "vitest";

import {
  ADVISOR_FALLBACK_TAB,
  ADVISOR_PARAMS,
  DEFAULT_TAB,
  OVERVIEW_TAB,
  PIECE_OF_SHIT_RANKINGS_TAB,
  PIECE_OF_SHIT_RANKINGS_TITLE,
  SECTION_FOR_TAB,
  SUB_TABS,
  TAB_ALIASES,
  VALID_TABS,
  TRADE_ADVISOR_TAB,
  LEAGUE_HOME_HREF,
  LEAGUE_OVERVIEW_HREF,
  OVERVIEW_LABEL_ADVISOR_OFF,
  leagueHomeHrefFor,
  leagueTabHref,
  normalizeTabKey,
  resolveTab,
  sectionForTab,
  visibleTabs,
} from "@/app/league/tabs.js";
import { PUBLIC_SECTION_KEYS } from "@/lib/public-league-data";

// Tabs that deliberately render from their own fetch rather than from a
// contract section.  Listed explicitly so ADDING a tab without deciding
// which bucket it belongs to fails here instead of silently rendering
// blank because its section was never shipped.
const SELF_FETCHING_TABS = [
  // Brisket Trade Advisor (2026-10-19): its own value-free public
  // endpoints, never a public-league contract section.
  "trade-advisor",
  "previews",
  "recaps",
  "power",
  "rosTeamStrength",
  "rosChampionship",
  "rosTradeDeadline",
  "draft-capital",
  // Moved here 2026-09-01: the NFL Team Affinity rewrite made
  // teamAssignment a private, session-gated section (same reason
  // rosTeamStrength/rosTradeDeadline self-fetch instead of riding the
  // anonymous eager aggregate).
  "teamAssignment",
];

describe("tab → section map", () => {
  it("classifies every tab as either section-backed or self-fetching", () => {
    for (const { key } of SUB_TABS) {
      const backed = Object.prototype.hasOwnProperty.call(SECTION_FOR_TAB, key);
      const selfFetching = SELF_FETCHING_TABS.includes(key);
      expect(
        backed !== selfFetching,
        `tab "${key}" must be exactly one of section-backed / self-fetching`,
      ).toBe(true);
    }
  });

  it("every mapped section is one the public API will actually serve", () => {
    // This is the lockstep guard: ``fetchPublicSection`` throws on a key
    // missing from PUBLIC_SECTION_KEYS, so a tab mapped to an unlisted
    // section would fail at runtime the moment a user opened it — which
    // is exactly what `teamAssignment` did before it was added.
    for (const [tab, section] of Object.entries(SECTION_FOR_TAB)) {
      expect(PUBLIC_SECTION_KEYS, `section for tab "${tab}"`).toContain(section);
    }
  });

  it("resolves aliases and unknown tabs to the canonical tab's section", () => {
    for (const [legacy, canonical] of Object.entries(TAB_ALIASES)) {
      expect(VALID_TABS.has(normalizeTabKey(legacy))).toBe(true);
      expect(sectionForTab(legacy)).toBe(SECTION_FOR_TAB[canonical] || null);
    }
    // A hand-typed junk tab must resolve like the UI will render it:
    // through DEFAULT_TAB, so the server pre-renders the section the
    // visitor is about to see rather than one they are not.
    // DEFAULT_TAB is the self-fetching advisor, so that is null.
    expect(sectionForTab("not-a-real-tab")).toBe(SECTION_FOR_TAB[DEFAULT_TAB] || null);
    expect(sectionForTab(undefined)).toBe(SECTION_FOR_TAB[DEFAULT_TAB] || null);
  });

  it("lands on the Brisket Trade Advisor, and on Overview when it is not served", () => {
    // The advisor reads no contract section; page.jsx always fetches
    // "overview" anyway (the header's season label reads it on every tab),
    // so the fallback landing is already server-rendered.
    expect(DEFAULT_TAB).toBe(TRADE_ADVISOR_TAB);
    expect(SUB_TABS[0].key).toBe(TRADE_ADVISOR_TAB);
    expect(SECTION_FOR_TAB[DEFAULT_TAB]).toBeUndefined();
    expect(ADVISOR_FALLBACK_TAB).toBe(OVERVIEW_TAB);
    expect(SECTION_FOR_TAB[ADVISOR_FALLBACK_TAB]).toBe("overview");
    expect(resolveTab(null)).toBe(TRADE_ADVISOR_TAB);
    expect(resolveTab("junk")).toBe(TRADE_ADVISOR_TAB);
    expect(resolveTab("advisor")).toBe(TRADE_ADVISOR_TAB);
    expect(resolveTab(null, { advisorAvailable: false })).toBe(OVERVIEW_TAB);
    expect(resolveTab("junk", { advisorAvailable: false })).toBe(OVERVIEW_TAB);
    expect(resolveTab(TRADE_ADVISOR_TAB, { advisorAvailable: false })).toBe(OVERVIEW_TAB);
    expect(resolveTab("awards", { advisorAvailable: false })).toBe("awards");
    expect(sectionForTab(null, { advisorAvailable: false })).toBe("overview");
    expect(visibleTabs({ advisorAvailable: false }).map((t) => t.key)).not.toContain(TRADE_ADVISOR_TAB);
    expect(visibleTabs().map((t) => t.key)[0]).toBe(TRADE_ADVISOR_TAB);
  });

  it("keeps the overview key (only its label changed) and canonical hrefs", () => {
    expect(SUB_TABS).toContainEqual({ key: OVERVIEW_TAB, label: "Overview" });
    expect(leagueTabHref(TRADE_ADVISOR_TAB)).toBe("/league");
    expect(leagueTabHref("advisor")).toBe("/league");
    expect(leagueTabHref(OVERVIEW_TAB)).toBe("/league?tab=overview");
    expect(leagueTabHref("not-a-real-tab")).toBe("/league");
  });

  it("drops the advisor's own params on every other tab and keeps other tabs' params", () => {
    expect(ADVISOR_PARAMS).toEqual(["team", "step"]);
    expect(leagueTabHref("awards", "team=4&step=result")).toBe("/league?tab=awards");
    expect(leagueTabHref(TRADE_ADVISOR_TAB, "tab=awards", { team: 4 })).toBe("/league?team=4");
    expect(leagueTabHref(TRADE_ADVISOR_TAB, "team=4&step=result", { step: null })).toBe("/league?team=4");
    // owner / week / year keep their pre-advisor behaviour.
    expect(leagueTabHref("franchise", "owner=abc")).toBe("/league?owner=abc&tab=franchise");
  });

  it("advisor OFF: the nav is main's — no advisor tab, Overview labelled 'Home'", () => {
    const off = visibleTabs({ advisorAvailable: false });
    expect(OVERVIEW_LABEL_ADVISOR_OFF).toBe("Home");
    expect(off[0]).toEqual({ key: OVERVIEW_TAB, label: "Home" });
    expect(off.map((t) => t.key)).toEqual(SUB_TABS.slice(1).map((t) => t.key));
    expect(off.slice(1)).toEqual(SUB_TABS.slice(2));
    expect(off.map((t) => t.label)).not.toContain("Overview");
  });

  it("advisor OFF: hrefs are built exactly as on main (Overview is the bare /league)", () => {
    const OFF = { advisorAvailable: false };
    expect(leagueTabHref(OVERVIEW_TAB, "", {}, OFF)).toBe("/league");
    expect(leagueTabHref("not-a-real-tab", "tab=awards", {}, OFF)).toBe("/league");
    expect(leagueTabHref("awards", "", {}, OFF)).toBe("/league?tab=awards");
    expect(leagueTabHref("matchupPreview", "tab=matchupPreview", {}, OFF)).toBe("/league?tab=previews");
    expect(leagueTabHref("franchise", "owner=abc", {}, OFF)).toBe("/league?owner=abc&tab=franchise");
    // No advisor param handling at all while it is off (main had none).
    expect(leagueTabHref("awards", "team=4", {}, OFF)).toBe("/league?team=4&tab=awards");
  });

  it("league back-links: /league unless the advisor is CONFIRMED served", () => {
    expect(LEAGUE_HOME_HREF).toBe("/league");
    expect(LEAGUE_OVERVIEW_HREF).toBe("/league?tab=overview");
    expect(leagueHomeHrefFor({ state: "disabled" })).toBe("/league");
    expect(leagueHomeHrefFor({ state: "unknown" })).toBe("/league");
    expect(leagueHomeHrefFor(null)).toBe("/league");
    expect(leagueHomeHrefFor({ state: "ready", data: {} })).toBe("/league?tab=overview");
  });

  it("uses Piece of Shit Rankings as the canonical label and URL key", () => {
    expect(SUB_TABS).toContainEqual({
      key: PIECE_OF_SHIT_RANKINGS_TAB,
      label: PIECE_OF_SHIT_RANKINGS_TITLE,
    });
    expect(PIECE_OF_SHIT_RANKINGS_TAB).toBe("piece-of-shit-rankings");
    expect(TAB_ALIASES.conduct).toBe(PIECE_OF_SHIT_RANKINGS_TAB);
    expect(VALID_TABS.has("conduct")).toBe(false);
    expect(SECTION_FOR_TAB[PIECE_OF_SHIT_RANKINGS_TAB]).toBe("conduct");
    expect(PUBLIC_SECTION_KEYS).toContain("conduct");
    expect(SELF_FETCHING_TABS).not.toContain(PIECE_OF_SHIT_RANKINGS_TAB);
    expect(leagueTabHref(PIECE_OF_SHIT_RANKINGS_TAB)).toBe(
      "/league?tab=piece-of-shit-rankings",
    );
    expect(leagueTabHref("conduct")).toBe(
      "/league?tab=piece-of-shit-rankings",
    );
  });
});

const pageSource = fs.readFileSync(
  path.resolve(__dirname, "..", "app", "league", "page.jsx"),
  "utf8",
);
const clientSource = fs.readFileSync(
  path.resolve(__dirname, "..", "app", "league", "LeagueClient.jsx"),
  "utf8",
);

describe("/league server component fetches sections, not the aggregate", () => {
  it("page.jsx requests per-section URLs", () => {
    expect(pageSource).toMatch(/\/api\/public\/league\/\$\{encodeURIComponent\(section\)\}/);
  });

  it("page.jsx does not fetch the aggregate contract", () => {
    // The aggregate is 2.01 MB and exceeds Next's 2 MB Data Cache entry
    // limit, so `revalidate` on it is silently inert and every render
    // re-fetches and re-parses the lot.
    const aggregate = /\$\{_backend\(\)\}\/api\/public\/league`/;
    expect(aggregate.test(pageSource)).toBe(false);
  });

  it("the client bootstraps from a section, not the aggregate", () => {
    expect(clientSource).not.toMatch(/fetchPublicLeague\s*\(/);
    expect(clientSource).toMatch(/fetchPublicSection\s*\(/);
  });
});
