import { describe, it, expect } from "vitest";
import fs from "node:fs";
import path from "node:path";
import url from "node:url";

// Regression guard for the prod-e2e-smoke.yml failure reproduced
// 2026-08-20 (run 32351289881): tests/e2e/specs/public-league.spec.js's
// visitLeague() waited only 15_000ms for a deep-linked tab's needle
// text after "Loading section..." cleared, but that message is
// next/dynamic's CODE-split loading state (LeagueClient.jsx's
// `sectionLoading`), not the section's own DATA fetch. A cold
// per-section Next Data Cache miss (revalidate: 60s, not proactively
// warmed — only the aggregate /api/public/league is) makes
// build_section_payload() a live request-time cost: GET
// /api/public/league/awards measured 13.998s cold vs 2.6s warm against
// production the same day, leaving almost no margin inside a 15s
// budget. This test does not re-measure production; it pins the fixed
// timeout so nobody quietly shrinks it back toward the value that was
// proven to fail.
const __dirname = path.dirname(url.fileURLToPath(import.meta.url));
const specPath = path.resolve(
  __dirname,
  "../../tests/e2e/specs/public-league.spec.js",
);
const src = fs.readFileSync(specPath, "utf-8");

function extractVisitLeagueBody(source) {
  const start = source.indexOf("async function visitLeague(");
  expect(
    start,
    "visitLeague() must still exist in public-league.spec.js",
  ).toBeGreaterThan(-1);
  const end = source.indexOf("\ntest.describe(", start);
  expect(
    end,
    "could not find the end of visitLeague() before test.describe(",
  ).toBeGreaterThan(start);
  return source.slice(start, end);
}

describe("public-league.spec.js visitLeague() cold-section timeout", () => {
  it("waits at least 30s for the deep-linked tab's needle text, not the 15s that measured failing", () => {
    const body = extractVisitLeagueBody(src);
    const waitForTextBlock = body.slice(body.indexOf("if (waitForText)"));
    const match = waitForTextBlock.match(/timeout:\s*(\d+)_?(\d*)/);
    expect(
      match,
      "expected a `timeout: N` option on the waitForText waitForFunction call",
    ).not.toBeNull();
    const timeoutMs = Number(match[1] + (match[2] || ""));
    expect(
      timeoutMs,
      "the waitForText timeout regressed toward the 15000ms budget measured " +
        "failing against production (13.998s cold-section response) — see the " +
        "comment above the waitForFunction call in visitLeague()",
    ).toBeGreaterThanOrEqual(30_000);
  });

  it('still waits for "Loading section..." (the code-split loader) before the needle check', () => {
    const body = extractVisitLeagueBody(src);
    expect(body).toContain("Loading section...");
    const loadingSectionIdx = body.indexOf("Loading section...");
    const waitForTextIdx = body.indexOf("if (waitForText)");
    expect(
      loadingSectionIdx,
      "the code-split loading wait must run before the needle-text wait",
    ).toBeLessThan(waitForTextIdx);
  });
});
