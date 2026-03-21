const assert = require("node:assert/strict");
const fs = require("node:fs");
const os = require("node:os");
const path = require("node:path");
const { pathToFileURL } = require("node:url");

const sourceFile = path.resolve(__dirname, "..", "lib", "dynasty-source.js");
const cases = [];

function test(name, run) {
  cases.push({ name, run });
}

function makeTempDir(prefix) {
  return fs.mkdtempSync(path.join(os.tmpdir(), prefix));
}

function writeFile(filePath, content) {
  fs.mkdirSync(path.dirname(filePath), { recursive: true });
  fs.writeFileSync(filePath, content, "utf8");
  return filePath;
}

function writeJson(filePath, value) {
  return writeFile(filePath, JSON.stringify(value));
}

function setMtime(filePath, timestampMs) {
  const date = new Date(timestampMs);
  fs.utimesSync(filePath, date, date);
}

async function importFreshDynastySource() {
  const moduleDir = makeTempDir("dynasty-source-module-");
  const modulePath = path.join(moduleDir, "dynasty-source.mjs");
  fs.copyFileSync(sourceFile, modulePath);
  const moduleUrl = `${pathToFileURL(modulePath).href}?t=${Date.now()}-${Math.random()}`;
  const mod = await import(moduleUrl);
  return {
    mod,
    cleanup() {
      fs.rmSync(moduleDir, { recursive: true, force: true });
    },
  };
}

function createLogger() {
  const warnings = [];
  return {
    warnings,
    logger: {
      warn(message) {
        warnings.push(String(message));
      },
    },
  };
}

async function runCase({ name, run }) {
  const afterFns = [];
  const context = {
    after(fn) {
      afterFns.push(fn);
    },
  };

  let failure = null;
  try {
    await run(context);
  } catch (error) {
    failure = error;
  }

  while (afterFns.length) {
    const cleanup = afterFns.pop();
    try {
      await cleanup();
    } catch (cleanupError) {
      if (!failure) {
        failure = cleanupError;
      }
    }
  }

  if (failure) {
    throw Object.assign(failure, { testName: name });
  }
}

test("falls back to the next valid JSON snapshot when the newest snapshot is corrupt", async (t) => {
  const repoRoot = makeTempDir("dynasty-source-repo-");
  const { mod, cleanup } = await importFreshDynastySource();
  const { logger, warnings } = createLogger();
  const originalFetch = global.fetch;
  const validPayload = { players: [{ id: "older-valid" }], generatedAt: "2026-03-19T12:00:00Z" };

  t.after(() => {
    global.fetch = originalFetch;
    cleanup();
    fs.rmSync(repoRoot, { recursive: true, force: true });
  });

  const newestBroken = writeFile(
    path.join(repoRoot, "data", "dynasty_data_2026-03-20.json"),
    '{"players": [',
  );
  const olderValid = writeJson(path.join(repoRoot, "dynasty_data_2026-03-19.json"), validPayload);
  setMtime(olderValid, Date.UTC(2026, 2, 19, 12, 0, 0));
  setMtime(newestBroken, Date.UTC(2026, 2, 20, 12, 0, 0));

  global.fetch = async () => {
    throw new Error("backend offline");
  };

  const result = await mod.loadDynastySource({
    allowRawFallback: true,
    backendUrl: "http://127.0.0.1:9001/api/data",
    force: true,
    logger,
    repoRoot,
  });

  assert.equal(result.ok, true);
  assert.equal(result.source, "dynasty_data_2026-03-19.json");
  assert.deepEqual(result.data, validPayload);
  assert.equal(warnings.length, 1);
  assert.match(warnings[0], /Skipped invalid raw dynasty data file data\/dynasty_data_2026-03-20\.json/i);
  assert.deepEqual(result.diagnostics, {
    skippedRawFiles: [
      {
        file: "data/dynasty_data_2026-03-20.json",
        reason: "Unexpected end of JSON input",
      },
    ],
  });
});

