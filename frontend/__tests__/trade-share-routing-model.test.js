/**
 * TC-A — share links round-trip 3+-team routing and carry the package model.
 *
 * The encoder kept every side's names but dropped each asset's destination,
 * so a 3-team trade re-opened with default routing — a different trade — and
 * links carried no model version (feature matrix TCM-C04).  Both are
 * additive fields; older links decode exactly as before.
 */
import fs from "node:fs";
import path from "node:path";
import { describe, it, expect } from "vitest";
import {
  decodeTrade,
  describeShareModelChange,
  encodeTrade,
} from "../lib/trade-share.js";

const threeTeam = {
  sides: [
    { name: "Side A", players: ["Pickens", "2027 Mid 1st", "2027 Mid 1st"], destinations: [2, 1, 1] },
    { name: "Side B", players: ["Kyren Williams"], destinations: [0] },
    { name: "Side C", players: ["Nico Collins"], destinations: [1] },
  ],
  packageModel: "geom_q078_v1",
};

describe("share links: routing and model", () => {
  it("round-trips every side's routing, copy by copy", () => {
    const out = decodeTrade(encodeTrade(threeTeam));
    expect(out.sides.map((s) => s.players)).toEqual(threeTeam.sides.map((s) => s.players));
    expect(out.sides.map((s) => s.destinations)).toEqual([[2, 1, 1], [0], [1]]);
    expect(out.packageModel).toBe("geom_q078_v1");
  });

  it("a 2-team link carries no routing and decodes to nulls", () => {
    const enc = encodeTrade({
      sides: [
        { name: "A", players: ["X"] },
        { name: "B", players: ["Y"] },
      ],
    });
    const json = JSON.parse(Buffer.from(enc.replace(/-/g, "+").replace(/_/g, "/"), "base64").toString());
    expect(json.s.every((s) => !("d" in s))).toBe(true);
    expect(decodeTrade(enc).sides[0].destinations).toEqual([null]);
  });

  it("an older link (no d, no pm) still decodes, with null routing and model", () => {
    const legacy = Buffer.from(
      JSON.stringify({ v: 1, s: [{ n: "A", p: ["X"] }, { n: "B", p: ["Y"] }, { n: "C", p: ["Z"] }] }),
    )
      .toString("base64")
      .replace(/\+/g, "-")
      .replace(/\//g, "_")
      .replace(/=+$/, "");
    const out = decodeTrade(legacy);
    expect(out.sides.map((s) => s.players)).toEqual([["X"], ["Y"], ["Z"]]);
    expect(out.sides.every((s) => s.destinations.every((d) => d === null))).toBe(true);
    expect(out.packageModel).toBeNull();
  });

  it("an out-of-range destination is dropped, never trusted", () => {
    const enc = encodeTrade({ sides: [{ players: ["X"], destinations: [9] }, { players: ["Y"] }] });
    expect(decodeTrade(enc).sides[0].destinations).toEqual([null]);
  });

  it("says when the sender's model differs from today's", () => {
    const models = { ktc_2026_04: { label: "KTC VA" }, geom_q078_v1: { label: "Geometric VA" } };
    expect(describeShareModelChange("geom_q078_v1", "geom_q078_v1", models)).toBeNull();
    expect(describeShareModelChange(null, "geom_q078_v1", models)).toBeNull();
    expect(describeShareModelChange("ktc_2026_04", "geom_q078_v1", models)).toMatch(
      /made under KTC VA; totals now use Geometric VA/,
    );
  });

  it("/trade encodes routing + the active model and restores routing on decode", () => {
    const src = fs.readFileSync(path.resolve(__dirname, "../app/trade/page.jsx"), "utf8");
    expect(src).toMatch(/packageModel: ACTIVE_PACKAGE_MODEL_ID/);
    expect(src).toMatch(/const d = resolvedDests\[i\]\?\.\[j\];/);
  });
});
