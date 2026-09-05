/**
 * PreviewsSection — the public "Previews" tab.
 *
 * The behaviour under test is a truthfulness one, not a layout one. On
 * 2026-09-05, Week 1 of the season, `/api/public/league/matchupPreview`
 * served all six upcoming matchups with real H2H and form data while the
 * Previews tab rendered the 2025 Week 17 articles — narrative generation is
 * blocked on a missing `ANTHROPIC_API_KEY`, and nothing on the page
 * distinguished "this week's previews" from "the last previews we have".
 *
 * Two rules are pinned here:
 *   1. an unscored current week gets its structured head-to-head block, so
 *      the pregame content that IS computed is reachable;
 *   2. missing stays missing — a first-ever meeting shows no margin, and a
 *      manager with no prior games shows no record.
 */
import { render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import ArticlesSection from "@/app/league/sections/articles.jsx";

// The section under test caches at module scope, so each test needs a
// fresh module instance.
async function loadSection() {
  vi.resetModules();
  const mod = await import("@/app/league/sections/matchup-previews.jsx");
  return mod.default;
}

const LEAGUE = {
  managers: [
    { ownerId: "owner-A", displayName: "Jason", currentTeamName: "Medical Murrayjuana", avatar: "" },
    { ownerId: "owner-B", displayName: "Collin", currentTeamName: "CollinFoz", avatar: "" },
    { ownerId: "owner-C", displayName: "Blaine", currentTeamName: "ughb", avatar: "" },
    { ownerId: "owner-D", displayName: "Ty", currentTeamName: "TyBWell", avatar: "" },
  ],
};

const PLAYED_SERIES = {
  matchupId: 4,
  home: { ownerId: "owner-A", displayName: "Jason", teamName: "Medical Murrayjuana", rosterId: 1, points: null },
  away: { ownerId: "owner-B", displayName: "Collin", teamName: "CollinFoz", rosterId: 4, points: null },
  h2h: {
    totalMeetings: 4,
    homeWins: 2,
    awayWins: 2,
    ties: 0,
    avgMargin: 51.77,
    biggestMargin: 108.0,
    playoffMeetings: 1,
    narrative: "series tied 2-2; most recent: Collin by 108.0 in 2025 wk 12.",
  },
  form: {
    home: {
      games: [{ season: "2025", week: 12, points: 233.58, opponentPoints: 341.58, result: "L" }],
      record: "0-1",
      avgPoints: 233.58,
      isPriorSeasonOnly: true,
    },
    away: {
      games: [{ season: "2025", week: 12, points: 341.58, opponentPoints: 233.58, result: "W" }],
      record: "1-0",
      avgPoints: 341.58,
      isPriorSeasonOnly: true,
    },
  },
};

// The shape the contract serves for two managers who have never played:
// undefined aggregates are null, counts are zero.
const FIRST_MEETING = {
  matchupId: 2,
  home: { ownerId: "owner-C", displayName: "Blaine", teamName: "ughb", rosterId: 12, points: null },
  away: { ownerId: "owner-D", displayName: "Ty", teamName: "TyBWell", rosterId: 3, points: null },
  h2h: {
    totalMeetings: 0,
    homeWins: 0,
    awayWins: 0,
    ties: 0,
    avgMargin: null,
    biggestMargin: null,
    playoffMeetings: 0,
    narrative: "First ever meeting between Blaine and Ty.",
  },
  form: {
    home: { games: [], record: "0-0", avgPoints: null, isPriorSeasonOnly: false },
    away: {
      games: [{ season: "2025", week: 12, points: 392.82, opponentPoints: 326.47, result: "W" }],
      record: "1-0",
      avgPoints: 392.82,
      isPriorSeasonOnly: true,
    },
  },
};

function previewPayload({ mode = "preview", matchups = [PLAYED_SERIES, FIRST_MEETING] } = {}) {
  return {
    league: LEAGUE,
    data: { currentSeason: "2026", currentWeek: 1, mode, isPlayoff: false, matchups },
  };
}

function mockFetch(routes) {
  return vi.fn((url) => {
    for (const [fragment, body] of Object.entries(routes)) {
      if (String(url).includes(fragment)) {
        return Promise.resolve({ ok: true, json: () => Promise.resolve(body) });
      }
    }
    return Promise.resolve({ ok: false, status: 404, json: () => Promise.resolve({}) });
  });
}

describe("PreviewsSection", () => {
  beforeEach(() => {
    globalThis.fetch = mockFetch({
      "matchupPreview": previewPayload(),
      "/api/league/articles": { articles: [] },
    });
  });

  afterEach(() => {
    vi.restoreAllMocks();
  });

  it("renders the structured head-to-head block for an unscored current week", async () => {
    const PreviewsSection = await loadSection();
    render(<PreviewsSection />);
    await waitFor(() => {
      expect(screen.getByText(/Week 1 matchups · 2026/)).toBeTruthy();
    });
    expect(screen.getByText("Jason vs Collin")).toBeTruthy();
    expect(screen.getByText("Blaine vs Ty")).toBeTruthy();
    expect(screen.getByText(/4 meetings · 2-2 · 1 playoff · avg margin/)).toBeTruthy();
  });

  it("shows a first-ever meeting with NO margin, never a zero one", async () => {
    const PreviewsSection = await loadSection();
    render(<PreviewsSection />);
    await waitFor(() => {
      expect(screen.getByText("First meeting")).toBeTruthy();
    });
    // The whole point: "avg margin 0.0" for a series that has never been
    // played says these two always tie. It must appear nowhere.
    expect(screen.queryByText(/avg margin 0/)).toBeNull();
    expect(screen.queryByText(/0 meetings/)).toBeNull();
  });

  it("shows a manager with no prior games as such, not as 0-0", async () => {
    const PreviewsSection = await loadSection();
    render(<PreviewsSection />);
    await waitFor(() => {
      expect(screen.getAllByText(/No prior games/).length).toBeGreaterThan(0);
    });
  });

  it("withholds the structured block once the week is scored", async () => {
    globalThis.fetch = mockFetch({
      "matchupPreview": previewPayload({ mode: "recap" }),
      "/api/league/articles": { articles: [] },
    });
    const PreviewsSection = await loadSection();
    render(<PreviewsSection />);
    // The recap surfaces own a scored week; rendering both would be the
    // second owner this section exists to avoid.
    await waitFor(() => {
      expect(screen.queryByText(/Week 1 matchups · 2026/)).toBeNull();
    });
    expect(screen.queryByText("Jason vs Collin")).toBeNull();
  });

  it("still renders the article slate when the preview section is unavailable", async () => {
    globalThis.fetch = mockFetch({ "/api/league/articles": { articles: [] } });
    const PreviewsSection = await loadSection();
    render(<PreviewsSection />);
    // Degrade, never fail: a 503 on the optional structured block must not
    // take down the tab.
    await waitFor(() => {
      expect(screen.getByText(/No previews yet/)).toBeTruthy();
    });
  });
});

describe("ArticlesSection slate labelling", () => {
  const OLD_ARTICLE = {
    season: "2025",
    week: 17,
    mode: "preview",
    matchupId: 1,
    title: "Down 18.43, with one week to find it",
    home: { displayName: "Ed", teamName: "JasonTuckerFanClub" },
    away: { displayName: "Brent", teamName: "Step Burrow Im Stuck" },
  };

  beforeEach(() => {
    globalThis.fetch = mockFetch({ "/api/league/articles": { articles: [OLD_ARTICLE] } });
  });

  afterEach(() => {
    vi.restoreAllMocks();
  });

  it("says so when the newest slate is not the current week", async () => {
    render(<ArticlesSection mode="preview" currentSeason="2026" currentWeek={1} />);
    await waitFor(() => {
      expect(screen.getByText(/Most recent previews · 2025 Week 17/)).toBeTruthy();
    });
    expect(screen.getByText(/No previews written yet for 2026 Week 1/)).toBeTruthy();
  });

  it("keeps the present-tense subhead when the slate IS the current week", async () => {
    render(<ArticlesSection mode="preview" currentSeason="2025" currentWeek={17} />);
    await waitFor(() => {
      expect(screen.getByText(/Week 17 previews · 2025/)).toBeTruthy();
    });
    expect(screen.getByText(/Wednesday-morning previews/)).toBeTruthy();
  });

  it("does not claim currency when the clock is unknown", async () => {
    // An unknown clock must not be reported as a match OR as a mismatch.
    render(<ArticlesSection mode="preview" />);
    await waitFor(() => {
      expect(screen.getByText(/Week 17 previews · 2025/)).toBeTruthy();
    });
    expect(screen.queryByText(/No previews written yet/)).toBeNull();
  });
});
