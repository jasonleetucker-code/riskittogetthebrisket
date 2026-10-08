/**
 * The 2026-10-05 Rankings banner: "Serving degraded — rankings … declining
 * this request for the reason above" with NO reason above it.  The backend
 * had put a sentence in `error`; the classifier kept it as a code, left
 * `message` empty, and the renderer never shows a code.  These pin that a
 * refusal always reaches the reader as a sentence, and never as a pointer to
 * an absent one.
 */
import { describe, it, expect } from "vitest";
import {
  classifyContractFailure,
  normalizeFailureBody,
  NO_REASON_GIVEN,
} from "@/lib/contract-failure";


describe("a 503 always carries a reason", () => {
  it("the incident body: a sentence in `error` is the message, not a code", () => {
    const f = classifyContractFailure(503, {
      error: "No data available yet. First scrape may still be running.",
    });
    expect(f.kind).toBe("degraded");
    expect(f.code).toBe("");
    expect(f.message).toMatch(/No data available yet/);
  });

  it("an error code alone maps to a known explanation and keeps the code", () => {
    const f = classifyContractFailure(503, { error: "contract_build_failed" });
    expect(f).toMatchObject({ kind: "degraded", code: "contract_build_failed" });
    expect(f.message).toMatch(/latest rankings build failed/);
    const g = classifyContractFailure(503, { error: "data_not_ready" });
    expect(g.message).toMatch(/not loaded/);
  });

  it("the server's own message/detail/reason win over the code table", () => {
    expect(
      classifyContractFailure(503, { error: "data_not_ready", message: "Scoring not proven." }).message,
    ).toBe("Scoring not proven.");
    expect(classifyContractFailure(503, { error: "x_y", detail: "From detail." }).message).toBe(
      "From detail.",
    );
    expect(classifyContractFailure(503, { error: "x_y", reason: "From reason." }).message).toBe(
      "From reason.",
    );
  });

  it("an unfamiliar code says the cause is not available — it invents none", () => {
    const f = classifyContractFailure(503, { error: "brand_new_refusal" });
    expect(f.kind).toBe("degraded");
    expect(f.code).toBe("brand_new_refusal");
    expect(f.message).toBe(NO_REASON_GIVEN);
  });

  it("a proxy's HTML page or an empty 503 is 'unavailable', not a refusal", () => {
    const html = classifyContractFailure(503, "<html><head><title>503</title></head></html>");
    expect(html.kind).toBe("unavailable");
    expect(html.message).not.toMatch(/</);
    expect(classifyContractFailure(503, null).kind).toBe("unavailable");
    expect(classifyContractFailure(502, "<html>Bad Gateway</html>").kind).toBe("unavailable");
    expect(classifyContractFailure(504, "").kind).toBe("unavailable");
  });

  it("never surfaces a traceback or a path", () => {
    const f = classifyContractFailure(500, {
      detail: 'Traceback (most recent call last):\n  File "/home/x/server.py", line 1',
    });
    expect(f.message).toBe("Server error (500).");
  });

  it("keeps 401 / 403 / 429 distinct and explained", () => {
    expect(classifyContractFailure(401, { error: "auth_required", message: "Sign-in required." }))
      .toMatchObject({ kind: "auth", code: "auth_required", message: "Sign-in required." });
    expect(classifyContractFailure(403, { error: "forbidden" })).toMatchObject({
      kind: "forbidden",
      retryable: false,
    });
    expect(classifyContractFailure(429, {}).kind).toBe("rate_limited");
  });

  it("normalizeFailureBody separates code from sentence", () => {
    expect(normalizeFailureBody({ error: "data_not_ready", message: "M" })).toEqual({
      code: "data_not_ready",
      message: "M",
    });
    expect(normalizeFailureBody({ error: "A sentence." })).toEqual({ code: "", message: "A sentence." });
  });
});
