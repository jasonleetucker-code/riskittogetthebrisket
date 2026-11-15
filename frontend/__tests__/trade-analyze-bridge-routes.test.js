/**
 * The two War Room bridges — POST /api/trade/analyze (2 teams) and
 * POST /api/trade/analyze-multi (3+ teams).  Production never reaches them
 * (nginx sends /api/* to FastAPI); `next start` without a proxy — the E2E
 * stack — reaches ONLY them.  The 2-team bridge was missing, so every real,
 * unmocked 2-team War Room in the E2E stack rendered "the server refused the
 * request" (CI run on #1883, trade-multi-team-e2e-keyboard-a11y.spec.js).
 * Pinned here: each exists, forwards the session cookie to its own backend
 * path, passes status + body through verbatim, never caches, and answers an
 * explicit 502 — never a fabricated analysis — when the backend is down.
 */
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { POST as analyzePost } from "@/app/api/trade/analyze/route.js";
import { POST as analyzeMultiPost } from "@/app/api/trade/analyze-multi/route.js";

beforeEach(() => {
  vi.stubGlobal(
    "fetch",
    vi.fn(
      async () =>
        new Response('{"error":"multi_team_analysis_disabled"}', {
          status: 503,
          headers: { "content-type": "application/json" },
        }),
    ),
  );
});
afterEach(() => vi.unstubAllGlobals());

const req = (path, body) =>
  new Request(`http://127.0.0.1:3000${path}`, {
    method: "POST",
    headers: { "content-type": "application/json", cookie: "jason_session=abc" },
    body: JSON.stringify(body),
  });

describe.each([
  ["/api/trade/analyze", analyzePost],
  ["/api/trade/analyze-multi", analyzeMultiPost],
])("%s bridge", (path, POST) => {
  it("forwards the body and the session cookie to the same backend path", async () => {
    const body = { teamName: "Jason", playersOut: ["A"], playersIn: ["B"] };
    await POST(req(path, body));
    expect(fetch).toHaveBeenCalledTimes(1);
    const [url, init] = fetch.mock.calls[0];
    expect(new URL(String(url)).pathname).toBe(path);
    expect(init.method).toBe("POST");
    expect(init.headers.Cookie).toBe("jason_session=abc");
    expect(JSON.parse(init.body)).toEqual(body);
  });

  it("passes the backend's status and body through verbatim, uncached", async () => {
    const res = await POST(req(path, {}));
    expect(res.status).toBe(503);
    expect(await res.json()).toEqual({ error: "multi_team_analysis_disabled" });
    expect(res.headers.get("cache-control")).toBe("no-store");
  });

  it("answers an explicit 502 when the backend is unreachable", async () => {
    fetch.mockRejectedValueOnce(new Error("ECONNREFUSED"));
    const res = await POST(req(path, {}));
    expect(res.status).toBe(502);
    expect((await res.json()).error).toBe("upstream_unavailable");
  });
});
