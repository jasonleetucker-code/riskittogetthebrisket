/**
 * TC-B2 / TCM-G18 — a calculator save carries the War Room decision served
 * for that trade, by run id; the server attaches its OWN logged record and the
 * desk shows it as "the answer when saved", never refreshed, never a status.
 */
import { afterEach, describe, expect, it, vi } from "vitest";
import React from "react";
import { render, screen } from "@testing-library/react";

vi.mock("@/lib/trade-share", () => ({ buildShareUrl: () => "/trade?share=x" }));

import TradeDeskView from "@/app/arbitrage/TradeDeskView";
import { deskDecisionText } from "@/lib/trade-desk";
import { deskBodyFromCalculator } from "@/lib/trade-next-actions";

const sides = [
  { label: "A", assets: [{ name: "Our WR", pos: "WR", assetClass: "offense" }] },
  { label: "B", assets: [{ name: "Their RB", pos: "RB", assetClass: "offense" }] },
];
const parties = { ok: true, mySideIdx: 0, myTeam: "Us", opponent: "Them" };

describe("deskBodyFromCalculator", () => {
  it("carries the current decision's run id, and only a run id", () => {
    const { body } = deskBodyFromCalculator({
      sides,
      parties,
      leagueKey: "main",
      decisionRunId: "0123456789abcdef0123",
    });
    expect(body.decisionRunId).toBe("0123456789abcdef0123");
    expect(body).not.toHaveProperty("decision");
    expect(body).not.toHaveProperty("headline");
  });

  it("no current answer, no field", () => {
    const { body } = deskBodyFromCalculator({ sides, parties, leagueKey: "main" });
    expect(body).not.toHaveProperty("decisionRunId");
  });
});

describe("deskDecisionText", () => {
  it("names the answer as of the save, and that it is not refreshed", () => {
    const text = deskDecisionText(
      {
        decision: {
          headlineText: "NO — TOO CLOSE",
          confidenceLevel: "MEDIUM",
          recordedAt: "2026-10-18T12:00:00+00:00",
        },
      },
      () => "Oct 18",
    );
    expect(text).toBe(
      "War Room answer when saved on Oct 18: NO — TOO CLOSE · medium confidence. Not refreshed; open it in the calculator for today's answer.",
    );
  });

  it("an unverifiable run is stated, and nothing at all when none was sent", () => {
    expect(deskDecisionText({ decisionUnavailable: "decision_run_not_found" })).toMatch(
      /could not be verified/,
    );
    expect(deskDecisionText({})).toBeNull();
  });
});

describe("Trade Desk view shows the saved decision", () => {
  const original = global.fetch;
  afterEach(() => {
    global.fetch = original;
  });

  it("renders the decision line beside the roster evidence", async () => {
    const item = {
      id: "0123456789abcdef",
      myTeam: "Us",
      opponent: "Them",
      send: [{ name: "Our WR", isPick: false }],
      receive: [{ name: "Their RB", isPick: false }],
      source: "calculator",
      status: "candidate",
      statusHistory: [{ status: "candidate", at: "2026-10-18T12:00:00+00:00", setBy: "user" }],
      note: "",
      rosterCheck: { state: "current", picksNotChecked: 0 },
      decision: {
        runId: "0123456789abcdef0123",
        recordedAt: "2026-10-18T12:00:00+00:00",
        headline: "YES",
        headlineText: "YES — MAKE THE TRADE",
        confidenceLevel: "HIGH",
      },
    };
    global.fetch = vi.fn().mockResolvedValue({
      ok: true,
      status: 200,
      json: async () => ({ leagueKey: "main", count: 1, limit: 100, items: [item] }),
    });
    render(<TradeDeskView leagueKey="main" />);
    const line = await screen.findByTestId("desk-item-decision");
    expect(line.textContent).toMatch(/War Room answer when saved on .*: YES — MAKE THE TRADE · high confidence/);
    // Still the user's status, untouched.
    expect(screen.getByText(/You marked Candidate on/)).toBeInTheDocument();
  });
});
