import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { buildRows, fetchDynastyData, prefetchBaseContract, _resetBaseContractCache, RANKING_SOURCES, getSiteKeys } from "@/lib/dynasty-data";
import { fetchPreparedPlayerDetail, resetPreparedDetails } from "@/lib/prepared-player-detail";
import { readModelForRoute, usesIntentCatalog } from "@/lib/read-model-policy";
import { formatSourceCell, exportSourceCells } from "@/app/rankings/board-utils";
import { matchesQuery } from "@/lib/player-filters";
import { effectiveValue, sideTotal, computeValueAdjustment } from "@/lib/trade-logic";

const player = (extra = {}) => ({
  readModelKey: "key-a", playerId: "10", displayName: "Player A", position: "WR", team: "KC",
  canonicalConsensusRank: 2, rankDerivedValue: 9500, displayValue: 9500, sourceCount: 2,
  sourceRanks: { ktcSf: 3 }, canonicalSiteValues: { ktcSf: 8000 },
  sourceRankMeta: { ktcSf: { valueContribution: 8100 } }, rankHistory: [{ date: "2026-01-01", rank: 4 }],
  ...extra,
});
const board = (generation = "gen-a", extra = {}) => ({
  schemaVersion: 1, meta: { readModelGeneration: generation, leagueKey: "league-a" },
  playersArray: [player()], sites: [{ key: "ktcSf" }], ...extra,
});
const ok = (data) => ({ ok: true, json: async () => data });

beforeEach(() => { vi.stubEnv("NEXT_PUBLIC_PREPARED_READ_MODELS", "1"); _resetBaseContractCache(); resetPreparedDetails(); });
afterEach(() => { vi.unstubAllEnvs(); vi.unstubAllGlobals(); vi.restoreAllMocks(); });

describe("prepared representation and private cache identity", () => {
  it("is off by default and migrates only the reviewed routes", async () => {
    vi.stubEnv("NEXT_PUBLIC_PREPARED_READ_MODELS", "");
    const fetcher = vi.fn(async () => ok(board())); vi.stubGlobal("fetch", fetcher);
    expect(readModelForRoute("/rankings")).toBeNull();
    expect(usesIntentCatalog("/game-day")).toBe(false);
    await fetchDynastyData({ readModel: "rankings" });
    expect(fetcher.mock.calls[0][0]).toContain("/api/dynasty-data");
    vi.stubEnv("NEXT_PUBLIC_PREPARED_READ_MODELS", "1");
    expect(readModelForRoute("/rankings")).toBe("rankings");
    expect(readModelForRoute("/trade")).toBe("trade");
    for (const path of ["/league", "/draft", "/waivers", "/rankings/wr", "/players/10"]) expect(readModelForRoute(path)).toBeNull();
  });

  it("deduplicates shell/page/prefetch but separates rankings, trade, catalog and legacy", async () => {
    const fetcher = vi.fn(async () => ok(board())); vi.stubGlobal("fetch", fetcher);
    const [a, b, c] = await Promise.all([prefetchBaseContract({ readModel: "rankings" }), fetchDynastyData({ readModel: "rankings" }), fetchDynastyData({ readModel: "rankings" })]);
    expect(a).toBe(b); expect(b).toBe(c); expect(fetcher).toHaveBeenCalledTimes(1);
    const [trade, catalog, legacy] = await Promise.all([fetchDynastyData({ readModel: "trade" }), fetchDynastyData({ readModel: "catalog" }), fetchDynastyData()]);
    expect(fetcher).toHaveBeenCalledTimes(4);
    expect(new Set([a, trade, catalog, legacy]).size).toBe(4);
    expect(await fetchDynastyData({ readModel: "rankings" })).toBe(a);
    expect(fetcher.mock.calls.map(([url]) => url)).toEqual(expect.arrayContaining(["/api/read-models/rankings", "/api/read-models/trade/context", "/api/read-models/players/catalog"]));
  });

  it("pins override delta to the board and retries one generation mismatch", async () => {
    let gets = 0, posts = 0;
    const fetcher = vi.fn(async (url) => {
      if (url.startsWith("/api/read-models/")) return ok(board(++gets === 1 ? "gen-a" : "gen-b"));
      posts += 1;
      if (posts === 1) return { ok: false, status: 409, json: async () => ({ error: "generation_changed" }) };
      return ok({ mode: "delta", meta: { readModelGeneration: "gen-b" }, rankingsDelta: { playerKey: "displayName", players: [{ id: "Player A", rankDerivedValue: 9000 }], activePlayerIds: ["Player A"] } });
    });
    vi.stubGlobal("fetch", fetcher);
    const result = await fetchDynastyData({ readModel: "rankings", tepMultiplier: 1.2 });
    expect(gets).toBe(2); expect(posts).toBe(2);
    expect(fetcher.mock.calls[1][0]).toBe("/api/rankings/overrides?view=board&generation=gen-a");
    expect(fetcher.mock.calls[3][0]).toBe("/api/rankings/overrides?view=board&generation=gen-b");
    expect(result.data.playersArray[0].rankDerivedValue).toBe(9000);
    expect(result.data.meta.readModelGeneration).toBe("gen-b");
  });

  it("fails closed after a second delta mismatch instead of mixing generations", async () => {
    const fetcher = vi.fn(async (url) => url.startsWith("/api/read-models/") ? ok(board()) : ok({ mode: "delta", meta: { readModelGeneration: "wrong" } }));
    vi.stubGlobal("fetch", fetcher);
    await expect(fetchDynastyData({ readModel: "rankings", tepMultiplier: 1.2 })).rejects.toMatchObject({ status: 409 });
    expect(fetcher).toHaveBeenCalledTimes(4);
  });

  it("rejects invalid prepared envelopes and never reuses a failed request", async () => {
    const fetcher = vi.fn().mockResolvedValueOnce(ok({ playersArray: [player()] })).mockResolvedValue(ok(board()));
    vi.stubGlobal("fetch", fetcher);
    await expect(fetchDynastyData({ readModel: "rankings" })).rejects.toMatchObject({ status: 503 });
    await fetchDynastyData({ readModel: "rankings" });
    expect(fetcher).toHaveBeenCalledTimes(2);
  });

  it("does not refill private caches with a response begun before reset", async () => {
    let resolve;
    const fetcher = vi.fn().mockImplementationOnce(() => new Promise((r) => { resolve = r; })).mockResolvedValue(ok(board("gen-b")));
    vi.stubGlobal("fetch", fetcher);
    const old = fetchDynastyData({ readModel: "rankings" });
    _resetBaseContractCache(); resolve(ok(board())); await old;
    expect((await fetchDynastyData({ readModel: "rankings" })).data.meta.readModelGeneration).toBe("gen-b");
    expect(fetcher).toHaveBeenCalledTimes(2);
  });
});

