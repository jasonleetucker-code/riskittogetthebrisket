import { NextResponse } from "next/server";
import fs from "node:fs";
import path from "node:path";

// Backend origin (scheme + host) resolved once at module load.  We
// build the ``/api/data`` URL per-request so the caller's view /
// leagueKey query params are forwarded to the backend.
const BACKEND_ORIGIN = (() => {
  const base = process.env.BACKEND_API_URL || "http://127.0.0.1:8000/api/data";
  try {
    const u = new URL(base);
    return `${u.protocol}//${u.host}`;
  } catch {
    return "http://127.0.0.1:8000";
  }
})();

// NOTE ON DEPLOYMENT SCOPE: in production, nginx routes every ``/api/*``
// request (including ``/api/dynasty-data``) straight to the Python
// backend — see ``deploy/nginx/chaseupside.com.conf`` — where
// ``server.py::get_dynasty_data_alias`` already honors the caller's
// ``view``/``leagueKey``.  This Next route only handles the dev flow
// (no nginx in front) and any Next-fronted deployment.  The improvements
// here (param forwarding, stream-through, idle-abort) bring that dev
// path in line with production; they are NOT a production data-path fix.

// Idle (per-chunk) timeout: abort if the backend stalls for this long
// without sending data, at header time OR mid-body.  Using an inactivity
// timeout rather than a total-duration cap means a legitimately slow but
// live transfer isn't killed, while a genuine stall still unblocks.
//
// ⚠ 4000 ms WAS TOO TIGHT.  Read this before lowering it back.
//
// The problem it caused is a CLASS of false failure, not one bug: a 4s
// idle budget reports a *busy* backend as a *dead* one.  The backend is
// single-threaded on its event loop and demonstrably stalls for longer
// than that.  MEASURED 2026-08-06 on hardware faster than a CI runner: a
// cold `POST /api/rankings/overrides` recompute takes 13.27s, and during
// it a trivial `/api/health` went from a 7 ms baseline to **10,218 ms**.
// It is CPU-bound pure Python holding the GIL, so the `run_in_threadpool`
// at server.py:4255/:4266 does not yield and cannot help.
//
// What that costs HERE, because the abort is deliberately not survivable
// downstream: it falls back to `loadFromDisk()`, the committed snapshots
// carry no rank stamps, and this route now refuses to serve those (503
// `disk_snapshot_unstamped`).  `_fetchBaseContractNetwork` throws on any
// non-2xx (lib/dynasty-data.js:1553-1557), `fetchDynastyData` lets that
// escape, and `/rankings` renders its error Banner INSTEAD OF the table
// (app/rankings/page.jsx:1642-1655) — so an E2E locator reports
// "element(s) not found" rather than an empty tbody.  One transient stall
// therefore reads as a total board failure.
//
// HOW STRONGLY THIS IS IMPLICATED, precisely.  A failing CI run logged
// `404, 404, 502, 503, 503, 404, 404` during the load.  By elimination
// this route is the only source the two 503s can have: it is the ONLY
// route on /rankings' load path that synthesizes one.  `rankings/sources`
// (3s -> 503) has no frontend caller at all; `/api/status` (3s -> 502) is
// reached only from the admin panel and /tools/source-health; the rest are
// POST engines /rankings never calls.  The 404s are `/api/health` — polled
// by StaleDataBanner on every page (AppShellWrapper.jsx:94) with no bridge
// route to answer it — plus favicon.  The 502 is `/api/auth/status`.
//
// That is elimination, not a URL.  tests/e2e/helpers/journey.js now
// records `msg.location().url`, so the next failing run states it outright
// instead of requiring this argument.
//
// ⚠ WHAT THIS IS *NOT*.  Two tempting stories about WHY the backend
// stalled are already refuted — do not re-derive them:
//   • "Playwright runs specs concurrently, so another spec's overrides
//     POST stalls the loop during this one's page load."  FALSE:
//     tests/e2e/playwright.config.js:190 sets `workers: 1` in CI and
//     :135 `fullyParallel: false`.  Specs run sequentially.
//   • "/rankings fires the overrides POST itself."  FALSE: `tepMultiplier`
//     defaults to `null`, not 1.15 (components/useSettings.js:51, changed
//     by 67caac3b), so default settings are not "customized" and no
//     overrides POST is issued on that page's load path.
// What IS established is that the backend was unresponsive for >3s during
// a failing load — `/api/auth/status`'s own 3s budget blew and emitted the
// 502 seen in the console.  WHY it stalled is still open.
//
// 30s is chosen against the measured stall (~3x), not by feel.  The cost
// is that a genuinely dead backend takes 30s to surface instead of 4s,
// which is the right trade for a multi-MB fetch that is legitimately slow.
//
// This is a floor under a symptom, NOT a fix for the stall.  Making the
// recompute not block the loop (process pool / precompute / cheaper
// pipeline) is the architectural item and is not attempted here.
//
// ⚠ AND IT COSTS AN ALARM, which is worth stating plainly rather than
// discovering later.  No E2E spec asserts on elapsed time — the journeys
// check content, and `grep` for a duration assertion across tests/e2e/specs
// finds none.  The 4s budget was therefore the only thing in CI, however
// accidentally, that failed when a page load got slow.  At 30s a backend
// stalling 25s now passes green and silently.
//
// That trade is still right: the old alarm fired on a HEALTHY backend
// (10.2s measured), so it was reporting noise, and a noisy alarm that
// blocks merges gets muted rather than heeded.  But "CI would catch it if
// the backend got slow" is no longer true, and nothing else covers it.
// A real check belongs in a perf budget that measures the backend
// directly, not in a bridge route's abort timer.
const BACKEND_IDLE_TIMEOUT_MS = 30000;

