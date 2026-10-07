/**
 * Model Lab dev/E2E bridge (AL-0b / IC-5): forwards the caller's cookie (the
 * backend decides admin access), never caches, preserves the backend status, and
 * refuses a family id that could address another backend route.
 */
import { beforeEach, describe, expect, it, vi } from "vitest";

const proxy = vi.hoisted(() => vi.fn());
vi.mock("@/lib/backend-proxy", () => ({ proxyGet: proxy }));

import { GET as getLab } from "@/app/api/model-lab/route";
import { GET as getFamily } from "@/app/api/model-lab/[family]/route";

beforeEach(() => proxy.mockReset());

describe("model-lab bridge", () => {
  it("forwards the cookie and preserves the backend refusal", async () => {
    proxy.mockResolvedValue({ data: { error: "admin_required" }, status: 403 });
    const res = await getLab({ headers: new Headers({ cookie: "jason_session=abc" }) });
    expect(proxy).toHaveBeenCalledWith("/api/model-lab", {
      cookie: "jason_session=abc",
      timeoutMs: 30000,
    });
    expect(res.status).toBe(403);
    expect(res.headers.get("cache-control")).toBe("no-store");
    expect(await res.json()).toEqual({ error: "admin_required" });
  });

  it("proxies one family by its snake_case id", async () => {
    proxy.mockResolvedValue({ data: { family: { family: "hill_scope_masters" } }, status: 200 });
    const res = await getFamily(
      { headers: new Headers({ cookie: "c=1" }) },
      { params: Promise.resolve({ family: "hill_scope_masters" }) },
    );
    expect(proxy).toHaveBeenCalledWith("/api/model-lab/hill_scope_masters", {
      cookie: "c=1",
      timeoutMs: 30000,
    });
    expect(res.status).toBe(200);
    expect(res.headers.get("cache-control")).toBe("no-store");
  });

  it.each(["..", "../data", "Hill", "a/b", ""])("refuses family id %j without calling the backend", async (family) => {
    const res = await getFamily(
      { headers: new Headers() },
      { params: Promise.resolve({ family }) },
    );
    expect(res.status).toBe(404);
    expect(proxy).not.toHaveBeenCalled();
  });

  it("reports an unreachable backend as 503, never as data", async () => {
    proxy.mockRejectedValue(new Error("ECONNREFUSED"));
    const res = await getLab({ headers: new Headers() });
    expect(res.status).toBe(503);
    expect((await res.json()).error).toBe("model_lab_unavailable");
  });
});
