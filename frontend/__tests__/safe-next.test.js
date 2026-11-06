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
});
