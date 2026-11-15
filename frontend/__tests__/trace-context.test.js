import { afterEach, describe, expect, it, vi } from "vitest";

import { proxyGet } from "@/lib/backend-proxy";
import { newTraceparent } from "@/lib/trace-context";

afterEach(() => vi.unstubAllGlobals());

describe("browser to backend trace propagation", () => {
  it("mints a valid W3C traceparent from crypto", () => {
    vi.stubGlobal("crypto", {
      getRandomValues(bytes) {
        bytes.forEach((_, index) => { bytes[index] = index + 1; });
        return bytes;
      },
    });
    expect(newTraceparent()).toMatch(/^00-[0-9a-f]{32}-[0-9a-f]{16}-01$/);
  });

  it("stays uninstrumented when secure randomness is unavailable", () => {
    vi.stubGlobal("crypto", undefined);
    expect(newTraceparent()).toBeNull();
  });

  it("forwards only a valid traceparent and returns backend correlation IDs", async () => {
    const traceparent = "00-" + "a".repeat(32) + "-" + "b".repeat(16) + "-01";
    const fetchStub = vi.fn(async () => new Response(JSON.stringify({ leagues: [] }), {
      status: 200,
      headers: { "X-Request-Id": "request-1", "X-Trace-Id": "a".repeat(32) },
    }));
    vi.stubGlobal("fetch", fetchStub);
    const result = await proxyGet("/api/leagues", { cookie: "session=private", traceparent });
    expect(fetchStub.mock.calls[0][1].headers).toEqual({ Cookie: "session=private", traceparent });
    expect(result.traceId).toBe("a".repeat(32));
    expect(result.requestId).toBe("request-1");

    await proxyGet("/api/leagues", { traceparent: "bad\nprivate" });
    expect(fetchStub.mock.calls[1][1].headers).toEqual({});
  });
});