// Headers worth forwarding from the backend response.  We intentionally
// DROP ``content-encoding``: undici exposes ``res.body`` as the DECODED
// stream, so re-advertising gzip would corrupt it — Next.js re-compresses
// on the way out.
const PASS_THROUGH_HEADERS = ["content-type", "cache-control", "etag", "vary"];

function backendDataUrl(reqUrl) {
  const incoming = new URL(reqUrl);
  const target = new URL(`${BACKEND_ORIGIN}/api/data`);
  // Forward the params that actually change the payload the backend
  // serves.  ``view`` is the big one — mobile / slow-network callers
  // ask for the compact (~90% smaller) view, which the previous proxy
  // silently dropped by always requesting the default.
  for (const key of ["view", "leagueKey"]) {
    const val = incoming.searchParams.get(key);
    if (val) target.searchParams.set(key, val);
  }
  if (!target.searchParams.has("view")) target.searchParams.set("view", "app");
  return target.toString();
}

// Fetch the backend response with an idle timeout that covers ONLY the
// header phase.  A header-time stall aborts and returns null so the
// caller falls back to disk.  Once headers arrive the timer is cleared;
// the body phase gets its own per-read idle timeout (see
// ``streamWithUpstreamIdleAbort``) so header latency doesn't eat into
// the first body chunk's budget.
async function fetchFromBackendApi(request, backendUrl) {
  const ctl = new AbortController();
  const headerTimer = setTimeout(() => ctl.abort(), BACKEND_IDLE_TIMEOUT_MS);
  try {
    const headers = {};
    const cookie = request.headers.get("cookie");
    if (cookie) headers.Cookie = cookie;
    // Forward conditional-revalidation headers so an unchanged payload
    // can round-trip as a 304 instead of re-sending the full contract.
    const inm = request.headers.get("if-none-match");
    if (inm) headers["If-None-Match"] = inm;
    const res = await fetch(backendUrl, {
      cache: "no-store",
      signal: ctl.signal,
      headers,
    });
    clearTimeout(headerTimer);
    return { res, ctl };
  } catch {
    clearTimeout(headerTimer);
    return null;
  }
}

