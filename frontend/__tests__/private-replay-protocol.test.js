import { fullReplayEnvelope, fullReplayBytes } from "../../tests/e2e/performance-lab/replay-envelope.mjs";
import { gzipSync } from "node:zlib";
import { describe, it, expect } from "vitest";
import { casePlan, validateControl, aggregateParity, safeFailure, consumerUniverse, validateRepresentation, selectedCells, finalDisposition, safeRenderObservation, sourceBreakdownDigest } from "../../tests/e2e/performance-lab/replay-smoke.mjs";
const hash = "a".repeat(64);
const indexFor = (payload) => Object.fromEntries(payload.playersArray.map((row, index) => [(index + 1).toString(16).padStart(64, "0"), structuredClone(row)]));
const preparedFor = (payload) => ({ ...payload, schemaVersion: 1, meta: { ...(payload.meta || {}), readModelGeneration: "a".repeat(64) }, playersArray: Object.entries(indexFor(payload)).map(([readModelKey, row]) => ({ ...row, readModelKey })) });
const row = (cell) => ({ ...cell, passed: true, popup: { count: 2, digest: hash, identityDigest: hash }, universe: { count: 2, digest: hash }, initial: { sha256: hash, lines: 3 }, filtered: { sha256: hash, lines: 2 }, geometry: { widths: [40, 80], tableWidth: 120 } });
describe("private replay protocol", () => {
  it("requires all sixteen explicit representation/route/transport/viewport cells", () => {
    const cases = casePlan();
    expect(cases).toHaveLength(16);
    expect(aggregateParity(cases.map(row))).toEqual({ passed: true, cases: 16 });
    expect(() => aggregateParity(cases.slice(1).map(row))).toThrow();
    expect(() => aggregateParity([...cases.map(row), row(cases[0])])).toThrow();
  });
  it("rejects incorrect control scope and route treatment", () => {
    const requested = { variant: "full", transport: "next-proxy", frontendPort: 3081 };
    expect(validateControl({ ...requested, privateReplay: true }, requested)).toBe(true);
    for (const bad of [{ privateReplay: false }, { variant: "prepared" }, { transport: "direct-gzip" }, { frontendPort: 3084 }]) {
      expect(() => validateControl({ ...requested, privateReplay: true, ...bad }, requested)).toThrow();
    }
  });
  it.each(["universe", "initial", "filtered", "geometry"])("fails different %s without exposing rows", (field) => {
    const cases = casePlan().map(row);
    const candidate = cases.find((c) => c.route === "/rankings" && c.variant === "prepared");
    candidate[field] = field === "universe" ? { count: 1, digest: hash } : field === "geometry" ? { widths: [40, 90], tableWidth: 130 } : { sha256: "b".repeat(64), lines: 2 };
    expect(() => aggregateParity(cases)).toThrow("private_replay_parity_failed");
  });
  it("never reports private error names, messages, stack or payload", () => {
    const error = { name: "SECRET", message: "PRIVATE PLAYER", stack: "TOKEN", payload: "KEY" };
    expect(safeFailure(error)).toEqual({ errorType: "semantic_failure" });
  });
});

