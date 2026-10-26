/**
 * ValueMovementDetail — "Why it moved" (IC-7 / UI contract §10).
 *
 * What must never blur:
 *   - the source changes are labelled NOT ADDITIVE and evidence-not-cause;
 *   - a source absent at one board reads "absent" (with its last-seen date),
 *     never 0, and its change is "—", never a number;
 *   - no comparator / pre-history renders the backend's reason, never a 0 move;
 *   - quantities the ledger does not store read "not recorded";
 *   - a ledger behind the live board says so;
 *   - nothing is computed client-side: the numbers shown are the payload's.
 */
import { afterEach, describe, expect, it, vi } from "vitest";
import React from "react";
import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import ValueMovementDetail, {
  ValueMovementDetailView,
  valueMovementUrl,
} from "@/components/ValueMovementDetail";
import { formatSignedValue, valueMovementView } from "@/lib/value-movement";

function payload(overrides = {}) {
  return {
    schema: "value-movement/v1",
    status: "ok",
    missingReason: null,
    historyFloor: "2026-07-14",
    additive: false,
    evidenceNotCause: true,
    nonAdditiveNote: "Per-source deltas do not sum to the value change.",
    comparatorBoardDate: "2026-09-01",
    current: {
      observedDate: "2026-09-02",
      fidelity: "exact",
      value: 6400,
      rank: 31,
      tier: 2,
      confidence: "high",
      pipelineVersion: "v2+bbbb",
    },
    previous: {
      observedDate: "2026-09-01",
      fidelity: "exact",
      value: 6000,
      rank: 40,
      tier: 3,
      confidence: "medium",
      pipelineVersion: "v2+aaaa",
    },
    change: { value: 400, rank: 9, tierChanged: true, confidenceChanged: true },
    methodology: {
      pipelineVersionChanged: true,
      covers: "contract shape version + Hill-curve constants (content hash)",
    },
    sources: [
      {
        source: "ktcCrowdSfTep",
        status: "moved",
        role: "model_input",
        previous: { present: true, value: 6100 },
        current: { present: true, value: 6517 },
        delta: 417,
      },
      {
        source: "idpTradeCalc",
        status: "disappeared",
        role: "model_input",
        previous: { present: true, value: 6200 },
        current: {
          present: false,
          value: null,
          lastObservedDate: "2026-09-02",
          lastObservedAt: "2026-09-02T08:00:00+00:00",
        },
        delta: null,
      },
      {
        source: "ktcCrowdTradesSfTep",
        status: "appeared",
        role: "benchmark_not_a_vote",
        previous: { present: false, value: null, lastObservedDate: null },
        current: { present: true, value: 6300 },
        delta: null,
      },
    ],
    sourcesNotObservedAtEitherGeneration: ["signalsSf"],
    unobserved: [
      { quantity: "sourceWeights", reason: "not stored" },
      { quantity: "sourceFreshness", reason: "not stored" },
      { quantity: "anomalyFlags", reason: "not stored" },
    ],
    liveBoard: { boardDate: "2026-09-02", value: 6400, rank: 31, rankChange: 9 },
    currentGenerationIsLiveBoard: true,
    currentContext: {
      scope: "current_board_only",
      anomalyFlags: [],
      quarantined: false,
      sourcesNotRecordedInLedger: [
        { source: "dlfSf", role: "voted_today" },
        { source: "yahooBoone", role: "not_voting_today" },
      ],
    },
    ...overrides,
  };
}

afterEach(() => {
  vi.restoreAllMocks();
});

