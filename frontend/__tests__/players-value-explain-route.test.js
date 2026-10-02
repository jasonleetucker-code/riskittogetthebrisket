import { beforeEach, expect, it, vi } from "vitest";

const proxy = vi.hoisted(() => vi.fn());
vi.mock("@/lib/backend-proxy", () => ({ proxyGet: proxy }));

import { GET } from "@/app/api/players/[player]/value-explain/route";

// Block body on purpose: a function RETURNED from beforeEach runs as the
// test's teardown, and mockReset() returns the mock itself.
beforeEach(() => {
  proxy.mockReset();
});

const req = (cookie) => ({ headers: new Headers(cookie ? { cookie } : {}) });

it("forwards the encoded player and the session cookie; private, never cached", async () => {
  proxy.mockResolvedValue({ data: { explainVersion: "value-explain/v2" }, status: 200 });
  const res = await GET(req("session=abc"), { params: Promise.resolve({ player: "2027 Early 1st" }) });
  expect(proxy).toHaveBeenCalledWith("/api/players/2027%20Early%201st/value-explain", {
    cookie: "session=abc",
    timeoutMs: 15000,
  });
  expect(res.status).toBe(200);
  expect(res.headers.get("Cache-Control")).toBe("no-store, private");
  expect(await res.json()).toEqual({ explainVersion: "value-explain/v2" });
});

it("preserves backend status (401 stays 401) and refuses dot segments", async () => {
  proxy.mockResolvedValue({ data: { error: "unauthorized" }, status: 401 });
  const res = await GET(req(), { params: Promise.resolve({ player: "1234" }) });
  expect(res.status).toBe(401);
  const dot = await GET(req(), { params: Promise.resolve({ player: ".." }) });
  expect(dot.status).toBe(404);
  expect(proxy).toHaveBeenCalledTimes(1);
});

it("answers 503 with a readable body when the backend is unreachable", async () => {
  proxy.mockRejectedValue(new Error("ECONNREFUSED"));
  const res = await GET(req(), { params: Promise.resolve({ player: "1234" }) });
  expect(res.status).toBe(503);
  expect((await res.json()).error).toBe("value_explain_unavailable");
});
