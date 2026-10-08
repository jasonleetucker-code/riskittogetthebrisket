// node --test tests/e2e/prod-auth-safe-reporter.test.js
//
// The prod-auth reporter's output is PUBLISHED (public repo: Actions log +
// artifact).  Owner directive 2026-10-08: no private data in public
// artifacts.  These tests feed it HOSTILE annotations and failures — owner
// ids, player and team names, win %, value/rank movement, recommendations,
// the session cookie, numbers under non-allowlisted keys — and assert none of
// it survives, while every test's status and fixed title stay visible.
const test = require("node:test");
const assert = require("node:assert/strict");
const fs = require("node:fs");
const os = require("node:os");
const path = require("node:path");

const { ALLOWLIST, isPublishable } = require("./prod-auth-annotation-allowlist.js");

const COOKIE = "c0ffee0123456789abcdef0123456789";
const OWNER_ID = "998877665544332211";

function withReporter(fn) {
  const dir = fs.mkdtempSync(path.join(os.tmpdir(), "prod-auth-safe-"));
  const cookieFile = path.join(dir, "cookie");
  fs.writeFileSync(cookieFile, COOKIE);
  const prev = process.env.PROD_SESSION_COOKIE_FILE;
  process.env.PROD_SESSION_COOKIE_FILE = cookieFile;
  const Reporter = require("./prod-auth-safe-reporter.js");
  const reporter = new Reporter();
  const writes = [];
  const realWrite = process.stdout.write.bind(process.stdout);
  process.stdout.write = (chunk) => {
    writes.push(String(chunk));
    return true;
  };
  try {
    fn(reporter);
  } finally {
    process.stdout.write = realWrite;
    if (prev === undefined) delete process.env.PROD_SESSION_COOKIE_FILE;
    else process.env.PROD_SESSION_COOKIE_FILE = prev;
  }
  const report = JSON.parse(fs.readFileSync(path.join(__dirname, "prod-auth-results.json"), "utf-8"));
  fs.rmSync(path.join(__dirname, "prod-auth-results.json"));
  return { report, stdout: writes.join("") };
}

function fakeTest(title, annotations = [], file = "example.spec.js") {
  return {
    title,
    annotations,
    location: { file: `/x/tests/e2e/specs/prod-auth/${file}` },
    parent: { project: () => ({ name: "prod-desktop" }) },
  };
}

const HOSTILE = [
  // identifying values under allowlisted-looking or real keys
  { type: "team-switch-A", description: `${OWNER_ID} dynasty_main w1 live AVAILABLE` },
  { type: "team-switch-reversal", description: "verified 63.2%" },
  { type: "team-selected", description: "Jason's Dynasty Squad" },
  { type: "value-movement", description: "player 4046 (rank 12): status=ok" },
  { type: "war-room-team", description: "Team Name (58 players) league=dynasty_main" },
  { type: "war-room-1for1", description: "rec=accept/high market=812 drops=Some Player" },
  { type: "player-award", description: "league_mvp: Josh Allen, Lamar Jackson" },
  // numbers under NON-allowlisted keys
  { type: "win-pct", description: "57" },
  { type: "roster-size", description: "58" },
  // an allowlisted key carrying the wrong kind
  { type: "team-switch-reversal-verified", description: "true (63.2%)" },
  { type: "team-switch-league", description: OWNER_ID },
  { type: "team-switch-A-mode", description: "Josh Allen" },
  // cookie text, both in a value and in a type
  { type: "session-auth-method", description: `jason_session=${COOKIE}` },
  { type: `jason_session=${COOKIE}`, description: "true" },
  // prototype keys must not resolve to inherited properties
  { type: "constructor", description: "anything" },
  { type: "__proto__", description: "anything" },
  { type: "hasOwnProperty", description: "anything" },
];

const SAFE = [
  { type: "team-switch-league", description: "dynasty_main" },
  { type: "team-switch-A-mode", description: "live" },
  { type: "team-switch-reversal-verified", description: "true" },
  { type: "team-switch-same-generation", description: "false" },
];

const LEAKS = [
  COOKIE,
  OWNER_ID,
  "63.2",
  "Jason's Dynasty Squad",
  "4046",
  "Team Name",
  "rec=accept",
  "Some Player",
  "Josh Allen",
  "Lamar Jackson",
  "Private Player",
  "Call log",
  "Received",
];

test("hostile annotations are withheld and counted; allowlisted ones survive", () => {
  const anns = [...HOSTILE, ...SAFE];
  const { report, stdout } = withReporter((r) => {
    r.onTestEnd(fakeTest("Team A -> B -> C within the selected league", anns, "game-day-team-switch.spec.js"), {
      status: "passed",
      duration: 7,
      errors: [],
      annotations: [],
    });
    r.onEnd({ status: "passed" });
  });
  const blob = JSON.stringify(report) + stdout;
  for (const leak of LEAKS) assert.ok(!blob.includes(leak), `leaked: ${leak}`);
  assert.deepEqual(report.tests[0].annotations, SAFE);
  assert.equal(report.tests[0].withheldCount, HOSTILE.length);
  assert.equal(report.annotationsWithheld, HOSTILE.length);
  assert.equal(report.tests[0].status, "passed");
  assert.equal(report.tests[0].title, "Team A -> B -> C within the selected league");
  assert.equal(report.sanitized, true);
});

