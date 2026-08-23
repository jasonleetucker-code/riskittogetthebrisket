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
  DEFAULT_TAB,
  PIECE_OF_SHIT_RANKINGS_TAB,
  PIECE_OF_SHIT_RANKINGS_TITLE,
  SECTION_FOR_TAB,
  SUB_TABS,
  TAB_ALIASES,
  VALID_TABS,
  leagueTabHref,
  normalizeTabKey,
  sectionForTab,
} from "@/app/league/tabs.js";
import { PUBLIC_SECTION_KEYS } from "@/lib/public-league-data";

// Tabs that deliberately render from their own fetch rather than from a
// contract section.  Listed explicitly so ADDING a tab without deciding
// which bucket it belongs to fails here instead of silently rendering
// blank because its section was never shipped.
const SELF_FETCHING_TABS = [
  "previews",
  "recaps",
  "power",
  "rosTeamStrength",
  "rosChampionship",
  "rosTradeDeadline",
  "draft-capital",
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
    expect(sectionForTab("not-a-real-tab")).toBe(SECTION_FOR_TAB[DEFAULT_TAB]);
    expect(sectionForTab(undefined)).toBe(SECTION_FOR_TAB[DEFAULT_TAB]);
  });

  it("keeps overview as the default tab's section", () => {
    // page.jsx always fetches "overview" (the header's season label
    // reads it on every tab) and skips a second request when the
    // landing tab needs the same one.
    expect(SECTION_FOR_TAB[DEFAULT_TAB]).toBe("overview");
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
