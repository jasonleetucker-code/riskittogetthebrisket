import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { GET, POST } from "@/app/api/dfs/[...path]/route.js";

const params = (path) => ({ params: Promise.resolve({ path }) });

beforeEach(() => {
  vi.stubGlobal(
    "fetch",
    vi.fn(async () => new Response('{"ok":true}', { status: 201, headers: { "content-type": "application/json" } })),
  );
});
afterEach(() => vi.unstubAllGlobals());

describe("/api/dfs bridge", () => {
  it("accepts a same-origin POST even when Next's request.url names a different bind host", async () => {
    // Measured under `next start`: request.url said localhost while the
    // browser (and its Origin/Host) said 127.0.0.1 — the old check 403'd.
    const req = new Request("http://localhost:3765/api/dfs/slates", {
      method: "POST",
      headers: { origin: "http://127.0.0.1:3765", host: "127.0.0.1:3765", cookie: "jason_session=x" },
      body: "{}",
    });
    const res = await POST(req, params(["slates"]));
    expect(res.status).toBe(201);
    const [url, init] = fetch.mock.calls[0];
    expect(String(url)).toMatch(/\/api\/dfs\/slates$/);
    expect(init.headers.Cookie).toBe("jason_session=x");
  });

  it("refuses a cross-origin POST before it reaches the backend", async () => {
    const req = new Request("http://127.0.0.1:3765/api/dfs/builds", {
      method: "POST",
      headers: { origin: "https://evil.example", host: "127.0.0.1:3765" },
      body: "{}",
    });
    const res = await POST(req, params(["builds"]));
    expect(res.status).toBe(403);
    expect(fetch).not.toHaveBeenCalled();
  });

  it("passes CSV exports through as text with their download headers", async () => {
    fetch.mockResolvedValueOnce(
      new Response("QB,RB\r\n1,2\r\n", {
        status: 200,
        headers: {
          "content-type": "text/csv; charset=utf-8",
          "content-disposition": 'attachment; filename="x.csv"',
          "x-dfs-export-verified": "false",
        },
      }),
    );
    const req = new Request("http://127.0.0.1:3765/api/dfs/builds/b1/export", { headers: { cookie: "c=1" } });
    const res = await GET(req, params(["builds", "b1", "export"]));
    expect(await res.text()).toBe("QB,RB\r\n1,2\r\n");
    expect(res.headers.get("content-disposition")).toContain("x.csv");
    expect(res.headers.get("x-dfs-export-verified")).toBe("false");
  });
});
