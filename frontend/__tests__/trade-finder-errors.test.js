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
    expect(f).toEqual({ message: "Player data or Sleeper rosters not available.", code: "" });
  });

  it("an unrecognised code never becomes the message", () => {
    const f = tradeToolFailure(400, { error: "invalid_something" }, { tool: "Best Offers" });
    expect(f.message).toBe("Best Offers could not run (HTTP 400). Try again.");
    expect(f.code).toBe("invalid_something");
  });

  it("an empty 401 still explains itself", () => {
    expect(tradeToolFailure(401, {}).message).toBe("Sign in to continue.");
  });

  it("a 503 with no JSON body is a restart, not a data problem", () => {
    expect(tradeToolFailure(503, null).message).toMatch(/restarting or briefly unavailable/);
  });

  it("a success status carrying an unknown error code is still a sentence", () => {
    const f = tradeToolFailure(200, { error: "weird_code" }, { tool: "Package Builder" });
    expect(f).toEqual({ message: "Package Builder could not run. Try again.", code: "weird_code" });
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

  it("any other error keeps its message with no code", () => {
    expect(failureFromError(new Error("Failed to fetch"))).toEqual({ message: "Failed to fetch", code: "" });
    expect(failureFromError(null)).toEqual({ message: "Request failed", code: "" });
  });
});