test("falls back to dynasty_data.js when every JSON snapshot is invalid", async (t) => {
  const repoRoot = makeTempDir("dynasty-source-repo-");
  const { mod, cleanup } = await importFreshDynastySource();
  const { logger, warnings } = createLogger();
  const originalFetch = global.fetch;
  const jsPayload = { players: [{ id: "from-js-fallback" }], generatedAt: "2026-03-18T08:30:00Z" };

  t.after(() => {
    global.fetch = originalFetch;
    cleanup();
    fs.rmSync(repoRoot, { recursive: true, force: true });
  });

  writeFile(path.join(repoRoot, "data", "dynasty_data_2026-03-20.json"), '{"players": ');
  writeFile(path.join(repoRoot, "dynasty_data.js"), `window.DYNASTY_DATA = ${JSON.stringify(jsPayload)};`);

  global.fetch = async () => {
    throw new Error("backend offline");
  };

  const result = await mod.loadDynastySource({
    allowRawFallback: true,
    backendUrl: "http://127.0.0.1:9001/api/data",
    force: true,
    logger,
    repoRoot,
  });

  assert.equal(result.ok, true);
  assert.equal(result.source, "dynasty_data.js");
  assert.deepEqual(result.data, jsPayload);
  assert.equal(warnings.length, 1);
  assert.match(warnings[0], /data\/dynasty_data_2026-03-20\.json/i);
  assert.deepEqual(result.diagnostics, {
    skippedRawFiles: [
      {
        file: "data/dynasty_data_2026-03-20.json",
        reason: "Unexpected end of JSON input",
      },
    ],
  });
});

test("isolates cache entries across raw-fallback policy and backend URL changes", async (t) => {
  const repoRoot = makeTempDir("dynasty-source-repo-");
  const { mod, cleanup } = await importFreshDynastySource();
  const { logger } = createLogger();
  const originalFetch = global.fetch;
  const rawPayload = { players: [{ id: "raw-fallback" }], generatedAt: "2026-03-19T12:00:00Z" };
  const calls = [];

  t.after(() => {
    global.fetch = originalFetch;
    cleanup();
    fs.rmSync(repoRoot, { recursive: true, force: true });
  });

  writeJson(path.join(repoRoot, "dynasty_data_2026-03-19.json"), rawPayload);

  global.fetch = async (url) => {
    const href = String(url);
    calls.push(href);
    if (href.includes("9001")) {
      throw new Error("primary backend offline");
    }
    return {
      ok: true,
      async json() {
        return { players: [{ id: "backend-beta" }], generatedAt: "2026-03-20T09:00:00Z" };
      },
    };
  };

  const first = await mod.loadDynastySource({
    allowRawFallback: false,
    backendUrl: "http://127.0.0.1:9001/api/data",
    logger,
    repoRoot,
  });
  const second = await mod.loadDynastySource({
    allowRawFallback: true,
    backendUrl: "http://127.0.0.1:9001/api/data",
    logger,
    repoRoot,
  });
  const third = await mod.loadDynastySource({
    allowRawFallback: true,
    backendUrl: "http://127.0.0.1:9002/api/data",
    logger,
    repoRoot,
  });

  assert.equal(first.ok, false);
  assert.equal(first.policy, "backend_contract_only");

  assert.equal(second.ok, true);
  assert.equal(second.source, "dynasty_data_2026-03-19.json");
  assert.deepEqual(second.data, rawPayload);

  assert.equal(third.ok, true);
  assert.equal(third.source, "backend:http://127.0.0.1:9002/api/data?view=app");
  assert.deepEqual(third.data, {
    players: [{ id: "backend-beta" }],
    generatedAt: "2026-03-20T09:00:00Z",
  });
  assert.deepEqual(calls, [
    "http://127.0.0.1:9001/api/data?view=app",
    "http://127.0.0.1:9001/api/data?view=app",
    "http://127.0.0.1:9002/api/data?view=app",
  ]);
  assert.equal(first.diagnostics, undefined);
  assert.equal(second.diagnostics, undefined);
  assert.equal(third.diagnostics, undefined);
});

async function main() {
  let failures = 0;

  for (const entry of cases) {
    try {
      await runCase(entry);
      console.log(`ok - ${entry.name}`);
    } catch (error) {
      failures += 1;
      console.error(`not ok - ${entry.name}`);
      console.error(error?.stack || error?.message || String(error));
    }
  }

  if (failures) {
    console.error(`${failures} loader test(s) failed.`);
    process.exitCode = 1;
    return;
  }

  console.log(`${cases.length} loader test(s) passed.`);
}

if (require.main === module) {
  main().catch((error) => {
    console.error(error?.stack || error?.message || String(error));
    process.exitCode = 1;
  });
}
