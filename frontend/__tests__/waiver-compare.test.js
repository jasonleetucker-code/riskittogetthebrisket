/**
 * Waiver Wire Comparison — pure helpers + the unlisted-route boundary.
 */
import { describe, expect, it } from "vitest";
import {
  AGE_ALL,
  AGE_MIN,
  WAIVER_PAGE_SIZE,
  ageLimitLabel,
  formatValue,
  matchesAge,
  recordsFor,
  selectPlayers,
  sortPlayers,
} from "@/lib/waiver-compare";
import {
  WAIVER_COMPARE_PATH,
  isPublicPath,
  isUnlistedPagePath,
} from "@/lib/public-routes";
import robots from "@/app/robots";

const P = (id, name, pos, age, value) => ({ id, name, pos, team: "DET", age, value });

const POOL = [
  P("1", "Alpha", "QB", 30, 5000),
  P("2", "Bravo", "WR", 22, 3000),
  P("3", "Charlie", "LB", null, 4000),
  P("4", "Delta", "WR", 25, null),
  P("5", "Echo", "DL", 20, 1000),
  P("6", "Foxtrot", "WR", 25, 3000.5),
];

const ids = (players) => players.map((p) => p.id);

describe("sorting", () => {
  it("value high→low puts missing values last", () => {
    expect(ids(sortPlayers(POOL, "value_desc"))).toEqual(["1", "3", "6", "2", "5", "4"]);
  });

  it("value low→high STILL puts missing values last (missing is not zero)", () => {
    expect(ids(sortPlayers(POOL, "value_asc"))).toEqual(["5", "2", "6", "3", "1", "4"]);
  });

  it("age youngest/oldest, unknown ages last both ways", () => {
    expect(ids(sortPlayers(POOL, "age_asc"))).toEqual(["5", "2", "6", "4", "1", "3"]);
    expect(ids(sortPlayers(POOL, "age_desc"))).toEqual(["1", "6", "4", "2", "5", "3"]);
  });

  it("player name A→Z", () => {
    expect(ids(sortPlayers(POOL, "name_asc"))).toEqual(["1", "2", "3", "4", "5", "6"]);
  });

  it("does not mutate its input", () => {
    const copy = [...POOL];
    sortPlayers(POOL, "name_asc");
    expect(POOL).toEqual(copy);
  });
});

describe("filters", () => {
  it("position filter", () => {
    expect(ids(selectPlayers(POOL, { position: "WR" }).players)).toEqual(["6", "2", "4"]);
    expect(selectPlayers(POOL, { position: "ALL" }).players).toHaveLength(6);
  });

  it("age limit is inclusive and keeps players younger than the minimum", () => {
    expect(matchesAge(P("x", "x", "WR", 25, 1), 25)).toBe(true);
    expect(matchesAge(P("x", "x", "WR", 26, 1), 25)).toBe(false);
    expect(matchesAge(P("x", "x", "WR", 20, 1), AGE_MIN)).toBe(true);
  });

  it("All ages keeps unknown ages; a limit hides and COUNTS them", () => {
    expect(selectPlayers(POOL, { maxAge: AGE_ALL }).players).toHaveLength(6);
    const limited = selectPlayers(POOL, { maxAge: 25 });
    expect(ids(limited.players)).toEqual(["6", "2", "5", "4"]);
    expect(limited.hiddenUnknownAge).toBe(1);
  });

  it("filters run over the WHOLE pool before paging", () => {
    // 120 players; only the last 60 (lowest values) are young.  A filter
    // applied to the first 50 displayed would find none.
    const pool = Array.from({ length: 120 }, (_, i) =>
      P(String(i), `P${i}`, "WR", i >= 60 ? 22 : 30, 10000 - i),
    );
    const young = selectPlayers(pool, { maxAge: 22 }).players;
    expect(young).toHaveLength(60);
    expect(young.slice(0, WAIVER_PAGE_SIZE)[0].id).toBe("60");
  });
});

describe("formatting", () => {
  it("shows N/A for missing values, never 0", () => {
    expect(formatValue(null)).toBe("N/A");
    expect(formatValue(undefined)).toBe("N/A");
    expect(formatValue(2105.5)).toBe("2,105.5");
    expect(formatValue(8043)).toBe("8,043");
  });

  it("labels the age limit", () => {
    expect(ageLimitLabel(AGE_ALL)).toBe("All ages");
    expect(ageLimitLabel(25)).toBe("25 and younger");
  });

  it("recordsFor drops ids the payload does not describe", () => {
    expect(recordsFor(["1", "zz"], { 1: POOL[0] })).toEqual([POOL[0]]);
  });
});

describe("unlisted route", () => {
  it("is reachable without a session but is NOT public", () => {
    expect(isUnlistedPagePath(WAIVER_COMPARE_PATH)).toBe(true);
    expect(isUnlistedPagePath(`${WAIVER_COMPARE_PATH}/`)).toBe(true);
    expect(isPublicPath(WAIVER_COMPARE_PATH)).toBe(false);
  });

  it("is matched exactly — no prefix widening", () => {
    expect(isUnlistedPagePath("/waiver-wire")).toBe(false);
    expect(isUnlistedPagePath(`${WAIVER_COMPARE_PATH}x`)).toBe(false);
    expect(isUnlistedPagePath(`${WAIVER_COMPARE_PATH}/anything`)).toBe(false);
  });

  it("robots.txt does not allow it", () => {
    const rules = robots().rules[0];
    const allowed = rules.allow.some(
      (a) => a !== "/$" && WAIVER_COMPARE_PATH.startsWith(a.replace(/\$$/, "")),
    );
    expect(allowed).toBe(false);
    expect(rules.disallow).toContain("/");
  });
});