test("an allowlisted type in the WRONG spec file is withheld (allowlist is per spec)", () => {
  const { report } = withReporter((r) => {
    r.onTestEnd(fakeTest("t", [{ type: "team-switch-league", description: "dynasty_main" }], "other.spec.js"), {
      status: "passed",
      duration: 1,
      errors: [],
      annotations: [],
    });
    r.onEnd({ status: "passed" });
  });
  assert.deepEqual(report.tests[0].annotations, []);
  assert.equal(report.tests[0].withheldCount, 1);
});

test("a failure keeps its status and an error CLASS, never the message", () => {
  const message =
    `Error: /api/matchup/intel?team=${OWNER_ID} (cookie ${COOKIE})\n\n` +
    "expect(received).toBe(expected)\n\nExpected: 403\nReceived: {\"untouchables\":[\"Private Player\"]}\n" +
    "Call log:\n  - Cookie: jason_session=" + COOKIE;
  const { report, stdout } = withReporter((r) => {
    r.onTestEnd(fakeTest("t1", [{ type: "session", description: `jason_session=${COOKIE}` }]), {
      status: "failed",
      duration: 12,
      errors: [{ message, stack: message, snippet: "Received: secret" }],
      annotations: [],
    });
    r.onTestEnd(fakeTest("t2"), { status: "timedOut", duration: 30000, errors: [], annotations: [] });
    r.onEnd({ status: "failed" });
  });
  const blob = JSON.stringify(report) + stdout;
  for (const leak of LEAKS) assert.ok(!blob.includes(leak), `leaked: ${leak}`);
  assert.equal(report.tests[0].status, "failed");
  assert.equal(report.tests[0].errorClass, "assertion");
  assert.equal("error" in report.tests[0], false);
  assert.equal(report.tests[0].withheldCount, 1);
  assert.equal(report.tests[1].errorClass, "timeout");
  assert.deepEqual(report.counts, { failed: 1, timedOut: 1 });
  assert.match(stdout, /FAIL \[prod-desktop\] example\.spec\.js › t1 \(12ms\) \[assertion\]/);
});

test("the report carries no attachments, stdout or raw annotations field", () => {
  const { report } = withReporter((r) => {
    r.onTestEnd(fakeTest("t3"), { status: "passed", duration: 5, errors: [], annotations: [] });
    r.onEnd({ status: "passed" });
  });
  const t = report.tests[0];
  assert.deepEqual(Object.keys(t).sort(), [
    "annotations",
    "durationMs",
    "file",
    "project",
    "status",
    "title",
    "withheldCount",
  ]);
});

test("every allowlist entry resolves to a real kind or a fixed set", () => {
  for (const [file, types] of Object.entries(ALLOWLIST)) {
    for (const [type, kind] of Object.entries(types)) {
      // A free-text probe must never pass any entry.
      assert.equal(isPublishable(file, type, "Josh Allen scored 31.4 for Team Name"), false, `${file} ${type}`);
      assert.ok(typeof kind === "function" || typeof kind === "string", `${file} ${type}`);
    }
  }
});

test("each converted spec emits only allowlisted annotation types", () => {
  // Static check over the specs the 2026-10-08 sanitization converted: every
  // annotate(testInfo, <type>, ...) type there is in the spec's allowlist, so
  // no evidence those specs mean to publish is silently withheld.
  const converted = [
    "game-day-team-switch.spec.js",
    "game-day-median-race.spec.js",
    "league-mvp-gate.spec.js",
    "awards-standings.spec.js",
    "pick-lifecycle-horizon.spec.js",
    "trade-stack-withdrawn.spec.js",
    "trade-war-room.spec.js",
    "train2-private-surfaces.spec.js",
  ];
  for (const file of converted) {
    const src = fs.readFileSync(path.join(__dirname, "specs", "prod-auth", file), "utf-8");
    const keys = Object.keys(ALLOWLIST[file] || {});
    const types = [...src.matchAll(/annotate\(\s*testInfo,\s*(["`])([^"`]+)\1/g)].map((m) => m[2]);
    assert.ok(types.length > 0, `${file}: no annotate() calls found`);
    for (const t of types) {
      const pattern = new RegExp(`^${t.replace(/[.*+?^()|[\]\\]/g, "\\$&").replace(/\$\{[^}]+\}/g, "[A-Za-z0-9_]+")}$`);
      assert.ok(keys.some((k) => pattern.test(k)), `${file}: annotation type "${t}" is not allowlisted`);
    }
  }
});
