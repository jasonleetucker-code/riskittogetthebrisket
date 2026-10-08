/**
 * RecentRealTrades (/trade, C3-CALC-01 / TC-07 + TC-10).
 *
 * Pins the four states the section must keep distinct — no assets,
 * loading, unavailable (no evidence ≠ no trades), populated — that unknown
 * format facts render AS unknown, that the request carries identity refs
 * (ids / board row names / owned pick ids, never matched names), and that
 * the section stays out of the /trade first-load chunk.
 */
import { describe, expect, it, vi, beforeEach, afterEach } from "vitest";
import React from "react";
import fs from "node:fs";
import path from "node:path";
import { render, screen, waitFor, act } from "@testing-library/react";
import RecentRealTrades from "@/components/trade/RecentRealTrades";
import {
  formatTagList,
  referenceQueryFromSides,
  referenceQueryString,
} from "@/lib/recent-real-trades";

const SIDES = [
  {
    assets: [
      { name: "Justin Jefferson", playerId: "6794", assetClass: "offense" },
      { name: "2027 Early 1st", assetClass: "pick" },
    ],
  },
  {
    assets: [
      { name: "2027 Mid 1st", assetClass: "pick", assetId: "pick:dynasty_main:2027:r1:o3" },
      { name: "Ja'Marr Chase", playerId: "7564", assetClass: "offense" },
    ],
  },
];

const OK_BODY = {
  state: "ok",
  since: "2025-10-08",
  ledger: { builtAt: "2026-10-08T08:52:00Z", targetLeague: "dynasty_main" },
  query: { players: ["6794"], picks: [], pickAssetIds: [], unresolved: [] },
  samplingBiases: ["KTC Trade Database: a rolling window."],
  withheld: { game_type_not_verified_dynasty: 2, sharp_trade_without_cohort_manager: 1 },
  truncated: false,
  matchingTrades: 2,
  trades: [
    {
      id: "aaaaaaaaaaaaaaaa",
      occurredDate: "2026-10-01",
      sidesSemantics: "packages_orientation_unstated",
      provenance: ["KTC_MARKET"],
      sides: [
        [
          { kind: "player", label: "Justin Jefferson", match: "exact" },
          {
            kind: "pick",
            label: "2027 Round 1",
            match: "round",
            pick: { year: 2027, round: 1, grade: "generic", gradeNote: "ktc_mid_is_vendor_default" },
          },
        ],
        [{ kind: "unresolved", label: "J. Smith", match: null }],
      ],
      formatTags: {
        superflex: true,
        teams: 12,
        starters: 10,
        ktcTepLevel: 2,
        teScoringEdge: null,
        pprPerReception: null,
        ktcPprCode: null,
        idp: false,
        bestBall: null,
        season: null,
      },
      formatTiming: "unknown",
      formatMatch: { appliesToThisLeague: true, disposition: "BROAD_CONTEXT" },
      possibleOverlap: false,
    },
    {
      id: "bbbbbbbbbbbbbbbb",
      occurredDate: "2026-09-10",
      sidesSemantics: "received_per_roster",
      provenance: ["OWN_LEAGUE"],
      sides: [[{ kind: "player", label: null, match: null }], [{ kind: "pick", label: "2028 Round 2", match: "exact" }]],
      formatTags: { teams: 10 },
      formatTiming: "post_trade",
      formatMatch: { appliesToThisLeague: false, disposition: null },
      possibleOverlap: true,
      caveats: [
        "sleeper_trade_faab_component_not_recorded",
        "released_in_trade:2",
        "partial_record_adds_without_sender:1",
      ],
    },
  ],
};

function mockFetch(impl) {
  const fn = vi.fn(impl);
  globalThis.fetch = fn;
  return fn;
}

