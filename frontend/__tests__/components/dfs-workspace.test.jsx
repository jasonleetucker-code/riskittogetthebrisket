import React from "react";
import { cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import DfsWorkspace from "@/components/dfs/DfsWorkspace";

function jsonResponse(status, body) {
  return { ok: status >= 200 && status < 300, status, json: async () => body };
}

const RULESET = {
  id: "draftkings.nfl.classic",
  version: "2026.1",
  key: "draftkings.nfl.classic@2026.1",
  label: "DraftKings NFL Classic",
  salaryCap: 50000,
  readiness: "research_only",
  verification: { state: "unverified", blocker: "Official page not yet checked." },
  export: { verification: { state: "unverified" } },
};

const CAPS = {
  matrix: [
    { platform: "draftkings", sport: "nfl", format: "classic", ruleset: RULESET.key, readiness: "research_only", reason: "Rule set encoded but not verified against official rules." },
    { platform: "draftkings", sport: "nba", format: "classic", ruleset: null, readiness: "not_implemented", reason: "NBA rule set not encoded yet." },
  ],
  rulesets: [RULESET],
  objectives: [
    { id: "projection_baseline", label: "Highest projected points", available: true, description: "Baseline." },
    { id: "contest_ev", label: "Contest-aware (cash / GPP)", available: false, description: "Not built yet." },
  ],
};

const SLATE = {
  snapshotId: "snap_1",
  contentHash: "abcdef0123456789",
  ruleset: RULESET,
  athletes: [
    { player_id: "1", name: "Syn QB", positions: ["QB"], team: "AAA", opponent: "BBB", salary: 7000, projection: 20.5, projection_source: "owner_import" },
    { player_id: "2", name: "Syn WR", positions: ["WR"], team: "AAA", opponent: "BBB", salary: 5000, projection: null, projection_source: null },
  ],
  games: ["AAA@BBB"],
  coverage: { athletes: 2, projected: 1, unprojected: 1 },
  importReport: { rejected: [] },
  projectionReport: { unmatched: [], ambiguous: [], conflicts: [], invalid: [] },
  platformAverageApplied: 0,
};

// Answers for the background GETs the panels make (contest list, presets,
// provider status, file detection) — none of them is under test here.
const BACKGROUND = {
  presets: [],
  contests: [],
  matrix: [],
  status: {},
  detection: { platform: null, reasons: [] },
};

beforeEach(() => {
  vi.stubGlobal("fetch", vi.fn());
  try {
    localStorage.clear();
  } catch {
    /* jsdom without storage */
  }
});
afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});

