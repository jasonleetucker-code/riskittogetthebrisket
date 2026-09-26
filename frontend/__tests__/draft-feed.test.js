import { describe, expect, it, vi } from "vitest";
import { createDraftCapitalLoader, draftTeamsFromContract } from "@/lib/draft-feed";

describe("draft-capital request sharing", () => {
  it("shares concurrent consumers, parses once, and refreshes on a later explicit call", async () => {
    const json = vi.fn(async () => ({ picks: [], teamTotals: [] }));
    const fetcher = vi.fn(async () => ({ ok: true, json }));
    const load = createDraftCapitalLoader(fetcher);
    const first = load("league A");
    expect(load("league A")).toBe(first);
    await first;
    expect(fetcher).toHaveBeenCalledTimes(1);
    expect(json).toHaveBeenCalledTimes(1);
    expect(fetcher.mock.calls[0][0]).toBe("/api/draft-capital?leagueKey=league+A");
    await load("league A");
    expect(fetcher).toHaveBeenCalledTimes(2);
  });
  it("never shares another league or caches failures", async () => {
    const fetcher = vi.fn(async () => ({ ok: false, status: 503 }));
    const load = createDraftCapitalLoader(fetcher);
    await Promise.all([expect(load("A")).rejects.toThrow("503"), expect(load("B")).rejects.toThrow("503")]);
    expect(fetcher).toHaveBeenCalledTimes(2);
    await expect(load("A")).rejects.toThrow("503");
    expect(fetcher).toHaveBeenCalledTimes(3);
  });
});

describe("draft contract readiness", () => {
  const teams = [{ name: "A", playerIds: ["p1"] }];
  const contract = { meta: { leagueKey: "A", sleeperDataReady: true }, sleeper: { teams } };
  it("reuses the exact owned team block without cloning or refetching", () => {
    expect(draftTeamsFromContract(contract, "A")).toBe(teams);
  });
  it("keeps pending, missing and mismatched data distinct from a ready empty list", () => {
    expect(draftTeamsFromContract(contract, "A", true)).toBeNull();
    expect(draftTeamsFromContract(contract, "B")).toBeNull();
    expect(draftTeamsFromContract(null, "A")).toBeNull();
    expect(draftTeamsFromContract({ meta: { sleeperDataReady: false }, sleeper: { teams } }, "A")).toBeNull();
    expect(draftTeamsFromContract({ sleeper: { teams: [] } }, "A")).toEqual([]);
    expect(draftTeamsFromContract({}, "A")).toBeNull();
  });
});