describe("referenceQueryFromSides", () => {
  it("sends ids, board pick names and owned pick ids — never names for players", () => {
    const q = referenceQueryFromSides(SIDES);
    expect(q).toEqual({
      players: ["6794", "7564"],
      picks: ["2027 Early 1st"],
      pickAssetIds: ["pick:dynasty_main:2027:r1:o3"],
    });
    const qs = new URLSearchParams(referenceQueryString(q, "dynasty_main"));
    expect(qs.get("players")).toBe("6794,7564");
    expect(qs.get("pickAssetIds")).toBe("pick:dynasty_main:2027:r1:o3");
    expect(qs.get("leagueKey")).toBe("dynasty_main");
  });

  it("a player with no id is not sent (no name matching)", () => {
    const q = referenceQueryFromSides([{ assets: [{ name: "Somebody", assetClass: "offense" }] }]);
    expect(q.players).toEqual([]);
  });
});

describe("formatTagList", () => {
  it("renders every unknown fact as unknown, never a default", () => {
    const tags = formatTagList({ teams: 10 });
    const byKey = Object.fromEntries(tags.map((t) => [t.key, t]));
    expect(byKey.teams).toEqual({ key: "teams", text: "10 teams", known: true });
    for (const k of ["qb", "starters", "te", "ppr", "idp"]) {
      expect(byKey[k].known).toBe(false);
      expect(byKey[k].text).toMatch(/\?$/);
    }
  });

  it("labels KTC vendor settings as KTC's, scoring-card facts plainly", () => {
    const byKey = Object.fromEntries(
      formatTagList({ superflex: false, ktcTepLevel: 3, pprPerReception: 0.5 }).map((t) => [t.key, t.text]),
    );
    expect(byKey.qb).toBe("1QB");
    expect(byKey.te).toBe("TE+++ (KTC setting)");
    expect(byKey.ppr).toBe("0.5 PPR");
  });
});

