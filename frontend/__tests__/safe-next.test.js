import { describe, it, expect } from "vitest";
import { sanitizeNextPath } from "@/lib/safe-next";

describe("sanitizeNextPath", () => {
  it.each([
    "//evil.example",
    "/\\evil.example",
    "/\tevil.example",
    "/\nevil.example",
    "/a\u0000b",
    "https://evil.example",
    "javascript:alert(1)",
    "evil.example",
    // dot segments normalize to a protocol-relative "//host" (review finding)
    "/..//evil.example",
    "/.//evil.example",
    "/a/../..//evil.example",
    "/%2e%2e//evil.example",
  ])("rejects %j", (v) => {
    expect(sanitizeNextPath(v)).toBe("/");
  });
  it("preserves normal paths", () => {
    expect(sanitizeNextPath("/trade?x=1#y")).toBe("/trade?x=1#y");
    expect(sanitizeNextPath("/rankings")).toBe("/rankings");
  });
  it("empty / nullish -> fallback", () => {
    expect(sanitizeNextPath("")).toBe("/");
    expect(sanitizeNextPath(null)).toBe("/");
    expect(sanitizeNextPath(undefined, "/home")).toBe("/home");
  });
  it("never emits a value that resolves to another origin", () => {
    const base = "https://app.example";
    for (const v of ["/..//evil.example", "/.//evil.example", "/x/..//evil.example", "/ok?n=//evil.example"]) {
      const out = sanitizeNextPath(v);
      expect(new URL(out, base).origin).toBe(base);
    }
  });
});
