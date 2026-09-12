import { afterEach, describe, expect, it, vi } from "vitest";
import React from "react";
import { cleanup, render } from "@testing-library/react";
import TeamCommandHeader from "@/components/terminal/TeamCommandHeader";
import { hasUsefulElement, summarise, validateRunOptions, buildMetricsInitScript } from "../../scripts/route-baseline-support.mjs";

const home = vi.hoisted(() => ({ team: {}, terminal: {}, history: {} }));
vi.mock("@/components/AppShell", () => ({ useApp: () => ({ rows: [] }) }));
vi.mock("@/components/useTeam", () => ({ useTeam: () => home.team }));
vi.mock("@/components/useLeague", () => ({ useLeague: () => ({ leagues: [] }) }));
vi.mock("@/components/useTerminal", () => ({ useTerminal: () => home.terminal }));
vi.mock("@/components/useRankHistory", () => ({ useRankHistory: () => home.history }));
vi.mock("@/components/terminal/TeamValueChart", () => ({ default: () => null }));

afterEach(() => { cleanup(); document.body.innerHTML = ""; vi.restoreAllMocks(); });

describe("home aggregate readiness", () => {
  it.each([
    [true, true, true, null, "loading"],
    [false, true, false, null, "loading"],
    [false, false, true, 100, "loading"],
    [false, false, false, 100, "ready"],
    [false, false, false, 0, "ready"],
    [false, false, false, null, "unavailable"],
  ])("distinguishes team/terminal/history %s/%s/%s with value %s", (teamLoading, terminalLoading, historyLoading, value, state) => {
    home.team = { loading: teamLoading, privateDataEnabled: true, selectedTeam: teamLoading ? null : { name: "My team", ownerId: "1", players: [] } };
    home.terminal = { loading: terminalLoading, teamAggregates: value == null ? null : { totalValue: value } };
    home.history = { loading: historyLoading, history: null };
    vi.spyOn(HTMLElement.prototype, "getBoundingClientRect").mockReturnValue({ width: 100, height: 30 });
    render(React.createElement(TeamCommandHeader));
    // The old selector accepts the real mounted loading/placeholder tiles.
    expect(hasUsefulElement('[aria-label="Team aggregates"]')).toBe(true);
    expect(document.querySelector('[aria-label="Team command bar"]').dataset.homeState).toBe(state);
    expect(hasUsefulElement('[data-home-state="ready"] [aria-label="Team aggregates"]')).toBe(state === "ready");
  });
  it.each([
    [{ needsSelection: true }, "needs-selection"],
    [{ leagueMismatch: true }, "unavailable"],
    [{ privateDataEnabled: false }, "unavailable"],
    [{ selectedTeam: null }, "unavailable"],
  ])("does not accept unresolved team scope %j", (overrides, state) => {
    home.team = { loading: false, privateDataEnabled: true, selectedTeam: { name: "My team", players: [] }, ...overrides };
    home.terminal = { loading: false, teamAggregates: { totalValue: 100 } };
    home.history = { loading: false, history: null };
    render(React.createElement(TeamCommandHeader));
    expect(document.querySelector('[aria-label="Team command bar"]').dataset.homeState).toBe(state);
  });
  it("preserves a displayed last-good value during refresh without counting unsettled inputs as initial usefulness", () => {
    home.team = { loading: false, privateDataEnabled: true, selectedTeam: { name: "My team", players: [] } };
    home.terminal = { loading: true, teamAggregates: { totalValue: 1234 } };
    home.history = { loading: false, history: null };
    const view = render(React.createElement(TeamCommandHeader));
    expect(view.getByText("1,234")).toBeTruthy();
    expect(document.querySelector('[data-home-state="loading"]')).toBeTruthy();
    home.terminal = { ...home.terminal, loading: false };
    view.rerender(React.createElement(TeamCommandHeader));
    expect(view.getByText("1,234")).toBeTruthy();
    expect(document.querySelector('[data-home-state="ready"]')).toBeTruthy();
  });
});

describe("route baseline validity", () => {
  it("rejects hidden streaming copies, loading skeletons, empty spacers, and zero geometry", () => {
    vi.spyOn(HTMLElement.prototype, "getBoundingClientRect").mockReturnValue({ width: 100, height: 30 });
    for (const html of ['<div hidden><p class="ready">Player</p></div>', '<p class="ready"><span class="ds-skeleton">Loading</span></p>', '<p class="ready"></p>']) {
      document.body.innerHTML = html;
      expect(hasUsefulElement(".ready")).toBe(false);
    }
    document.body.innerHTML = '<p class="ready">A loaded player</p>';
    expect(hasUsefulElement(".ready")).toBe(true);
    HTMLElement.prototype.getBoundingClientRect.mockReturnValue({ width: 0, height: 0 });
    expect(hasUsefulElement(".ready")).toBe(false);
  });
  it("keeps failed samples and unobserved metrics visible, and never rounds CLS to zero", () => {
    const result = summarise([{ usefulMs: 80, cls: 0.072 }, { usefulMs: null }, { error: "auth" }]);
    expect(result.usefulMissing).toBe(2);
    expect(result.errors).toBe(1);
    expect(result.cls.p95).toBe(0.072);
    expect(result.inpMs).toEqual({ p50: null, p95: null, n: 0 });
  });
  it("refuses a vacuous or mislabeled measurement configuration", () => {
    const valid = { runs: 5, viewport: "mobile", cpu: 4, network: "4g", timeout: 45000, routes: ["/rankings"] };
    expect(() => validateRunOptions(valid, ["/rankings"])).not.toThrow();
    for (const invalid of [{ runs: 0 }, { cpu: 0 }, { viewport: "phone" }, { routes: ["/missing"] }, { network: "fast-ish" }]) {
      expect(() => validateRunOptions({ ...valid, ...invalid }, ["/rankings"])).toThrow();
    }
  });
  it("runs the pinned CJS asset-base shim and makes initialization failure explicit", () => {
    vi.stubGlobal("PerformanceObserver", class { static supportedEntryTypes = []; });
    window.eval(buildMetricsInitScript('const base = __dirname + "/"; module.exports = { onLCP(cb) { cb({name:"LCP",value:100}); }, onINP() {}, onCLS(cb) { cb({name:"CLS",value:0}); } };'));
    expect(window.__routeBaselineMetricsReady).toBe(true);
    expect(window.__routeBaselineVitals).toEqual({ LCP: 100, CLS: 0 });
    window.eval(buildMetricsInitScript('throw new Error("broken pinned bundle");'));
    expect(window.__routeBaselineMetricsReady).toBe(false);
    expect(window.__routeBaselineInitError).toBe("vitals_initialization_failed");
    expect(summarise([{ instrumentationError: window.__routeBaselineInitError }]).instrumentationErrors).toBe(1);
    vi.unstubAllGlobals();
  });
});
