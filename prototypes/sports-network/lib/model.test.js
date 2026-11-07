import { describe, it, expect } from "vitest";
import {
  players,
  selectPlayers,
  selectStories,
  tickerStories,
  csvFor,
} from "./model";
describe("independent fixture acceptance cases", () => {
  it("searches names and teams, conjunctively with position", () => {
    expect(
      selectPlayers({ query: "vale", pos: "WR" }).map((p) => p.id),
    ).toEqual(["demo-01"]);
    expect(selectPlayers({ query: "vale", pos: "QB" })).toEqual([]);
    expect(selectPlayers({ query: "BUF" }).every((p) => p.team === "BUF")).toBe(
      true,
    );
  });
  it("sorts numeric values rather than formatted text", () => {
    const result = selectPlayers({ sort: "value", direction: "desc" });
    expect(result[0].values.Superflex).toBe(9860);
    expect(result.at(-1).values.Superflex).toBeNull();
  });
  it("uses predetermined 1QB ranks and histories", () => {
    const result = selectPlayers({ format: "1QB" });
    expect(result.find((p) => p.id === "demo-02").values["1QB"]).toBe(9317);
    expect(result.find((p) => p.id === "demo-03").values["1QB"]).toBe(9634);
    expect(result.findIndex((p) => p.id === "demo-03")).toBeLessThan(
      result.findIndex((p) => p.id === "demo-02"),
    );
    expect(result.find((p) => p.id === "demo-02").history.at(-1).value).toBe(
      9317,
    );
  });
  it("format boards are descending by fixture value when ordered by rank", () => {
    for (const format of ["Superflex", "1QB", "TE Premium"]) {
      const values = selectPlayers({ format })
        .map((p) => p.values[format])
        .filter((v) => v != null);
      expect(values).toEqual([...values].sort((a, b) => b - a));
    }
  });
  it("filters movement and does not reinterpret unchanged as missing", () => {
    expect(
      selectPlayers({ movement: "Risers" }).every((p) => p.movement > 0),
    ).toBe(true);
    expect(
      selectPlayers({ movement: "Fallers" }).every((p) => p.movement < 0),
    ).toBe(true);
    expect(selectPlayers({ movement: "Unchanged" }).map((p) => p.id)).toContain(
      "demo-07",
    );
  });
  it("sorts missing source spread last in both directions", () => {
    for (const direction of ["asc", "desc"])
      expect(
        selectPlayers({ sort: "disagreement", direction }).at(-1).disagreement,
      ).toBeNull();
  });
  it("preserves missing projections, source coverage and historical gaps", () => {
    expect(players[4].projection).toBeNull();
    expect(players[4].disagreement).toBeNull();
    expect(players[0].history[3].value).toBeNull();
    expect(players[5].sourceAsOf).toBe("2026-11-01T18:00:00Z");
    expect(players.at(-1).histories.Superflex.at(-1).value).toBeNull();
  });
  it("matches seven-day movement to the fixed Oct31 and Nov7 observations", () => {
    for (const p of players)
      for (const format of ["Superflex", "1QB", "TE Premium"]) {
        if (p.values[format] == null) continue;
        const history = p.histories[format];
        expect(history.at(-2).date).toBe("2026-10-31");
        expect(history.at(-1).value - history.at(-2).value).toBe(p.movement);
      }
  });
  it("exports exactly the filtered board with demonstration label and format", () => {
    const csv = csvFor(selectPlayers({ query: "Vale" }), "1QB");
    expect(csv.split("\r\n")).toHaveLength(2);
    expect(csv).toContain("SYNTHETIC DEMO");
    expect(csv).toContain('"1QB"');
    expect(csv).toContain('"9880"');
    expect(csv).not.toContain("Elias Brooks");
  });
  it("filters news facets over the same player mention", () => {
    expect(selectStories({ team: "SEA", pos: "WR" }).length).toBe(2);
    expect(selectStories({ team: "SEA", pos: "QB" })).toEqual([]);
    expect(
      selectStories({ query: "Vale", scope: "Demo roster" }).map(
        (s) => s.playerId,
      ),
    ).toEqual(["demo-01", "demo-01"]);
  });
  it("keeps stale and unconfirmed stories out of the priority tape", () => {
    const tape = tickerStories();
    expect(
      tape.every((s) => !s.stale && s.classification !== "Unconfirmed"),
    ).toBe(true);
    expect(tape[0].classification).toBe("Official confirmation");
  });
});