it("checks actual materialized/searchable rows without dropping unknown value identities", () => {
  const payload = { playersArray: [
    { displayName: "PRIVATE A", position: "QB", canonicalConsensusRank: 1, rankDerivedValue: 9000, assetClass: "player" },
    { displayName: "PRIVATE B", position: "LB", canonicalConsensusRank: 2, rankDerivedValue: 4000, assetClass: "player" },
  ] };
  const actual = consumerUniverse(payload, "/trade");
  expect(actual.summary.count).toBe(2);
  expect(JSON.stringify(actual.summary)).not.toContain("PRIVATE");
  const changed = structuredClone(payload); changed.playersArray[1].rankDerivedValue = 0;
  expect(consumerUniverse(changed, "/trade").summary).not.toEqual(actual.summary);
});
it("separates exact producer gzip from decoded Next transport and rejects wrong bytes", () => {
  const raw = Buffer.from('{"playersArray":[]}'); const gzip = gzipSync(raw);
  expect(validateRepresentation({ status: 200, encoding: "gzip", body: gzip }, raw, gzip, "direct-gzip")).toBe(true);
  expect(validateRepresentation({ status: 200, encoding: null, body: raw }, raw, gzip, "next-proxy")).toBe(true);
  for (const wire of [{ status: 304, encoding: "gzip", body: gzip }, { status: 200, encoding: null, body: gzip }, { status: 200, encoding: "gzip", body: Buffer.from("private") }]) {
    expect(() => validateRepresentation(wire, raw, gzip, "direct-gzip")).toThrow();
  }
  expect(() => validateRepresentation({ status: 200, encoding: "gzip", body: gzip }, raw, gzip, "next-proxy")).toThrow();
});
it.each([
  ["playerId", (row) => { row.playerId = "id-other"; }],
  ["raw value", (row) => { row.values.rawComposite = 777; }],
  ["full value", (row) => { row.values.displayValue = 777; }],
  ["position", (row) => { row.position = "DB"; }],
  ["team", (row) => { row.team = "OTHER"; }],
  ["blended search rank", (row) => { row.blendedSourceRank = 777; }],
])("rejects unselected asset %s divergence through actual materializer", (_label, mutate) => {
  const payload = { playersArray: [1, 2, 3].map((index) => ({ displayName: `PRIVATE ${index}`, playerId: `id-${index}`, position: "LB", team: "TEAM", assetClass: "player", canonicalConsensusRank: index, rankDerivedValue: index === 2 ? null : 1000 - index, blendedSourceRank: index, values: { rawComposite: 500, displayValue: 800 } })) };
  const original = consumerUniverse(payload, "/trade").summary;
  const changed = structuredClone(payload); mutate(changed.playersArray[1]);
  const after = consumerUniverse(changed, "/trade").summary;
  expect(after).not.toEqual(original);
  const cases = casePlan().map(row);
  for (const cell of cases) cell.universe = original;
  cases.find((cell) => cell.route === "/trade" && cell.variant === "prepared").universe = after;
  expect(() => aggregateParity(cases)).toThrow("private_replay_parity_failed");
  expect(JSON.stringify(after)).not.toContain("PRIVATE");
});