describe("RecentRealTrades", () => {
  const realFetch = globalThis.fetch;
  beforeEach(() => {
    vi.useFakeTimers({ shouldAdvanceTime: true });
  });
  afterEach(() => {
    vi.useRealTimers();
    globalThis.fetch = realFetch;
  });

  it("empty calculator: asks for assets and makes no request", () => {
    const fetchFn = mockFetch(async () => ({ ok: true, json: async () => OK_BODY }));
    render(<RecentRealTrades sides={[{ assets: [] }, { assets: [] }]} leagueKey="dynasty_main" />);
    expect(screen.getByText("No assets yet")).toBeTruthy();
    act(() => vi.advanceTimersByTime(1000));
    expect(fetchFn).not.toHaveBeenCalled();
  });

  it("loading: a busy skeleton while the request is in flight", () => {
    mockFetch(() => new Promise(() => {}));
    render(<RecentRealTrades sides={SIDES} leagueKey="dynasty_main" />);
    expect(screen.getByLabelText("Loading recent real trades")).toBeTruthy();
  });

  it("unavailable: says evidence is missing, not that there are no trades", async () => {
    mockFetch(async () => ({
      ok: false,
      status: 503,
      json: async () => ({ error: "trade_ledger_unavailable", state: "unavailable" }),
    }));
    render(<RecentRealTrades sides={SIDES} leagueKey="dynasty_main" />);
    await act(async () => {
      vi.advanceTimersByTime(500);
    });
    await waitFor(() => expect(screen.getByText("Real-trade evidence unavailable")).toBeTruthy());
    expect(screen.queryByText("No recorded trades")).toBeNull();
  });

  it("request error (4xx): says the request was rejected, not that evidence is missing", async () => {
    mockFetch(async () => ({
      ok: false,
      status: 400,
      json: async () => ({ error: "bad_request" }),
    }));
    render(<RecentRealTrades sides={SIDES} leagueKey="dynasty_main" />);
    await act(async () => {
      vi.advanceTimersByTime(500);
    });
    await waitFor(() => expect(screen.getByText("Request not understood")).toBeTruthy());
    expect(screen.queryByText("Real-trade evidence unavailable")).toBeNull();
  });

  it("ok with no trades: an explicit empty state", async () => {
    mockFetch(async () => ({ ok: true, json: async () => ({ ...OK_BODY, trades: [] }) }));
    render(<RecentRealTrades sides={SIDES} leagueKey="dynasty_main" />);
    await act(async () => {
      vi.advanceTimersByTime(500);
    });
    await waitFor(() => expect(screen.getByText("No recorded trades")).toBeTruthy());
  });

  it("populated: assets, matches, format tags, timing and source", async () => {
    const fetchFn = mockFetch(async () => ({ ok: true, json: async () => OK_BODY }));
    render(<RecentRealTrades sides={SIDES} leagueKey="dynasty_main" />);
    await act(async () => {
      vi.advanceTimersByTime(500);
    });
    await waitFor(() => expect(screen.getByText("2026-10-01")).toBeTruthy());
    const url = String(fetchFn.mock.calls[0][0]);
    expect(url).toMatch(/^\/api\/market\/trades\/reference\?/);
    expect(url).toContain("leagueKey=dynasty_main");

    expect(screen.getByText("KTC trade database")).toBeTruthy();
    expect(screen.getByText("This league")).toBeTruthy();
    expect(screen.getByText("Package A")).toBeTruthy();
    expect(screen.getByText("Team 2 received")).toBeTruthy();
    // Matched assets say so in TEXT, not colour alone.
    expect(screen.getAllByText(/\(on your calculator\)/).length).toBe(2);
    expect(screen.getByText(/\(same round\)/)).toBeTruthy();
    expect(screen.getByText("Player not on board")).toBeTruthy();
    // TC-10 tags: known and unknown both visible.
    expect(screen.getByText("SF")).toBeTruthy();
    expect(screen.getByText("TE++ (KTC setting)")).toBeTruthy();
    expect(screen.getAllByText("PPR ?").length).toBe(2);
    expect(screen.getByText("QB ?")).toBeTruthy();
    // Evidence timing and the ledger's own disposition, or why there is none.
    expect(screen.getByText(/Format timing unknown · Broad context only/)).toBeTruthy();
    expect(
      screen.getByText(/Format captured after the trade · Format match not computed for this league/),
    ).toBeTruthy();
    expect(screen.getByText(/May duplicate another listed trade/)).toBeTruthy();
    expect(screen.getByText(/Reference evidence, not a valuation/)).toBeTruthy();
    // KTC's default "Mid" never reads as a stated tier.
    expect(screen.getByText(/2027 Round 1 \(KTC "Mid" — tier not stated\)/)).toBeTruthy();
    // Caveats in words.
    expect(screen.getByText(/FAAB in the trade not recorded/)).toBeTruthy();
    expect(screen.getByText(/2 players released in the trade \(not exchanged\)/)).toBeTruthy();
    expect(screen.getByText(/Partial record — part of the trade was not captured/)).toBeTruthy();
    // Game-type withholding is stated, privacy withholding only counted.
    expect(
      screen.getByText(/2 not shown because the league was not verified as dynasty; 1 not shown for privacy/),
    ).toBeTruthy();
  });
});

describe("/trade wiring", () => {
  const page = fs.readFileSync(path.resolve(__dirname, "../../app/trade/page.jsx"), "utf8");

  it("loads the section only through `dyn` (React.lazy), never statically", () => {
    expect(page).not.toMatch(/import\s+RecentRealTrades\b/);
    expect(page).toMatch(
      /const RecentRealTrades = dyn\(\s*\(\) => import\("@\/components\/trade\/RecentRealTrades"\)/,
    );
  });

  it("is mounted only while its panel is open (no fetch, no refetch while folded)", () => {
    const at = page.indexOf('title="Recent real trades"');
    expect(at).toBeGreaterThan(-1);
    const block = page.slice(at, page.indexOf("</Panel>", at));
    expect(block).toMatch(/collapsed=\{!realTradesOpen\}/);
    expect(block).toMatch(/\{realTradesOpen \? \(\s*<RecentRealTrades\b/);
    expect(page).toMatch(/const \[realTradesOpen, setRealTradesOpen\] = useState\(false\)/);
  });
});
