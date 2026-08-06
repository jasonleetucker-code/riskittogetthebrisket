/**
 * The Next bridge must not serve an unstamped disk snapshot as a contract.
 *
 * WHY THIS EXISTS
 * ---------------
 * `frontend/app/api/dynasty-data/route.js` aborts the backend fetch after
 * a 4s idle timeout and falls back to `loadFromDisk()`. The committed
 * scraper seed (`exports/latest/dynasty_data_*.json`) carries ~1075
 * players and ZERO rank stamps of either name.
 *
 * `buildRows` fail-fasts on exactly that shape (lib/dynasty-data.js) —
 * deliberately, so a drift-prone local blend never renders. So the
 * fallback was manufacturing precisely the input the client is built to
 * reject: the user got a blank board, with no error, while the backend
 * was healthy.
 *
 * It is also sticky. The module-scope base-contract cache then serves the
 * poisoned payload to every subsequent mount for its TTL, and AppShell
 * mounts `useDynastyData` on EVERY route — so one 4s stall degrades the
 * whole app. That is what made the E2E suite fail on a different spec
 * each run, which in turn produced two wrong root-cause diagnoses.
 *
 * These tests pin the two halves of the fix: the stamp check understands
 * BOTH encodings, and an unstamped snapshot is refused rather than served.
 */
import { describe, expect, it } from "vitest";
import fs from "node:fs";
import path from "node:path";

const ROUTE = path.resolve(
  __dirname,
  "..",
  "app",
  "api",
  "dynasty-data",
  "route.js",
);
const source = fs.readFileSync(ROUTE, "utf8");

// The route is a Next server module (next/server imports, filesystem
// access at module scope), so it is asserted structurally rather than
// imported. The behavioural half is covered by the extracted predicate
// below, which is a verbatim copy of the route's logic — kept honest by
// the source assertions.
function hasRankStamps(payload) {
  const arr = Array.isArray(payload?.playersArray) ? payload.playersArray : [];
  for (const r of arr) {
    if (r && Number.isInteger(r.canonicalConsensusRank) && r.canonicalConsensusRank > 0) {
      return true;
    }
  }
  const dict = payload?.players;
  if (dict && typeof dict === "object") {
    for (const p of Object.values(dict)) {
      const rk = p?._canonicalConsensusRank;
      if (Number.isInteger(rk) && rk > 0) return true;
    }
  }
  return false;
}

describe("bridge refuses an unstamped disk snapshot", () => {
  it("guards the disk fallback with a stamp check", () => {
    expect(source).toMatch(/function hasRankStamps/);
    // The fallback must be conditional on it, not unconditional.
    expect(source).toMatch(/if \(hasRankStamps\(parsed\)\)/);
  });

  it("answers 503 rather than serving an unusable contract", () => {
    expect(source).toMatch(/disk_snapshot_unstamped/);
    expect(source).toMatch(/status: 503/);
  });
});

describe("hasRankStamps understands both payload encodings", () => {
  it("accepts an array-encoded payload (full/array view)", () => {
    expect(
      hasRankStamps({ playersArray: [{ canonicalConsensusRank: 1 }] }),
    ).toBe(true);
  });

  it("accepts a legacy-dict payload with the UNDERSCORED field", () => {
    // server.py pops `playersArray` from the runtime view by design, so a
    // healthy `view=app` payload has only the dict — and the dict names
    // the field `_canonicalConsensusRank` (data_contract.py:8346).
    // Checking only the array is what made the old E2E diagnostic report
    // "no rank stamps" on every healthy runtime response.
    expect(
      hasRankStamps({ players: { "Justin Jefferson": { _canonicalConsensusRank: 1 } } }),
    ).toBe(true);
  });

  it("rejects the committed seed's shape: rows present, no stamps anywhere", () => {
    expect(
      hasRankStamps({
        players: { A: { name: "A" }, B: { name: "B" } },
        playersArray: [],
      }),
    ).toBe(false);
  });

  it("rejects null/zero ranks, matching the client's 'positive integer' rule", () => {
    expect(hasRankStamps({ playersArray: [{ canonicalConsensusRank: null }] })).toBe(false);
    expect(hasRankStamps({ playersArray: [{ canonicalConsensusRank: 0 }] })).toBe(false);
    expect(hasRankStamps({ players: { A: { _canonicalConsensusRank: 0 } } })).toBe(false);
  });

  it("tolerates junk without throwing", () => {
    for (const junk of [null, undefined, {}, { players: null }, { playersArray: "no" }]) {
      expect(() => hasRankStamps(junk)).not.toThrow();
      expect(hasRankStamps(junk)).toBe(false);
    }
  });
});

describe("the committed seed really is unstamped", () => {
  // This is what makes the whole fix load-bearing rather than theoretical.
  // If a future seed DOES carry stamps, this test fails and the 503 path
  // becomes unreachable — at which point the guard can be reconsidered.
  it("exports/latest snapshot has no rank stamps", () => {
    const dir = path.resolve(__dirname, "..", "..", "exports", "latest");
    if (!fs.existsSync(dir)) return; // nothing committed in this checkout
    const seed = fs
      .readdirSync(dir)
      .filter((f) => /^dynasty_data_.*\.json$/.test(f))
      .sort()
      .pop();
    if (!seed) return;
    const payload = JSON.parse(fs.readFileSync(path.join(dir, seed), "utf8"));
    expect(Object.keys(payload.players || {}).length).toBeGreaterThan(0);
    expect(hasRankStamps(payload)).toBe(false);
  });
});
