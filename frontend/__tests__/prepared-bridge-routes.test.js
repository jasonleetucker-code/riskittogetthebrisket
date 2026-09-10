import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { GET } from "@/app/api/read-models/[...path]/route";
import { POST as overrides } from "@/app/api/rankings/overrides/route";
import { POST as telemetry } from "@/app/api/telemetry/web-vitals/route";

const request = (path, init) => new Request(`http://localhost:3000${path}`, init);
const context = (path) => ({ params: Promise.resolve({ path: path.split("/") }) });
const response = (status = 200, headers = {}) => new Response(status === 304 ? null : '{"ok":true}', { status, headers: { "content-type": "application/json", ...headers } });
beforeEach(() => vi.stubGlobal("fetch", vi.fn(async () => response())));
afterEach(() => { vi.useRealTimers(); vi.unstubAllGlobals(); vi.restoreAllMocks(); });

describe("prepared private GET bridge", () => {
  it.each(["rankings", "trade/context", "players/catalog", "players/opaque-key", "players/1234"])("forwards allowed %s with cookie, scope, generation and revalidation", async (path) => {
    const result = await GET(request(`/api/read-models/${path}?leagueKey=lab&generation=gen-a&ignored=secret`, { headers: { cookie: "jason_session=lab", "if-none-match": '"gen-a"', "x-request-id": "lab-id", traceparent: "00-abc-def-01", referer: "https://private.invalid/?owner=secret" } }), context(path));
    expect(result.status).toBe(200); expect(await result.json()).toEqual({ ok: true });
    const [target, options] = fetch.mock.calls[0];
    expect(target.pathname).toBe(`/api/read-models/${path}`);
    expect(target.search).toBe("?leagueKey=lab&generation=gen-a");
    expect(options.headers.get("cookie")).toBe("jason_session=lab");
    expect(options.headers.get("if-none-match")).toBe('"gen-a"');
    expect(options.headers.get("x-request-id")).toBe("lab-id");
    expect(options.headers.get("traceparent")).toBe("00-abc-def-01");
    expect(options.headers.get("referer")).toBeNull();
    expect(options.cache).toBe("no-store"); expect(options.redirect).toBe("error");
  });

  it.each(["players/../rankings", "admin", "players/key/extra", "players/%2fadmin"])("refuses unrecognized path %s without contacting upstream", async (path) => {
    expect((await GET(request("/api/read-models/invalid"), context(path))).status).toBe(404);
    expect(fetch).not.toHaveBeenCalled();
  });

  it("keeps a conditional 304 bodyless and drops decoded-body encoding/length", async () => {
    fetch.mockResolvedValue(response(304, { etag: '"gen-a"', "cache-control": "private, max-age=30", "content-encoding": "gzip", "content-length": "100", "server-timing": "read_model;dur=2" }));
    const result = await GET(request("/api/read-models/rankings"), context("rankings"));
    expect(result.status).toBe(304); expect(await result.text()).toBe("");
    expect(result.headers.get("etag")).toBe('"gen-a"');
    expect(result.headers.get("server-timing")).toBe("read_model;dur=2");
    expect(result.headers.get("content-encoding")).toBeNull(); expect(result.headers.get("content-length")).toBeNull();
  });

  it.each([401, 403, 409, 503])("preserves upstream %s without cacheable private error data", async (status) => {
    fetch.mockResolvedValue(response(status, { "cache-control": "public, max-age=300", "www-authenticate": "Cookie" }));
    const result = await GET(request("/api/read-models/rankings"), context("rankings"));
    expect(result.status).toBe(status); expect(result.headers.get("cache-control")).toBe("no-store");
    expect(result.headers.get("www-authenticate")).toBe("Cookie"); expect(await result.json()).toEqual({ ok: true });
  });

  it("rejects successful HTML and reports unavailable transport without exposing details", async () => {
    fetch.mockResolvedValueOnce(new Response("private proxy details", { headers: { "content-type": "text/html" } })).mockRejectedValueOnce(new Error("private origin"));
    expect((await GET(request("/api/read-models/rankings"), context("rankings"))).status).toBe(502);
    const result = await GET(request("/api/read-models/rankings"), context("rankings"));
    expect(result.status).toBe(503); expect(await result.text()).not.toContain("private origin");
  });
});

it("override bridge preserves pinned generation, league and trace headers", async () => {
  const result = await overrides(request("/api/rankings/overrides?view=board&generation=gen-a&leagueKey=lab&ignored=x", { method: "POST", headers: { cookie: "jason_session=lab", traceparent: "trace", "x-request-id": "request" }, body: "{}" }));
  expect(result.status).toBe(200);
  const [target, options] = fetch.mock.calls[0];
  expect(new URL(target).search).toBe("?view=board&generation=gen-a&leagueKey=lab");
  expect(options.headers).toMatchObject({ Cookie: "jason_session=lab", traceparent: "trace", "x-request-id": "request" });
});

describe("tiny public telemetry bridge", () => {
  it("forwards the metric body without cookie, referrer or arbitrary headers", async () => {
    const body = JSON.stringify({ name: "CLS", value: 0, id: "random", route: "/rankings", device: "desktop", navigationType: "navigate" });
    const result = await telemetry(request("/api/telemetry/web-vitals", { method: "POST", body, headers: { cookie: "private", referer: "https://private.invalid", "x-private-id": "secret" } }));
    expect(result.status).toBe(200);
    const [target, options] = fetch.mock.calls[0];
    expect(target.pathname).toBe("/api/telemetry/web-vitals"); expect(options.body).toBe(body);
    expect(options.headers).toEqual({ "Content-Type": "application/json" });
    expect(options.referrerPolicy).toBe("no-referrer"); expect(result.headers.get("cache-control")).toBe("no-store");
  });

  it("enforces the body cap even without Content-Length and rejects malformed JSON", async () => {
    const large = await telemetry(request("/api/telemetry/web-vitals", { method: "POST", body: "x".repeat(8193) }));
    expect(large.status).toBe(413); expect(fetch).not.toHaveBeenCalled();
    expect((await telemetry(request("/api/telemetry/web-vitals", { method: "POST", body: "not-json" }))).status).toBe(400);
    expect(fetch).not.toHaveBeenCalled();
  });
});
