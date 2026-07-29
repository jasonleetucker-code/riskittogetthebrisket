/**
 * /bdvm page smoke tests — the states that must never blur:
 * flag-off (503 feature_disabled) is an explanation, not an error;
 * no_projection_snapshot (HTTP 200) tells the operator what to run;
 * a real payload renders the board with backend numbers verbatim.
 */

import { describe, expect, it, vi, beforeEach, afterEach } from "vitest";
import React from "react";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import BdvmPage from "@/app/bdvm/page";

function jsonResponse(status, body) {
  return {
    ok: status >= 200 && status < 300,
    status,
    json: async () => body,
  };
}

const OK_PAYLOAD = {
  status: "ok",
  meta: {
    modelVersion: "1.0.0",
    paramSetId: "params_v1:abc123",
    counts: { priced: 2, unpriced: 1 },
    projectionSnapshot: { asOf: "2026-07-27", recordCount: 2815 },
  },
  replacement: {},
  players: [
    {
      playerId: "p1",
      name: "Elite Backer",
      position: "LB",
      group: "LB",
      raw: { age: 24.0 },
      tradeValue: { contender: 7000, balanced: 7200, rebuilder: 7400, risk_neutral: 7100 },
      projection: { fpg: 16.8, sourceCount: 1, anyProxy: false },
      market: { marketValue: 6400, marketSource: "idpTradeCalc", gap: 800.0 },
      signal: { signal: "BUY", reason: "gap above threshold" },
      quality: { confidenceScore: 0.6, confidenceLabel: "medium" },
      range: { floor_p20: 6000, ceiling_p85: 8500 },
      dynastyScore0to100: 95.0,
    },
    {
      playerId: "p2",
      name: "Proxy Vet",
      position: "WR",
      group: "WR",
      raw: { age: 29.5 },
      tradeValue: { contender: 5200, balanced: 4200, rebuilder: 2100, risk_neutral: 4100 },
      projection: { fpg: 13.1, sourceCount: 1, anyProxy: true },
      market: { marketValue: null, marketSource: null, gap: null },
      signal: { signal: "NO_MARKET", reason: "no anchor" },
      quality: { confidenceScore: 0.3, confidenceLabel: "low" },
      range: { floor_p20: 3000, ceiling_p85: 5000 },
      dynastyScore0to100: 41.0,
    },
  ],
  picks: [],
  unpriced: [{ name: "No Age Guy", reason: "missing_age", position: "CB" }],
};

beforeEach(() => {
  vi.stubGlobal("fetch", vi.fn());
});

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("BdvmPage states", () => {
  it("renders the flag-off explanation on 503 feature_disabled", async () => {
    fetch.mockResolvedValue(
      jsonResponse(503, { error: "feature_disabled", flag: "bdvm_engine" }),
    );
    render(<BdvmPage />);
    expect(
      await screen.findByText("Fundamental values are switched off"),
    ).toBeInTheDocument();
    // Never a generic error banner for a configuration state.
    expect(screen.queryByText("Fundamentals unavailable")).toBeNull();
  });

  it("states the flag-off case without leaking backend configuration", async () => {
    // The copy used to name the env var an operator would set
    // (RISKIT_FEATURE_BDVM_ENGINE=1).  This page is behind login but
    // guest-pass holders reach it too, and a deployment switch is not
    // something any reader of this page can act on.  The runbook lives
    // in CLAUDE.md, where the operator actually looks.
    fetch.mockResolvedValue(
      jsonResponse(503, { error: "feature_disabled", flag: "bdvm_engine" }),
    );
    render(<BdvmPage />);
    await screen.findByText("Fundamental values are switched off");
    expect(screen.queryByText(/RISKIT_FEATURE/)).toBeNull();
    // It must still say the rest of the site is unaffected — that is
    // the question a reader actually has.
    expect(screen.getByText(/Nothing else changes/i)).toBeInTheDocument();
  });

  it("explains the missing-snapshot state in user terms", async () => {
    fetch.mockResolvedValue(
      jsonResponse(200, {
        status: "no_projection_snapshot",
        meta: { projectionSnapshot: null },
        message: "BDVM has no projection snapshot for season 2026",
        players: [],
        picks: [],
        unpriced: [],
        replacement: {},
      }),
    );
    render(<BdvmPage />);
    expect(
      await screen.findByText("No projection snapshot yet"),
    ).toBeInTheDocument();
    // Says it recovers on its own rather than printing a script path
    // the reader cannot run.
    expect(screen.getByText(/refreshes automatically/i)).toBeInTheDocument();
    expect(screen.queryByText(/refresh_bdvm_projections/)).toBeNull();
  });

  it("renders backend numbers verbatim on a real payload", async () => {
    fetch.mockResolvedValue(jsonResponse(200, OK_PAYLOAD));
    render(<BdvmPage />);
    expect(await screen.findByText("Elite Backer")).toBeInTheDocument();
    // balanced trade value, rounded + locale-formatted
    expect(screen.getByText((7200).toLocaleString())).toBeInTheDocument();
    expect(screen.getByText("+800")).toBeInTheDocument();
    expect(screen.getByText("Buy")).toBeInTheDocument();
    // proxy projection is labeled, null market renders as absence
    expect(screen.getByText("proxy")).toBeInTheDocument();
    expect(screen.getByText("No market")).toBeInTheDocument();
    // meta strip shows the snapshot stamp
    expect(screen.getByText("2026-07-27")).toBeInTheDocument();
  });

  it("keeps the values payload across a tab round-trip without refetching", async () => {
    fetch.mockImplementation(async (url) => {
      if (String(url).startsWith("/api/bdvm/roster")) {
        return jsonResponse(200, { status: "ok", rosters: [], meta: {} });
      }
      return jsonResponse(200, OK_PAYLOAD);
    });
    const user = userEvent.setup();
    render(<BdvmPage />);
    await screen.findByText("Elite Backer");
    const valuesCalls = () =>
      fetch.mock.calls.filter((c) => String(c[0]).startsWith("/api/bdvm/values")).length;
    expect(valuesCalls()).toBe(1);

    await user.click(screen.getByRole("tab", { name: "Rosters" }));
    await screen.findByText("No rosters");

    await user.click(screen.getByRole("tab", { name: "Value Board" }));
    // payload survives the round-trip; no second /values fetch
    expect(await screen.findByText("Elite Backer")).toBeInTheDocument();
    expect(valuesCalls()).toBe(1);
  });
});
