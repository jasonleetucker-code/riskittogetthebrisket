import fs from "node:fs";
import path from "node:path";

const DEFAULT_BACKEND_API_URL = "http://127.0.0.1:8000/api/data";
const warnedRawFallbackIssues = new Set();

function envBool(name, fallback = false) {
  const raw = String(process.env?.[name] ?? "").trim().toLowerCase();
  if (!raw) return Boolean(fallback);
  return ["1", "true", "yes", "on"].includes(raw);
}

function parseJsonObject(text) {
  if (!text) {
    return { value: null, reason: "File was empty." };
  }
  try {
    const parsed = JSON.parse(text);
    if (!parsed || typeof parsed !== "object" || Array.isArray(parsed)) {
      return { value: null, reason: "Parsed value was not an object." };
    }
    return { value: parsed, reason: null };
  } catch (error) {
    return { value: null, reason: error?.message || "Invalid JSON." };
  }
}

function parseDynastyDataJs(jsText) {
  if (!jsText) {
    return { value: null, reason: "File was empty." };
  }
  const match = jsText.match(/window\.DYNASTY_DATA\s*=\s*(\{[\s\S]*\})\s*;?/);
  if (!match) {
    return { value: null, reason: "window.DYNASTY_DATA assignment was not found." };
  }
  return parseJsonObject(match[1]);
}

function normalizeDiagnosticFilePath(filePath, repoRoot) {
  if (!filePath) return null;
  if (!repoRoot) return path.basename(filePath);
  const relative = path.relative(repoRoot, filePath);
  if (!relative || relative.startsWith("..") || path.isAbsolute(relative)) {
    return path.basename(filePath);
  }
  return relative.split(path.sep).join("/");
}

function recordRawFallbackIssue({ logger, diagnostics, filePath, reason, repoRoot }) {
  if (!filePath || !reason) return;
  const diagnosticFile = normalizeDiagnosticFilePath(filePath, repoRoot);
  if (diagnostics && Array.isArray(diagnostics.skippedRawFiles)) {
    diagnostics.skippedRawFiles.push({
      file: diagnosticFile,
      reason,
    });
  }
  warnRawFallbackIssue(logger, diagnosticFile, reason);
}

function warnRawFallbackIssue(logger, filePath, reason) {
  if (!logger || typeof logger.warn !== "function" || !filePath || !reason) return;
  const key = `${filePath}:${reason}`;
  if (warnedRawFallbackIssues.has(key)) return;
  warnedRawFallbackIssues.add(key);
  logger.warn(`[dynasty-source] Skipped invalid raw dynasty data file ${filePath}: ${reason}`);
}

function buildDiagnosticsPayload(diagnostics) {
  if (!diagnostics || !Array.isArray(diagnostics.skippedRawFiles) || !diagnostics.skippedRawFiles.length) {
    return null;
  }
  return {
    skippedRawFiles: diagnostics.skippedRawFiles,
  };
}

function withDiagnostics(payload, diagnostics) {
  const diagnosticsPayload = buildDiagnosticsPayload(diagnostics);
  if (!diagnosticsPayload) return payload;
  return {
    ...payload,
    diagnostics: diagnosticsPayload,
  };
}

function listCandidates(baseDir) {
  const checks = [path.join(baseDir, "data"), baseDir];
  const candidates = [];

  for (const dir of checks) {
    if (!fs.existsSync(dir)) continue;
    const files = fs
      .readdirSync(dir)
      .filter((f) => /^dynasty_data_\d{4}-\d{2}-\d{2}\.json$/i.test(f))
      .map((f) => path.join(dir, f));
    candidates.push(...files);
  }

  return candidates;
}

function newestFiles(files) {
  if (!files.length) return [];
  return files
    .map((f) => ({ f, m: fs.statSync(f).mtimeMs }))
    .sort((a, b) => b.m - a.m)
    .map(({ f }) => f);
}

function readJsonCandidate(filePath, { logger = console, diagnostics = null, repoRoot = null } = {}) {
  if (!fs.existsSync(filePath)) return null;
  try {
    const parsed = parseJsonObject(fs.readFileSync(filePath, "utf8"));
    if (parsed.value) return parsed.value;
    recordRawFallbackIssue({ logger, diagnostics, filePath, reason: parsed.reason, repoRoot });
    return null;
  } catch (error) {
    recordRawFallbackIssue({
      logger,
      diagnostics,
      filePath,
      reason: error?.message || "Unable to read file.",
      repoRoot,
    });
    return null;
  }
}

