/**
 * The Power tab publishes ONE ranking.
 *
 * It used to carry three at once: a Canonical / Results-only lens toggle, a
 * week dropdown of results-only reconstructions (labelled "· diagnostic", and
 * reaching back into previous seasons), and a "Power score over time" chart
 * built from that same reconstruction. Three surfaces, three orderings, one
 * page — and the share card next to them could disagree with all of them.
 *
 * The diagnostic lens still exists in the ENGINE (``?lens=results_only``, spec
 * section 3). It is not a thing this page offers, so these tests assert its
 * absence structurally rather than trusting that nobody re-adds the button.
 *
 * Movement is backend-owned throughout: both the table and its share card read
 * ``weekRankDelta`` from the current row. Frozen snapshots own history only.
 * There is no rank arithmetic in the component to test, and that is the point.
 */

import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { render, screen, waitFor, fireEvent, within } from "@testing-library/react";

vi.mock("@/components/ui", () => ({
  LoadingState: ({ message }) => <div>{message}</div>,
  EmptyState: ({ title, message }) => (
    <div>
      <h3>{title}</h3>
      <p>{message}</p>
    </div>
  ),
}));

vi.mock("../../app/league/shared-server.jsx", () => ({
  Card: ({ title, subtitle, children }) => (
    <section>
      {title ? <h2>{title}</h2> : null}
      {subtitle ? <p>{subtitle}</p> : null}
      {children}
    </section>
  ),
}));

async function renderFresh() {
  // The component caches its fetch at module scope, so every test needs a
  // fresh module instance or the second one asserts against the first's data.
  vi.resetModules();
  const mod = await import("../../app/league/sections/ros-power.jsx");
  return mod.default;
}

function serve(body) {
  const calls = [];
  global.fetch = vi.fn((url) => {
    calls.push(String(url));
    return Promise.resolve({
      ok: true,
      json: () =>
        Promise.resolve(String(url).includes("playoffOdds") ? { owners: [] } : body),
    });
  });
  return calls;
}

/** A published week, in the shape ``power_snapshots`` freezes it. */
function snapshotWeek(week, rows, { preseason = false } = {}) {
  return {
    season: "2026",
    week,
    preseason,
    ranking: rows.map((row) => ({
      ownerId: row.ownerId,
      displayName: row.displayName,
      teamName: row.teamName,
      rank: row.rank,
      powerScore: row.powerScore ?? null,
      priorRank: row.priorRank ?? null,
      rankDelta: row.rankDelta ?? null,
    })),
  };
}

function payload({ ranking, shareSnapshot = null, officialHistory = [], blend = {}, asOfWeek = 1 }) {
  return {
    currentRanking: ranking,
    unrankable: null,
    lens: "canonical",
    weights: { team_ros_strength: 0.4, all_play: 0.2 },
    effectiveWeights: { team_ros_strength: 0.75, all_play: 0.25 },
    blend: { forwardWeight: 0.75, resultsWeight: 0.25, ...blend },
    missingInputs: ["team_vorp"],
    rosTeamStrengthAvailable: true,
    preseason: false,
    asOfSeason: "2026",
    asOfWeek,
    shareSnapshot,
    officialSnapshot: shareSnapshot,
    officialHistory,
    // Still on the payload for the engine's diagnostic lens. The page must
    // not render it.
    trend: {
      lens: "results_only",
      weeks: [
        { season: "2025", week: 12, rankings: [], effectiveWeights: {}, blend: {} },
        { season: "2026", week: 1, rankings: [], effectiveWeights: {}, blend: {} },
      ],
      seriesByOwner: {
        o1: [
          { season: "2025", week: 12, powerScore: 70, rank: 4 },
          { season: "2026", week: 1, powerScore: 80, rank: 1 },
        ],
      },
    },
  };
}

const ROWS = [
  { ownerId: "o1", displayName: "Alice", teamName: "A Team", rank: 1, powerScore: 92.1 },
  { ownerId: "o2", displayName: "Bob", teamName: "B Team", rank: 2, powerScore: 80.4 },
  { ownerId: "o3", displayName: "Cass", teamName: "C Team", rank: 3, powerScore: 64.0 },
];

