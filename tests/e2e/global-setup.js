/**
 * Global setup — proves the stack can actually serve the suite before
 * a single spec runs, and fails with an actionable message when it
 * can't.
 *
 * Why this exists: two agents in a row could not get a real E2E run,
 * and both misread the symptoms, because the signals you naturally
 * reach for are misleading here:
 *
 *   - ``GET /api/health`` returns **503** whenever the backend is
 *     "degraded", which is the *steady state* offline: the startup
 *     scrape can't reach ranking sites, so ``last_error`` is set
 *     forever.  503 here does NOT mean "no data".
 *   - ``GET /api/data`` returns **401** without a session cookie.
 *     That is correct behaviour, not a broken backend.
 *   - A failed scrape leaves ``last_success_at: null`` permanently.
 *     Also expected — the suite runs on the committed snapshot, not
 *     on a live scrape.
 *
 * The signals that actually matter, checked here in order:
 *   1. ``/api/status`` answers and reports ``has_data: true``
 *      (the seeded snapshot was loaded by ``load_from_disk``).
 *   2. ``/api/test/create-session`` issues a session — i.e. the
 *      backend really has E2E_TEST_MODE + a matching secret, so the
 *      signed-in specs will run instead of silently skipping.
 *   3. An **authenticated** ``/api/data`` returns a populated player
 *      pool.
 *
 * Skipped when E2E_BASE_URL points at an external stack (prod smoke):
 * that target is not ours to provision.
 */
const REQUIRED_PLAYERS = 50;

function fail(lines) {
  const banner = "─".repeat(68);
  throw new Error(
    `\n${banner}\nE2E PREFLIGHT FAILED — the stack cannot serve this suite\n${banner}\n` +
      lines.join("\n") +
      `\n${banner}\n`,
  );
}

async function getJson(url, init) {
  const res = await fetch(url, init);
  let body = null;
  try {
    body = await res.json();
  } catch {
    /* non-JSON body — leave null, callers report the status */
  }
  return { status: res.status, body, headers: res.headers };
}

/**
 * Block until the Next.js frontend actually serves.
 *
 * Playwright's ``webServer`` array does not reliably gate the run on
 * the SECOND entry: observed cold, tests started (and failed with
 * ERR_CONNECTION_REFUSED on :3000) while `next build` was still
 * running.  Page specs navigate to the Next origin directly — see
 * pageUrl() in helpers/journey.js — so a half-up stack produces a
 * screenful of connection-refused noise that looks like a product
 * regression.  Waiting here makes readiness explicit and the failure
 * message honest.
 *
 * Budget is generous because a cold production build of this app is
 * minutes, not seconds.
 */
async function waitForFrontend(origin, budgetMs = 900_000) {
  const started = Date.now();
  let announced = false;
  for (;;) {
    try {
      const res = await fetch(`${origin}/login`, { redirect: "manual" });
      if (res.status > 0 && res.status < 500) return Date.now() - started;
    } catch {
      /* not listening yet */
    }
    if (Date.now() - started > budgetMs) {
      fail([
        `The Next.js frontend never came up at ${origin} ` +
          `(waited ${Math.round(budgetMs / 1000)}s).`,
        "",
        "`npm run e2e` builds and starts it automatically.  A cold",
        "production build takes minutes; if it is failing outright,",
        "reproduce it directly:",
        "",
        "  npm --prefix frontend ci   # lockfile-exact, safe",
        "  npm --prefix frontend run build:nocheck && npm --prefix frontend run start",
      ]);
    }
    if (!announced && Date.now() - started > 20_000) {
      console.log(
        "[e2e] waiting for the Next.js frontend to finish building " +
          "(cold production build — this takes a few minutes)…",
      );
      announced = true;
    }
    await new Promise((r) => setTimeout(r, 2_000));
  }
}