describe("full detail preserves board semantics", () => {
  it("pins identity/generation/league, single-flights and overlays current values", async () => {
    const row = buildRows(board())[0];
    const full = player({ rankDerivedValue: 8000, sourceAudit: { reason: "verified" }, pickDetails: { round: 1 } });
    const fetcher = vi.fn(async () => ok({ schemaVersion: 1, generation: "gen-a", player: full })); vi.stubGlobal("fetch", fetcher);
    const [a, b] = await Promise.all([fetchPreparedPlayerDetail(row, board()), fetchPreparedPlayerDetail(row, board())]);
    expect(fetcher).toHaveBeenCalledTimes(1);
    expect(fetcher.mock.calls[0][0]).toBe("/api/read-models/players/key-a?generation=gen-a&leagueKey=league-a");
    expect(a.values.full).toBe(9500); expect(a.rank).toBe(row.rank);
    expect(a.raw.sourceAudit.reason).toBe("verified"); expect(a).toEqual(b);
    expect(row.raw.sourceAudit).toBeUndefined();
  });

  it("rejects another player's response and retries authorization failures", async () => {
    const fetcher = vi.fn().mockResolvedValueOnce({ ok: false, status: 403, json: async () => ({ error: "forbidden" }) }).mockResolvedValueOnce(ok({ schemaVersion: 1, generation: "gen-a", player: player({ readModelKey: "other" }) }));
    vi.stubGlobal("fetch", fetcher);
    const row = buildRows(board())[0];
    await expect(fetchPreparedPlayerDetail(row, board())).rejects.toMatchObject({ status: 403 });
    await expect(fetchPreparedPlayerDetail(row, board())).rejects.toThrow("did not match");
    expect(fetcher).toHaveBeenCalledTimes(2);
  });

  it("retains ordering, search, source exports/mobile cells, history and trade math after detail-only fields are omitted", () => {
    const full = board("gen-a", { playersArray: [player({ sourceAudit: { reason: "one" }, hillValueSpread: 1, marketDispersionCV: 0.2, pickDetails: {} }), player({ readModelKey: "key-b", displayName: "Player B", position: "LB", canonicalConsensusRank: 4, rankDerivedValue: 7200 }), player({ readModelKey: "pick", displayName: "2027 Early 1st", position: "PICK", canonicalConsensusRank: 7, rankDerivedValue: 4000, pickGenericSuppressed: true })] });
    const prepared = structuredClone(full);
    prepared.playersArray.forEach((p) => { for (const field of ["sourceAudit", "hillValueSpread", "marketDispersionCV", "pickDetails"]) delete p[field]; });
    const a = buildRows(full), b = buildRows(prepared);
    expect(a.map(({ raw, ...row }) => row)).toEqual(b.map(({ raw, ...row }) => row));
    expect(getSiteKeys(prepared)).toEqual(getSiteKeys(full));
    for (const query of ["player", "wr kc", "pos:lb", "2027"]) expect(a.filter((r) => matchesQuery(r, query)).map((r) => r.name)).toEqual(b.filter((r) => matchesQuery(r, query)).map((r) => r.name));
    for (let i = 0; i < a.length; i++) for (const src of RANKING_SOURCES) {
      expect(formatSourceCell(a[i], src)).toEqual(formatSourceCell(b[i], src));
      expect(exportSourceCells(a[i], src)).toEqual(exportSourceCells(b[i], src));
    }
    expect(a.map((r) => effectiveValue(r, "full"))).toEqual(b.map((r) => effectiveValue(r, "full")));
    expect(sideTotal(a, "full")).toEqual(sideTotal(b, "full"));
    expect(computeValueAdjustment(a.slice(0, 1), a.slice(1), "full")).toEqual(computeValueAdjustment(b.slice(0, 1), b.slice(1), "full"));
  });
});
