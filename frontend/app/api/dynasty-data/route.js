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
// backend — see ``deploy/nginx/riskittogetthebrisket.org.conf`` — where
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

// Fetch the backend response.  The AbortController's idle timer stays
// ARMED after this resolves — the caller is responsible for keeping it
// alive across the body stream (or clearing it) so a mid-body stall
// still aborts instead of hanging.  On a header-time failure we clear
// the timer and return null so the caller can fall back to disk.
async function fetchFromBackendApi(request, backendUrl) {
  const ctl = new AbortController();
  const state = { timer: setTimeout(() => ctl.abort(), BACKEND_IDLE_TIMEOUT_MS) };
  const resetIdle = () => {
    clearTimeout(state.timer);
    state.timer = setTimeout(() => ctl.abort(), BACKEND_IDLE_TIMEOUT_MS);
  };
  const clear = () => clearTimeout(state.timer);
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
    return { res, ctl, resetIdle, clear };
  } catch {
    clear();
    return null;
  }
}

// Pipe the backend body through unchanged while keeping the idle-abort
// timer armed: each chunk rearms the timeout, and a stall of
// BACKEND_IDLE_TIMEOUT_MS aborts the upstream fetch so the stream errors
// out instead of hanging forever.  Streaming (vs. buffering the whole
// multi-MB payload) sends the first byte as soon as it arrives.
function streamWithIdleAbort({ res, resetIdle, clear }) {
  const ts = new TransformStream({
    transform(chunk, controller) {
      resetIdle();
      controller.enqueue(chunk);
    },
    flush() {
      clear();
    },
    cancel() {
      clear();
    },
  });
  return res.body.pipeThrough(ts);
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

export async function GET(request) {
  try {
    const backendUrl = backendDataUrl(request.url);
    const backend = await fetchFromBackendApi(request, backendUrl);

    // Happy path: stream the backend response straight through without
    // buffering / re-serializing the multi-MB contract, preserving its
    // Cache-Control + ETag so the browser can revalidate.
    if (backend && (backend.res.ok || backend.res.status === 304)) {
      const { res, clear } = backend;
      const headers = new Headers();
      for (const h of PASS_THROUGH_HEADERS) {
        const v = res.headers.get(h);
        if (v) headers.set(h, v);
      }
      // 304 carries no body — release the idle timer and return.
      if (res.status === 304 || !res.body) {
        clear();
        return new NextResponse(null, { status: res.status, headers });
      }
      // Stream the body; the idle-abort timer stays armed for the
      // stream's lifetime (each chunk rearms it, flush clears it).
      return new NextResponse(streamWithIdleAbort(backend), {
        status: res.status,
        headers,
      });
    }

    // Backend unreachable or errored at header time — fall back to a
    // disk snapshot.  (Once streaming has started we can no longer fall
    // back; a mid-stream stall aborts and surfaces as a fetch error.)
    if (backend) backend.clear();
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
