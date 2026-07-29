/**
 * Frontend half of the strict canonical name-key parity test (debt item D1).
 *
 * There is exactly ONE cross-language normalizer pair in this repo:
 * `src/utils/name_clean.py::normalize_player_name` and
 * `frontend/lib/player-name-match.js::normalizePlayerNameKey`.
 *
 * The JS side keys the news-by-player index, the news filters, and the
 * BDVM "Fund gap" column join on /rankings and /draft (`lib/bdvm.js`)
 * — all lookups against rows the backend keyed with the Python
 * function. Drift there is silent: no error, just no news and no gap
 * column for the affected players.
 *
 * `lib/dynasty-data.js` used to carry a THIRD copy, also documented as
 * a mirror, which had drifted (no apostrophe rule, so "Ja'Marr Chase"
 * → "ja marr chase" instead of "jamarr chase"). Nothing caught it: it
 * had no production callers and its own tests used no apostrophe
 * names. It was deleted on 2026-07-29 and this file exists so the
 * surviving pair cannot drift the same way.
 *
 * BOTH halves assert against ONE fixture,
 * `tests/fixtures/name_key_cases.json` — expectations are generated
 * from the Python function, which is the source of truth. Neither half
 * hardcodes expectations of its own, so a divergence turns exactly one
 * suite red against a shared, human-reviewable statement of what the
 * key means.
 *
 * Backend twin: `tests/utils/test_name_key_parity.py`.
 *
 * NOT pinned here, on purpose:
 *   - The backend's `CANONICAL_NAME_ALIASES` nickname table. It is
 *     deliberately not mirrored in JS (see the `player-name-match.js`
 *     header) — both sides of every news lookup already share the
 *     contract's display-name vocabulary.
 *   - `waiver-logic.js::normalizeNameCompact` vs the Python
 *     `compact_name_key`. Those two look identical and are not
 *     (Python's `isalnum()` keeps "é"; the JS `[^a-z0-9]` strip drops
 *     it). They join different populations and are never compared.
 */
import fs from "node:fs";
import path from "node:path";
import { describe, it, expect } from "vitest";
import { normalizePlayerNameKey } from "@/lib/player-name-match";

const REPO_ROOT = path.resolve(__dirname, "../..");
const FIXTURE_PATH = path.join(
  REPO_ROOT,
  "tests",
  "fixtures",
  "name_key_cases.json",
);

const FIXTURE = JSON.parse(fs.readFileSync(FIXTURE_PATH, "utf8"));

describe("normalizePlayerNameKey — cross-language parity", () => {
  it("loads a non-trivial shared corpus", () => {
    expect(Array.isArray(FIXTURE.cases)).toBe(true);
    expect(FIXTURE.cases.length).toBeGreaterThanOrEqual(25);
    // The apostrophe rule is the one that actually drifted; a corpus
    // without it would have passed against the broken implementation.
    expect(
      FIXTURE.cases.some(
        (c) => c.input.includes("'") || c.input.includes("’"),
      ),
    ).toBe(true);
  });

  it("matches the shared fixture on every case", () => {
    const failures = [];
    for (const { input, expected } of FIXTURE.cases) {
      const got = normalizePlayerNameKey(input);
      if (got !== expected) {
        failures.push(
          `  ${JSON.stringify(input)}: expected ${JSON.stringify(
            expected,
          )}, got ${JSON.stringify(got)}`,
        );
      }
    }
    expect(
      failures.join("\n"),
      "normalizePlayerNameKey diverged from " +
        "tests/fixtures/name_key_cases.json (generated from " +
        "src/utils/name_clean.py::normalize_player_name):\n" +
        failures.join("\n"),
    ).toBe("");
  });

  it("returns '' for null/undefined, matching the Python contract", () => {
    expect(normalizePlayerNameKey(null)).toBe("");
    expect(normalizePlayerNameKey(undefined)).toBe("");
  });
});
