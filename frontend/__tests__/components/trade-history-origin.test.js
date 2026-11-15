/**
 * TC-B2 / TCM-N03 — the Trade History hand-off rides in sessionStorage, keyed
 * to the exact share payload, so no URL changes (share format frozen, owner
 * closeout 2026-10-18) and a link opened any other way shows no note.
 */
import { beforeEach, describe, expect, it, vi } from "vitest";
import {
  HISTORY_ORIGIN_STORAGE_KEY,
  historyOriginFor,
  rememberHistoryOrigin,
  sharePayloadOf,
} from "@/lib/trade-history-origin";

describe("trade-history-origin", () => {
  beforeEach(() => window.sessionStorage.clear());

  it("matches only the payload that was opened from Trade History", () => {
    rememberHistoryOrigin("abc", "2025-10-03");
    expect(historyOriginFor("abc")).toEqual({ tradedAt: "2025-10-03" });
    expect(historyOriginFor("abd")).toBeNull();
    expect(historyOriginFor(null)).toBeNull();
  });

  it("a combined trade names no date", () => {
    rememberHistoryOrigin("abc", null);
    expect(historyOriginFor("abc")).toEqual({ tradedAt: null });
  });

  it("garbage or blocked storage means no note, never an error", () => {
    window.sessionStorage.setItem(HISTORY_ORIGIN_STORAGE_KEY, "{not json");
    expect(historyOriginFor("abc")).toBeNull();
    const spy = vi.spyOn(Storage.prototype, "setItem").mockImplementation(() => {
      throw new Error("blocked");
    });
    expect(() => rememberHistoryOrigin("abc", "x")).not.toThrow();
    spy.mockRestore();
  });

  it("reads the share payload from a search string", () => {
    expect(sharePayloadOf("?share=xyz&q=1")).toBe("xyz");
    expect(sharePayloadOf("")).toBeNull();
  });
});