it("keeps single-cell diagnostics incomplete regardless of their successful result", () => {
  const cell = selectedCells("0");
  expect(cell).toHaveLength(1);
  expect(finalDisposition(cell.map(row), "0")).toEqual({ passed: false, diagnosticOnly: true, diagnosticPassed: true, cases: 1 });
  expect(() => finalDisposition(cell.map(row))).toThrow();
  expect(() => finalDisposition(cell.map(row), "1")).toThrow();
  expect(selectedCells()).toHaveLength(16);
  for (const bad of ["", "16", "-1", "PRIVATE", "0;PRIVATE"]) expect(() => selectedCells(bad)).toThrow();
});
it("reports only approved failure stage enums and ignores private exception fields", () => {
  expect(safeFailure({ message: "PRIVATE" }, "wire")).toEqual({ errorType: "semantic_failure", failureStage: "wire" });
  for (const bad of ["PRIVATE", "wire\nPRIVATE", { name: "PRIVATE" }]) expect(safeFailure({ message: "PRIVATE" }, bad)).toEqual({ errorType: "semantic_failure" });
});
it("retains only bounded render counts and numeric geometry, never DOM text", () => {
  expect(safeRenderObservation("resize-widths", { rows: 30, pageErrors: 0, tableWidth: 400, widths: [40, 0, 80], text: "PRIVATE" })).toEqual({ renderCheck: "resize-widths", rows: 30, pageErrors: 0, tableWidth: 400, widths: [40, 0, 80] });
  expect(safeRenderObservation("PRIVATE", { rows: -1, pageErrors: "SECRET", tableWidth: Infinity, widths: [1, NaN], name: "PRIVATE" })).toEqual({});
  expect(safeRenderObservation(undefined, { widths: Array(65).fill(0), rows: 20001 })).toEqual({});
});
it("adds only the lab compatibility envelope and preserves every original field/value", () => {
  const original = { meta: { leagueKey: "fixture" }, playersArray: [{ displayName: "PRIVATE", values: { rawComposite: 0, missing: null }, source: [1, null] }], other: { preserved: true } };
  const before = structuredClone(original);
  const result = fullReplayEnvelope(original, "a".repeat(64), indexFor(original), preparedFor(original));
  expect(original).toEqual(before);
  const { schemaVersion, meta, ...rest } = result;
  expect(schemaVersion).toBe(1);
  expect(meta).toEqual({ ...original.meta, readModelGeneration: "a".repeat(64) });
  expect({ ...rest, playersArray: rest.playersArray.map(({ readModelKey, ...row }) => row) }).toEqual({ playersArray: original.playersArray, other: original.other });
  expect(result.playersArray[0].readModelKey).toBe("1".padStart(64, "0"));
});
it("refuses conflicting schema or generation rather than silently relabeling", () => {
  const payload = { playersArray: [{ displayName: "PRIVATE", value: 0 }] };
  for (const bad of [{ ...payload, schemaVersion: 2 }, { ...payload, schemaVersion: null }, { ...payload, meta: { readModelGeneration: "b".repeat(64) } }, { ...payload, meta: [] }, { playersArray: [] }]) {
    expect(() => fullReplayEnvelope(bad, "a".repeat(64), indexFor(payload), preparedFor(payload))).toThrow("private_replay_envelope_invalid");
  }
  expect(() => fullReplayEnvelope(payload, "PRIVATE", indexFor(payload), preparedFor(payload))).toThrow();
  expect(() => fullReplayEnvelope(payload, ["a".repeat(64)], indexFor(payload), preparedFor(payload))).toThrow();
});
it("distinguishes immutable producer bytes from derived lab gzip", () => {
  const raw = Buffer.from(JSON.stringify({ playersArray: [{ displayName: "PRIVATE", value: null }] }));
  const gzip = gzipSync(raw); const savedRaw = Buffer.from(raw), savedGzip = Buffer.from(gzip);
  const result = fullReplayBytes(raw, gzip, "a".repeat(64), indexFor(JSON.parse(raw)), preparedFor(JSON.parse(raw)));
  expect(raw).toEqual(savedRaw); expect(gzip).toEqual(savedGzip);
  expect(result.scope).toBe("lab-derived-full-envelope-and-identity");
  expect(result.sourceRawSha256).not.toBe(result.rawSha256);
  expect(result.sourceGzipSha256).not.toBe(result.gzipSha256);
  expect(() => fullReplayBytes(Buffer.from("wrong"), gzip, "a".repeat(64))).toThrow();
});
it("binds every additive key to exactly one unchanged accepted index identity", () => {
  const payload = { playersArray: [{ displayName: "PRIVATE", playerId: "id", position: "LB", value: 0 }] };
  const index = indexFor(payload);
  const good = fullReplayEnvelope(payload, "a".repeat(64), index, preparedFor(payload));
  expect(good.playersArray[0].readModelKey).toBe(Object.keys(index)[0]);
  for (const bad of [undefined, {}, { ...index, ["b".repeat(64)]: payload.playersArray[0] }, { ["b".repeat(64)]: { ...payload.playersArray[0], position: "DB" } }]) {
    expect(() => fullReplayEnvelope(payload, "a".repeat(64), bad, preparedFor(payload))).toThrow("private_replay_envelope_invalid");
  }
  expect(() => fullReplayEnvelope({ playersArray: [{ ...payload.playersArray[0], readModelKey: "b".repeat(64) }] }, "a".repeat(64), index, preparedFor(payload))).toThrow();
  expect(() => fullReplayEnvelope({ playersArray: [payload.playersArray[0], payload.playersArray[0]] }, "a".repeat(64), index, preparedFor(payload))).toThrow();
});
it("requires exact full/prepared/index identity and factual league binding", () => {
  const payload = { playersArray: [{ displayName: "PRIVATE", playerId: "id", position: "LB" }], meta: { leagueKey: "league-a" } };
  const index = indexFor(payload), reference = preparedFor(payload);
  for (const bad of [undefined, { ...reference, meta: { ...reference.meta, leagueKey: "league-b" } }, { ...reference, meta: { ...reference.meta, readModelGeneration: "b".repeat(64) } }, { ...reference, playersArray: [{ ...reference.playersArray[0], readModelKey: "b".repeat(64) }] }, { ...reference, playersArray: [{ ...reference.playersArray[0], position: "DB" }] }]) {
    expect(() => fullReplayEnvelope(payload, "a".repeat(64), index, bad)).toThrow("private_replay_envelope_invalid");
  }
});
it("compares every rendered popup source value/title for the same selected identity", () => {
  const original = sourceBreakdownDigest([["vendor-a", "123 (4)", "Normalized PRIVATE 123"], ["vendor-b", "0", ""]], hash);
  expect(original.count).toBe(2);
  expect(JSON.stringify(original)).not.toMatch(/PRIVATE|vendor/);
  for (const changed of [sourceBreakdownDigest([["vendor-a", "124 (4)", "Normalized PRIVATE 123"], ["vendor-b", "0", ""]], hash), sourceBreakdownDigest([["vendor-a", "123 (4)", "changed"], ["vendor-b", "0", ""]], hash), { ...original, identityDigest: "b".repeat(64) }]) {
    const cases = casePlan().map(row); cases.forEach((cell) => { cell.popup = original; });
    cases.find((cell) => cell.variant === "prepared").popup = changed;
    expect(() => aggregateParity(cases)).toThrow("private_replay_parity_failed");
  }
  for (const bad of [[], [["same", "1", ""], ["same", "2", ""]], [[null, "1", ""]]]) expect(() => sourceBreakdownDigest(bad, hash)).toThrow();
});