/**
 * ValueExplainDetail — renders the backend value-explain/v2 contract.
 *
 * What must never blur (owner directive, #1555 Batch 2 Lane 6 decision D):
 *   - an unknown clock reads "unknown", never blank and never 0;
 *   - a non-voting source is listed WITH its reason, never as a zero share;
 *   - attribution is called exact ONLY when the backend says exact: true;
 *   - leave-one-out is labelled non-additive, and an unavailable one says why;
 *   - no Signals opinion renders unless the caller passes one (seam for #1572).
 */
import { afterEach, describe, expect, it, vi } from "vitest";
import React from "react";
import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import ValueExplainDetail, {
  ValueExplainDetailView,
  valueExplainUrl,
} from "@/components/ValueExplainDetail";

const NOW = Date.now();
const hoursAgo = (h) => new Date(NOW - h * 3600_000).toISOString();

function source(overrides = {}) {
  return {
    source: "ktcCrowdSfTep",
    family: "ktcCrowd",
    status: "voting",
    voteShare: 0.5,
    contribution: 3000.4,
    normalizedValue: 6000.8,
    contributionIsApproximate: true,
    exclusionReason: null,
    freshnessTreatment: { factor: 1.0, state: "ON_SCHEDULE", treatment: "full_weight" },
    clocks: {
      lastFetchedAt: hoursAgo(3),
      publishedAsOf: hoursAgo(30),
      lastConfirmedChangeAt: hoursAgo(30),
      lastBroadChangeAt: hoursAgo(50),
      judgedOn: "lastBroadDatasetChangeAt",
      unknown: [],
    },
    ...overrides,
  };
}

function payload(overrides = {}) {
  return {
    explainVersion: "value-explain/v2",
    player: "Test Player",
    playerId: "1234",
    modelValue: 6123,
    sourceBreakdownAvailable: true,
    estimator: {
      path: "flat_count_aware_blend",
      rung: "weighted_mean_median_untrimmed",
      voters: 3,
      singleSourceRetentionApplied: false,
      limitedEvidence: false,
      postBlendOverrides: [],
      anchorValue: null,
      alphaShrinkage: null,
    },
    attribution: { kind: "weighted_vote_share", exact: false, note: "backend note" },
    leaveOneOut: {
      nonAdditive: true,
      basis: "aggregator_rerun_over_stamped_survivors",
      available: true,
      publishedBlend: 6123.4,
      withoutEach: [
        { source: "ktcCrowdSfTep", valueWithout: 6000.0, delta: -123.4 },
        { source: "dlfSf", valueWithout: 6200.5, delta: 77.1 },
      ],
    },
    modelSources: [
      source(),
      source({
        source: "dlfSf",
        family: "dlf",
        voteShare: 0.3,
        contribution: 1800,
        freshnessTreatment: { factor: 0.82, state: "OVERDUE", treatment: "down_weighted" },
      }),
      source({
        source: "fantasyCalc",
        family: "fantasyCalc",
        status: "excluded_stale_or_unhealthy",
        voteShare: null,
        contribution: null,
        exclusionReason: "freshness_or_health_zero_weight",
        freshnessTreatment: { factor: 0.0, state: "QUARANTINED", treatment: "excluded" },
        clocks: {
          lastFetchedAt: null,
          publishedAsOf: null,
          lastConfirmedChangeAt: null,
          lastBroadChangeAt: null,
          judgedOn: null,
          unknown: ["judgedOn", "lastBroadChangeAt", "lastConfirmedChangeAt", "lastFetchedAt", "publishedAsOf"],
        },
      }),
      source({
        source: "dynastyDaddySf",
        family: "dynastyDaddy",
        status: "hampel_outlier",
        voteShare: null,
        contribution: null,
        exclusionReason: "outlier:hampel",
      }),
    ],
    ...overrides,
  };
}

function rowFor(name) {
  // DataTable renders each source row followed by its detail row.
  const cell = screen.getAllByText(name)[0];
  return cell.closest("tr");
}