describe("ValueMovementDetailView", () => {
  it("labels the evidence not-additive and not-a-cause", () => {
    render(<ValueMovementDetailView payload={payload()} />);
    expect(screen.getByText("Evidence, not a cause.")).toBeTruthy();
    expect(screen.getByText(/do not sum to the value change/)).toBeTruthy();
    expect(screen.getByRole("heading", { name: /Source evidence/ }).textContent).toMatch(
      /not additive/,
    );
  });

  it("shows both boards and the backend's change, unaltered", () => {
    render(<ValueMovementDetailView payload={payload()} />);
    expect(screen.getByText(/2026-09-01 → 2026-09-02/)).toBeTruthy();
    expect(screen.getByRole("img", { name: "up 400" })).toBeTruthy();
    expect(screen.getByRole("img", { name: "up 9" })).toBeTruthy();
    expect(screen.getByText(/changed between these boards/)).toBeTruthy();
    // The per-source change is the payload's 417, not 6517 − 6100 recomputed
    // or rescaled: the view prints what it was given.
    const table = screen.getByRole("table");
    expect(within(table).getByText("+417")).toBeTruthy();
  });

  it("renders an absent source as absent with its last-seen date — never 0", () => {
    render(<ValueMovementDetailView payload={payload()} />);
    const table = screen.getByRole("table");
    const gone = within(table).getByText("Disappeared").closest("tr");
    // Last seen at an EARLIER scrape the same day — named with its time.
    expect(within(gone).getByText("absent (last seen 2026-09-02 08:00 UTC)")).toBeTruthy();
    expect(within(gone).getByText("no change computed — absent at one board")).toBeTruthy();
    expect(gone.textContent).not.toMatch(/(^|[^0-9,])0($|[^0-9,])/);
    const fresh = within(table).getByText("Appeared").closest("tr");
    expect(within(fresh).getByText("absent")).toBeTruthy();
    expect(within(fresh).getByText(/Benchmark — not a vote/)).toBeTruthy();
  });

  it("names what the ledger does not record per board", () => {
    render(<ValueMovementDetailView payload={payload()} />);
    expect(screen.getByText("Source weights")).toBeTruthy();
    expect(screen.getByText("Source freshness")).toBeTruthy();
    expect(screen.getAllByText("not recorded").length).toBeGreaterThanOrEqual(3);
    expect(screen.getByText(/Not recorded at either board/)).toBeTruthy();
    const today = screen.getByText(/On today’s board, with no per-board history kept/).textContent;
    expect(today).toMatch(/DLF SF \(voted today\)/);
    expect(today).toMatch(/\(not voting today\)/);
    expect(today).not.toMatch(/also priced by/);
  });

  it("explains a missing comparator instead of showing a zero move", () => {
    render(
      <ValueMovementDetailView
        payload={payload({
          status: "no_comparator",
          missingReason: "no_prior_board_generation",
          previous: null,
          change: null,
          sources: [],
        })}
      />,
    );
    expect(screen.getByText(/no earlier board generation to compare against/)).toBeTruthy();
    expect(screen.getByText(/first board generation the ledger holds/)).toBeTruthy();
    expect(screen.queryByRole("img", { name: /unchanged|up|down/ })).toBeNull();
    expect(screen.queryByRole("table")).toBeNull();
  });

  it("explains a pre-history request with the boundary reason", () => {
    render(
      <ValueMovementDetailView
        payload={payload({
          status: "no_current_generation",
          missingReason: "before_history_boundary",
          current: null,
          previous: null,
          change: null,
          sources: [],
        })}
      />,
    );
    expect(screen.getByText(/before the history floor/)).toBeTruthy();
  });

  it("says when the recorded history is behind the live board", () => {
    render(
      <ValueMovementDetailView
        payload={payload({
          currentGenerationIsLiveBoard: false,
          liveBoard: { boardDate: "2026-09-03" },
        })}
      />,
    );
    expect(screen.getByText("History is behind the live board")).toBeTruthy();
    expect(screen.getByText(/the board on screen is 2026-09-03/)).toBeTruthy();
  });

  it("an unknown methodology change reads not recorded, not unchanged", () => {
    render(
      <ValueMovementDetailView
        payload={payload({ methodology: { pipelineVersionChanged: null } })}
      />,
    );
    const dt = screen.getByText("Valuation constants");
    expect(dt.parentElement.textContent).toMatch(/not recorded/);
    expect(dt.parentElement.textContent).not.toMatch(/unchanged/);
  });
});

