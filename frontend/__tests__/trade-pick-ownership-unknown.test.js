/**
 * TC-A — /trade renders UNKNOWN pick ownership as unknown, never as "owns no
 * picks".
 *
 * After a failed /traded_picks fetch every `sleeper.teams[]` entry carries
 * `picks: null` + `pickOwnershipState: "unavailable"` (#1618).  /trade read
 * `team.picks || []` in app/trade/page.jsx, lib/trade-assets.js and the
 * suggestions desk, so the team showed "0 picks", its owned picks silently
 * vanished from search and the equalizer, and nothing said why (CLAUDE.md
 * "League pick OWNERSHIP is observed or unknown" named /trade as the open
 * follow-up).
 */
import fs from "node:fs";
import path from "node:path";
import { describe, it, expect } from "vitest";
import { teamPickInventory, teamPickLabels, teamPickEntries } from "../lib/trade-assets.js";
import { PICK_OWNERSHIP_UNAVAILABLE_LABEL } from "../lib/pick-ownership.js";

const UNKNOWN = {
  name: "Ty",
  players: ["A"],
  picks: null,
  pickDetails: null,
  pickOwnershipState: "unavailable",
  pickOwnershipReason: "traded_picks_fetch_failed",
};
const KNOWN = { name: "Jason", players: ["B"], picks: ["2027 1st (own)"], pickOwnershipState: "observed" };
const resolve = (label) => ({ name: "2027 Mid 1st", assetClass: "pick", label });

describe("pick inventory: observed or unknown", () => {
  it("unknown ownership is null with its reason, never []", () => {
    expect(teamPickLabels(UNKNOWN)).toBeNull();
    expect(teamPickInventory(UNKNOWN, resolve)).toEqual({
      entries: [],
      unavailableReason: "traded_picks_fetch_failed",
    });
  });

  it("observed ownership lists the picks", () => {
    expect(teamPickLabels(KNOWN)).toEqual(["2027 1st (own)"]);
    const inv = teamPickInventory(KNOWN, resolve);
    expect(inv.unavailableReason).toBeNull();
    expect(inv.entries).toHaveLength(1);
    expect(teamPickEntries(KNOWN, resolve)).toEqual(inv.entries);
  });

  it("the suggestions desk says 'pick ownership unavailable', not '0 picks'", async () => {
    const { pickCountText } = await import("../app/trade/trade-suggestions-desk.jsx");
    expect(pickCountText(UNKNOWN)).toBe(PICK_OWNERSHIP_UNAVAILABLE_LABEL.toLowerCase());
    expect(pickCountText(KNOWN)).toBe("1 picks");
  });

  it("/trade no longer reads team.picks || [] and shows the unknown state", () => {
    const root = path.resolve(__dirname, "..");
    for (const f of ["app/trade/page.jsx", "lib/trade-assets.js", "app/trade/trade-suggestions-desk.jsx"]) {
      expect(fs.readFileSync(path.join(root, f), "utf8")).not.toMatch(/\.picks \|\| \[\]/);
    }
    const page = fs.readFileSync(path.join(root, "app/trade/page.jsx"), "utf8");
    expect(page).toMatch(/title=\{PICK_OWNERSHIP_UNAVAILABLE_LABEL\}/);
  });
});
