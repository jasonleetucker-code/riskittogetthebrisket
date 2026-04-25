import { NextResponse } from "next/server";
import fs from "node:fs";
import path from "node:path";

// Pre-compute backend URL once at module load.
const BACKEND_URL = (() => {
  const base = process.env.BACKEND_API_URL || "http://127.0.0.1:8000/api/data";
  try {
    const u = new URL(base);
    if (/\/api\/data$/i.test(u.pathname) && !u.searchParams.has("view")) {
      u.searchParams.set("view", "app");
    }
    return u.toString();
  } catch {
    return base;
  }
})();

async function fetchFromBackendApi(cookie) {
  const ctl = new AbortController();
  const timer = setTimeout(() => ctl.abort(), 1500);
  try {
    const headers = cookie ? { Cookie: cookie } : undefined;
    const res = await fetch(BACKEND_URL, { cache: "no-store", signal: ctl.signal, headers });
    if (!res.ok) return null;
    const data = await res.json();
    if (!data || typeof data !== "object") return null;
    return { source: `backend:${BACKEND_URL}`, data };
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

export async function GET(request) {
  try {
    const cookie = request.headers.get("cookie") || "";
    const backendPayload = await fetchFromBackendApi(cookie);
    if (backendPayload) {
      return NextResponse.json({ ok: true, source: backendPayload.source, data: backendPayload.data });
    }

    const repoRoot = path.resolve(process.cwd(), "..");

    const jsonFile = newestFile(listCandidates(repoRoot));
    if (jsonFile && fs.existsSync(jsonFile)) {
      const parsed = JSON.parse(fs.readFileSync(jsonFile, "utf8"));
      return NextResponse.json({ ok: true, source: path.basename(jsonFile), data: parsed });
    }

    const jsCandidates = [
      path.join(repoRoot, "exports", "latest", "dynasty_data.js"),
      path.join(repoRoot, "dynasty_data.js"),
      path.join(repoRoot, "data", "dynasty_data.js"),
    ];

    for (const jsFile of jsCandidates) {
      if (!fs.existsSync(jsFile)) continue;
      const parsed = parseDynastyDataJs(fs.readFileSync(jsFile, "utf8"));
      if (parsed) {
        return NextResponse.json({ ok: true, source: path.basename(jsFile), data: parsed });
      }
    }

    return NextResponse.json({ ok: false, error: "No dynasty_data_YYYY-MM-DD.json or dynasty_data.js found." }, { status: 404 });
  } catch (err) {
    return NextResponse.json({ ok: false, error: err?.message || "Unknown server error" }, { status: 500 });
  }
}
