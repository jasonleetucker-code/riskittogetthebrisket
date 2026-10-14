// node --test tests/e2e/prod-auth-safe-reporter.test.js
//
// The prod-auth reporter's output is PUBLISHED (public repo: Actions log +
// artifact).  These tests feed it a failure whose message carries private
// "Received" data and the session cookie, and assert neither survives.
const test = require("node:test");
const assert = require("node:assert/strict");
const fs = require("node:fs");
const os = require("node:os");
const path = require("node:path");

const COOKIE = "c0ffee0123456789abcdef0123456789";

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

function fakeTest(title, annotations = []) {
  return {
    title,
    annotations,
    location: { file: "/x/tests/e2e/specs/prod-auth/example.spec.js" },
    parent: { project: () => ({ name: "prod-desktop" }) },
  };
}

test("a failure keeps only the assertion's first line, never Received data or the cookie", () => {
  const message =
    `Error: a guest-pass PUT must be refused (cookie ${COOKIE})\n\n` +
    "expect(received).toBe(expected)\n\nExpected: 403\nReceived: {\"untouchables\":[\"Private Player\"]}\n" +
    "Call log:\n  - Cookie: jason_session=" + COOKIE;
  const { report, stdout } = withReporter((r) => {
    r.onTestEnd(fakeTest("t1", [{ type: "session", description: `jason_session=${COOKIE}` }]), {
      status: "failed",
      duration: 12,
      errors: [{ message, stack: message, snippet: "Received: secret" }],
      annotations: [],
    });
    r.onEnd({ status: "failed" });
  });
  const blob = JSON.stringify(report) + stdout;
  assert.ok(!blob.includes(COOKIE), "the cookie value leaked");
  assert.ok(!blob.includes("Private Player"), "Received data leaked");
  assert.ok(!blob.includes("Call log"), "the call log leaked");
  assert.equal(report.sanitized, true);
  assert.equal(report.tests[0].error, "Error: a guest-pass PUT must be refused (cookie [REDACTED])");
  assert.equal(report.tests[0].annotations[0].description, "jason_session=[REDACTED]");
  assert.deepEqual(report.counts, { failed: 1 });
});

test("a pass keeps the evidence annotations, deduplicated", () => {
  const ann = [{ type: "states-observed", description: "populated" }];
  const { report } = withReporter((r) => {
    r.onTestEnd(fakeTest("t2", ann), { status: "passed", duration: 5, errors: [], annotations: ann });
    r.onEnd({ status: "passed" });
  });
  assert.deepEqual(report.tests[0].annotations, ann);
  assert.equal(report.tests[0].error, undefined);
  assert.equal("attachments" in report.tests[0], false);
  assert.equal("stdout" in report.tests[0], false);
});