// Stream the backend body through unchanged, timing out only while an
// UPSTREAM read is actually in flight.  ``pull`` runs solely when the
// downstream (client) is ready for more, so a slow client applying
// backpressure never has a timer running against it — only a genuine
// backend stall between chunks trips the abort.  Each read gets a fresh
// full idle window, including the first body chunk after headers.
function streamWithUpstreamIdleAbort(res, ctl) {
  const reader = res.body.getReader();
  return new ReadableStream({
    async pull(controller) {
      let timer;
      try {
        const idle = new Promise((_, reject) => {
          timer = setTimeout(() => {
            ctl.abort();
            reject(new Error("backend idle timeout"));
          }, BACKEND_IDLE_TIMEOUT_MS);
        });
        const { done, value } = await Promise.race([reader.read(), idle]);
        clearTimeout(timer);
        if (done) {
          controller.close();
          return;
        }
        controller.enqueue(value);
      } catch (err) {
        clearTimeout(timer);
        try {
          ctl.abort();
        } catch {
          /* already aborted */
        }
        controller.error(err);
      }
    },
    cancel(reason) {
      try {
        ctl.abort();
      } catch {
        /* already aborted */
      }
      return reader.cancel(reason);
    },
  });
}

function parseDynastyDataJs(jsText) {
  if (!jsText) return null;
  const match = jsText.match(/window\.DYNASTY_DATA\s*=\s*(\{[\s\S]*\})\s*;?/);
  if (!match) return null;
  try {
    return JSON.parse(match[1]);
  } catch {
    return null;
  }
}

function listCandidates(baseDir) {
  const checks = [
    path.join(baseDir, "exports", "latest"),
    path.join(baseDir, "data"),
    baseDir,
  ];

  const candidates = [];
  for (const dir of checks) {
    if (!fs.existsSync(dir)) continue;
    const files = fs.readdirSync(dir)
      .filter((f) => /^dynasty_data_\d{4}-\d{2}-\d{2}\.json$/i.test(f))
      .map((f) => path.join(dir, f));
    candidates.push(...files);
  }

  return candidates;
}

function newestFile(files) {
  if (!files.length) return null;
  return files
    .map((f) => ({ f, m: fs.statSync(f).mtimeMs }))
    .sort((a, b) => b.m - a.m)[0]?.f || null;
}

// Disk fallback — used only when the backend is unreachable / errored.
// Returns the RAW contract object; the client normalizes both the raw
// contract and the legacy ``{ ok, source, data }`` wrapper.
/**
 * Does this payload carry backend rank stamps, i.e. can it function as a
 * contract at all?
 *
 * Mirrors `_hasBackendRankStamps` in lib/dynasty-data.js — "any" rather
 * than "all", because the board is capped near the tail and players past
 * the cap legitimately have a null rank.
 *
 * Checks BOTH encodings, because they use different field names and the
 * payload may carry either: `playersArray` rows use
 * `canonicalConsensusRank`, while the legacy `players` dict uses the
 * underscore-prefixed `_canonicalConsensusRank`
 * (src/api/data_contract.py:8346). Checking only the array would reject
 * every runtime-view payload, since server.py:2150 pops that array by
 * design.
 */
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

function loadFromDisk() {
  const repoRoot = path.resolve(process.cwd(), "..");

  const jsonFile = newestFile(listCandidates(repoRoot));
  if (jsonFile && fs.existsSync(jsonFile)) {
    return JSON.parse(fs.readFileSync(jsonFile, "utf8"));
  }

  const jsCandidates = [
    path.join(repoRoot, "exports", "latest", "dynasty_data.js"),
    path.join(repoRoot, "dynasty_data.js"),
    path.join(repoRoot, "data", "dynasty_data.js"),
  ];
  for (const jsFile of jsCandidates) {
    if (!fs.existsSync(jsFile)) continue;
    const parsed = parseDynastyDataJs(fs.readFileSync(jsFile, "utf8"));
    if (parsed) return parsed;
  }
  return null;
}

// Copy the response headers we forward downstream (content-type,
// cache-control, etag, vary — never content-encoding; see note above).
function passThroughHeaders(res) {
  const headers = new Headers();
  for (const h of PASS_THROUGH_HEADERS) {
    const v = res.headers.get(h);
    if (v) headers.set(h, v);
  }
  return headers;
}