function maybeRuntimeViewUrl(input) {
  try {
    const u = new URL(input);
    if (/\/api\/data$/i.test(u.pathname) && !u.searchParams.has("view")) {
      u.searchParams.set("view", "app");
    }
    return u.toString();
  } catch {
    return input;
  }
}

async function fetchFromBackendApi({ timeoutMs = 1500, backendUrl = DEFAULT_BACKEND_API_URL } = {}) {
  const runtimeBackendUrl = maybeRuntimeViewUrl(backendUrl || DEFAULT_BACKEND_API_URL);
  const ctl = new AbortController();
  const timer = setTimeout(() => ctl.abort(), timeoutMs);

  try {
    const res = await fetch(runtimeBackendUrl, { cache: "no-store", signal: ctl.signal });
    if (!res.ok) return null;
    const data = await res.json();
    if (!data || typeof data !== "object") return null;
    return { source: `backend:${runtimeBackendUrl}`, data };
  } catch {
    return null;
  } finally {
    clearTimeout(timer);
  }
}

function defaultRepoRoot() {
  return path.resolve(process.cwd(), "..");
}

function loadFromRawRepoFiles({ repoRoot = defaultRepoRoot(), logger = console, diagnostics = null } = {}) {
  for (const jsonFile of newestFiles(listCandidates(repoRoot))) {
    const parsed = readJsonCandidate(jsonFile, { logger, diagnostics, repoRoot });
    if (parsed) {
      return { source: path.basename(jsonFile), data: parsed };
    }
  }

  const jsCandidates = [
    path.join(repoRoot, "dynasty_data.js"),
    path.join(repoRoot, "data", "dynasty_data.js"),
  ];
  for (const jsFile of jsCandidates) {
    if (!fs.existsSync(jsFile)) continue;
    try {
      const parsed = parseDynastyDataJs(fs.readFileSync(jsFile, "utf8"));
      if (parsed.value) {
        return { source: path.basename(jsFile), data: parsed.value };
      }
      recordRawFallbackIssue({ logger, diagnostics, filePath: jsFile, reason: parsed.reason, repoRoot });
    } catch (error) {
      recordRawFallbackIssue({
        logger,
        diagnostics,
        filePath: jsFile,
        reason: error?.message || "Unable to read file.",
        repoRoot,
      });
    }
  }
  return null;
}

let cachedPayload = null;
let cachedAtMs = 0;
let cachedKey = "";
const CACHE_TTL_MS = 15_000;

export async function loadDynastySource({
  timeoutMs = 1500,
  force = false,
  backendUrl = process.env.BACKEND_API_URL || DEFAULT_BACKEND_API_URL,
  allowRawFallback = envBool("NEXT_ALLOW_RAW_DYNASTY_FALLBACK", false),
  logger = console,
  repoRoot = defaultRepoRoot(),
} = {}) {
  const now = Date.now();
  const diagnostics = { skippedRawFiles: [] };
  const cacheKey = JSON.stringify({ backendUrl, repoRoot, allowRawFallback });
  if (!force && cachedPayload && cachedKey === cacheKey && now - cachedAtMs < CACHE_TTL_MS) {
    return cachedPayload;
  }

  try {
    const backendPayload = await fetchFromBackendApi({ timeoutMs, backendUrl });
    if (backendPayload) {
      cachedPayload = withDiagnostics(
        { ok: true, source: backendPayload.source, data: backendPayload.data },
        diagnostics,
      );
      cachedAtMs = now;
      cachedKey = cacheKey;
      return cachedPayload;
    }

    if (allowRawFallback) {
      const rawFallback = loadFromRawRepoFiles({ repoRoot, logger, diagnostics });
      if (rawFallback) {
        cachedPayload = withDiagnostics(
          { ok: true, source: rawFallback.source, data: rawFallback.data },
          diagnostics,
        );
        cachedAtMs = now;
        cachedKey = cacheKey;
        return cachedPayload;
      }
    }

    cachedPayload = withDiagnostics(
      {
        ok: false,
        errorCode: "backend_unavailable",
        policy: allowRawFallback ? "backend_then_raw_fallback" : "backend_contract_only",
        error: allowRawFallback
          ? "Backend unavailable and no local dynasty_data raw fallback found."
          : "Backend /api/data unavailable. Next runtime is configured for backend contract only.",
      },
      diagnostics,
    );
    cachedAtMs = now;
    cachedKey = cacheKey;
    return cachedPayload;
  } catch (err) {
    cachedPayload = withDiagnostics({ ok: false, error: err?.message || "Unknown server error" }, diagnostics);
    cachedAtMs = now;
    cachedKey = cacheKey;
    return cachedPayload;
  }
}
