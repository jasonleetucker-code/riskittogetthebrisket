/**
 * A scrape that died mid-run must reach the operator.
 *
 * `_reconcile_orphaned_running_state` detects a worker that exited
 * without cleanup. It used to set `stalled`/`hung`, both of which were
 * recomputed back to false before the payload was built, so
 * `/api/health` reported every flag false and this banner never fired.
 * The operator saw a normal page.
 *
 * The ordering assertion matters as much as the rendering one: the
 * interrupted banner sits ABOVE the `!hasData` early return, because a
 * worker that died before producing any payload is exactly the case
 * where `hasData` is false and exactly when the operator most needs
 * telling.
 */
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import React from "react";
import { render, screen, waitFor } from "@testing-library/react";
import StaleDataBanner from "@/components/StaleDataBanner";

const FRESH = { has_data: true, data_age_hours: 1, last_scrape: new Date().toISOString() };

// The component polls /api/health itself rather than taking props, so
// the health payload is injected by stubbing fetch.
function mountWith(health) {
  global.fetch = vi.fn(async () => ({ ok: true, status: 200, json: async () => health }));
  return render(<StaleDataBanner />);
}

beforeEach(() => vi.useRealTimers());
afterEach(() => vi.restoreAllMocks());

describe("StaleDataBanner — interrupted scrape", () => {
  it("fires when the last run died mid-flight", async () => {
    mountWith({ ...FRESH, scrape_interrupted: true });
    expect(await screen.findByText(/did not finish/i)).toBeInTheDocument();
  });

  it("fires even when no payload was ever produced", async () => {
    // The case `!hasData` would otherwise swallow.
    mountWith({ has_data: false, scrape_interrupted: true });
    expect(await screen.findByText(/did not finish/i)).toBeInTheDocument();
  });

  it("says the worker will not retry, because it will not", async () => {
    mountWith({ ...FRESH, scrape_interrupted: true });
    expect(await screen.findByText(/not retry/i)).toBeInTheDocument();
  });

  it("yields to a stalled worker, which is the more urgent state", async () => {
    mountWith({ ...FRESH, scrape_stalled: true, scrape_interrupted: true });
    expect(await screen.findByText(/stalled/i)).toBeInTheDocument();
    expect(screen.queryByText(/did not finish/i)).toBeNull();
  });

  it("stays silent on a healthy server", async () => {
    // The control: without it these would pass against a banner that
    // rendered unconditionally.
    const { container } = mountWith(FRESH);
    await waitFor(() => expect(global.fetch).toHaveBeenCalled());
    expect(container.textContent).not.toMatch(/did not finish/i);
  });
});
