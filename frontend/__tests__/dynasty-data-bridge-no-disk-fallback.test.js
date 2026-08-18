/**
 * The data bridge must never answer a refusal with a board.
 *
 * AUDIT FINDING F-14 (2026-08-18)
 * ───────────────────────────────
 * `frontend/app/api/dynasty-data/route.js` is THE base-contract fetch for the
 * whole app — `frontend/lib/dynasty-data.js` sets
 * `DEFAULT_DATA_URL = "/api/dynasty-data"`. It used to fall back to a disk
 * snapshot on ANY non-2xx, on a non-JSON 200, or on a 4-second header stall,
 * and return it as an unconditional **HTTP 200**.
 *
 * TWO DEFECTS, AND THE FIRST IS THE SERIOUS ONE
 *
 * (a) A REFUSAL WAS CONVERTED INTO A GRANT. `401` is non-2xx, so an
 *     unauthenticated caller received the board off disk under 200.
 *     `frontend/middleware.js`'s matcher is
 *     `"/((?!_next/static|_next/image|api/|.*\\.[\\w]+$).*)"` — it EXCLUDES
 *     `api/` by design, because the backend's own `/api/*` gate is meant to be
 *     the authority. The fallback overrode the only gate there was.
 *     Measured against a live stack: unauthenticated request → 200 with
 *     635,170 bytes while the backend answered 401, byte-identical to the disk
 *     file. The CI artifact for run 32120428479 shows ten
 *     `GET /api/data?view=array HTTP/1.1 401 Unauthorized`.
 *
 * (b) IT COULD NOT SERVE A BOARD ANYWAY. Every candidate the loader reached —
 *     `exports/latest/dynasty_data_*.json`, `data/dynasty_data_*.json`, and
 *     `dynasty_data.js` — is the RAW SCRAPER EXPORT. Measured 2026-08-18: all
 *     three carry no `contractVersion`, no `playersArray` and ZERO rank
 *     stamps, which is exactly what `buildRows`' fail-fast rejects. So the
 *     "resilience" path turned a diagnosable backend status into an
 *     undiagnosable empty board under a status code that said all was well.
 *
 * SCOPE, STATED HONESTLY
 * Production is not affected: `deploy/nginx/chaseupside-proxy.conf` and
 * `deploy/nginx/riskittogetthebrisket.org.conf` both route `location /api/`
 * to the backend, so this file is never reached there. Dev, the E2E stack and
 * any Next-fronted deployment are — the same asymmetry
 * `bridge-routes-forward-cookies.test.js` was written for, and for the same
 * reason: production being fine is what lets a defect here stay invisible.
 * The protection is a deployment convention, not a property of the code, and
 * nothing tested it. That is what this file is.
 */

import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import fs from "node:fs";
import path from "node:path";

import { GET } from "../app/api/dynasty-data/route.js";

const ROUTE_PATH = path.join(process.cwd(), "app", "api", "dynasty-data", "route.js");

function request(url = "http://localhost:3000/api/dynasty-data", headers = {}) {
  return new Request(url, { headers });
}

function backendResponse(status, body, headers = {}) {
  return new Response(body, {
    status,
    headers: { "content-type": "application/json", ...headers },
  });
}

