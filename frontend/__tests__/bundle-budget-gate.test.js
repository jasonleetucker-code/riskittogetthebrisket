import { describe, it, expect, beforeAll, afterAll } from "vitest";
import { spawnSync } from "node:child_process";
import fs from "node:fs";
import os from "node:os";
import path from "node:path";
import url from "node:url";

// ``check-bundle-sizes.mjs`` is the BLOCKING per-page budget gate in PR
// Validation, which makes it the instrument every performance claim in
// this repo rests on.  An instrument that cannot fail is not a gate, and
// this file exists because it could not: a budgeted page whose chunks did
// not resolve was logged as "(no chunks — skipped)" and the run still
// printed "all pages under budget ✓" and exited 0.  ``/rankings/page``
// could disappear from the build entirely and CI stayed green.
//
// These tests drive the real script against a SYNTHETIC dist dir via
// ``NEXT_DIST_DIR`` (the same env var ``deploy/deploy.sh`` uses to point
// it at a staging build), so they assert the shipped exit codes rather
// than a reimplementation of its logic.

const HERE = path.dirname(url.fileURLToPath(import.meta.url));
const SCRIPT = path.join(HERE, "..", "scripts", "check-bundle-sizes.mjs");

// Read the budgeted page keys out of the script itself.  Hardcoding a
// copy here would make the test pass while the gate policed a different
// set — the failure mode this whole file is about.
function budgetedPageKeys() {
  const src = fs.readFileSync(SCRIPT, "utf8");
  const block = src.slice(
    src.indexOf("const BUDGETS_KB = {"),
    src.indexOf("\n};", src.indexOf("const BUDGETS_KB = {")),
  );
  return [...block.matchAll(/^\s*"([^"]+)":\s*\d+/gm)].map((m) => m[1]);
}

function runGate(distDir) {
  const res = spawnSync(process.execPath, [SCRIPT], {
    env: { ...process.env, NEXT_DIST_DIR: distDir },
    encoding: "utf8",
  });
  return { code: res.status, out: `${res.stdout}${res.stderr}` };
}

/** Write a 1 KB stub chunk for each page key, so every budget passes. */
function buildFakeDist(dir, pageKeys) {
  const appDir = path.join(dir, "static", "chunks", "app");
  for (const key of pageKeys) {
    const rel = key.replace(/^\//, "");
    const target = path.join(appDir, `${rel}-testhash.js`);
    fs.mkdirSync(path.dirname(target), { recursive: true });
    fs.writeFileSync(target, "x".repeat(1024));
  }
}

function chunkPathFor(dir, pageKey) {
  return path.join(
    dir,
    "static",
    "chunks",
    "app",
    `${pageKey.replace(/^\//, "")}-testhash.js`,
  );
}

describe("check-bundle-sizes gate", () => {
  let tmp;
  let keys;

  beforeAll(() => {
    keys = budgetedPageKeys();
    tmp = fs.mkdtempSync(path.join(os.tmpdir(), "bundle-gate-"));
    buildFakeDist(tmp, keys);
  });

  afterAll(() => {
    fs.rmSync(tmp, { recursive: true, force: true });
  });

  // Self-guard: if the parse above silently returned nothing, every other
  // test in this file would trivially "pass" against an empty build.
  it("parses the real budget table, and it is not empty", () => {
    expect(keys.length).toBeGreaterThan(10);
    expect(keys).toContain("/rankings/page");
    expect(keys).toContain("/page");
  });

  it("passes when every budgeted page resolves and is under budget", () => {
    const { code, out } = runGate(tmp);
    expect(out).toContain("all pages under budget");
    expect(code).toBe(0);
  });

  it("reports how many pages it actually measured", () => {
    // A gate that says "✓" without saying what it measured is how the
    // silent skip stayed invisible: the reader cannot tell 14 of 14 from
    // 13 of 14 without counting the lines by hand.
    const { out } = runGate(tmp);
    expect(out).toMatch(new RegExp(`measured ${keys.length} of ${keys.length}`));
  });

  it("FAILS when a budgeted page is missing from the build", () => {
    // The regression itself.  /rankings is the densest route in the app
    // and the one #760's windowing numbers are measured against, so its
    // budget going unmeasured is the worst version of this bug.
    const victim = chunkPathFor(tmp, "/rankings/page");
    const saved = fs.readFileSync(victim);
    fs.rmSync(victim);
    try {
      const { code, out } = runGate(tmp);
      expect(code).not.toBe(0);
      expect(out).toContain("/rankings/page");
      // The message has to be actionable: a deleted route needs its
      // budget entry deleted in the same change, and that is the audit
      // trail BUDGETS_KB exists to keep.
      expect(out).toMatch(/did not resolve|no chunks/i);
    } finally {
      fs.writeFileSync(victim, saved);
    }
  });

  it("still fails, with the structural diagnosis, when NOTHING resolves", () => {
    // The zero case has its own cause (Turbopack's flat chunk layout) and
    // keeps its own message; it must not be swallowed by the new
    // per-page failure.
    const empty = fs.mkdtempSync(path.join(os.tmpdir(), "bundle-gate-empty-"));
    fs.mkdirSync(path.join(empty, "static", "chunks", "app"), {
      recursive: true,
    });
    try {
      const { code, out } = runGate(empty);
      expect(code).toBe(2);
      expect(out).toContain("ZERO");
      expect(out).toMatch(/Turbopack/);
    } finally {
      fs.rmSync(empty, { recursive: true, force: true });
    }
  });

  it("still fails a page that is over budget", () => {
    // Guard against the new refusal path shadowing the original one.
    const victim = chunkPathFor(tmp, "/more/page"); // 10 KB budget
    const saved = fs.readFileSync(victim);
    fs.writeFileSync(victim, "x".repeat(64 * 1024));
    try {
      const { code, out } = runGate(tmp);
      expect(code).toBe(1);
      expect(out).toContain("over budget");
      expect(out).toContain("/more/page");
    } finally {
      fs.writeFileSync(victim, saved);
    }
  });

  it("documents no flag it does not implement", () => {
    // The header advertised a ``--strict`` flag, and line 225 pointed at
    // it as the thing that "would change" the silent skip.  The script
    // never read argv at all, so the documented escape hatch was the
    // reason the default looked deliberate.
    const src = fs.readFileSync(SCRIPT, "utf8");
    const mentionsStrict = /--strict/.test(src);
    const readsArgv = /process\.argv/.test(src);
    expect(mentionsStrict && !readsArgv).toBe(false);
  });
});
