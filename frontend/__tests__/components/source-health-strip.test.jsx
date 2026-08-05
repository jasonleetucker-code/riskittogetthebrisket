// SourceHealthStrip must not fail silently on the page it *is*.
//
// Observed by driving /tools/source-health with /api/status forced to
// 500 (fresh browser context, so no warm HTTP cache):
//
//   strip rendered: false | alerts: 0
//   "Source Health / Scraper status for every ranking source in the
//    pipeline. / Auto-refreshes every 60 seconds.  Green dot = last
//    run OK and recent (<4h)…"
//
// i.e. a page whose entire purpose is scraper health rendered a legend
// for dots that were not there, and gave the reader no way to tell
// "every source is fine" from "the status endpoint is down".
//
// The hide-on-failure behaviour is deliberate for the *inline* variant
// (a broken status card should not clutter an otherwise-functional
// page) and is kept.  The page variant is the whole surface, so a
// failure there has to be visible — CLAUDE.md's fail-fast convention.
import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";

import SourceHealthStrip from "@/components/SourceHealthStrip";

// Row set comes from `source_health.sources_detail` (registry-keyed,
// built by server._source_health_rows) — NOT from
// `source_runtime.enabled_sources`, which is the legacy scraper's own
// four-name run plan.  See source-health-registry.test.jsx.
function detailRow(key, rows) {
  return {
    key,
    displayName: key,
    inRegistry: true,
    inBlend: true,
    rows,
    blendRows: rows,
    lastFetched: new Date().toISOString(),
    ageHours: 0.1,
    maxAgeHours: 6,
    staleness: "fresh",
    status: "ok",
    reason: null,
  };
}

const HEALTHY = {
  source_health: {
    source_runtime: {
      overall_status: "partial",
      enabled_sources: ["KTC", "IDPTradeCalc"],
      failed_sources: [],
      partial_sources: ["KTC"],
      finished_at: new Date().toISOString(),
    },
    source_counts: { ktc: 500, idpTradeCalc: 900 },
    sources: {},
    source_failures: [],
    missing_sources: [],
    sources_detail: [detailRow("ktc", 500), detailRow("idpTradeCalc", 900)],
  },
};

const NO_SOURCES = {
  source_health: {
    source_runtime: { overall_status: "unknown", enabled_sources: [] },
    source_counts: {},
    sources: {},
    source_failures: [],
    missing_sources: [],
    sources_detail: [],
  },
};

beforeEach(() => {
  vi.stubGlobal("fetch", vi.fn());
});
afterEach(() => {
  vi.unstubAllGlobals();
});

function mockStatus({ ok = true, body = HEALTHY, reject = false } = {}) {
  globalThis.fetch.mockImplementation(() =>
    reject
      ? Promise.reject(new Error("network down"))
      : Promise.resolve({ ok, status: ok ? 200 : 500, json: () => Promise.resolve(body) }),
  );
}

describe("SourceHealthStrip", () => {
  it("page variant surfaces an explicit failure when /api/status errors", async () => {
    mockStatus({ ok: false });
    render(<SourceHealthStrip variant="page" />);
    await waitFor(() => {
      expect(screen.getByRole("status")).toHaveTextContent(/source health unavailable/i);
    });
  });

  it("page variant surfaces a failure when the status fetch throws", async () => {
    mockStatus({ reject: true });
    render(<SourceHealthStrip variant="page" />);
    await waitFor(() => {
      expect(screen.getByRole("status")).toHaveTextContent(/source health unavailable/i);
    });
  });

  it("page variant says so when status loads but reports no enabled sources", async () => {
    mockStatus({ body: NO_SOURCES });
    render(<SourceHealthStrip variant="page" />);
    await waitFor(() => {
      expect(screen.getByRole("status")).toHaveTextContent(/no sources/i);
    });
  });

  it("inline variant still hides itself on failure (deliberate)", async () => {
    mockStatus({ ok: false });
    const { container } = render(<SourceHealthStrip variant="inline" />);
    await waitFor(() => expect(globalThis.fetch).toHaveBeenCalled());
    expect(container.querySelector(".source-health-strip")).toBeNull();
    expect(container.textContent).toBe("");
  });

  it("renders the real summary when status is healthy", async () => {
    mockStatus({});
    render(<SourceHealthStrip variant="page" />);
    await waitFor(() => {
      expect(screen.getByRole("region", { name: /scrape source health/i })).toBeInTheDocument();
    });
    expect(document.body.textContent).toMatch(/Sources · 2/);
  });
});