describe("RosPowerSection — one ranking", () => {
  beforeEach(() => vi.clearAllMocks());
  afterEach(() => vi.restoreAllMocks());

  it("fetches the one ranking with no lens parameter, and offers no way to pick another", async () => {
    const calls = serve(payload({ ranking: ROWS }));
    const RosPowerSection = await renderFresh();
    render(<RosPowerSection />);
    await waitFor(() => expect(screen.getAllByText("Alice").length).toBeGreaterThan(0));

    expect(calls.filter((u) => u.includes("rosPower"))).toEqual([
      "/api/public/league/rosPower",
    ]);
    expect(calls.some((u) => u.includes("lens="))).toBe(false);

    expect(screen.queryByRole("button", { name: /results only/i })).toBeNull();
    expect(screen.queryByRole("button", { name: /^canonical$/i })).toBeNull();
    // The week dropdown was the other way to reach a second ordering.
    expect(screen.queryByRole("combobox")).toBeNull();
  });

  it("never renders the results-only reconstruction, even though the payload still carries it", async () => {
    serve(payload({ ranking: ROWS }));
    const RosPowerSection = await renderFresh();
    const { container } = render(<RosPowerSection />);
    await waitFor(() => expect(screen.getAllByText("Alice").length).toBeGreaterThan(0));

    expect(container.textContent).not.toContain("diagnostic");
    expect(container.textContent).not.toContain("Results only");
    expect(container.textContent).not.toContain("results-only");
    // 2025 weeks were reachable from the old dropdown; nothing on the page
    // may reach a previous season now.
    expect(container.textContent).not.toContain("2025");
  });

  it("states the blend it actually applied, naming the missing input", async () => {
    serve(payload({ ranking: ROWS }));
    const RosPowerSection = await renderFresh();
    const { container } = render(<RosPowerSection />);
    await waitFor(() => expect(screen.getAllByText("Alice").length).toBeGreaterThan(0));

    expect(container.textContent).toContain(
      "Blend: 75% forward-looking strength + 25% results",
    );
    expect(container.textContent).toContain("Forward-looking ROS strength (75%)");
    // Missing is reported, never rendered as a zero-weight component.
    expect(container.textContent).toContain("Missing inputs: team_vorp");
    expect(container.textContent).not.toContain("Realized lineup VORP/PAR (0%)");
  });

  it("shows table movement from the backend's official comparison", async () => {
    const ranking = [
      { ...ROWS[0], weekRankDelta: 1 },
      { ...ROWS[1], weekRankDelta: -1 },
      { ...ROWS[2], weekRankDelta: 0 },
    ];
    serve(payload({ ranking }));
    const RosPowerSection = await renderFresh();
    const { container } = render(<RosPowerSection />);
    await waitFor(() => expect(screen.getAllByText("Alice").length).toBeGreaterThan(0));

    expect(container.textContent).toContain("▲ 1");
    expect(container.textContent).toContain("▼ 1");
    // A zero delta is "did not move": "—", the SAME glyph the share card uses
    // (owner spec, 2026-09-23). The table used to say "•" while the card said
    // "—" for the same row.
    const cassRow = within(screen.getByRole("table")).getAllByRole("row")[3];
    const cells = within(cassRow).getAllByRole("cell");
    expect(cells[7].textContent).toBe("—");
    expect(container.textContent).not.toContain("•");
  });
});