describe("dynasty-data bridge", () => {
  beforeEach(() => {
    vi.restoreAllMocks();
  });
  afterEach(() => {
    vi.restoreAllMocks();
  });

  // ── (a) the refusal half ────────────────────────────────────────────

  it.each([401, 403])("propagates a %s instead of answering with a board", async (status) => {
    vi.stubGlobal(
      "fetch",
      vi.fn(async () => backendResponse(status, JSON.stringify({ detail: "nope" }))),
    );
    const res = await GET(request());
    expect(res.status).toBe(status);
    const text = await res.text();
    // Whatever it returns, it must not be a board.
    expect(text).not.toMatch(/"players"/);
    expect(text.length).toBeLessThan(10_000);
  });

  it("does not launder a 401 into a 200 for an anonymous caller", async () => {
    vi.stubGlobal("fetch", vi.fn(async () => backendResponse(401, '{"detail":"unauthenticated"}')));
    const res = await GET(request());
    expect(res.status).not.toBe(200);
  });

  it("forwards the challenge header on a 401 so the caller can act on it", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn(async () =>
        backendResponse(401, "{}", { "www-authenticate": 'Cookie realm="dynasty"' }),
      ),
    );
    const res = await GET(request());
    expect(res.headers.get("www-authenticate")).toBe('Cookie realm="dynasty"');
  });

  it("propagates a 5xx rather than substituting a payload", async () => {
    vi.stubGlobal("fetch", vi.fn(async () => backendResponse(503, '{"detail":"not ready"}')));
    const res = await GET(request());
    expect(res.status).toBe(503);
  });

  // ── (b) the "not the contract" half ─────────────────────────────────

  it("reports a transport failure as a failure, never a 200", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn(async () => {
        throw new Error("ECONNREFUSED");
      }),
    );
    const res = await GET(request());
    expect(res.status).toBe(503);
    const body = await res.json();
    expect(body.ok).toBe(false);
    expect(body.reason).toBe("backend_unreachable");
  });

  it("reports a header-time abort as a failure, never a 200", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn(async () => {
        const err = new Error("aborted");
        err.name = "AbortError";
        throw err;
      }),
    );
    const res = await GET(request());
    expect(res.status).toBe(503);
    expect((await res.json()).reason).toBe("backend_idle_timeout");
  });

  it("treats a non-JSON 200 as a bad gateway, not as a cue to invent one", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn(async () => new Response("<html>gateway</html>", {
        status: 200,
        headers: { "content-type": "text/html" },
      })),
    );
    const res = await GET(request());
    expect(res.status).toBe(502);
    expect((await res.json()).reason).toBe("backend_non_json");
  });

  // ── the happy paths must still work ─────────────────────────────────

  it("streams a healthy contract through unchanged", async () => {
    const payload = JSON.stringify({ contractVersion: "2026-03-10.v2", playersArray: [] });
    vi.stubGlobal(
      "fetch",
      vi.fn(async () => backendResponse(200, payload, { etag: 'W/"abc"' })),
    );
    const res = await GET(request());
    expect(res.status).toBe(200);
    expect(res.headers.get("etag")).toBe('W/"abc"');
    expect(JSON.parse(await res.text()).contractVersion).toBe("2026-03-10.v2");
  });

  it("round-trips a 304 with no body", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn(async () => new Response(null, { status: 304, headers: { etag: 'W/"abc"' } })),
    );
    const res = await GET(request("http://localhost:3000/api/dynasty-data", {
      "if-none-match": 'W/"abc"',
    }));
    expect(res.status).toBe(304);
  });

  it("still forwards the session cookie and view/leagueKey params", async () => {
    const spy = vi.fn(async () => backendResponse(200, "{}"));
    vi.stubGlobal("fetch", spy);
    await GET(
      request("http://localhost:3000/api/dynasty-data?view=array&leagueKey=dynasty_new", {
        cookie: "jason_session=abc",
      }),
    );
    const [url, init] = spy.mock.calls[0];
    expect(url).toContain("view=array");
    expect(url).toContain("leagueKey=dynasty_new");
    expect(init.headers.Cookie).toBe("jason_session=abc");
  });

  // ── structural: the seam must be GONE, not merely unused ────────────
  //
  // Read the file, because a dormant loader is a seam somebody re-threads.
  // These assertions are what stop the fallback coming back as "resilience".

  it("has no disk-snapshot loader left in the file", async () => {
    const src = fs.readFileSync(ROUTE_PATH, "utf8");
    const code = src
      .split("\n")
      .filter((l) => !l.trim().startsWith("//") && !l.trim().startsWith("*"))
      .join("\n");
    for (const seam of ["loadFromDisk", "listCandidates", "newestFile", "parseDynastyDataJs"]) {
      expect(code, `${seam} must not survive as a dormant seam`).not.toContain(seam);
    }
    expect(code, "the route must not read the filesystem at all").not.toMatch(
      /require\(["']node:fs["']\)|from ["']node:fs["']/,
    );
  });
});