export async function GET(request) {
  try {
    const backendUrl = backendDataUrl(request.url);
    const backend = await fetchFromBackendApi(request, backendUrl);

    // Happy path: stream the backend response straight through without
    // buffering / re-serializing the multi-MB contract, preserving its
    // Cache-Control + ETag so the browser can revalidate.
    if (backend) {
      const { res, ctl } = backend;

      // Conditional hit — no body to stream.
      if (res.status === 304) {
        return new NextResponse(null, { status: 304, headers: passThroughHeaders(res) });
      }

      // A 200 is only streamable if it's actually the JSON contract.  We
      // can't validate the full body without buffering (that would defeat
      // streaming), but we can reject a non-JSON 200 — an HTML gateway
      // page, an error interstitial, a scalar — up front so the client
      // gets the disk snapshot instead of a body it can't parse.
      const contentType = res.headers.get("content-type") || "";
      const isJson = /\bapplication\/json\b/i.test(contentType);
      if (res.ok && isJson) {
        if (!res.body) {
          return new NextResponse(null, { status: res.status, headers: passThroughHeaders(res) });
        }
        // Stream the body with a per-read (upstream-only) idle timeout.
        return new NextResponse(streamWithUpstreamIdleAbort(res, ctl), {
          status: res.status,
          headers: passThroughHeaders(res),
        });
      }
      // Non-2xx, or a 200 that isn't JSON — fall through to disk.
    }

    // Backend unreachable / errored / served a non-contract response —
    // fall back to a disk snapshot.  (Once streaming has started we can
    // no longer fall back; a mid-stream stall aborts and surfaces as a
    // fetch error.)  Release the unconsumed backend response, if any.
    if (backend) {
      try {
        backend.ctl.abort();
      } catch {
        /* already aborted */
      }
    }
    const parsed = loadFromDisk();
    if (parsed) {
      // A disk snapshot is only a usable CONTRACT if the pipeline has
      // stamped ranks into it.  The committed scraper seed has not:
      // `exports/latest/dynasty_data_*.json` carries ~1075 players with
      // zero `canonicalConsensusRank` and zero `_canonicalConsensusRank`.
      //
      // Serving it anyway is how a 4-second backend stall became a blank
      // board with no error. `buildRows` fail-fasts on a payload with no
      // rank stamps (lib/dynasty-data.js:1358) — deliberately, so a
      // drift-prone local blend never renders — so this fallback was
      // manufacturing precisely the input the client is built to reject,
      // and the user saw "no players" while the backend was healthy.
      //
      // Worse, it is sticky: the module-scope base-contract cache
      // (lib/dynasty-data.js) then serves that payload to every mount for
      // its TTL, and AppShell mounts useDynastyData on EVERY route — so
      // one stall degrades the whole app, not one page. That is what made
      // the E2E suite fail on a different spec each run.
      //
      // So: only serve the snapshot when it can actually function as a
      // contract. Otherwise report the upstream failure honestly and let
      // the client's error path do its job.
      if (hasRankStamps(parsed)) {
        return NextResponse.json(parsed);
      }
      return NextResponse.json(
        {
          ok: false,
          error:
            "Backend unavailable and the on-disk snapshot carries no rank stamps, " +
            "so it cannot be served as a contract. This is an upstream/backend " +
            "problem, not a rendering one.",
          diagnostic: {
            reason: "disk_snapshot_unstamped",
            players: Object.keys(parsed?.players || {}).length,
            playersArray: Array.isArray(parsed?.playersArray) ? parsed.playersArray.length : 0,
          },
        },
        { status: 503 },
      );
    }

    return NextResponse.json(
      { ok: false, error: "No dynasty_data_YYYY-MM-DD.json or dynasty_data.js found." },
      { status: 404 },
    );
  } catch (err) {
    return NextResponse.json(
      { ok: false, error: err?.message || "Unknown server error" },
      { status: 500 },
    );
  }
}
