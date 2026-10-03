/**
 * lib/team-context.js — the one client source of truth for Use Team Context
 * (#842).  Server owner: src/trade/team_context.py.
 */
import { describe, it, expect, beforeEach } from "vitest";
import { act, renderHook } from "@testing-library/react";
import {
  ASSET_ONLY_LABEL,
  EXCLUDED_NOTE,
  TEAM_CONTEXT_STORAGE_KEY,
  normalizeTeamContext,
  readTeamContextPreference,
  teamContextDimensionRows,
  teamContextModeLabel,
  useTeamContextPreference,
  withTeamContext,
  writeTeamContextPreference,
} from "@/lib/team-context";

describe("team-context", () => {
  beforeEach(() => window.localStorage.clear());

  it("mirrors the server rule: only an explicit false is Asset-Only", () => {
    for (const raw of [undefined, null, "false", 0, "off", {}]) {
      expect(normalizeTeamContext(raw)).toBe(true);
    }
    expect(normalizeTeamContext(false)).toBe(false);
  });

  it("attaches the mode in one place", () => {
    expect(withTeamContext({ a: 1 }, false)).toEqual({ a: 1, useTeamContext: false });
    expect(withTeamContext({ a: 1 }, "nope")).toEqual({ a: 1, useTeamContext: true });
  });

  it("persists the viewer's choice and defaults ON", () => {
    expect(readTeamContextPreference()).toBe(true);
    writeTeamContextPreference(false);
    expect(window.localStorage.getItem(TEAM_CONTEXT_STORAGE_KEY)).toBe("asset");
    expect(readTeamContextPreference()).toBe(false);
  });

  it("a share link's mode applies to the page without overwriting the preference", () => {
    writeTeamContextPreference(true);
    const { result } = renderHook(() => useTeamContextPreference());
    act(() => result.current[2](false));
    expect(result.current[0]).toBe(false);
    expect(readTeamContextPreference()).toBe(true);
    act(() => result.current[1](false));
    expect(readTeamContextPreference()).toBe(false);
  });

  it("uses the supersession's words", () => {
    expect(ASSET_ONLY_LABEL).toBe("Asset-Only Analysis");
    expect(EXCLUDED_NOTE).toBe("Not included in this verdict");
    expect(teamContextModeLabel({ applied: false })).toBe("Asset-Only Analysis");
    expect(teamContextModeLabel(null, true)).toBe("Team Context");
  });

  it("renders the server's dimension rows verbatim", () => {
    const rows = teamContextDimensionRows({
      applied: true,
      dimensions: [
        { dimension: "rosterCapacity", label: "Roster capacity", state: "included", includedInVerdict: true },
        { dimension: "competitivePosture", label: "Posture", state: "unavailable", reason: "no_sim" },
      ],
    });
    expect(rows[0]).toMatchObject({ included: true, stateText: "Included in this verdict" });
    expect(rows[1]).toMatchObject({ included: false, stateText: "Unavailable", reason: "no sim" });
  });
});
