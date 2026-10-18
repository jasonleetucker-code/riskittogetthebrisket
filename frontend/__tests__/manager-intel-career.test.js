import { describe, expect, it } from "vitest";
import {
  archetypeEvidenceRows,
  archetypeThresholdText,
  careerCoverageProblems,
  careerQuery,
  careerTiles,
  compareHref,
  compareQuery,
  compareRows,
  finishLabel,
  heldText,
  percentileText,
  readCompareParams,
  suggestedArchetypes,
} from "@/lib/manager-intel";
import { CAREER, COMPARE } from "./fixtures/manager-intel-career";

describe("career helpers (Batch E)", () => {
  it("builds the API queries", () => {
    expect(careerQuery("fan1")).toBe("/api/manager-intel/career?username=fan1");
    expect(careerQuery("fan1", "keeper")).toBe(
      "/api/manager-intel/career?username=fan1&scope=keeper",
    );
    expect(compareQuery({ a: "x", b: "y" })).toBe("/api/manager-intel/compare?a=x&b=y");
    expect(compareQuery({ a: "x", leagueId: "12", window: "90d" })).toBe(
      "/api/manager-intel/compare?a=x&leagueId=12&window=90d",
    );
  });

  it("links the private compare page only for valid inputs", () => {
    expect(compareHref({ a: "fan1", b: "fan2" })).toBe("/managers/compare?a=fan1&b=fan2");
    expect(compareHref({ a: "fan1", leagueId: "123" })).toBe(
      "/managers/compare?a=fan1&league=123",
    );
    expect(compareHref({ a: "fan1" })).toBe("/managers/compare?a=fan1");
    expect(compareHref({ a: "../x" })).toBeNull();
    expect(compareHref({ a: "fan1", b: "bad name" })).toBeNull();
    expect(compareHref({ a: "fan1", leagueId: "abc" })).toBeNull();
    expect(readCompareParams("?a=fan1&b=../x&league=42")).toEqual({
      a: "fan1",
      b: "",
      league: "42",
    });
  });

  it("an unread bracket reads Unknown, never Missed; an unread season is Not read", () => {
    expect(finishLabel(CAREER.seasons[1])).toBe("Unknown");
    expect(finishLabel({ held: "full", finish: "missed" })).toBe("Missed playoffs");
    expect(finishLabel({ held: null })).toBe("Not read");
    expect(
      finishLabel({ held: "until_week", finish: null, finishReason: "left_before_season_end" }),
    ).toBe("Left mid-season");
    expect(heldText(CAREER.seasons[1])).toBe("co-owner");
    expect(heldText({ held: "from_week", heldFromWeek: 6 })).toBe("took over in week 6");
  });

  it("career tiles state the seasons each total covers", () => {
    const tiles = Object.fromEntries(careerTiles(CAREER).map((t) => [t.key, t]));
    expect(tiles.titles.value).toBe("0");
    expect(tiles.titles.meta).toBe("over 0 complete seasons");
    expect(tiles.playoffs.value).toBe("0 of 0");
    expect(tiles.playoffs.meta).toBe("no complete season with a known finish");
    expect(tiles.record.value).toBe("9-5");
    expect(tiles.record.meta).toBe("64.3% · over 1 complete season");
    expect(tiles.pf.value).toBe("1.14");
  });

  it("names unread seasons and chains", () => {
    const texts = careerCoverageProblems(CAREER).map((p) => p.text);
    expect(texts).toHaveLength(2);
    expect(texts[0]).toMatch(/Alpha League 2025/);
    expect(texts[1]).toMatch(/history stopped early \(predecessor rate limited\)/);
  });

  it("archetype helpers expose the declared prior and the evidence", () => {
    const items = CAREER.archetypes.items;
    expect(suggestedArchetypes(CAREER.archetypes).map((i) => i.key)).toEqual(["consolidator"]);
    expect(archetypeThresholdText(items[0])).toBe("0.5 (PRIOR CONSOLIDATOR_SHARE_MIN)");
    expect(archetypeEvidenceRows(items[0])).toEqual([
      { key: "matching", label: "matching", value: "4" },
      { key: "trades", label: "trades", value: "6" },
      { key: "share", label: "share", value: "0.667" },
    ]);
  });

  it("comparison rows read straight from each side's blocks", () => {
    const rows = Object.fromEntries(compareRows(COMPARE.managers).map((r) => [r.key, r]));
    expect(rows.trades).toMatchObject({ a: "6", b: "6" });
    expect(rows.picks).toMatchObject({ a: "14", b: "—" }); // unavailable, never 0
    expect(rows.pickValue.a).toBe("—");
    expect(rows.titles.a).toBe("0 of 0");
    expect(rows.archetypes).toMatchObject({ a: "Consolidator", b: "None" });
  });

  it("an unread career is 'Not evaluated', never 'None'", () => {
    const payload = {
      ...COMPARE.managers,
      b: { ...COMPARE.managers.b, career: null, archetypes: null },
    };
    const rows = Object.fromEntries(compareRows(payload).map((r) => [r.key, r]));
    expect(rows.archetypes.b).toBe("Not evaluated");
    expect(rows.titles.b).toBe("—");
  });

  it("a missing percentile says why", () => {
    const [value, picks] = COMPARE.league.metrics;
    expect(percentileText(value)).toBe("Higher than 67% of the league");
    expect(percentileText(picks)).not.toMatch(/%/);
    expect(percentileText({ percentile: null, reason: "manager_not_in_league" })).toBe(
      "Not in this league",
    );
  });
});
