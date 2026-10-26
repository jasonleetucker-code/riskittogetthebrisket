import { afterEach, describe, expect, it, vi } from "vitest";
import { auctionFetch, formatActiveSeconds, parseDollars, sendCommand } from "../lib/auction-client.js";
import { isPublicPath, isSelfAuthedPagePath } from "../lib/public-routes.js";

afterEach(() => {
  vi.restoreAllMocks();
  vi.unstubAllGlobals();
});

describe("parseDollars — whole dollars only, never rounded", () => {
  it.each([
    ["0", 0],
    ["$0", 0],
    ["45", 45],
    [" $12 ", 12],
  ])("%s → %s", (input, out) => expect(parseDollars(input)).toBe(out));
  it.each(["", "-1", "1.5", "1e3", "abc", "12.0", "NaN", "Infinity", "99999999"])("rejects %s", (input) =>
    expect(parseDollars(input)).toBeNull(),
  );
});

describe("formatActiveSeconds", () => {
  it("formats hours, minutes and seconds", () => {
    expect(formatActiveSeconds(65 * 3600)).toBe("65h 00m");
    expect(formatActiveSeconds(125)).toBe("2m 05s");
    expect(formatActiveSeconds(9)).toBe("9s");
    expect(formatActiveSeconds(null)).toBe("—");
  });
});

function jsonResponse(status, body) {
  return { status, ok: status >= 200 && status < 300, json: async () => body };
}

describe("sendCommand — unknown outcomes are reconciled by receipt, never blindly re-sent", () => {
  it("returns the committed receipt when the POST connection drops after commit", async () => {
    const calls = [];
    vi.stubGlobal(
      "fetch",
      vi.fn(async (url, init) => {
        calls.push([url, init?.method || "GET", init?.headers?.["Idempotency-Key"]]);
        if (init?.method === "POST") throw new TypeError("network down");
        return jsonResponse(200, { status: 200, result: { ok: true, leading: true }, revision: 9 });
      }),
    );
    const out = await sendCommand("r_1", { kind: "bid", auction: "A1", max: 5 });
    expect(out.leading).toBe(true);
    expect(calls.filter((c) => c[1] === "POST")).toHaveLength(1); // no second POST
    expect(calls[1][0]).toContain(`/receipts/${encodeURIComponent(calls[0][2])}`);
  });

  it("re-sends with the SAME key only when no receipt exists", async () => {
    const keys = [];
    let posts = 0;
    vi.stubGlobal(
      "fetch",
      vi.fn(async (url, init) => {
        if (init?.method === "POST") {
          posts += 1;
          keys.push(init.headers["Idempotency-Key"]);
          if (posts === 1) throw new TypeError("network down");
          return jsonResponse(200, { ok: true, revision: 3 });
        }
        return jsonResponse(404, { error: "no_receipt" });
      }),
    );
    const out = await sendCommand("r_1", { kind: "nominate", player: "p" });
    expect(out.ok).toBe(true);
    expect(keys).toHaveLength(2);
    expect(keys[0]).toBe(keys[1]);
  });

  it("a definitive rejection is not retried", async () => {
    const f = vi.fn(async () => jsonResponse(409, { error: "quiet_hours", message: "closed" }));
    vi.stubGlobal("fetch", f);
    await expect(sendCommand("r_1", { kind: "bid", auction: "A1", max: 5 })).rejects.toMatchObject({ code: "quiet_hours" });
    expect(f).toHaveBeenCalledTimes(1);
  });

  it("reports UNKNOWN (not failure) when the outcome cannot be established", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn(async () => {
        throw new TypeError("offline");
      }),
    );
    await expect(sendCommand("r_1", { kind: "bid", auction: "A1", max: 5 }, { attempts: 1 })).rejects.toMatchObject({ unknown: true });
  });
});

describe("auction pages are self-authenticated, not public", () => {
  it("bypasses the site-cookie gate without becoming public/indexable", () => {
    expect(isSelfAuthedPagePath("/auction")).toBe(true);
    expect(isSelfAuthedPagePath("/auction/r_abc")).toBe(true);
    expect(isSelfAuthedPagePath("/auctions")).toBe(false);
    expect(isPublicPath("/auction")).toBe(false);
    expect(isPublicPath("/auction/r_abc")).toBe(false);
  });
});

describe("auctionFetch — room-changing POSTs always carry an Idempotency-Key", () => {
  afterEach(() => vi.unstubAllGlobals());
  it("adds a key to a POST that has none, keeps a caller's key, and adds none to GET", async () => {
    const seen = [];
    vi.stubGlobal("fetch", async (_url, init) => {
      seen.push(init.headers || {});
      return new Response("{}", { status: 200, headers: { "Content-Type": "application/json" } });
    });
    await auctionFetch("/rooms/r1/clock", { method: "POST", body: { advanceSeconds: 60 } });
    await auctionFetch("/rooms/r1/clock", { method: "POST", body: {}, headers: { "Idempotency-Key": "mine-12345" } });
    await auctionFetch("/rooms/r1/view");
    expect(seen[0]["Idempotency-Key"]).toMatch(/^[A-Za-z0-9_-]{8,100}$/);
    expect(seen[1]["Idempotency-Key"]).toBe("mine-12345");
    expect(seen[2]["Idempotency-Key"]).toBeUndefined();
  });
});
