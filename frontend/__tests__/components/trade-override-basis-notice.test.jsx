/**
 * TC-A / UX audit P0-7 — when the builder holds value overrides, every
 * surface that prices on the canonical board instead says so.
 *
 * Overriding Bowers to 9,500 moved the meter to LOPSIDED 29% while the War
 * Room still read "+4,726 … you give 9,981" and LEAN MAKE; the only
 * explanation sat inside the collapsed "How this was decided".  The total
 * itself carried no "edited" marker.  (User SOURCE weights need no notice:
 * the server ignores them — normalize_source_overrides, disabled 2026-08-14.)
 */
import { describe, it, expect, vi, afterEach } from "vitest";
import React from "react";
import { cleanup, render, screen } from "@testing-library/react";

vi.mock("@/components/useSettings", () => ({ useSettings: () => ({ settings: {} }) }));

const { overrideBasisNotice } = await import("@/lib/trade-war-room");
const { default: CONSOLIDATION } = await import("../fixtures/trade-war-room/consolidation.json");
const req = (fixture) => ({ ...fixture._fixture.request, mySide: 0 });
const { default: TradeWarRoom } = await import("@/components/trade/TradeWarRoom");
const { SimulationPanel } = await import("@/app/trade/trade-simulation-panel");

afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
});

const request = {
  teamName: "Jason",
  playersIn: ["A"],
  playersOut: ["B"],
  picksIn: [],
  picksOut: [],
  pickAssetIdsIn: [],
  pickAssetIdsOut: [],
  mySide: 0,
};

describe("override basis notice", () => {
  it("is null without overrides and names the count with them", () => {
    expect(overrideBasisNotice(0)).toBeNull();
    expect(overrideBasisNotice(1)).toMatch(
      /your 1 value override in the builder is not applied here/,
    );
    expect(overrideBasisNotice(3)).toMatch(/your 3 value overrides in the builder are not applied/);
  });

  it("the War Room shows it up front with the analysis, outside the collapsed details", async () => {
    vi.spyOn(globalThis, "fetch").mockImplementation(async () => ({
      ok: true,
      status: 200,
      json: async () => CONSOLIDATION,
    }));
    render(
      <TradeWarRoom
        request={req(CONSOLIDATION)}
        leagueKey="main"
        useTeamContext
        overrideCount={2}
      />,
    );
    const notice = await screen.findByTestId("war-room-basis-notice", {}, { timeout: 3000 });
    expect(notice.textContent).toMatch(/2 value overrides/);
  });

  it("while the analysis runs it is not shown: the trade value on screen then INCLUDES the overrides", () => {
    vi.spyOn(globalThis, "fetch").mockImplementation(() => new Promise(() => {}));
    render(<TradeWarRoom request={request} overrideCount={1} />);
    expect(screen.queryByTestId("war-room-basis-notice")).toBeNull();
  });

  it("after a failed analysis it is not shown either", async () => {
    vi.spyOn(globalThis, "fetch").mockImplementation(async () => ({
      ok: false,
      status: 503,
      json: async () => ({ error: "data_not_ready" }),
    }));
    render(<TradeWarRoom request={request} overrideCount={1} />);
    await screen.findByTestId("war-room-error", {}, { timeout: 3000 });
    expect(screen.queryByTestId("war-room-basis-notice")).toBeNull();
  });

  it("the War Room says nothing when there are no overrides", () => {
    vi.spyOn(globalThis, "fetch").mockImplementation(() => new Promise(() => {}));
    render(<TradeWarRoom request={request} overrideCount={0} />);
    expect(screen.queryByTestId("war-room-basis-notice")).toBeNull();
  });

  it("Simulate impact shows it too", () => {
    render(
      <SimulationPanel
        simResult={{ team: { name: "Jason" }, delta: {}, before: {}, after: {} }}
        overrideCount={1}
        onReset={() => {}}
      />,
    );
    expect(screen.getByTestId("simulation-basis-notice").textContent).toMatch(/1 value override/);
  });

  it("/trade passes the override count to both and marks edited totals", async () => {
    const fs = await import("node:fs");
    const path = await import("node:path");
    const page = fs.readFileSync(path.resolve(__dirname, "../../app/trade/page.jsx"), "utf8");
    // Two-team War Room, Simulate impact, and the multi-team War Room.
    expect(page.match(/overrideCount=\{Object\.keys\(valueOverrides\)\.length\}/g)).toHaveLength(3);
    const sections = fs.readFileSync(
      path.resolve(__dirname, "../../app/trade/trade-sections.jsx"),
      "utf8",
    );
    expect(sections).toMatch(/data-testid="side-total-edited"/);
  });
});
