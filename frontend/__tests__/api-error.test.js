import { describe, expect, it } from "vitest";
import { apiErrorMessage } from "@/lib/api-error";

describe("apiErrorMessage", () => {
  it("extracts normal API messages", () => {
    expect(apiErrorMessage({ error: "auth_required", message: "Sign-in required." }, 401)).toBe(
      "Sign-in required.",
    );
  });

  it("extracts nested object details instead of rendering object Object", () => {
    expect(apiErrorMessage({ detail: { message: "Sharp market unavailable" } }, 503)).toBe(
      "Sharp market unavailable",
    );
  });

  it("reads Error instances and falls back to HTTP status", () => {
    expect(apiErrorMessage(new Error("Network failed"))).toBe("Network failed");
    expect(apiErrorMessage({}, 502)).toBe("HTTP 502");
  });
});
