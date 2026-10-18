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
    expect(overrideBasisNotice(1)).toMatch(/your 1 value override in the builder is not applied here/);
    expect(overrideBasisNotice(3)).toMatch(/your 3 value overrides in the builder are not applied/);
  });

  it("the War Room shows it up front, outside the collapsed details", () => {
    vi.spyOn(globalThis, "fetch").mockImplementation(() => new Promise(() => {}));
    render(<TradeWarRoom request={request} overrideCount={2} />);
    expect(screen.getByTestId("war-room-basis-notice").textContent).toMatch(/2 value overrides/);
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
    expect(page.match(/overrideCount=\{Object\.keys\(valueOverrides\)\.length\}/g)).toHaveLength(2);
    const sections = fs.readFileSync(path.resolve(__dirname, "../../app/trade/trade-sections.jsx"), "utf8");
    expect(sections).toMatch(/data-testid="side-total-edited"/);
  });
});
