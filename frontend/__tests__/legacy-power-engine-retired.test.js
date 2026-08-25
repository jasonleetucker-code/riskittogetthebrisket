/**
 * V1-52: the legacy power engine must never come back on the frontend
 * either. Mirrors tests/public_league/test_legacy_power_engine_retired.py
 * on the Python side -- structural reachability guards, not behavior
 * tests, so a future change that quietly reintroduces the retired file
 * or conditional goes RED here rather than shipping a second renderer.
 *
 * Mutation-proved (see the PR description) by temporarily restoring a
 * stub power.jsx and re-adding the conditional to LeagueClient.jsx.
 */
import fs from "node:fs";
import path from "node:path";
import { describe, expect, it } from "vitest";

const ROOT = path.resolve(path.dirname(new URL(import.meta.url).pathname), "..");

describe("legacy power engine retirement", () => {
  it("the legacy renderer file does not exist", () => {
    const legacyPath = path.join(ROOT, "app/league/sections/power.jsx");
    expect(fs.existsSync(legacyPath)).toBe(false);
  });

  it("LeagueClient.jsx never imports the legacy renderer", () => {
    const src = fs.readFileSync(path.join(ROOT, "app/league/LeagueClient.jsx"), "utf8");
    expect(src).not.toMatch(/sections\/power\.jsx/);
    expect(src).not.toMatch(/\bPowerSection\b/);
  });

  it("LeagueClient.jsx renders RosPowerSection unconditionally for the power tab", () => {
    const src = fs.readFileSync(path.join(ROOT, "app/league/LeagueClient.jsx"), "utf8");
    expect(src).toMatch(/activeTab === "power" && <RosPowerSection/);
  });

  it("the retired settings flag is gone from every layer", () => {
    const files = [
      "app/league/LeagueClient.jsx",
      "components/useSettings.js",
      "app/settings/page.jsx",
    ];
    for (const rel of files) {
      const src = fs.readFileSync(path.join(ROOT, rel), "utf8");
      expect(src, rel).not.toMatch(/useRosPowerRankings/);
    }
  });

  it("PUBLIC_SECTION_KEYS no longer lists 'power'", () => {
    const src = fs.readFileSync(path.join(ROOT, "lib/public-league-data.js"), "utf8");
    const match = src.match(/PUBLIC_SECTION_KEYS = Object\.freeze\(\[([\s\S]*?)\]\)/);
    expect(match).toBeTruthy();
    const keys = match[1].match(/"([a-zA-Z]+)"/g) || [];
    expect(keys).not.toContain('"power"');
  });

  it("tabs.js SECTION_FOR_TAB no longer maps 'power'", () => {
    const src = fs.readFileSync(path.join(ROOT, "app/league/tabs.js"), "utf8");
    expect(src).not.toMatch(/power:\s*"power"/);
  });
});