module.exports = async function globalSetup() {
  if (process.env.E2E_BASE_URL) {
    // External target (e.g. the prod smoke run through nginx, or a
    // stack you booted yourself).  We must not try to provision it —
    // but we DO check it answers, because the alternative is every
    // spec failing with ECONNREFUSED and burning the full suite
    // runtime to tell you nothing was listening.  (Setting
    // E2E_BASE_URL also disables the config's own webServer boot,
    // which is exactly how you end up pointed at a dead port.)
    const target = process.env.E2E_BASE_URL.replace(/\/+$/, "");
    let reachable = false;
    try {
      const res = await fetch(`${target}/api/status`);
      reachable = res.status > 0;
    } catch {
      reachable = false;
    }
    if (!reachable) {
      fail([
        `E2E_BASE_URL is set to ${target} but nothing is answering there.`,
        "",
        "Setting E2E_BASE_URL tells this config NOT to boot the stack,",
        "so you are responsible for it.  Either start it yourself, or",
        "unset the variable and let the suite provision everything:",
        "",
        "  unset E2E_BASE_URL E2E_PAGE_ORIGIN && npm run e2e",
      ]);
    }
    return;
  }
  const base = "http://127.0.0.1:8000";

  // 1. Snapshot loaded?  webServer already waited for /api/status to
  // answer, so a failure here is about data, not liveness.
  const status = await getJson(`${base}/api/status`).catch((err) => ({
    status: 0,
    body: { error: String(err) },
  }));
  if (status.status !== 200) {
    fail([
      `GET /api/status returned ${status.status}.`,
      "",
      "The backend did not start.  The usual cause is a hard boot",
      "failure, not a data problem — run it in the foreground to see:",
      "",
      "  ALLOW_DEFAULT_LOGIN_DEV=1 python server.py",
    ]);
  }
  if (!status.body || status.body.has_data !== true) {
    fail([
      "The backend is up but has no player data loaded",
      `(/api/status has_data=${status.body && status.body.has_data}).`,
      "",
      "The suite runs on the COMMITTED snapshot, never a live scrape.",
      "`npm run regression:preflight` seeds data/ from exports/latest/",
      "and is what `npm run e2e` runs first — run the full command:",
      "",
      "  npm run e2e",
      "",
      "If that still fails, the committed snapshot may be missing:",
      "  ls exports/latest/dynasty_data_*.json",
    ]);
  }

  // 2. Test-session endpoint really unlocked?  A 404 here means the
  // server lacks E2E_TEST_MODE / the matching secret, which would make
  // every signed-in spec skip — a green run that tested nothing.
  const secret = process.env.E2E_TEST_SECRET;
  if (!secret) {
    fail([
      "E2E_TEST_SECRET is not set on the runner.",
      "",
      "playwright.config.js normally defaults this when it boots the",
      "stack itself.  Set it explicitly if you are driving your own:",
      "",
      "  export E2E_TEST_SECRET=e2e-local-insecure-secret",
    ]);
  }
  const session = await getJson(`${base}/api/test/create-session`, {
    method: "POST",
    headers: { Authorization: `Bearer ${secret}` },
  });
  if (session.status !== 200) {
    fail([
      `POST /api/test/create-session returned ${session.status} (expected 200).`,
      "",
      "The endpoint 404s unless the SERVER process has both:",
      "  E2E_TEST_MODE=1",
      `  E2E_TEST_SECRET=${secret}`,
      "",
      "A 500 means the gate passed but E2E_TEST_USERNAME is unset —",
      "the endpoint fails closed rather than defaulting to a real",
      "account.  Set it to a throwaway name:",
      "  E2E_TEST_USERNAME=e2e-test-user",
      "",
      "Without it every signed-in spec skips and the run is green",
      "while covering nothing.  If you booted the backend yourself,",
      "restart it with those vars — or let `npm run e2e` boot it.",
    ]);
  }

  // 3. Authenticated data actually populated?  This is the check that
  // /api/data's bare 401 hides.
  const cookie = (session.headers.get("set-cookie") || "").split(";")[0];
  const data = await getJson(`${base}/api/data?view=app`, {
    headers: { cookie },
  });
  if (data.status !== 200) {
    fail([
      `Authenticated GET /api/data returned ${data.status} (expected 200).`,
      "",
      "A session cookie was issued, so this is not the auth gate —",
      "check the backend log for a contract-build error.",
    ]);
  }
  const players = Object.keys((data.body && data.body.players) || {}).length;
  if (players < REQUIRED_PLAYERS) {
    fail([
      `/api/data served only ${players} players (need >= ${REQUIRED_PLAYERS}).`,
      "",
      "The snapshot loaded but is empty or truncated.  Check that",
      "exports/latest/dynasty_data_*.json is a full export, then",
      "re-seed:  rm -f data/dynasty_data_*.json && npm run e2e",
    ]);
  }

  // 4. Frontend serving?  Page specs navigate to the Next origin
  // directly, so this must be up before any of them run.
  const pageOrigin = (
    process.env.E2E_PAGE_ORIGIN || "http://127.0.0.1:3000"
  ).replace(/\/+$/, "");
  const waited = await waitForFrontend(pageOrigin);

  console.log(
    `[e2e] stack verified — ${players} players served, ` +
      "test sessions enabled, snapshot loaded, " +
      `frontend ready at ${pageOrigin} (${Math.round(waited / 1000)}s)`,
  );
};
