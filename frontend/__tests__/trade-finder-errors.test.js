// Trade-tool request failures read as sentences; the backend's machine code is
// kept only as a detail.  The defect: Package Scan, Golden Upgrades, Best
// Offers and /angle put `data.error` straight into the banner, so a code-only
// body ("auth_required", "data_not_ready", "unknown_team") showed the code.
import { describe, expect, it } from "vitest";
import {
  TradeToolRequestError,
  failureFromError,
  tradeToolCodeText,
  tradeToolFailure,
} from "@/lib/trade-finder-errors";

describe("tradeToolFailure", () => {
  it.each([
    [401, "auth_required", "Sign in to use the trade tools."],
    [503, "data_not_ready", "This league's rosters and values are not loaded on the server yet — try again in a moment."],
    [400, "unknown_team", "That team is not in this league's rosters — choose your team again."],
  ])("a bare %s %s code becomes a sentence and keeps the code as detail", (status, code, text) => {
    const f = tradeToolFailure(status, { error: code });
    expect(f.message).toBe(text);
    expect(f.message).not.toContain(code);
    expect(f.code).toBe(code);
  });

  it("the server's own words win over the stock sentence", () => {
    const f = tradeToolFailure(503, {
      error: "data_not_ready",
      message: "Rankings are not compatible: league scores players differently.",
    });
    expect(f.message).toBe("Rankings are not compatible: league scores players differently.");
    expect(f.code).toBe("data_not_ready");
  });

  it("a sentence in `error` is the message, not a code", () => {
    const f = tradeToolFailure(503, { error: "Player data or Sleeper rosters not available." });
    expect(f).toEqual({
      message: "Player data or Sleeper rosters not available.",
      code: "",
      detail: "",
    });
  });

  it("an unrecognised code never becomes the message", () => {
    const f = tradeToolFailure(400, { error: "invalid_something" }, { tool: "Best Offers" });
    expect(f.message).toBe("Best Offers did not accept this request (HTTP 400).");
    expect(f.code).toBe("invalid_something");
  });

  // A deterministic 4xx refusal fails the same way on a retry, so it never
  // says "Try again" (this test previously pinned "Try again" — the defect).
  it.each([
    [400, "invalid_refinement"],
    [400, "invalid_numbers"],
    [422, "invalid_return_positions"],
    [404, "not_found_here"],
  ])("an unrecognised %s %s says the request was not accepted, not 'Try again'", (status, code) => {
    const f = tradeToolFailure(status, { error: code }, { tool: "Package Builder" });
    expect(f.message).toBe(`Package Builder did not accept this request (HTTP ${status}).`);
    expect(f.message).not.toMatch(/try again/i);
    expect(f.message).not.toContain(code);
    expect(f.code).toBe(code);
  });

  it("a backend sentence on a 4xx still wins (invalid_refinement carries one)", () => {
    const f = tradeToolFailure(400, {
      error: "invalid_refinement",
      message: "'refinementByOpponent' keys must be other teams in this league.",
    });
    expect(f.message).toBe("'refinementByOpponent' keys must be other teams in this league.");
    expect(f.code).toBe("invalid_refinement");
  });

  it("an empty 401 still explains itself", () => {
    expect(tradeToolFailure(401, {}).message).toBe("Sign in to continue.");
  });

  it("a 503 with no JSON body is a restart, not a data problem", () => {
    expect(tradeToolFailure(503, null).message).toMatch(/restarting or briefly unavailable/);
  });

  it("a success status carrying an unknown error code is still a sentence", () => {
    const f = tradeToolFailure(200, { error: "weird_code" }, { tool: "Package Builder" });
    expect(f).toEqual({
      message: "Package Builder could not run. Try again.",
      code: "weird_code",
      detail: "",
    });
  });

  // The Next bridge answers 503 {error: "<Tool> service unavailable",
  // detail: err.message} when the backend restarts or times out.  That
  // transport text is a detail; the banner says "temporarily unavailable".
  it.each([
    ["Trade finder service unavailable", "fetch failed", "Package Scan"],
    ["Angle packages service unavailable", "This operation was aborted", "Package Builder"],
    ["Best-offers service unavailable", "connect ECONNREFUSED 127.0.0.1:8000", "Best Offers"],
    ["Golden-upgrades service unavailable", undefined, "Golden Upgrades"],
  ])("a bridge 503 (%s / %s) reads temporarily unavailable", (error, detail, tool) => {
    const f = tradeToolFailure(503, { error, detail }, { tool });
    expect(f.message).toBe(
      `${tool} is temporarily unavailable — the server is restarting or did not answer in time. Try again shortly.`,
    );
    if (detail) expect(f.message).not.toContain(detail);
    expect(f.detail).toBe(detail ? `${error}: ${detail}` : error);
    expect(f.code).toBe("");
  });

  it("a backend 503 with its own code or message is not mistaken for the bridge", () => {
    // FastAPI's own HTTPException shape: a reason in `detail`, no bridge text.
    const fastapi = tradeToolFailure(503, { detail: "Scoring identity is unprovable for this league." });
    expect(fastapi.message).toBe("Scoring identity is unprovable for this league.");
    expect(fastapi.detail).toBe("");
    const said = tradeToolFailure(503, {
      error: "Angle packages service unavailable",
      message: "Scoring is not proven identical.",
    });
    expect(said.message).toBe("Scoring is not proven identical.");
    expect(said.detail).toBe("");
  });

  it("knows only the codes it has copy for", () => {
    expect(tradeToolCodeText("auth_required")).toBeTruthy();
    expect(tradeToolCodeText("nope")).toBeNull();
    expect(tradeToolCodeText("")).toBeNull();
  });
});

describe("failureFromError", () => {
  it("carries a classified failure through a throw", () => {
    const failure = tradeToolFailure(400, { error: "unknown_team" });
    expect(failureFromError(new TradeToolRequestError(failure))).toBe(failure);
  });

  // "Failed to fetch" is the browser's transport text; it was previously
  // pinned as the message (the defect) and is now a detail.
  it("a fetch the browser could not complete reads unreachable, text as detail", () => {
    for (const text of ["Failed to fetch", "NetworkError when attempting to fetch resource.", "Load failed"]) {
      const f = failureFromError(new TypeError(text), { tool: "Best Offers" });
      expect(f.message).toBe(
        "Best Offers could not reach the server. Check your connection and try again shortly.",
      );
      expect(f.detail).toBe(text);
      expect(f.code).toBe("");
    }
  });

  it("any other error keeps its message with no code", () => {
    expect(failureFromError(new Error("Something specific"))).toEqual({
      message: "Something specific",
      code: "",
      detail: "",
    });
    expect(failureFromError(null)).toEqual({ message: "Request failed", code: "", detail: "" });
  });
});