describe("Power methodology text — rendered from the calculation's own weights", () => {
  beforeEach(() => vi.clearAllMocks());
  afterEach(() => vi.restoreAllMocks());

  function methodology(parts, inactive = []) {
    return {
      components: [
        ...parts.map(([key, pct, group]) => ({
          key,
          group,
          weight: pct / 100,
          displayPct: pct,
          status: "active",
          reason: null,
          activatesAfterGames: null,
        })),
        ...inactive.map((key) => ({
          key,
          group: "results",
          weight: 0,
          displayPct: 0,
          status: "inactive",
          reason: "redundant",
          activatesAfterGames: 4,
        })),
        {
          key: "team_vorp",
          group: "results",
          weight: 0,
          displayPct: 0,
          status: "unavailable",
          reason: "not yet available",
          activatesAfterGames: null,
        },
      ],
      forwardDisplayPct: parts.filter(([, , g]) => g === "forward").reduce((a, [, p]) => a + p, 0),
      resultsDisplayPct: parts.filter(([, , g]) => g === "results").reduce((a, [, p]) => a + p, 0),
    };
  }

  async function renderWith(m, extra = {}) {
    serve({ ...payload({ ranking: ROWS }), methodology: m, ...extra });
    const RosPowerSection = await renderFresh();
    render(<RosPowerSection />);
    await waitFor(() => expect(screen.getAllByText("Alice").length).toBeGreaterThan(0));
    return {
      blend: screen.getByTestId("power-methodology-blend").textContent,
      formula: screen.getByTestId("power-methodology-formula").textContent,
    };
  }

  const pcts = (text) => [...text.matchAll(/\((\d+)%/g)].map((m) => Number(m[1]));

  it("shows the effective early-season blend, with recent form at 0% and when it activates", async () => {
    const m = methodology(
      [
        ["team_ros_strength", 40, "forward"],
        ["all_play", 45, "results"],
        ["wl_record", 15, "results"],
      ],
      ["recent"],
    );
    // A stale blend on the same payload must not be what the reader sees.
    const { blend, formula } = await renderWith(m, {
      blend: { forwardWeight: 0.3, resultsWeight: 0.7 },
    });
    expect(blend).toBe("Blend: 40% forward-looking strength + 60% results.");
    expect(formula).toBe(
      "Season all-play (45%) + Forward-looking ROS strength (40%) + Official record (15%)" +
        " + Recent form (last 4) (0% — activates after 4 games)",
    );
    expect(pcts(formula).reduce((a, b) => a + b, 0)).toBe(100);
    expect(formula).not.toContain("30%");
    expect(formula).not.toContain("VORP");
  });

  it("renders the backend's displayPct verbatim, so a 34/33/33 split still sums to 100", async () => {
    const m = methodology([
      ["team_ros_strength", 34, "forward"],
      ["all_play", 33, "results"],
      ["wl_record", 33, "results"],
    ]);
    const { blend, formula } = await renderWith(m);
    expect(blend).toBe("Blend: 34% forward-looking strength + 66% results.");
    expect(pcts(formula)).toEqual([34, 33, 33]);
    expect(formula).not.toContain("activates");
  });

  it("follows the model into late season without any week-specific wording", async () => {
    const m = methodology([
      ["team_ros_strength", 30, "forward"],
      ["all_play", 42, "results"],
      ["recent", 14, "results"],
      ["wl_record", 14, "results"],
    ]);
    const { blend, formula } = await renderWith(m);
    expect(blend).toBe("Blend: 30% forward-looking strength + 70% results.");
    expect(pcts(formula).reduce((a, b) => a + b, 0)).toBe(100);
    expect(formula).toContain("Recent form (last 4) (14%)");
  });
});

describe("LeaguePowerShareCard — movement since last week", () => {
  beforeEach(() => vi.clearAllMocks());
  afterEach(() => vi.restoreAllMocks());

  const WEEK_ZERO = snapshotWeek(
    0,
    [
      { ownerId: "o1", displayName: "Alice", teamName: "A Team", rank: 1 },
      { ownerId: "o2", displayName: "Bob", teamName: "B Team", rank: 3 },
      { ownerId: "o3", displayName: "Cass", teamName: "C Team", rank: 2 },
    ],
    { preseason: true },
  );

  const WEEK_ONE = snapshotWeek(1, [
    { ...ROWS[0], priorRank: 1, rankDelta: 0 },
    { ...ROWS[1], priorRank: 3, rankDelta: 1 },
    { ...ROWS[2], priorRank: 2, rankDelta: -1 },
  ]);

  async function openCard(body) {
    serve(body);
    const RosPowerSection = await renderFresh();
    render(<RosPowerSection />);
    await waitFor(() => expect(screen.getAllByText("Alice").length).toBeGreaterThan(0));
    fireEvent.click(screen.getByRole("button", { name: /share rankings/i }));
    return screen.findByTestId("league-power-share-card");
  }

  it("renders current backend movement, not frozen snapshot movement", async () => {
    const card = await openCard(
      payload({
        ranking: [
          { ...ROWS[0], previousOfficialRank: 1, weekRankDelta: 0 },
          { ...ROWS[1], previousOfficialRank: 3, weekRankDelta: 1 },
          { ...ROWS[2], previousOfficialRank: 2, weekRankDelta: -1 },
        ],
        shareSnapshot: WEEK_ONE,
        officialHistory: [WEEK_ZERO, WEEK_ONE],
      }),
    );

    expect(card.textContent).toContain("League Power Rankings");
    expect(card.textContent).toContain("Week 1");
    expect(card.textContent).toContain("Current");
    expect(card.textContent).not.toContain(" · Official");
    expect(card.textContent).toContain("▲ 1"); // Bob, 3 -> 2
    expect(card.textContent).toContain("▼ 1"); // Cass, 2 -> 3
    // Alice held her rank: that is a dash, not a NEW and not a zero.
    expect(card.textContent).not.toContain("NEW");

    // Spec section 10: rank + owner/team + movement, nothing else.
    expect(card.textContent).not.toContain("92.1");
    expect(card.textContent).not.toContain("Blend");
    expect(card.textContent).not.toContain("Missing inputs");
  });

  it("names the week the arrows are measured against", async () => {
    const card = await openCard(
      payload({
        ranking: [
          { ...ROWS[0], previousOfficialRank: 1, weekRankDelta: 0 },
          { ...ROWS[1], previousOfficialRank: 3, weekRankDelta: 1 },
          { ...ROWS[2], previousOfficialRank: 2, weekRankDelta: -1 },
        ],
        shareSnapshot: WEEK_ONE,
        officialHistory: [WEEK_ZERO, WEEK_ONE],
      }),
    );
    expect(card.textContent).toContain("vs preseason");
  });

  it("claims no baseline when the previous week was never published", async () => {
    const orphan = snapshotWeek(1, [
      { ...ROWS[0], priorRank: null, rankDelta: null },
      { ...ROWS[1], priorRank: null, rankDelta: null },
      { ...ROWS[2], priorRank: null, rankDelta: null },
    ]);
    const card = await openCard(
      payload({ ranking: ROWS, shareSnapshot: orphan, officialHistory: [orphan] }),
    );

    // Every row is NEW, and the header does not invent a comparison week.
    expect(card.textContent.match(/NEW/g)).toHaveLength(3);
    expect(card.textContent).not.toContain("vs ");
    expect(card.textContent).not.toContain("▲");
    expect(card.textContent).not.toContain("▼");
  });

  it("marks only the rows that genuinely have no baseline as NEW", async () => {
    // A manager who joined after the baseline week: no prior rank for them,
    // real movement for everyone else. Per-row, never per-card.
    const mixed = snapshotWeek(1, [
      { ...ROWS[0], priorRank: 2, rankDelta: 1 },
      { ...ROWS[1], priorRank: 1, rankDelta: -1 },
      { ...ROWS[2], priorRank: null, rankDelta: null },
    ]);
    const card = await openCard(
      payload({
        ranking: [
          { ...ROWS[0], previousOfficialRank: 2, weekRankDelta: 1 },
          { ...ROWS[1], previousOfficialRank: 1, weekRankDelta: -1 },
          { ...ROWS[2], previousOfficialRank: null, weekRankDelta: null },
        ],
        shareSnapshot: mixed,
        officialHistory: [WEEK_ZERO, mixed],
      }),
    );

    expect(card.textContent.match(/NEW/g)).toHaveLength(1);
    expect(card.textContent).toContain("▲ 1");
    expect(card.textContent).toContain("▼ 1");
  });
  it.each(["shareSnapshot", "officialSnapshot"])(
    "matches all 12 table ranks and arrows despite a stale %s",
    async (snapshotKey) => {
      // Different order, names, movement and methodology in the frozen data.
      // Checking only card presence or labels would miss the reported defect.
      const ranking = Array.from({ length: 12 }, (_, i) => ({
        ownerId: `owner-${i}`,
        displayName: i === 0 ? "Alice" : `Manager ${i}`,
        teamName: `Current team ${i}`,
        rank: i + 1,
        powerScore: 100 - i,
        previousOfficialRank: 12 - i,
        weekRankDelta: 11 - 2 * i,
      }));
      const frozen = snapshotWeek(2, [...ranking].reverse().map((row, i) => ({
        ...row,
        rank: i + 1,
        teamName: `Old team ${i}`,
        rankDelta: 0,
        priorRank: i + 1,
      })));
      frozen.methodologyVersion = "old-methodology";
      const body = {
        ...payload({ ranking, asOfWeek: 2 }),
        methodologyVersion: "new-methodology",
        [snapshotKey]: frozen,
      };
      const frozenBefore = JSON.stringify(frozen);
      const card = await openCard(body);
      const tableRows = within(screen.getByRole("table")).getAllByRole("row").slice(1);
      const cardRows = within(card).getAllByTestId("league-power-share-row");
      expect(cardRows).toHaveLength(12);
      expect(tableRows).toHaveLength(12);
      cardRows.forEach((cardRow, i) => {
        const cells = within(tableRows[i]).getAllByRole("cell");
        expect(cardRow.children[0].textContent).toBe(cells[0].textContent);
        expect(within(cardRow).getByText(ranking[i].displayName)).toBeTruthy();
        expect(within(cells[1]).getByText(ranking[i].displayName)).toBeTruthy();
        expect(within(cardRow).getByText(ranking[i].teamName)).toBeTruthy();
        expect(cardRow.children[2].textContent).toBe(cells[7].textContent);
      });
      expect(card.textContent).not.toContain("Old team");
      expect(card.textContent).not.toContain(" · Official");
      expect(JSON.stringify(frozen)).toBe(frozenBefore);
      // Opening/closing the card must not fetch a different ranking response.
      fireEvent.click(screen.getByRole("button", { name: /hide share card/i }));
      expect(screen.queryByTestId("league-power-share-card")).toBeNull();
      fireEvent.click(screen.getByRole("button", { name: /share rankings/i }));
      expect(screen.getAllByTestId("league-power-share-row")).toHaveLength(12);
      expect(global.fetch.mock.calls.filter(([url]) => String(url).includes("rosPower"))).toHaveLength(1);
    },
  );

  it("uses the current week and its exact N-1 baseline, not the stale card's week", async () => {
    const card = await openCard(payload({
      ranking: [
        { ...ROWS[1], rank: 1, previousOfficialRank: 2, weekRankDelta: 1 },
        { ...ROWS[0], rank: 2, previousOfficialRank: 1, weekRankDelta: -1 },
        { ...ROWS[2], previousOfficialRank: 3, weekRankDelta: 0 },
      ],
      asOfWeek: 2,
      shareSnapshot: WEEK_ONE,
      officialHistory: [WEEK_ZERO, WEEK_ONE],
    }));
    expect(card.textContent).toContain("2026 · Week 2 · Current");
    expect(card.textContent).toContain("vs Week 1");
    expect(card.textContent).not.toContain("vs preseason");
    expect(card.textContent).not.toContain("NEW");
  });

  it("does not substitute an older publication when exactly N-1 is missing", async () => {
    const card = await openCard(payload({
      ranking: ROWS.map((row) => ({ ...row, previousOfficialRank: null, weekRankDelta: null })),
      asOfWeek: 3,
      shareSnapshot: WEEK_ONE,
      officialHistory: [WEEK_ZERO, WEEK_ONE],
    }));
    expect(card.textContent).toContain("Week 3 · Current");
    expect(card.textContent).not.toContain("vs ");
    expect(card.textContent.match(/NEW/g)).toHaveLength(3);
  });

  it("shares the current ranking without any published snapshot", async () => {
    const card = await openCard(payload({ ranking: ROWS }));
    expect(within(card).getAllByTestId("league-power-share-row")).toHaveLength(3);
    expect(card.textContent).toContain("Week 1 · Current");
    expect(card.textContent).not.toContain(" · Official");
  });

  it("labels week zero as current preseason without leaking a prior-season snapshot", async () => {
    const card = await openCard({
      ...payload({ ranking: ROWS, asOfWeek: 0, shareSnapshot: { ...WEEK_ONE, season: "2025" } }),
      preseason: true,
    });
    expect(card.textContent).toContain("2026 · Preseason · Current");
    expect(card.textContent).not.toContain("2025");
    expect(card.textContent).not.toContain("Week 1");
    expect(card.textContent).not.toContain("vs ");
  });

  it("does not call a known prior rank NEW when its current delta is unavailable", async () => {
    const card = await openCard(payload({
      ranking: ROWS.map((row) => ({ ...row, previousOfficialRank: row.rank, weekRankDelta: null })),
      shareSnapshot: WEEK_ONE,
    }));
    expect(card.textContent).not.toContain("NEW");
    expect(card.textContent).not.toContain("▲");
    expect(card.textContent).not.toContain("▼");
  });

  it("does not offer a stale share card when the current ranking is empty or unrankable", async () => {
    serve({
      ...payload({ ranking: [], shareSnapshot: WEEK_ONE }),
      unrankable: { explanation: "Current evidence is unavailable" },
    });
    const RosPowerSection = await renderFresh();
    render(<RosPowerSection />);
    await screen.findByText("Current evidence is unavailable");
    expect(screen.queryByRole("button", { name: /share rankings/i })).toBeNull();
    expect(screen.queryByTestId("league-power-share-card")).toBeNull();
  });

  // ── 2026-09-23 audit: dropped owners, false NEW, wrong week label ─────

  function twelveRows({ previous = (i) => i + 1, delta = () => 0 } = {}) {
    return Array.from({ length: 12 }, (_, i) => ({
      ownerId: `owner-${i}`,
      displayName: i === 0 ? "Alice" : `Manager ${i}`,
      teamName: `Team ${i}`,
      rank: i + 1,
      powerScore: 100 - i,
      previousOfficialRank: previous(i),
      weekRankDelta: delta(i),
    }));
  }

  it("renders exactly the canonical 12 rows on the card, in the table's order and glyphs", async () => {
    // Deltas cover every glyph: up, down, unchanged, and NEW.
    const ranking = twelveRows({
      previous: (i) => (i === 11 ? null : [3, 2, 1][i] ?? i + 1),
      delta: (i) => (i === 11 ? null : [2, 0, -2][i] ?? 0),
    });
    const card = await openCard({
      ...payload({ ranking, asOfWeek: 2 }),
      expectedTeamCount: 12,
      rankingComplete: true,
      movementBaseline: { status: "compared", week: 1, preseason: false },
    });
    const cardRows = within(card).getAllByTestId("league-power-share-row");
    const tableRows = within(screen.getByRole("table")).getAllByRole("row").slice(1);
    expect(cardRows).toHaveLength(12);
    expect(tableRows).toHaveLength(12);
    cardRows.forEach((cardRow, i) => {
      const cells = within(tableRows[i]).getAllByRole("cell");
      expect(cardRow.children[0].textContent).toBe(String(ranking[i].rank));
      expect(cells[0].textContent).toBe(String(ranking[i].rank));
      expect(within(cardRow).getByText(ranking[i].displayName)).toBeTruthy();
      expect(cardRow.children[2].textContent).toBe(cells[7].textContent);
    });
    expect(cardRows[0].children[2].textContent).toBe("▲ 2"); // previous 3 -> current 1
    expect(cardRows[1].children[2].textContent).toBe("—"); // previous 2 -> current 2
    expect(cardRows[2].children[2].textContent).toBe("▼ 2"); // previous 1 -> current 3
    expect(cardRows[11].children[2].textContent).toBe("NEW"); // genuinely no previous rank
    expect(card.textContent.match(/NEW/g)).toHaveLength(1);
    expect(card.textContent).toContain("2026 · Week 2 · Current · vs Week 1 official");
  });

  it("offers no share card for a ranking the backend marks incomplete", async () => {
    serve({
      ...payload({ ranking: twelveRows().slice(0, 10), asOfWeek: 2 }),
      expectedTeamCount: 12,
      rankingComplete: false,
    });
    const RosPowerSection = await renderFresh();
    render(<RosPowerSection />);
    await waitFor(() => expect(screen.getAllByText("Alice").length).toBeGreaterThan(0));
    fireEvent.click(screen.getByRole("button", { name: /share rankings/i }));
    const notice = await screen.findByTestId("league-power-share-incomplete");
    expect(notice.textContent).toContain("10 of 12 teams");
    expect(screen.queryByTestId("league-power-share-card")).toBeNull();
    expect(screen.queryAllByTestId("league-power-share-row")).toHaveLength(0);
  });

  it("offers no share card when the row count disagrees with the league size", async () => {
    serve({ ...payload({ ranking: twelveRows().slice(0, 10), asOfWeek: 2 }), expectedTeamCount: 12 });
    const RosPowerSection = await renderFresh();
    render(<RosPowerSection />);
    await waitFor(() => expect(screen.getAllByText("Alice").length).toBeGreaterThan(0));
    fireEvent.click(screen.getByRole("button", { name: /share rankings/i }));
    expect(await screen.findByTestId("league-power-share-incomplete")).toBeTruthy();
    expect(screen.queryByTestId("league-power-share-card")).toBeNull();
  });

  it("never renders NEW when a previous publication gave every team a rank", async () => {
    const card = await openCard({
      ...payload({ ranking: twelveRows({ delta: (i) => (i % 2 ? 1 : -1) }), asOfWeek: 3 }),
      expectedTeamCount: 12,
      rankingComplete: true,
      movementBaseline: { status: "compared", week: 2, preseason: false },
    });
    expect(card.textContent).not.toContain("NEW");
  });

  it("reads '—', not NEW, when the movement comparison itself was unavailable", async () => {
    const card = await openCard({
      ...payload({
        ranking: twelveRows({ previous: () => null, delta: () => null }),
        asOfWeek: 2,
      }),
      expectedTeamCount: 12,
      rankingComplete: true,
      movementBaseline: { status: "unavailable", reason: "lookup failed" },
    });
    expect(card.textContent).not.toContain("NEW");
    expect(card.textContent).not.toContain("vs ");
  });

  it("labels an in-season week-0 table 'Week 1 in progress', not Preseason", async () => {
    const card = await openCard({
      ...payload({ ranking: twelveRows({ previous: () => null, delta: () => null }), asOfWeek: 0 }),
      preseason: false,
      expectedTeamCount: 12,
      rankingComplete: true,
      movementBaseline: { status: "not_applicable" },
    });
    expect(card.textContent).toContain("2026 · Week 1 in progress · Current");
    expect(card.textContent).not.toContain("Preseason");
    expect(card.textContent).not.toContain("NEW");
  });
});

describe("Rank history", () => {
  beforeEach(() => vi.clearAllMocks());
  afterEach(() => vi.restoreAllMocks());

  it("plots the published weeks, including a baseline week that carries no score", async () => {
    const weekZero = snapshotWeek(
      0,
      [
        { ownerId: "o1", displayName: "Alice", rank: 1 },
        { ownerId: "o2", displayName: "Bob", rank: 2 },
      ],
      { preseason: true },
    );
    const weekOne = snapshotWeek(1, [
      { ownerId: "o1", displayName: "Alice", rank: 2, powerScore: 80 },
      { ownerId: "o2", displayName: "Bob", rank: 1, powerScore: 85 },
    ]);
    serve(payload({ ranking: ROWS, officialHistory: [weekZero, weekOne] }));
    const RosPowerSection = await renderFresh();
    const { container } = render(<RosPowerSection />);
    await waitFor(() => expect(screen.getAllByText("Alice").length).toBeGreaterThan(0));

    const svg = container.querySelector('svg[aria-label="Published rank by week per manager"]');
    expect(svg).toBeTruthy();
    // Two lines: the score-less baseline week is a point on both of them.
    expect(svg.querySelectorAll("path").length).toBe(2);
    expect(svg.textContent).toContain("Pre");
    expect(svg.textContent).toContain("Wk 1");
  });

  it("says history has not started rather than drawing a one-point chart", async () => {
    serve(
      payload({
        ranking: ROWS,
        officialHistory: [snapshotWeek(1, [{ ownerId: "o1", displayName: "Alice", rank: 1 }])],
      }),
    );
    const RosPowerSection = await renderFresh();
    const { container } = render(<RosPowerSection />);
    await waitFor(() => expect(screen.getAllByText("Alice").length).toBeGreaterThan(0));

    expect(container.textContent).toContain(
      "Rank history begins once a second week is published",
    );
    expect(
      container.querySelector('svg[aria-label="Published rank by week per manager"]'),
    ).toBeNull();
  });
});


describe("PPG/Recent denominator — the reported defect", () => {
  beforeEach(() => vi.clearAllMocks());
  afterEach(() => vi.restoreAllMocks());

  const ROWS_WITH_GAMES = [
    {
      ...ROWS[0],
      gamesUsed: 1,
      recentGamesUsed: 1,
      components: { pointsPerGame: 453.37, recentAvg: 453.37 },
    },
    {
      ...ROWS[1],
      gamesUsed: 1,
      recentGamesUsed: 1,
      components: { pointsPerGame: 240.1, recentAvg: 240.1 },
    },
    {
      ...ROWS[2],
      gamesUsed: 1,
      recentGamesUsed: 1,
      components: { pointsPerGame: 174.3, recentAvg: 174.3 },
    },
  ];

  it("names the number of counted weeks in the PPG and Recent headers", async () => {
    serve(payload({ ranking: ROWS_WITH_GAMES, blend: { scoredGames: 1 } }));
    const RosPowerSection = await renderFresh();
    const { container } = render(<RosPowerSection />);
    await waitFor(() => expect(screen.getAllByText("Alice").length).toBeGreaterThan(0));

    expect(container.textContent).toContain("PPG (1 wk)");
    expect(container.textContent).toContain("Recent (1 of 4)");
  });

  it("caps the Recent header's game count at the 4-game window", async () => {
    serve(payload({ ranking: ROWS_WITH_GAMES, blend: { scoredGames: 9 } }));
    const RosPowerSection = await renderFresh();
    const { container } = render(<RosPowerSection />);
    await waitFor(() => expect(screen.getAllByText("Alice").length).toBeGreaterThan(0));

    expect(container.textContent).toContain("PPG (9 wk)");
    expect(container.textContent).toContain("Recent (4 of 4)");
  });

  it("plain PPG/Recent headers before any week is complete", async () => {
    serve(payload({ ranking: ROWS_WITH_GAMES.map((r) => ({ ...r, gamesUsed: 0 })) }));
    const RosPowerSection = await renderFresh();
    const { container } = render(<RosPowerSection />);
    await waitFor(() => expect(screen.getAllByText("Alice").length).toBeGreaterThan(0));

    expect(container.textContent).toContain("PPG");
    expect(container.textContent).not.toContain("PPG (");
  });

  it("calls out a row whose own count disagrees with the table's shared count", async () => {
    const mismatched = [
      ROWS_WITH_GAMES[0],
      { ...ROWS_WITH_GAMES[1], gamesUsed: 2, components: { pointsPerGame: 500.0, recentAvg: 500.0 } },
      ROWS_WITH_GAMES[2],
    ];
    serve(payload({ ranking: mismatched, blend: { scoredGames: 1 } }));
    const RosPowerSection = await renderFresh();
    const { container } = render(<RosPowerSection />);
    await waitFor(() => expect(screen.getAllByText("Alice").length).toBeGreaterThan(0));

    // Bob's row differs from the table's shared count and must say so.
    expect(container.textContent).toContain("(2g)");
    // Alice and Cass agree with the table and get no per-row annotation.
    const annotations = container.textContent.match(/\(\d+g\)/g) || [];
    expect(annotations).toHaveLength(1);
  });

  it("renders an em dash, never a number, when a row has no games counted", async () => {
    const noEvidence = [
      { ...ROWS[0], gamesUsed: 0, recentGamesUsed: 0, components: { pointsPerGame: null, recentAvg: null } },
      ROWS_WITH_GAMES[1],
      ROWS_WITH_GAMES[2],
    ];
    serve(payload({ ranking: noEvidence, blend: { scoredGames: 1 } }));
    const RosPowerSection = await renderFresh();
    render(<RosPowerSection />);
    await waitFor(() => expect(screen.getAllByText("Alice").length).toBeGreaterThan(0));

    const aliceRow = screen.getAllByText("Alice")[0].closest("tr");
    expect(aliceRow.textContent).toContain("—");
    expect(aliceRow.textContent).not.toContain("0.0");
  });

  it("does no denominator arithmetic — every number it shows came from the payload", async () => {
    // Structural: the component may format (toFixed, string interpolation)
    // but must never compute an average, a ratio, or a game count itself.
    const fs = await import("fs");
    const path = await import("path");
    const filePath = path.join(process.cwd(), "app/league/sections/ros-power.jsx");
    const src = fs.readFileSync(filePath, "utf8");
    expect(src).not.toMatch(/pointsPerGame\s*\/\s*/);
    expect(src).not.toMatch(/points\s*\/\s*games/);
    expect(src).not.toMatch(/reduce\(/); // no client-side aggregation over rows
  });

  it("labels Record when the league runs a median game, so it does not read as a mismatch with PPG", async () => {
    serve(
      payload({
        ranking: ROWS_WITH_GAMES,
        blend: { scoredGames: 1 },
      }),
    );
    const RosPowerSection = await renderFresh();
    const { container } = render(<RosPowerSection />);
    await waitFor(() => expect(screen.getAllByText("Alice").length).toBeGreaterThan(0));

    const recordHeader = Array.from(container.querySelectorAll("th")).find(
      (th) => th.textContent === "Record",
    );
    expect(recordHeader).toBeTruthy();
    // Unverified (medianGameEnabled absent from the payload) must not read
    // as "off".
    expect(recordHeader.title).toMatch(/unverified/i);
  });
});
