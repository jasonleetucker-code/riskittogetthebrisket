import { describe, it, expect } from "vitest";
import { tradeWorkspaceToCSV, tradeWorkspaceToJSON } from "../lib/trade-logic.js";

const sides = [
  { label: "A", assets: [{ name: "Josh Allen", pos: "QB", team: "BUF", values: { full: 8000, raw: 7900 } }], destinations: {} },
  { label: "B", assets: [{ name: "Bijan, Jr.", pos: "RB", team: "ATL", values: { full: 7000 } }], destinations: {} },
];

describe("tradeWorkspaceToCSV", () => {
  it("emits header + a row per asset with the right value mode", () => {
    const csv = tradeWorkspaceToCSV(sides, "full");
    const lines = csv.trim().split("\n");
    expect(lines[0]).toBe("Side,Asset,Position,Team,Value");
    expect(lines[1]).toBe("A,Josh Allen,QB,BUF,8000");
    // comma in name must be quoted
    expect(lines[2]).toBe('B,"Bijan, Jr.",RB,ATL,7000');
  });
  it("raw mode falls back to full when raw missing", () => {
    const csv = tradeWorkspaceToCSV(sides, "raw");
    expect(csv).toContain("A,Josh Allen,QB,BUF,7900");
    expect(csv).toContain('"Bijan, Jr.",RB,ATL,7000');
  });
});

describe("tradeWorkspaceToJSON", () => {
  it("is the canonical workspace payload, pretty-printed", () => {
    const obj = JSON.parse(tradeWorkspaceToJSON(sides, "full", 0));
    expect(obj.version).toBe(2);
    expect(obj.valueMode).toBe("full");
    expect(obj.sides[0].assets).toEqual(["Josh Allen"]);
  });
});