describe("ValueMovementDetailView — generations (review F1/F2)", () => {
  it("says when the rank change shown elsewhere compares different boards", () => {
    render(
      <ValueMovementDetailView
        payload={payload({
          rankChangeAlignment: {
            sameBoardsAsRankChange: false,
            rankChangeComparatorDate: "2026-09-03",
            reasons: ["asset_absent_from_comparator_board"],
          },
        })}
      />,
    );
    const dt = screen.getByText("Rank change shown elsewhere");
    expect(dt.parentElement.textContent).toMatch(/compares different boards/);
    expect(dt.parentElement.textContent).toMatch(/not on the previous board/);
  });

  it("stays quiet when both compare the same boards", () => {
    render(
      <ValueMovementDetailView
        payload={payload({
          rankChangeAlignment: { sameBoardsAsRankChange: true, reasons: [] },
        })}
      />,
    );
    expect(screen.queryByText("Rank change shown elsewhere")).toBeNull();
  });

  it("names scrape times when the ledger is behind the board on screen", () => {
    render(
      <ValueMovementDetailView
        payload={payload({
          current: { ...payload().current, observedAt: "2026-09-02T08:00:00+00:00" },
          currentGenerationIsLiveBoard: false,
          currentGenerationIsLiveBoardBasis: "instant",
          liveBoard: { boardDate: "2026-09-02", scrapeTimestamp: "2026-09-02T22:00:00+00:00" },
        })}
      />,
    );
    expect(screen.getByText(/2026-09-02 08:00 UTC; the board on screen is 2026-09-02 22:00 UTC/)).toBeTruthy();
  });

  it("labels a source value matched only by date", () => {
    const p = payload();
    p.sources[0].previous = { present: true, value: 6100, generationMatch: "date" };
    render(<ValueMovementDetailView payload={p} />);
    expect(screen.getByText("(by date)")).toBeTruthy();
  });
});

describe("lib/value-movement", () => {
  it("keeps absent values null and never invents a delta", () => {
    const v = valueMovementView(payload());
    const gone = v.sources.find((s) => s.key === "idpTradeCalc");
    expect(gone.current.value).toBeNull();
    expect(gone.delta).toBeNull();
    expect(v.additive).toBe(false);
    expect(valueMovementView({}).ok).toBe(false);
    expect(formatSignedValue(null)).toBeNull();
    expect(formatSignedValue(-1234.4)).toBe("−1,234");
  });
});

describe("ValueMovementDetail (fetching)", () => {
  it("requests the private endpoint and renders the payload", async () => {
    const fetchMock = vi
      .spyOn(globalThis, "fetch")
      .mockResolvedValue({ ok: true, status: 200, json: async () => payload() });
    render(<ValueMovementDetail playerKey="4034" />);
    expect(await screen.findByText("Evidence, not a cause.")).toBeTruthy();
    expect(fetchMock.mock.calls[0][0]).toBe("/api/players/4034/value-movement");
    expect(valueMovementUrl("2027 Early 1st")).toBe(
      "/api/players/2027%20Early%201st/value-movement",
    );
  });

  it("offers a retry on a server error but not on sign-in", async () => {
    vi.spyOn(globalThis, "fetch").mockResolvedValue({
      ok: false,
      status: 503,
      json: async () => ({ error: "data_not_ready" }),
    });
    render(<ValueMovementDetail playerKey="4034" />);
    expect(await screen.findByText(/not loaded on the server yet/)).toBeTruthy();
    const retry = screen.getByRole("button", { name: "Try again" });
    await userEvent.click(retry);

    vi.restoreAllMocks();
    vi.spyOn(globalThis, "fetch").mockResolvedValue({
      ok: false,
      status: 401,
      json: async () => ({ error: "unauthorized" }),
    });
    render(<ValueMovementDetail playerKey="9999" />);
    expect(await screen.findByText(/Sign in to see why this value moved/)).toBeTruthy();
  });
});
