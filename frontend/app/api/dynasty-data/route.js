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

// The backend's per-request Sleeper overlay can occasionally take a
// beat on a cold 15-min window; keep a generous-but-bounded budget so
// we prefer fresh data and only fall back to a disk snapshot when the
// backend is genuinely unresponsive.
const BACKEND_TIMEOUT_MS = 4000;

// Headers worth forwarding from the backend response.  We intentionally
// DROP ``content-encoding``: Node's fetch has already decompressed the
// body we read, so re-advertising gzip would corrupt it — Next.js
// re-compresses on the way out.
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

async function fetchFromBackendApi(request, backendUrl) {
  const ctl = new AbortController();
  const timer = setTimeout(() => ctl.abort(), BACKEND_TIMEOUT_MS);
  try {
    const headers = {};
    const cookie = request.headers.get("cookie");
    if (cookie) headers.Cookie = cookie;
    // Forward conditional-revalidation headers so an unchanged payload
    // can round-trip as a 304 instead of re-sending the full contract.
    const inm = request.headers.get("if-none-match");
    if (inm) headers["If-None-Match"] = inm;
    return await fetch(backendUrl, {
      cache: "no-store",
      signal: ctl.signal,
      headers,
    });
  } catch {
    return null;
  } finally {
    clearTimeout(timer);
  }
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
    const res = await fetchFromBackendApi(request, backendUrl);

    // Happy path: stream the backend response straight through without
    // re-parsing / re-serializing the multi-MB contract, preserving its
    // Cache-Control + ETag so the browser can revalidate.  A 304 carries
    // no body.
    if (res && (res.ok || res.status === 304)) {
      const headers = new Headers();
      for (const h of PASS_THROUGH_HEADERS) {
        const v = res.headers.get(h);
        if (v) headers.set(h, v);
      }
      const body = res.status === 304 ? null : await res.arrayBuffer();
      return new NextResponse(body, { status: res.status, headers });
    }

    // Backend unreachable or errored — fall back to a disk snapshot.
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