describe("ValueExplainDetailView", () => {
  it("names the actual estimator, rung and voters", () => {
    render(<ValueExplainDetailView payload={payload()} />);
    expect(screen.getByRole("heading", { name: "Estimator" })).toBeInTheDocument();
    expect(screen.getByText(/Count-aware weighted blend/)).toBeInTheDocument();
    expect(screen.getByText(/weighted mean-median of 3–4 sources, untrimmed · 3 voting/)).toBeInTheDocument();
    expect(screen.getByText("not applied")).toBeInTheDocument();
    expect(screen.getByText("6,123")).toBeInTheDocument();
  });

  it("renders unknown clocks as 'unknown', never blank or 0", () => {
    render(<ValueExplainDetailView payload={payload()} />);
    const detail = rowFor("FC").nextElementSibling;
    const clocks = within(detail);
    for (const label of ["Last fetched", "Published / as of", "Last confirmed change", "Last broad change"]) {
      const dt = clocks.getByText(label);
      expect(dt.nextElementSibling).toHaveTextContent("unknown");
    }
    expect(detail).toHaveTextContent("age clock unknown");
    // A known clock is a relative time with the exact instant on <time>.
    const knownDetail = rowFor("KTC Crowd").nextElementSibling;
    const time = knownDetail.querySelector("time");
    expect(time).not.toBeNull();
    expect(time.getAttribute("dateTime")).toMatch(/T/);
  });

  it("keeps the fetch, publication and confirmed-change clocks distinct", () => {
    render(<ValueExplainDetailView payload={payload()} />);
    const detail = within(rowFor("KTC Crowd").nextElementSibling);
    expect(detail.getByText("Last fetched").nextElementSibling).toHaveTextContent("3h ago");
    expect(detail.getByText("Published / as of").nextElementSibling).toHaveTextContent("1d ago");
    expect(detail.getByText("Last broad change").nextElementSibling).toHaveTextContent("2d ago");
    expect(detail.getByText(/age judged on its last broad change/)).toBeInTheDocument();
  });

  it("lists excluded sources with their reasons and no share", () => {
    render(<ValueExplainDetailView payload={payload()} />);
    const stale = rowFor("FC");
    expect(stale).toHaveTextContent("Not voting — too stale or unhealthy to carry weight");
    expect(stale).toHaveTextContent("no share — not voting");
    expect(stale).not.toHaveTextContent("0.0%");
    const outlier = rowFor("DD");
    expect(outlier).toHaveTextContent("Not voting — dropped as an outlier (Hampel filter)");
  });

  it("shows freshness treatment, including the down-weight factor", () => {
    render(<ValueExplainDetailView payload={payload()} />);
    const detail = rowFor("DLF SF").nextElementSibling;
    expect(detail).toHaveTextContent("Down-weighted for age ×0.82");
    expect(detail).toHaveTextContent("source overdue");
    expect(rowFor("FC").nextElementSibling).toHaveTextContent("Freshness: Excluded");
  });

  it("labels attribution approximate when exact is false, and contributions with ≈", () => {
    render(<ValueExplainDetailView payload={payload()} />);
    expect(screen.getByText("Approximate attribution.")).toBeInTheDocument();
    expect(screen.queryByText("Exact attribution for this row.")).toBeNull();
    expect(rowFor("KTC Crowd")).toHaveTextContent("≈ 3,000");
  });

  it("treats a missing attribution block as approximate, never exact", () => {
    render(<ValueExplainDetailView payload={payload({ attribution: undefined })} />);
    expect(screen.getByText("Approximate attribution.")).toBeInTheDocument();
  });

  it("calls attribution exact only when the backend says exact: true", () => {
    render(
      <ValueExplainDetailView
        payload={payload({ attribution: { kind: "weighted_vote_share", exact: true } })}
      />,
    );
    expect(screen.getByText("Exact attribution for this row.")).toBeInTheDocument();
  });

  it("labels leave-one-out non-additive", () => {
    render(<ValueExplainDetailView payload={payload()} />);
    expect(screen.getByRole("heading", { name: /Leave-one-out \(not additive\)/ })).toBeInTheDocument();
    expect(screen.getByText(/The changes are not additive/)).toBeInTheDocument();
    expect(screen.getByText("−123.4")).toBeInTheDocument();
    expect(screen.getByText("+77.1")).toBeInTheDocument();
  });

  it("says why leave-one-out is unavailable", () => {
    render(
      <ValueExplainDetailView
        payload={payload({
          leaveOneOut: { nonAdditive: true, available: false, reason: "not_applicable" },
        })}
      />,
    );
    expect(screen.getByText(/Leave-one-out unavailable: only computed for offense rows/)).toBeInTheDocument();
    // Still labelled non-additive even when unavailable.
    expect(screen.getByRole("heading", { name: /not additive/ })).toBeInTheDocument();
  });

  it("names a pick's provenance class as the estimator", () => {
    render(
      <ValueExplainDetailView
        payload={payload({
          estimator: { path: "derived_year_step", rung: "no_voters", voters: 0, postBlendOverrides: [] },
          sourceBreakdownAvailable: false,
          modelSources: [],
        })}
      />,
    );
    expect(screen.getByText("Pick — derived from the nearest priced year")).toBeInTheDocument();
    expect(screen.getByText(/No per-source breakdown is published/)).toBeInTheDocument();
  });

  it("flags an older explanation format instead of padding it", () => {
    const v1 = payload();
    delete v1.explainVersion;
    delete v1.estimator;
    render(<ValueExplainDetailView payload={v1} />);
    expect(screen.getByText("Older explanation format")).toBeInTheDocument();
    expect(screen.getByText(/The estimator is not published/)).toBeInTheDocument();
  });

  it("says when it explains the default board under a custom mix", () => {
    render(<ValueExplainDetailView payload={payload()} customMix />);
    expect(screen.getByText("Explains the default board")).toBeInTheDocument();
  });

  it("renders no Signals / second-opinion section unless one is passed in", () => {
    const { rerender } = render(<ValueExplainDetailView payload={payload()} />);
    expect(screen.queryByRole("heading", { name: /Second opinions/ })).toBeNull();
    expect(screen.queryByText(/Signals/)).toBeNull();
    rerender(
      <ValueExplainDetailView
        payload={payload()}
        secondOpinion={<p>Signals Fantasy — positional rank only · not counted</p>}
      />,
    );
    expect(screen.getByRole("heading", { name: /Second opinions \(not counted\)/ })).toBeInTheDocument();
  });

  it("uses semantic tables with captions and section headings", () => {
    render(<ValueExplainDetailView payload={payload()} />);
    expect(screen.getAllByRole("table").length).toBe(2);
    expect(screen.getByRole("heading", { name: "Sources, clocks and exclusions" })).toBeInTheDocument();
  });
});

