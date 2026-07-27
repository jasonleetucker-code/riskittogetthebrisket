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
const BACKEND_IDLE_TIMEOUT_MS = 4000;

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
      return NextResponse.json(parsed);
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
