// Lab transport compatibility only. No valuation or projection ownership.
import { createHash } from "node:crypto";
import { gunzipSync, gzipSync } from "node:zlib";
const hash = (value) => createHash("sha256").update(value).digest("hex");
const invalid = () => { throw new Error("private_replay_envelope_invalid"); };
function exactIdentity(row) {
  if (!row || typeof row !== "object" || Array.isArray(row)) invalid();
  const fields = ["displayName", "canonicalName", "playerId", "position", "assetClass"];
  if (!fields.some((field) => row[field] != null && row[field] !== "")) invalid();
  if (fields.some((field) => row[field] != null && !["string", "number"].includes(typeof row[field]))) invalid();
  return JSON.stringify(fields.map((field) => [Object.hasOwn(row, field), row[field] ?? null]));
}
export function fullReplayEnvelope(payload, generation, playerIndex, prepared) {
  if (!payload || typeof payload !== "object" || Array.isArray(payload) || !Array.isArray(payload.playersArray) || !payload.playersArray.length || typeof generation !== "string" || !/^[a-f0-9]{64}$/.test(generation)) invalid();
  if (payload.schemaVersion !== undefined && payload.schemaVersion !== 1) invalid();
  if (payload.meta != null && (typeof payload.meta !== "object" || Array.isArray(payload.meta))) invalid();
  if (payload.meta?.readModelGeneration !== undefined && payload.meta.readModelGeneration !== generation) invalid();
  if (!playerIndex || typeof playerIndex !== "object" || Array.isArray(playerIndex)) invalid();
  const identities = new Map();
  for (const [key, row] of Object.entries(playerIndex)) {
    const identity = exactIdentity(row);
    if (!/^[a-f0-9]{64}$/.test(key) || identities.has(identity)) invalid();
    identities.set(identity, key);
  }
  if (prepared?.schemaVersion !== 1 || prepared?.meta?.readModelGeneration !== generation || !Array.isArray(prepared.playersArray) || prepared.playersArray.length !== payload.playersArray.length || (prepared.meta?.leagueKey ?? null) !== (payload.meta?.leagueKey ?? null)) invalid();
  const referenceKeys = new Set();
  for (const row of prepared.playersArray) {
    const key = identities.get(exactIdentity(row));
    if (!key || row.readModelKey !== key || referenceKeys.has(key)) invalid();
    referenceKeys.add(key);
  }
  if (referenceKeys.size !== identities.size) invalid();
  const used = new Set();
  const playersArray = payload.playersArray.map((row) => {
    const key = identities.get(exactIdentity(row));
    if (!key || used.has(key) || (row.readModelKey !== undefined && row.readModelKey !== key)) invalid();
    used.add(key);
    return { ...row, readModelKey: key };
  });
  if (used.size !== identities.size) invalid();
  return { ...payload, playersArray, schemaVersion: 1, meta: { ...(payload.meta || {}), readModelGeneration: generation } };
}
export function fullReplayBytes(sourceRaw, sourceGzip, generation, playerIndex, prepared) {
  if (!gunzipSync(sourceGzip).equals(sourceRaw)) invalid();
  const source = JSON.parse(sourceRaw);
  const payload = fullReplayEnvelope(source, generation, playerIndex, prepared);
  const raw = Buffer.from(JSON.stringify(payload));
  const gzip = gzipSync(raw, { level: 5 });
  return { payload, raw, gzip, sourceRawSha256: hash(sourceRaw), sourceGzipSha256: hash(sourceGzip), rawSha256: hash(raw), gzipSha256: hash(gzip), scope: "lab-derived-full-envelope-and-identity" };
}
