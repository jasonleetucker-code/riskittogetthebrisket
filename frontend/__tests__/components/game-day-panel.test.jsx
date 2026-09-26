/**
 * GameDayPanel — the canonical Game Day surface (#1335 / #1334, owner
 * escalation 2026-09-24).
 *
 * Most payloads here are REAL `GET /api/matchup/intel` output: the U4
 * replay captures (tests/fixtures/game_day/replay/) run through the backend
 * builder by `tests/game_day/ui_payloads.py`, and
 * `tests/game_day/test_game_day_ui_fixtures.py` fails if the backend stops
 * emitting exactly these. So a number asserted below is the number the API
 * publishes, formatted — UI and API agree by construction.
 *
 * What is pinned:
 *   - the owner hierarchy: hero -> what matters now -> slate -> collapsed
 *     best-ball details -> collapsed data info;
 *   - every state: pregame, live, halftime, overtime (withheld with its
 *     named reason), final, live feed down;
 *   - MISSING IS NEVER ZERO and 1-family honesty;
 *   - refresh in place, carried from draft PR #1346 (its tests, adapted),
 *     plus the league guard #1346 lacked, and preservation of scroll,
 *     focus and expanded sections across a refresh.
 */
import { act, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import GameDayPanel, { validMatchupPayload } from "@/components/GameDayPanel";
import { formatPct, formatPoints } from "@/lib/game-day-view";

import PREGAME from "../fixtures/game-day/pregame.json";
import HALFTIME from "../fixtures/game-day/halftime.json";
import OVERTIME from "../fixtures/game-day/overtime.json";
import TNF_FINAL from "../fixtures/game-day/final.json";
import WEEK_FINAL from "../fixtures/game-day/week-final.json";
import MIXED from "../fixtures/game-day/mixed-slate.json";
import FEED_DOWN from "../fixtures/game-day/live-feed-down.json";
import STALE from "../fixtures/game-day/stale.json";
import PENDING from "../fixtures/game-day/pending.json";

const mockUserState = { state: { selectedTeam: null } };
vi.mock("@/components/useUserState", () => ({
  useUserState: () => mockUserState,
}));

const mockSearchParams = { value: new Map() };
const mockRouter = { push: vi.fn() };
vi.mock("next/navigation", () => ({
  useSearchParams: () => mockSearchParams.value,
  useRouter: () => mockRouter,
  usePathname: () => "/game-day",
}));

// The league switcher's answer. `dynasty_main` is what every fixture says.
const mockLeague = { selectedLeagueKey: "dynasty_main", loading: false };
vi.mock("@/components/useLeague", () => ({
  useLeague: () => mockLeague,
}));

const clone = (x) => JSON.parse(JSON.stringify(x));

function mockJson(body, { ok = true, status = 200 } = {}) {
  globalThis.fetch = vi.fn(() => Promise.resolve({ ok, status, json: () => Promise.resolve(body) }));
}

function heroTable() {
  return screen.getByRole("table", { name: /matchup:/ });
}

function heroRow(name) {
  return within(heroTable()).getByRole("row", { name: new RegExp(name) });
}

async function renderReady(payload) {
  mockJson(payload);
  const view = render(<GameDayPanel />);
  await screen.findByText(`Week ${payload.week} · ${payload.season}`);
  return view;
}

beforeEach(() => {
  mockUserState.state = { selectedTeam: null };
  mockSearchParams.value = new Map();
  mockRouter.push = vi.fn();
  mockLeague.selectedLeagueKey = "dynasty_main";
  mockLeague.loading = false;
});

afterEach(() => {
  vi.restoreAllMocks();
});

// ── Hierarchy and states, from real payloads ────────────────────────────

describe("GameDayPanel — owner hierarchy", () => {
  it("renders hero, what matters now, slate, then collapsed details and data info", async () => {
    const { container } = await renderReady(HALFTIME);
    const headings = [...container.querySelectorAll("h2")].map((h) => h.textContent.trim());
    // Owner amendment 2026-09-26: the Live Median Race sits directly after
    // the hero, ahead of What matters now.
    expect(headings).toEqual([
      "Live median race",
      "What matters now",
      "NFL slate",
      "Best-ball details",
      "Data info",
    ]);
    // Both disclosures are collapsed by default.
    expect(screen.getByRole("button", { name: "Best-ball details" })).toHaveAttribute(
      "aria-expanded",
      "false",
    );
    expect(screen.getByRole("button", { name: "Data info" })).toHaveAttribute(
      "aria-expanded",
      "false",
    );
    // No walls of repeated slot-eligibility arrays anywhere on the page.
    expect(container.textContent).not.toMatch(/eligible at/i);
    expect(container.textContent).not.toMatch(/SUPER_FLEX/);
  });
});

describe("GameDayPanel — pregame", () => {
  it("shows projected finish, win and beat-median chances and the margin", async () => {
    await renderReady(PREGAME);
    expect(screen.getByText("Upcoming")).toBeInTheDocument();
    expect(within(heroTable()).queryByText("Score now")).toBeNull();
    const team = PREGAME.team.outcome;
    const row = heroRow("Team 8");
    expect(within(row).getByText(formatPoints(team.expectedFinalBestBall))).toBeInTheDocument();
    expect(within(row).getByText(formatPct(team.winMatchupPct))).toBeInTheDocument();
    expect(within(row).getByText(formatPct(team.beatMedianPct))).toBeInTheDocument();
    const opp = PREGAME.opponent.outcome;
    expect(within(heroRow("Team 10")).getByText(formatPct(opp.winMatchupPct))).toBeInTheDocument();
    expect(
      screen.getByText(`Team 8 by ${Math.abs(team.expectedMarginVsOpponent).toFixed(1)}`),
    ).toBeInTheDocument();
    expect(screen.getByText(/^Current · as of/)).toBeInTheDocument();
  });

  it("labels the pregame lineup illustrative and never shows a counting lineup", async () => {
    await renderReady(PREGAME);
    fireEvent.click(screen.getByRole("button", { name: "Best-ball details" }));
    // First test to open the lazy BestBallDetailsBody: its cold import
    // (now incl. the ds PlayerNameButton → next/link, #1337) can exceed
    // the default 1 s under a full parallel suite run.
    expect(
      (await screen.findAllByText("Projected lineup (illustrative)", {}, { timeout: 5000 })).length,
    ).toBe(2);
    expect(screen.queryByText("Currently counting")).toBeNull();
    expect(screen.getAllByText(/Projected finish averages the best lineup/).length).toBe(2);
  });
});

describe("GameDayPanel — live (real halftime capture)", () => {
  it("shows score now, projected finish and win chance from the payload", async () => {
    await renderReady(HALFTIME);
    expect(screen.getByText("Live")).toBeInTheDocument();
    const row = heroRow("Team 8");
    expect(
      within(row).getByText(formatPoints(HALFTIME.team.scoreNow.bestBallFromBankedPoints)),
    ).toBeInTheDocument();
    expect(
      within(row).getByText(formatPoints(HALFTIME.team.outcome.expectedFinalBestBall)),
    ).toBeInTheDocument();
    expect(within(row).getByText(formatPct(HALFTIME.team.outcome.winMatchupPct))).toBeInTheDocument();
    expect(screen.getByText(/^Current · as of .*\(20 s old\)$/)).toBeInTheDocument();
    expect(screen.queryByText(/Win chance paused/)).toBeNull();
  });

  it("scores the best-ball lineup of points scored and shows a lagging host total beside it", async () => {
    await renderReady(HALFTIME);
    // Real capture: Sleeper's team total for roster 10 still read 0.0 while
    // two of its players had scored (lineup 3.77).
    const sn = HALFTIME.opponent.scoreNow;
    expect(sn.hostReportedTotal).toBe(0);
    expect(sn.hostTotalDiffers).toBe(true);
    const row = heroRow("Team 10");
    expect(within(row).getByText(formatPoints(sn.bestBallFromBankedPoints))).toBeInTheDocument();
    expect(within(row).getByText("Sleeper shows 0.0")).toBeInTheDocument();
  });

  it("keeps a real 0.0 and says nobody has played yet, rather than faking a lineup", async () => {
    const p = clone(HALFTIME);
    p.opponent.actualScore = 0;
    p.opponent.pointsBanked = 0;
    p.opponent.scoreNow = {
      bestBallFromBankedPoints: 0,
      complete: true,
      hostReportedTotal: 0,
      hostTotalDiffers: false,
    };
    p.opponent.actualLineup = {
      ...p.opponent.actualLineup,
      slots: [],
      total: 0,
      knownSubtotal: 0,
      lineupState: "not_started",
    };
    await renderReady(p);
    const row = heroRow("Team 10");
    expect(within(row).getByText("0.0")).toBeInTheDocument();
    expect(within(row).getByText("No players have played yet")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Best-ball details" }));
    expect(await screen.findByText(/no lineup is counting/)).toBeInTheDocument();
  });

  it("lists the NFL slate in the payload's kickoff order, halftime observed", async () => {
    const { container } = await renderReady(HALFTIME);
    const ids = [...container.querySelectorAll("[data-game-id]")].map((el) => el.dataset.gameId);
    expect(ids).toEqual(HALFTIME.nflSlate.games.map((g) => g.gameId));
    const tnf = container.querySelector('[data-game-id="2026_3_ATL_GB"]');
    expect(tnf).toHaveTextContent("Halftime");
  });

  it("puts backend-ordered key games and could-enter players under What matters now", async () => {
    await renderReady(HALFTIME);
    const section = screen.getByRole("heading", { name: "What matters now" }).closest("section");
    const items = within(section).getAllByRole("listitem");
    expect(items.length).toBeGreaterThanOrEqual(3);
    expect(items.length).toBeLessThanOrEqual(5);
    const first = HALFTIME.team.outcome.gameLeverage.find((r) => r.leverage !== null);
    const game = HALFTIME.nflSlate.games.find((g) => g.gameId === first.gameId);
    expect(items[0]).toHaveTextContent(`${game.awayTeam} @ ${game.homeTeam}`);
    expect(items[0]).toHaveTextContent(formatPct(first.winPctWhenGameFavorsTeam));
    expect(section).toHaveTextContent(/Could enter/);
  });
});

describe("GameDayPanel — withheld probability", () => {
  it("names overtime in plain language and shows no number for the win chance", async () => {
    await renderReady(OVERTIME);
    expect(screen.getByText("Overtime in ATL @ GB: win chance paused.")).toBeInTheDocument();
    const row = heroRow("Team 8");
    expect(within(row).getAllByText("Paused").length).toBeGreaterThanOrEqual(2);
    expect(within(heroTable()).queryByText(/%$/)).toBeNull();
    // Banked points survive the withholding.
    expect(within(row).getByText(formatPoints(OVERTIME.team.pointsBanked))).toBeInTheDocument();
  });

  it("says the live feed is down instead of presenting schedule state as live", async () => {
    await renderReady(FEED_DOWN);
    // ESPN refused (HTTP 403): the collector's own freshness state says so.
    expect(screen.getByText(/^Partial · as of .* · live game feed unavailable$/)).toBeInTheDocument();
    expect(
      screen.getByText(/Game status unknown for ATL @ GB — the live game feed is unavailable/),
    ).toBeInTheDocument();
    expect(within(heroTable()).queryByText(/%$/)).toBeNull();
  });

  it("scores banked points while the feed is down and shows Sleeper's lagging total beside them", async () => {
    await renderReady(FEED_DOWN);
    const sn = FEED_DOWN.team.scoreNow;
    const row = heroRow("Team 8");
    expect(within(row).getByText(formatPoints(sn.bestBallFromBankedPoints))).toBeInTheDocument();
    expect(within(row).getByText(`Sleeper shows ${formatPoints(sn.hostReportedTotal)}`)).toBeInTheDocument();
    expect(within(row).queryByText("No players have played yet")).toBeNull();
  });

  it("names unknown-state players with nothing banked instead of dropping them", async () => {
    const p = clone(FEED_DOWN);
    const ghost = p.team.players.find((x) => !p.team.actualLineup.slots.some((s) => s.playerId === x.playerId));
    p.team.actualLineup.unknownStatePlayerIds = [ghost.playerId];
    p.team.actualLineup.lineupState = "partial";
    await renderReady(p);
    expect(within(heroRow("Team 8")).getByText("Game status unknown for 1 player")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Best-ball details" }));
    // #1337: the named player is the canonical Player File link inside
    // the sentence, so the text spans two elements — match the paragraph.
    const note = await screen.findByText(
      (_, el) =>
        el?.tagName === "P" && el.textContent.startsWith(`Game status unknown for ${ghost.name}`),
    );
    expect(within(note).getByRole("link", { name: ghost.name })).toHaveAttribute(
      "href",
      `/players/${encodeURIComponent(ghost.playerId)}`,
    );
  });
});

describe("GameDayPanel — freshness is never hidden", () => {
  it("shows a stale generation as stale, with its age, in the hero and a banner", async () => {
    await renderReady(STALE);
    expect(screen.getByText(/^Stale · as of .*\(2 h old\)/)).toBeInTheDocument();
    expect(screen.getByText("These numbers are out of date")).toBeInTheDocument();
    expect(screen.getByText(/Last collected 2 h ago, past the 3 min budget/)).toBeInTheDocument();
  });

  it("shows a degraded, background-computed answer as degraded", async () => {
    const p = clone(HALFTIME);
    p.freshness = { ...p.freshness, state: "degraded", reasons: ["no_collector_generation"] };
    await renderReady(p);
    expect(screen.getByText(/^Degraded · .* computed in the background/)).toBeInTheDocument();
  });

  it("answers a cold request with real scores and a computing forecast, not a paused chance", async () => {
    await renderReady(PENDING);
    expect(screen.getByText("Computing the forecast")).toBeInTheDocument();
    expect(screen.queryByText("Win chance paused")).not.toBeInTheDocument();
    expect(screen.queryByText("Win chance unavailable")).not.toBeInTheDocument();
    const row = heroRow("Selected team");
    expect(row).toHaveTextContent(PENDING.team.scoreNow.bestBallFromBankedPoints.toFixed(1));
    // One "Computing…" cell spans the forecast columns (fits a phone).
    expect(within(row).getByText("Computing…").closest("td")).toHaveAttribute("colspan");
    fireEvent.click(screen.getByRole("button", { name: "Data info" }));
    expect(await screen.findByText(/forecast still computing/)).toBeInTheDocument();
    expect(screen.getByText(/Not read yet — the forecast is still computing/)).toBeInTheDocument();
  });

  it("polls again soon while the forecast is computing, then shows it", async () => {
    vi.useFakeTimers({ shouldAdvanceTime: true });
    try {
      let calls = 0;
      globalThis.fetch = vi.fn(() => {
        calls += 1;
        const body = calls === 1 ? PENDING : HALFTIME;
        return Promise.resolve({ ok: true, status: 200, json: () => Promise.resolve(body) });
      });
      render(<GameDayPanel />);
      await screen.findByText("Computing the forecast");
      await vi.advanceTimersByTimeAsync(10500);
      await waitFor(() => expect(screen.queryByText("Computing the forecast")).not.toBeInTheDocument());
      expect(calls).toBeGreaterThanOrEqual(2);
    } finally {
      vi.useRealTimers();
    }
  });

  it("lists a stat correction the host has not applied, without rescoring", async () => {
    const p = clone(HALFTIME);
    const player = p.team.players[0];
    p.freshness = {
      ...p.freshness,
      state: "partial",
      reasons: ["stat_correction_pending_host"],
      statCorrections: {
        scoringSourceOfRecord: "sleeper:league matchups players_points (host scoring)",
        pendingHost: [
          {
            playerId: player.playerId,
            gameId: "g1",
            detectedAt: p.freshness.asOf,
            statChanges: {},
            scoredDeltaUnderLeagueCard: -3.95,
            hostPointsBefore: 22.07,
            hostPointsNow: 22.07,
            state: "pending_host",
            reflectedAt: null,
          },
        ],
        reflectedInHostCount: 1,
        notScoredByLeagueCount: 0,
      },
    };
    await renderReady(p);
    fireEvent.click(screen.getByRole("button", { name: "Data info" }));
    expect(
      await screen.findByText(/1 awaiting the host · 1 already in the host's scores/),
    ).toBeInTheDocument();
    expect(screen.getByText(/-4\.0 pts under this league's scoring/)).toHaveTextContent(player.name);
    expect(
      screen.getByText(/host has not applied to its scores yet/, { selector: "li" }),
    ).toBeInTheDocument();
  });

  it("lists every source with its status and age in Data info, failures visible", async () => {
    await renderReady(FEED_DOWN);
    fireEvent.click(screen.getByRole("button", { name: "Data info" }));
    const table = await screen.findByRole("table", { name: /data sources and their freshness/ });
    const espn = within(table).getByText(/^ESPN scoreboard/).closest("tr");
    expect(espn).toHaveTextContent("error (http_error:403)");
    expect(within(table).getByText(/^Sleeper league/).closest("tr")).toHaveTextContent("ok");
    expect(screen.getByText("Partial")).toBeInTheDocument();
    expect(screen.getByText(/live game feed \(ESPN\) failed \(HTTP 403\)/, { selector: "li" })).toBeInTheDocument();
    expect(
      screen.getByText(/live game feed \(SportsDataIO\) not configured/, { selector: "li" }),
    ).toBeInTheDocument();
    expect(screen.getByText(/Shared live collector/)).toBeInTheDocument();
  });
});

describe("GameDayPanel — beat median verification", () => {
  it("marks an unverified median rule in the scoreboard with its reason", async () => {
    const p = clone(PREGAME);
    p.team.outcome.beatMedianVerified = false;
    p.team.outcome.beatMedianUnverifiedReason = "odd_team_count_host_rule_unverified";
    await renderReady(p);
    expect(
      within(heroRow("Team 8")).getByText(/Unverified — odd team count: the host's median rule is unverified/),
    ).toBeInTheDocument();
    expect(within(heroRow("Team 8")).getByText(formatPct(p.team.outcome.beatMedianPct))).toBeInTheDocument();
  });

  it("does not mark a verified median", async () => {
    await renderReady(PREGAME);
    expect(PREGAME.team.outcome.beatMedianVerified).toBe(true);
    expect(screen.queryByText(/^Unverified/)).toBeNull();
  });
});

describe("GameDayPanel — final", () => {
  it("shows the final score and result, links the recap, and drops forecasts", async () => {
    await renderReady(WEEK_FINAL);
    expect(screen.getAllByText("Final").length).toBeGreaterThan(0);
    expect(within(heroRow("Team 8")).getByText(formatPoints(WEEK_FINAL.team.actualScore))).toBeInTheDocument();
    expect(within(heroTable()).getByText("Final score")).toBeInTheDocument();
    expect(within(heroRow("Team 8")).getByText(WEEK_FINAL.team.result)).toBeInTheDocument();
    expect(screen.queryByRole("heading", { name: "What matters now" })).toBeNull();
    expect(within(heroTable()).queryByText("Win chance")).toBeNull();
    expect(screen.getByRole("link", { name: /articles and recap/ })).toHaveAttribute(
      "href",
      WEEK_FINAL.recapUrl,
    );
  });

  it("marks a finished TNF game while the rest of the week is still live", async () => {
    const { container } = await renderReady(TNF_FINAL);
    expect(container.querySelector('[data-game-id="2026_3_ATL_GB"]')).toHaveTextContent("Final");
    fireEvent.click(screen.getByRole("button", { name: "Best-ball details" }));
    // Both sides have TNF players whose game is over.
    expect(
      (await screen.findAllByRole("heading", { name: "Game finished", level: 4 })).length,
    ).toBe(2);
  });
});

describe("GameDayPanel — mixed slate game status", () => {
  it("renders observed quarter and clock for every stage", async () => {
    const { container } = await renderReady(MIXED);
    const status = (id) => container.querySelector(`[data-game-id="${id}"]`).textContent;
    expect(status("2026_3_TEN_NYG")).toContain("Q4 2:00");
    expect(status("2026_3_CAR_CLE")).toContain("End Q3");
    expect(status("2026_3_HOU_IND")).toContain("Halftime");
    expect(status("2026_3_KC_MIA")).toContain("Final");
    expect(status("2026_3_NE_JAX")).toContain("Q1 10:00");
  });

  it("expands a game into its players, keeping real zeros and negative scores", async () => {
    const { container } = await renderReady(MIXED);
    const played = MIXED.nflSlate.games.find((g) =>
      g.players.some((p) => p.state !== "not_started" && p.pointsScored < 0),
    );
    expect(played).toBeTruthy();
    const row = container.querySelector(`[data-game-id="${played.gameId}"]`);
    fireEvent.click(within(row).getByRole("button", { name: /Players/ }));
    const negative = played.players.find((p) => p.state !== "not_started" && p.pointsScored < 0);
    expect(await within(row).findByText(formatPoints(negative.pointsScored))).toBeInTheDocument();
  });
});

// ── Missing is never zero / honest provenance ───────────────────────────

describe("GameDayPanel — missing is never zero", () => {
  it("shows Unavailable, not 0.0, for a missing host score and a missing live score", async () => {
    const p = clone(HALFTIME);
    p.team.actualScore = null;
    p.team.pointsBanked = null;
    p.team.actualLineup.total = null;
    p.team.actualLineup.missingPlayerIds = ["9509"];
    p.team.scoreNow = {
      bestBallFromBankedPoints: null,
      complete: false,
      hostReportedTotal: null,
      hostTotalDiffers: null,
    };
    const game = p.nflSlate.games.find((g) => g.gameId === "2026_3_ATL_GB");
    const live = game.players.find((x) => x.side === "team");
    live.pointsScored = null;
    live.projectedRemaining = null;
    const { container } = await renderReady(p);
    expect(within(heroRow("Team 8")).getByText("Unavailable")).toBeInTheDocument();
    expect(within(heroRow("Team 8")).getByText("Partial — scoring missing for 1 player")).toBeInTheDocument();
    const row = container.querySelector('[data-game-id="2026_3_ATL_GB"]');
    fireEvent.click(within(row).getByRole("button", { name: /Players/ }));
    const cells = (await within(row).findByText(live.name)).closest("tr");
    expect(cells).toHaveTextContent("Unavailable");
    expect(cells).not.toHaveTextContent(/\b0\.0\b/);
  });

  it("keeps an in-progress 0.0 distinct from missing evidence", async () => {
    const p = clone(HALFTIME);
    const game = p.nflSlate.games.find((g) => g.gameId === "2026_3_ATL_GB");
    const live = game.players.find((x) => x.side === "team");
    live.pointsScored = 0;
    const { container } = await renderReady(p);
    const row = container.querySelector('[data-game-id="2026_3_ATL_GB"]');
    fireEvent.click(within(row).getByRole("button", { name: /Players/ }));
    expect((await within(row).findByText(live.name)).closest("tr")).toHaveTextContent("0.0");
  });

  it("never shows a fabricated 50% when nothing priced the week", async () => {
    const p = clone(PREGAME);
    p.team.outcome = null;
    p.opponent.outcome = null;
    p.probabilityState = "UNAVAILABLE";
    // The league board of a week nothing priced carries no probabilities
    // either (the backend's forecast_unavailable state).
    p.medianRace = {
      ...p.medianRace,
      state: "forecast_unavailable",
      projectedMedianMean: null,
      projectedMedianP10: null,
      projectedMedianP50: null,
      projectedMedianP90: null,
      bubble: [],
      teams: p.medianRace.teams.map((t) => ({
        ...t,
        beatMedianPct: null,
        medianMarginMean: null,
        projectedMean: null,
      })),
    };
    await renderReady(p);
    expect(screen.queryByText(/50\.0%/)).toBeNull();
    expect(within(heroRow("Team 8")).getAllByText("Unavailable").length).toBeGreaterThan(0);
    expect(screen.getByText(/No projection could price this week/)).toBeInTheDocument();
  });
});

describe("GameDayPanel — data info honesty", () => {
  it("says 1 projection family and never calls one family an ensemble", async () => {
    const { container } = await renderReady(HALFTIME);
    expect(HALFTIME.lineage.projectionFamiliesContributing).toBe(1);
    fireEvent.click(screen.getByRole("button", { name: "Data info" }));
    expect(await screen.findByText("1 projection family")).toBeInTheDocument();
    expect(container.textContent).not.toMatch(/ensemble/i);
    expect(screen.getAllByText(/RotoWire via Sleeper/).length).toBeGreaterThan(0);
    expect(screen.getByText(/pregame provider baseline x observed share/)).toBeInTheDocument();
  });

  it("names more than one family as independent families", async () => {
    const p = clone(HALFTIME);
    p.lineage.projectionFamiliesContributing = 2;
    await renderReady(p);
    fireEvent.click(screen.getByRole("button", { name: "Data info" }));
    expect(await screen.findByText(/2 independent projection families/)).toBeInTheDocument();
  });

  it("labels the preseason basis as a fallback and our imputed categories as our estimate", async () => {
    const p = clone(HALFTIME);
    p.lineage.projectionBasisCounts = { "weekly:rotowire_via_sleeper": 500, preseason_fallback: 12 };
    p.lineage.projectionBasisLabels = {
      "weekly:rotowire_via_sleeper": "Weekly projection — RotoWire via Sleeper, locked at kickoff",
      preseason_fallback: "Preseason full-season per-game average — FALLBACK, NOT a current-week forecast",
    };
    p.team.players[0].imputedScoringKeys = ["bonus_rec_te"];
    await renderReady(p);
    fireEvent.click(screen.getByRole("button", { name: "Data info" }));
    expect(
      await screen.findByText(/FALLBACK, NOT a current-week forecast: 12 players/),
    ).toBeInTheDocument();
    // The real capture already carries our first-down bonus estimates.
    expect(
      screen.getByText(/Our estimate \(not the provider's\) fills bonus_fd_qb.*bonus_rec_te/),
    ).toBeInTheDocument();
  });

});

// ── States that are not errors (carried) ─────────────────────────────────

describe("GameDayPanel — states that are not errors", () => {
  it("renders a week already in progress as a state, not a failure", async () => {
    mockJson({ error: "week_in_progress" }, { ok: false, status: 409 });
    render(<GameDayPanel />);
    expect(await screen.findByText("This week has already started")).toBeInTheDocument();
  });

  it("explains an unstated clock rather than showing a generic error", async () => {
    mockJson({ error: "clock_unavailable" }, { ok: false, status: 503 });
    render(<GameDayPanel />);
    expect(await screen.findByText(/has not stated the current week/)).toBeInTheDocument();
  });

  it("asks for a team when one could not be inferred", async () => {
    mockJson({ error: "team_required" }, { ok: false, status: 400 });
    render(<GameDayPanel />);
    expect(await screen.findByText("No team selected")).toBeInTheDocument();
  });

  it("falls back to a real error state for anything else", async () => {
    mockJson({ error: "matchup_unavailable", message: "the host returned no rosters" }, {
      ok: false,
      status: 503,
    });
    render(<GameDayPanel />);
    expect(await screen.findByText(/the host returned no rosters/)).toBeInTheDocument();
  });
});

// ── Request context (carried + league) ───────────────────────────────────

describe("GameDayPanel — request context", () => {
  it("requests with no caching, the selected league and the selected team", async () => {
    mockUserState.state = { selectedTeam: { ownerId: "owner-8" } };
    await renderReady(HALFTIME);
    const [url, opts] = globalThis.fetch.mock.calls[0];
    expect(opts.cache).toBe("no-store");
    expect(url).toContain("leagueKey=dynasty_main");
    expect(url).toContain("team=owner-8");
  });

  it("lets ?team= and ?leagueKey= win and forwards week/season verbatim", async () => {
    mockUserState.state = { selectedTeam: { ownerId: "switcher" } };
    mockSearchParams.value = new Map([
      ["team", "owner-8"],
      ["leagueKey", "dynasty_main"],
      ["week", "3"],
      ["season", "2026"],
    ]);
    await renderReady(HALFTIME);
    const [url] = globalThis.fetch.mock.calls[0];
    expect(url).toContain("team=owner-8");
    expect(url).not.toContain("switcher");
    expect(url).toContain("week=3");
    expect(url).toContain("season=2026");
  });

  it("omits team when none is selected, rather than sending an empty one", async () => {
    await renderReady(HALFTIME);
    expect(globalThis.fetch.mock.calls[0][0]).not.toContain("team=");
  });

  it("waits for the league list instead of asking about a default league", async () => {
    mockLeague.loading = true;
    mockLeague.selectedLeagueKey = "";
    mockJson(HALFTIME);
    const view = render(<GameDayPanel />);
    await act(async () => {});
    expect(globalThis.fetch).not.toHaveBeenCalled();
    mockLeague.loading = false;
    mockLeague.selectedLeagueKey = "dynasty_main";
    view.rerender(<GameDayPanel />);
    await screen.findByText("Week 3 · 2026");
    expect(globalThis.fetch.mock.calls[0][0]).toContain("leagueKey=dynasty_main");
  });

  it("refuses a 200 that answers for a different league than the one selected", async () => {
    mockJson({ ...HALFTIME, leagueKey: "dynasty_new" });
    const view = render(<GameDayPanel />);
    expect(await screen.findByText(/The matchup response is incomplete/)).toBeInTheDocument();
    expect(view.container.querySelector('[data-game-day-ready="true"]')).toBeNull();
  });
});

// ── Refresh in place (carried from #1346, + league guard, + preservation) ─

describe("GameDayPanel — background refresh", () => {
  let tick;
  let hidden;
  beforeEach(() => {
    hidden = false;
    vi.spyOn(document, "hidden", "get").mockImplementation(() => hidden);
    const realSetInterval = globalThis.setInterval;
    vi.spyOn(globalThis, "setInterval").mockImplementation((callback, delay, ...args) => {
      if (delay === 60000) {
        tick = callback;
        return 123;
      }
      return realSetInterval(callback, delay, ...args);
    });
    mockJson(HALFTIME);
  });

  const WIN = formatPct(HALFTIME.team.outcome.winMatchupPct);

  it("keeps the successful answer while a slow poll runs and prevents overlapping polls", async () => {
    const view = render(<GameDayPanel />);
    await screen.findByText(WIN);
    let finish;
    globalThis.fetch.mockImplementationOnce(() => new Promise((resolve) => (finish = resolve)));
    await act(async () => tick());
    expect(screen.getByText(WIN)).toBeInTheDocument();
    expect(screen.queryByText("Loading this week's matchup...")).not.toBeInTheDocument();
    expect(view.container.querySelector('[aria-busy="true"]')).not.toBeNull();
    await act(async () => tick());
    expect(globalThis.fetch).toHaveBeenCalledTimes(2);
    await act(async () => finish({ ok: true, json: async () => HALFTIME }));
    expect(screen.getByText(WIN)).toBeInTheDocument();
  });

  it("pauses hidden-tab requests and refreshes when the tab becomes visible", async () => {
    hidden = true;
    render(<GameDayPanel />);
    await act(async () => tick());
    expect(globalThis.fetch).not.toHaveBeenCalled();
    hidden = false;
    await act(async () => document.dispatchEvent(new Event("visibilitychange")));
    await screen.findByText(WIN);
    hidden = true;
    await act(async () => tick());
    expect(globalThis.fetch).toHaveBeenCalledTimes(1);
  });

  it("retains the same-context answer with a warning after a malformed background response", async () => {
    render(<GameDayPanel />);
    await screen.findByText(WIN);
    globalThis.fetch.mockResolvedValueOnce({ ok: true, status: 200, json: async () => ({}) });
    await act(async () => tick());
    expect(screen.getByText(WIN)).toBeInTheDocument();
    expect(screen.getByText(/Refresh unavailable/)).toHaveTextContent("last successful");
    globalThis.fetch.mockResolvedValueOnce({
      ok: false,
      status: 401,
      json: async () => ({ error: "unauthorized" }),
    });
    await act(async () => tick());
    expect(screen.queryByText(WIN)).not.toBeInTheDocument();
  });

  it("labels a retained transient failure, but clears a domain refusal", async () => {
    render(<GameDayPanel />);
    await screen.findByText(WIN);
    globalThis.fetch.mockResolvedValueOnce({
      ok: false,
      status: 503,
      json: async () => ({ error: "temporarily_unavailable" }),
    });
    await act(async () => tick());
    expect(screen.getByText(WIN)).toBeInTheDocument();
    expect(screen.getByText(/Refresh unavailable/)).toHaveTextContent("last successful");
    globalThis.fetch.mockResolvedValueOnce({
      ok: false,
      status: 409,
      json: async () => ({ error: "week_in_progress" }),
    });
    await act(async () => tick());
    expect(screen.queryByText(WIN)).not.toBeInTheDocument();
    expect(screen.getByText("This week has already started")).toBeInTheDocument();
  });

  it("updates in place, preserving expanded sections, the focused control and the DOM", async () => {
    const view = render(<GameDayPanel />);
    await screen.findByText(WIN);
    fireEvent.click(screen.getByRole("button", { name: "Best-ball details" }));
    fireEvent.click(screen.getByRole("button", { name: "Data info" }));
    const tnf = view.container.querySelector('[data-game-id="2026_3_ATL_GB"]');
    const toggle = within(tnf).getByRole("button", { name: /Players/ });
    fireEvent.click(toggle);
    await screen.findByText("1 projection family");
    await within(tnf).findByRole("table");
    await screen.findAllByText("Currently counting");
    toggle.focus();
    const root = view.container.querySelector('[data-game-day-ready="true"]');
    const scrollSpy = vi.spyOn(window, "scrollTo").mockImplementation(() => {});

    const next = clone(HALFTIME);
    next.team.outcome.winMatchupPct = 64.2;
    next.team.scoreNow.bestBallFromBankedPoints = 31.4;
    globalThis.fetch.mockResolvedValueOnce({ ok: true, status: 200, json: async () => next });
    await act(async () => tick());

    expect(screen.getByText("64.2%")).toBeInTheDocument();
    expect(within(heroRow("Team 8")).getByText("31.4")).toBeInTheDocument();
    expect(view.container.querySelector('[data-game-day-ready="true"]')).toBe(root);
    expect(screen.getByRole("button", { name: "Best-ball details" })).toHaveAttribute(
      "aria-expanded",
      "true",
    );
    expect(screen.getByRole("button", { name: "Data info" })).toHaveAttribute(
      "aria-expanded",
      "true",
    );
    expect(toggle).toHaveAttribute("aria-expanded", "true");
    expect(document.activeElement).toBe(toggle);
    expect(scrollSpy).not.toHaveBeenCalled();
  });

  it("keeps the Refresh control focusable while it refreshes", async () => {
    render(<GameDayPanel />);
    await screen.findByText(WIN);
    let finish;
    globalThis.fetch.mockImplementationOnce(() => new Promise((resolve) => (finish = resolve)));
    const button = screen.getByRole("button", { name: "Refresh" });
    button.focus();
    await act(async () => fireEvent.click(button));
    expect(button).not.toBeDisabled();
    expect(document.activeElement).toBe(button);
    expect(button).toHaveTextContent("Updating…");
    await act(async () => finish({ ok: true, json: async () => HALFTIME }));
    expect(document.activeElement).toBe(button);
  });

  it.each([
    ["week", "2"],
    ["season", "2027"],
  ])("rejects an obsolete %s response even if abort is ignored", async (field, value) => {
    let finishOld;
    globalThis.fetch.mockImplementationOnce(() => new Promise((resolve) => (finishOld = resolve)));
    const view = render(<GameDayPanel />);
    const oldSignal = globalThis.fetch.mock.calls[0][1].signal;
    mockSearchParams.value = new Map([[field, value]]);
    const next = { ...HALFTIME, [field]: Number(value) };
    globalThis.fetch.mockResolvedValueOnce({ ok: true, json: async () => next });
    view.rerender(<GameDayPanel />);
    await screen.findByText(`Week ${next.week} · ${next.season}`);
    expect(oldSignal.aborted).toBe(true);
    await act(async () => finishOld({ ok: true, json: async () => HALFTIME }));
    expect(screen.queryByText("Week 3 · 2026")).not.toBeInTheDocument();
    expect(globalThis.fetch.mock.calls[1][0]).toContain(`${field}=${value}`);
    view.unmount();
  });

  it.each(["http", "malformed", "network"])(
    "never retains the prior week after a hidden context change and %s failure",
    async (failure) => {
      const view = render(<GameDayPanel />);
      await screen.findByText("Week 3 · 2026");
      hidden = true;
      mockSearchParams.value = new Map([["week", "2"]]);
      view.rerender(<GameDayPanel />);
      expect(screen.queryByText("Week 3 · 2026")).not.toBeInTheDocument();
      expect(globalThis.fetch).toHaveBeenCalledTimes(1);
      if (failure === "network") globalThis.fetch.mockRejectedValueOnce(new Error("offline"));
      else
        globalThis.fetch.mockResolvedValueOnce({
          ok: failure === "malformed",
          status: failure === "malformed" ? 200 : 503,
          json: async () => (failure === "malformed" ? {} : { error: "temporarily_unavailable" }),
        });
      hidden = false;
      await act(async () => document.dispatchEvent(new Event("visibilitychange")));
      expect(globalThis.fetch.mock.calls[1][0]).toContain("week=2");
      expect(screen.queryByText("Week 3 · 2026")).not.toBeInTheDocument();
      expect(view.container.querySelector('[data-game-day-ready="true"]')).toBeNull();
    },
  );

  it("aborts the active request on unmount and rejects its late completion", async () => {
    let finish;
    globalThis.fetch.mockImplementationOnce(() => new Promise((resolve) => (finish = resolve)));
    const view = render(<GameDayPanel />);
    const signal = globalThis.fetch.mock.calls[0][1].signal;
    view.unmount();
    expect(signal.aborted).toBe(true);
    await act(async () => finish({ ok: true, json: async () => HALFTIME }));
    expect(view.container).toBeEmptyDOMElement();
  });

  it("rejects a previous team's late response even when a transport ignores abort", async () => {
    let finishOld;
    globalThis.fetch.mockImplementationOnce(() => new Promise((resolve) => (finishOld = resolve)));
    const view = render(<GameDayPanel />);
    mockUserState.state = { selectedTeam: { ownerId: "owner-10" } };
    const other = { ...HALFTIME, week: 4, team: { ...HALFTIME.opponent } };
    globalThis.fetch.mockResolvedValueOnce({ ok: true, json: async () => other });
    view.rerender(<GameDayPanel />);
    await screen.findByText("Week 4 · 2026");
    await act(async () => finishOld({ ok: true, json: async () => HALFTIME }));
    expect(screen.queryByText("Week 3 · 2026")).not.toBeInTheDocument();
    expect(globalThis.fetch.mock.calls[1][0]).toContain("team=owner-10");
  });

  it("rejects a previous LEAGUE's late response (the key #1346 lacked)", async () => {
    let finishOld;
    globalThis.fetch.mockImplementationOnce(() => new Promise((resolve) => (finishOld = resolve)));
    const view = render(<GameDayPanel />);
    expect(globalThis.fetch.mock.calls[0][0]).toContain("leagueKey=dynasty_main");
    // Same team, same week, same season — only the league changes.
    mockLeague.selectedLeagueKey = "dynasty_new";
    const newLeague = { ...HALFTIME, leagueKey: "dynasty_new", week: 5 };
    globalThis.fetch.mockResolvedValueOnce({ ok: true, json: async () => newLeague });
    view.rerender(<GameDayPanel />);
    await screen.findByText("Week 5 · 2026");
    expect(globalThis.fetch.mock.calls[1][0]).toContain("leagueKey=dynasty_new");
    await act(async () => finishOld({ ok: true, json: async () => HALFTIME }));
    expect(screen.queryByText("Week 3 · 2026")).not.toBeInTheDocument();
    expect(screen.getByText("Week 5 · 2026")).toBeInTheDocument();
  });

  it("blanks to loading, not to the old league's answer, while a new league loads", async () => {
    const view = render(<GameDayPanel />);
    await screen.findByText(WIN);
    globalThis.fetch.mockImplementationOnce(() => new Promise(() => {}));
    mockLeague.selectedLeagueKey = "dynasty_new";
    view.rerender(<GameDayPanel />);
    expect(screen.queryByText(WIN)).not.toBeInTheDocument();
    expect(screen.getByText("Loading this week's matchup...")).toBeInTheDocument();
  });
});

describe("validMatchupPayload", () => {
  it.each([
    {},
    [],
    { ...HALFTIME, team: null },
    { ...HALFTIME, season: null },
    { ...HALFTIME, week: "1" },
    { ...HALFTIME, week: 0 },
    { ...HALFTIME, mode: "unknown" },
    { ...HALFTIME, team: { ownerId: "" } },
  ])("refuses a malformed body", (body) => {
    expect(validMatchupPayload(body)).toBe(false);
  });

  it("accepts every real fixture and checks the league echo", () => {
    for (const p of [PREGAME, HALFTIME, OVERTIME, TNF_FINAL, WEEK_FINAL, MIXED, FEED_DOWN]) {
      expect(validMatchupPayload(p, "dynasty_main")).toBe(true);
      expect(validMatchupPayload(p, "dynasty_new")).toBe(false);
    }
  });

  it("does not mark a malformed HTTP 200 as useful", async () => {
    mockJson({});
    const view = render(<GameDayPanel />);
    expect(await screen.findByText("The matchup response is incomplete. Please retry.")).toBeInTheDocument();
    expect(view.container.querySelector('[data-game-day-ready="true"]')).toBeNull();
  });
});
