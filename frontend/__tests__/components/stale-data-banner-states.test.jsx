/**
 * StaleDataBanner, 6-24h tier: the copy follows what the refresh pipeline is
 * actually doing.  "The next scheduled scrape should land soon" is only true
 * when nothing says recent attempts are failing.
 *
 * `PROD` is the shape of production's /api/health on 2026-11-12 (see
 * `current_step: "failed"`, non-empty latest_run_critical_source_failures).
 */
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import React from "react";
import { render, screen, waitFor } from "@testing-library/react";
import StaleDataBanner from "@/components/StaleDataBanner";

const LAST = new Date(Date.now() - 21 * 3600 * 1000).toISOString();
const BASE = {
  status: "ok",
  has_data: true,
  data_stale: true,
  data_age_hours: 21.1,
  last_scrape: LAST,
  scrape_running: false,
  scrape_stalled: false,
  scrape_interrupted: false,
  current_step: "complete",
  source_health_ok: true,
  latest_run_critical_source_failures: [],
};
const PROD = {
  ...BASE,
  status: "degraded",
  current_step: "failed",
  source_health_ok: false,
  latest_run_critical_source_failures: ["IDPTradeCalc", "KTC", "ktcSfTep"],
};

function mountWith(health, status = 200) {
  global.fetch = vi.fn(async () => ({ ok: status === 200, status, json: async () => health }));
  return render(<StaleDataBanner />);
}

beforeEach(() => vi.useRealTimers());
afterEach(() => vi.restoreAllMocks());

describe("StaleDataBanner — 6-24h tier states", () => {
  it("failed last attempt + failing critical sources (production today): no 'should land soon'", async () => {
    mountWith(PROD, 503);
    expect(await screen.findByText(/last refresh attempt did not complete/i)).toBeInTheDocument();
    expect(screen.getByText(/Data is 21h old/)).toBeInTheDocument();
    expect(screen.getByText(/Failing sources: IDPTradeCalc, KTC, ktcSfTep/)).toBeInTheDocument();
    expect(screen.queryByText(/should land soon/i)).toBeNull();
  });

  it("a blocked attempt (nothing promoted) reads as a failed attempt", async () => {
    mountWith({ ...BASE, current_step: "blocked" });
    expect(await screen.findByText(/did not complete/i)).toBeInTheDocument();
    expect(screen.queryByText(/should land soon/i)).toBeNull();
  });

  it("failing critical sources alone (step not failed) warn without promising a refresh", async () => {
    mountWith({ ...BASE, latest_run_critical_source_failures: ["KTC"], source_health_ok: false });
    expect(await screen.findByText(/not completing cleanly/i)).toBeInTheDocument();
    expect(screen.getByText(/Failing sources: KTC/)).toBeInTheDocument();
    expect(screen.queryByText(/should land soon/i)).toBeNull();
  });

  it("source_health_ok false with no named sources still warns", async () => {
    mountWith({ ...BASE, source_health_ok: false });
    expect(await screen.findByText(/not completing cleanly/i)).toBeInTheDocument();
    expect(screen.queryByText(/Failing sources/)).toBeNull();
  });

  it("a refresh in progress says so and promises nothing", async () => {
    mountWith({ ...PROD, scrape_running: true, current_step: "fetching" });
    expect(await screen.findByText(/refresh is running now/i)).toBeInTheDocument();
    expect(screen.queryByText(/should land soon/i)).toBeNull();
    expect(screen.queryByText(/did not complete/i)).toBeNull();
  });

  it("stalled worker keeps its existing critical copy", async () => {
    mountWith({ ...PROD, scrape_stalled: true });
    expect(await screen.findByText(/Scrape worker stalled/i)).toBeInTheDocument();
    expect(screen.queryByText(/did not complete/i)).toBeNull();
  });

  it("interrupted run keeps its existing critical copy", async () => {
    mountWith({ ...PROD, scrape_interrupted: true });
    expect(await screen.findByText(/did not finish/i)).toBeInTheDocument();
  });

  it("data simply aging with no failure signal keeps the existing copy", async () => {
    mountWith(BASE);
    expect(await screen.findByText(/next scheduled scrape should land soon/i)).toBeInTheDocument();
    expect(screen.getByText(/Data is 21h old/)).toBeInTheDocument();
  });

  it("older than 24h keeps the critical 'Data is Nd old' copy", async () => {
    mountWith({ ...PROD, data_age_hours: 50 });
    expect(await screen.findByText(/Data is 2d old/)).toBeInTheDocument();
  });

  it("no banner at or under 6h, even if the last attempt failed", async () => {
    const { container } = mountWith({ ...PROD, data_age_hours: 3 });
    await waitFor(() => expect(global.fetch).toHaveBeenCalled());
    expect(container.querySelector(".stale-data-banner")).toBeNull();
  });
});
