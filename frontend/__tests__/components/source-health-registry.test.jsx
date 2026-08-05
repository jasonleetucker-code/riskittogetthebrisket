// /tools/source-health must list every source in the pipeline.
//
// R13 / W05-F001 / W23-F007.  The page's subtitle is "Scraper status for
// every ranking source in the pipeline"; it rendered four rows, taken
// from `source_health.source_runtime.enabled_sources` — the legacy
// browser scraper's own run plan (['IDPTradeCalc','KTC','KTC_TradeDB',
// 'KTC_WaiverDB']).  The 17 CSV-loaded registry sources appeared
// nowhere, and the per-row count lookup
// `counts[src] || counts[src.toLowerCase()]` resolved 'KTC'→'ktc' but
// missed 'IDPTradeCalc'→'idptradecalc', so a 911-row source rendered as
// an em-dash.
//
// The row set is now `source_health.sources_detail`, registry-keyed and
// built by one backend helper.
import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";

import SourceHealthStrip from "@/components/SourceHealthStrip";

function row(key, over = {}) {
  return {
    key,
    displayName: key,
    inRegistry: true,
    inBlend: true,
    rows: 300,
    blendRows: 290,
    lastFetched: new Date(Date.now() - 3600_000).toISOString(),
    ageHours: 1,
    maxAgeHours: 6,
    staleness: "fresh",
    status: "ok",
    reason: null,
    ...over,
  };
}

const REGISTRY_KEYS = [
  "ktc",
  "ktcSfTep",
  "idpTradeCalc",
  "dlfIdp",
  "idpShow",
  "dlfSf",
  "dynastyNerdsSfTep",
  "fantasyProsSf",
  "fantasyProsIdp",
  "fantasyCalc",
  "otcffbSf",
  "dynastyDaddySf",
  "flockFantasySf",
  "flockFantasySfRookies",
  "yahooBoone",
  "fantasyProsFitzmaurice",
  "dlfRookieSf",
  "dlfRookieIdp",
  "draftSharks",
  "draftSharksIdp",
  "fantasyNavigatorSf",
  "pfkDynasty",
];

function statusBody(detail, extra = {}) {
  return {
    source_health: {
      source_runtime: {
        overall_status: "complete",
        // Deliberately still the four-name legacy run plan: the page
        // must NOT be built from it.
        enabled_sources: ["IDPTradeCalc", "KTC", "KTC_TradeDB", "KTC_WaiverDB"],
        failed_sources: [],
        partial_sources: [],
        finished_at: new Date().toISOString(),
      },
      source_counts: {},
      sources: {},
      source_failures: [],
      missing_sources: [],
      sources_detail: detail,
      ...extra,
    },
  };
}

function mockStatus(body) {
  globalThis.fetch.mockImplementation(() =>
    Promise.resolve({ ok: true, status: 200, json: () => Promise.resolve(body) }),
  );
}

beforeEach(() => {
  vi.stubGlobal("fetch", vi.fn());
});
afterEach(() => {
  vi.unstubAllGlobals();
});

describe("SourceHealthStrip — registry-keyed rows", () => {
  it("renders one row per registered source, not the 4-name scraper run plan", async () => {
    mockStatus(statusBody(REGISTRY_KEYS.map((k) => row(k))));
    render(<SourceHealthStrip variant="page" />);
    await waitFor(() =>
      expect(screen.getByRole("region", { name: /scrape source health/i })).toBeInTheDocument(),
    );
    expect(document.body.textContent).toMatch(
      new RegExp(`Sources · ${REGISTRY_KEYS.length}`),
    );
    await userEvent.click(document.querySelector(".source-health-toggle"));
    const names = [...document.querySelectorAll(".source-health-name")].map((n) => n.textContent);
    expect(names).toEqual(REGISTRY_KEYS);
  });

  it("renders the row count for a camelCase key instead of an em-dash", async () => {
    mockStatus(statusBody([row("idpTradeCalc", { rows: 911 })]));
    render(<SourceHealthStrip variant="page" />);
    await waitFor(() =>
      expect(screen.getByRole("region", { name: /scrape source health/i })).toBeInTheDocument(),
    );
    await userEvent.click(document.querySelector(".source-health-toggle"));
    const count = document.querySelector(".source-health-count").textContent;
    expect(count).toBe("911 rows");
  });

  it("shows 0 rows as zero and an unknown count as an em-dash", async () => {
    mockStatus(
      statusBody([
        row("ktcSfTep", { rows: 0, status: "empty", reason: "no rows on the served board" }),
        row("ktc", { rows: null, status: "unknown", inBlend: false }),
      ]),
    );
    render(<SourceHealthStrip variant="page" />);
    await waitFor(() =>
      expect(screen.getByRole("region", { name: /scrape source health/i })).toBeInTheDocument(),
    );
    await userEvent.click(document.querySelector(".source-health-toggle"));
    const counts = [...document.querySelectorAll(".source-health-count")].map((n) => n.textContent);
    expect(counts).toEqual(["0 rows", "—"]);
    // A dead source is red, an unknown one is not.
    const tones = [...document.querySelectorAll(".source-health-row")].map((n) => n.className);
    expect(tones[0]).toMatch(/source-health-row--down/);
    expect(tones[1]).toMatch(/source-health-row--flat/);
  });

  it("surfaces the per-source failure reason the backend stamped", async () => {
    mockStatus(
      statusBody([row("otcffbSf", { status: "failed", reason: "schema_mismatch" })]),
    );
    render(<SourceHealthStrip variant="page" />);
    await waitFor(() =>
      expect(screen.getByRole("region", { name: /scrape source health/i })).toBeInTheDocument(),
    );
    await userEvent.click(document.querySelector(".source-health-toggle"));
    expect(document.querySelector(".source-health-reason").textContent).toBe("schema_mismatch");
  });
});