describe("DfsWorkspace", () => {
  it("labels an unverified rule set as research-only and names the blocker", async () => {
    fetch.mockResolvedValue(jsonResponse(200, CAPS));
    render(<DfsWorkspace />);
    expect(await screen.findByText(/Research only — rules unverified/)).toBeInTheDocument();
    expect(screen.getByText(/Official page not yet checked/)).toBeInTheDocument();
  });

  it("shows a not-available state for a sport with no rule set instead of fake controls", async () => {
    fetch.mockResolvedValue(jsonResponse(200, CAPS));
    render(<DfsWorkspace />);
    await screen.findByText(/Research only/);
    fireEvent.click(screen.getByRole("radio", { name: "NBA" }));
    expect(await screen.findByText(/NBA on DraftKings is not available yet/)).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Import slate" })).not.toBeInTheDocument();
  });

  it("imports a slate, never renders a missing projection as zero, and blocks locking it", async () => {
    fetch.mockImplementation(async (url) => {
      if (/\/api\/dfs\/(presets|contests|providers|slates\/detect)$/.test(String(url))) return jsonResponse(200, BACKGROUND);
      if (String(url).endsWith("/capabilities")) return jsonResponse(200, CAPS);
      if (String(url).endsWith("/slates")) return jsonResponse(201, SLATE);
      throw new Error(`unexpected ${url}`);
    });
    render(<DfsWorkspace />);
    await screen.findByText(/Research only/);
    fireEvent.change(screen.getByLabelText("Salary CSV text"), { target: { value: "Position,Name,ID,Salary,TeamAbbrev\n" } });
    fireEvent.click(screen.getByRole("button", { name: "Import slate" }));
    const table = await screen.findByRole("table", { name: /Slate player pool/ });
    expect(within(table).getByText("No projection")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Lock Syn WR" })).toBeDisabled();
    // The contest-aware objective is visible but not selectable.
    const radios = screen.getAllByRole("radio").filter((r) => r.getAttribute("name") === "objective");
    expect(radios.find((r) => r.checked)).toBeTruthy();
    expect(radios.some((r) => r.disabled)).toBe(true);
  });

  it("builds via the explicit baseline objective and surfaces the unverified export format", async () => {
    const calls = [];
    fetch.mockImplementation(async (url, init) => {
      if (/\/api\/dfs\/(presets|contests|providers|slates\/detect)$/.test(String(url))) return jsonResponse(200, BACKGROUND);
      calls.push({ url: String(url), body: init?.body ? JSON.parse(init.body) : null });
      if (String(url).endsWith("/capabilities")) return jsonResponse(200, CAPS);
      if (String(url).endsWith("/slates")) return jsonResponse(201, SLATE);
      if (String(url).endsWith("/builds")) {
        return jsonResponse(201, {
          buildId: "build_1",
          createdAt: "2026-09-30T12:00:00+00:00",
          researchOnly: true,
          solver: "HiGHS",
          methodNote: "sequential",
          ruleset: { key: RULESET.key, exportVerification: "unverified" },
          snapshot: { contentHash: "abcdef0123456789" },
          constraintsHash: "0123456789abcdef",
          limits: ["No ownership modelling."],
          result: {
            status: "optimal",
            requested: 1,
            built: 1,
            shortfall: null,
            elapsedMs: 12,
            excludedUnprojected: ["2"],
            exposure: [],
            lineups: [
              {
                index: 1,
                projection: 20.5,
                salary: 7000,
                salaryRemaining: 43000,
                players: [{ slot: "QB", playerId: "1", name: "Syn QB", team: "AAA", opponent: "BBB", salary: 7000, projection: 20.5 }],
              },
            ],
          },
        });
      }
      throw new Error(`unexpected ${url}`);
    });
    render(<DfsWorkspace />);
    await screen.findByText(/Research only/);
    fireEvent.change(screen.getByLabelText("Salary CSV text"), { target: { value: "x" } });
    fireEvent.click(screen.getByRole("button", { name: "Import slate" }));
    await screen.findByRole("table", { name: /Slate player pool/ });
    fireEvent.click(screen.getByRole("button", { name: "Optimal Lineup" }));
    await waitFor(() => expect(screen.getByRole("button", { name: "Download upload CSV" })).toBeInTheDocument());
    const buildCall = calls.find((c) => c.url.endsWith("/builds"));
    expect(buildCall.body.objective).toBe("projection_baseline");
    expect(buildCall.body.mode).toBe("research");
    expect(buildCall.body.constraints.lineups).toBe(1);
    // Portfolio-only controls are not sent with a single-lineup build.
    expect("maxExposure" in buildCall.body.constraints).toBe(false);
    expect(screen.getByText(/not contest-evaluated/)).toBeInTheDocument();
    expect(screen.getByText(/not yet verified against an official platform template/)).toBeInTheDocument();
    expect(screen.getByText(/Downloading submits nothing/)).toBeInTheDocument();
  });

  it("shows an export refusal instead of saving the error as a file", async () => {
    fetch.mockImplementation(async (url) => {
      if (/\/api\/dfs\/(presets|contests|providers|slates\/detect)$/.test(String(url))) return jsonResponse(200, BACKGROUND);
      const u = String(url);
      if (u.endsWith("/capabilities")) return jsonResponse(200, CAPS);
      if (u.endsWith("/slates")) return jsonResponse(201, SLATE);
      if (u.endsWith("/export")) return jsonResponse(409, { error: "RULESET_SUPERSEDED", message: "The rule-set version this build used is no longer current." });
      return jsonResponse(201, {
        buildId: "build_3",
        createdAt: "2026-09-30T12:00:00+00:00",
        researchOnly: true,
        solver: "HiGHS",
        ruleset: { key: RULESET.key, exportVerification: "unverified" },
        snapshot: { contentHash: "abcdef0123456789" },
        constraintsHash: "0123456789abcdef",
        limits: [],
        result: {
          status: "optimal", requested: 1, built: 1, shortfall: null, elapsedMs: 3, exposure: [],
          lineups: [{ index: 1, projection: 20.5, salary: 7000, salaryRemaining: 43000, players: [{ slot: "QB", playerId: "1", name: "Syn QB", team: "AAA", salary: 7000, projection: 20.5 }] }],
        },
      });
    });
    render(<DfsWorkspace />);
    await screen.findByText(/Research only/);
    fireEvent.change(screen.getByLabelText("Salary CSV text"), { target: { value: "x" } });
    fireEvent.click(screen.getByRole("button", { name: "Import slate" }));
    await screen.findByRole("table", { name: /Slate player pool/ });
    fireEvent.click(screen.getByRole("button", { name: "Optimal Lineup" }));
    fireEvent.click(await screen.findByRole("button", { name: "Download upload CSV" }));
    expect(await screen.findByText("The rule-set version this build used is no longer current.")).toBeInTheDocument();
  });

  it("explains an infeasible build with the conflicting constraints", async () => {
    fetch.mockImplementation(async (url) => {
      if (/\/api\/dfs\/(presets|contests|providers|slates\/detect)$/.test(String(url))) return jsonResponse(200, BACKGROUND);
      if (String(url).endsWith("/capabilities")) return jsonResponse(200, CAPS);
      if (String(url).endsWith("/slates")) return jsonResponse(201, SLATE);
      return jsonResponse(201, {
        buildId: "build_2",
        createdAt: "2026-09-30T12:00:00+00:00",
        researchOnly: true,
        solver: "HiGHS",
        ruleset: { key: RULESET.key, exportVerification: "unverified" },
        snapshot: { contentHash: "abcdef0123456789" },
        constraintsHash: "0123456789abcdef",
        limits: [],
        result: {
          status: "infeasible",
          requested: 1,
          built: 0,
          elapsedMs: 5,
          lineups: [],
          exposure: [],
          shortfall: { missing: 1, reason: "infeasible", conflict: { state: "isolated", described: ["Lock Syn QB", "Lock Other QB"] } },
        },
      });
    });
    render(<DfsWorkspace />);
    await screen.findByText(/Research only/);
    fireEvent.change(screen.getByLabelText("Salary CSV text"), { target: { value: "x" } });
    fireEvent.click(screen.getByRole("button", { name: "Import slate" }));
    await screen.findByRole("table", { name: /Slate player pool/ });
    fireEvent.click(screen.getByRole("button", { name: "Optimal Lineup" }));
    expect(await screen.findByText("No lineup could be built")).toBeInTheDocument();
    expect(screen.getByText("Lock Other QB")).toBeInTheDocument();
    expect(screen.getByText(/Nothing was relaxed/)).toBeInTheDocument();
    expect(screen.queryByRole("link", { name: "Download upload CSV" })).not.toBeInTheDocument();
  });

  it("shows the backend's refusal message when capabilities are unavailable", async () => {
    fetch.mockResolvedValue(jsonResponse(503, { error: "FEATURE_DISABLED", message: "The DFS workspace is switched off." }));
    render(<DfsWorkspace />);
    expect(await screen.findByText("The DFS workspace is switched off.")).toBeInTheDocument();
  });
});