describe("ValueExplainDetail (fetching wrapper)", () => {
  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it("fetches the encoded player key with same-origin credentials", async () => {
    const fetchMock = vi.fn(async () => ({ ok: true, status: 200, json: async () => payload() }));
    vi.stubGlobal("fetch", fetchMock);
    render(<ValueExplainDetail playerKey="2027 Early 1st" />);
    expect(await screen.findByRole("heading", { name: "Estimator" })).toBeInTheDocument();
    expect(fetchMock.mock.calls[0][0]).toBe("/api/players/2027%20Early%201st/value-explain");
    expect(fetchMock.mock.calls[0][1].credentials).toBe("same-origin");
    expect(valueExplainUrl("a/b")).toBe("/api/players/a%2Fb/value-explain");
  });

  it("explains a 401 without a retry and retries a 503", async () => {
    let calls = 0;
    vi.stubGlobal(
      "fetch",
      vi.fn(async () => {
        calls += 1;
        return calls === 1
          ? { ok: false, status: 503, json: async () => ({ error: "data_not_ready" }) }
          : { ok: true, status: 200, json: async () => payload() };
      }),
    );
    render(<ValueExplainDetail playerKey="1234" />);
    expect(await screen.findByText(/board is not loaded on the server yet/)).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: "Try again" }));
    expect(await screen.findByRole("heading", { name: "Estimator" })).toBeInTheDocument();
  });

  it("does not offer a retry for an auth failure", async () => {
    vi.stubGlobal("fetch", vi.fn(async () => ({ ok: false, status: 401, json: async () => ({}) })));
    render(<ValueExplainDetail playerKey="1234" />);
    expect(await screen.findByText(/Sign in to see how this value was computed/)).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Try again" })).toBeNull();
  });
});
