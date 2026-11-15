// LI1842-DEFECT-08: the dev bridge for POST /api/rankings/overrides forwards
// the page's ``leagueKey`` (and ``view``) to the backend instead of dropping
// it, so the backend resolves the requested league rather than saved state.
import { afterEach, describe, expect, it, vi } from "vitest";
import { POST } from "@/app/api/rankings/overrides/route";

function req(url, body = { ktc: { include: false } }) {
  return new Request(url, {
    method: "POST",
    headers: { "Content-Type": "application/json", cookie: "jason_session=s" },
    body: JSON.stringify(body),
  });
}

describe("rankings overrides bridge", () => {
  afterEach(() => vi.unstubAllGlobals());

  it("forwards view and leagueKey, drops anything else", async () => {
    const fetchMock = vi.fn(async () => new Response("{}", { status: 200 }));
    vi.stubGlobal("fetch", fetchMock);
    await POST(
      req("http://localhost/api/rankings/overrides?view=delta&leagueKey=dynasty_new&x=1"),
    );
    const forwarded = new URL(fetchMock.mock.calls[0][0]);
    expect(forwarded.pathname).toBe("/api/rankings/overrides");
    expect(Object.fromEntries(forwarded.searchParams)).toEqual({
      view: "delta",
      leagueKey: "dynasty_new",
    });
    expect(fetchMock.mock.calls[0][1].headers.Cookie).toBe("jason_session=s");
  });

  it("adds no leagueKey when the page sent none", async () => {
    const fetchMock = vi.fn(async () => new Response("{}", { status: 200 }));
    vi.stubGlobal("fetch", fetchMock);
    await POST(req("http://localhost/api/rankings/overrides?view=delta"));
    const forwarded = new URL(fetchMock.mock.calls[0][0]);
    expect(forwarded.searchParams.has("leagueKey")).toBe(false);
  });
});
