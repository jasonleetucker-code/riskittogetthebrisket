/**
 * /tools/source-health — the Source voting panel (owner directive 2026-10-19
 * §8) and the freshness / weighting table share ONE fetch of
 * /api/sources/weighting.  Before the backend publishes `votingStatus` the
 * voting panel says "not available yet" while the existing table keeps
 * working; once it does, the panel renders the backend's rows.
 */
import { afterEach, describe, expect, it, vi } from "vitest";
import React from "react";
import { render, screen, within } from "@testing-library/react";
import SourceHealthPage from "@/app/tools/source-health/page";
import weightingFixture from "../fixtures/source-weighting-2026-10-13.json";
import votingFixture from "../fixtures/source-voting-status-2026-10-19.json";

function mockFetch(weightingBody) {
  globalThis.fetch = vi.fn(async (url) => {
    const u = String(url);
    if (u.startsWith("/api/sources/weighting")) {
      return { ok: true, status: 200, json: async () => weightingBody };
    }
    // SourceHealthStrip's /api/status poll — not under test here.
    return { ok: true, status: 200, json: async () => ({}) };
  });
}

function weightingCalls() {
  return globalThis.fetch.mock.calls.filter(([u]) => String(u).startsWith("/api/sources/weighting"));
}

afterEach(() => {
  vi.restoreAllMocks();
});

describe("Source Health → Source voting", () => {
  it("before the backend publishes votingStatus: honest unavailable state, table intact", async () => {
    mockFetch(weightingFixture); // a 2026-10-13 payload: no votingStatus key
    render(<SourceHealthPage />);

    expect(await screen.findByTestId("source-voting-unavailable")).toBeTruthy();
    expect(screen.getByText("Voting status not available yet")).toBeTruthy();
    // The freshness / weighting diagnostic still renders from the same payload.
    expect(await screen.findByTestId("source-weighting-summary")).toBeTruthy();
    expect(screen.queryByText("Active — 100%")).toBeNull();
    expect(weightingCalls()).toHaveLength(1);
  });

  it("with votingStatus: one row per source in the owner's labels, same single fetch", async () => {
    mockFetch({ ...weightingFixture, votingStatus: votingFixture });
    render(<SourceHealthPage />);

    const summary = await screen.findByTestId("source-voting-summary");
    expect(summary.textContent).toMatch(/17\s+of\s+26\s+sources voting/);
    const stale = screen.getByTestId("source-voting-status-fantasyProsIdp");
    expect(within(stale).getByText("Stale — Not Voting")).toBeTruthy();
    const seasonal = screen.getByTestId("source-voting-status-flockFantasySfRookies");
    expect(within(seasonal).getByText("Seasonal — Not Voting")).toBeTruthy();
    expect(screen.queryByTestId("source-voting-unavailable")).toBeNull();
    expect(weightingCalls()).toHaveLength(1);
  });
});
