/**
 * Brisket Trade Advisor — public client against the frozen §4 fixtures
 * (shared byte-for-byte with the backend unit, which pins them against real
 * responses).  Pins: the allowlist (a non-contract field — a value, a rank —
 * never survives into the client), the bootstrap classification that decides
 * whether the hub offers the advisor at all, the fixed error copy, and the
 * request hygiene (no credentials, analyze never cached, one retry on a
 * gateway flap).
 */
import fs from "node:fs";
import path from "node:path";
import { afterEach, describe, expect, it, vi } from "vitest";

import {
  ADVISOR_API,
  classifyTeamsResult,
  errorFromResponse,
  fetchAdvisorAssets,
  fetchAdvisorTeams,
  postAdvisorAnalyze,
  sanitizeAnalyzePayload,
  sanitizeAssetsPayload,
  sanitizeTeamsPayload,
} from "@/lib/trade-advisor-client";

const FIX = path.resolve(__dirname, "fixtures", "trade-advisor");
const fixture = (name) => JSON.parse(fs.readFileSync(path.join(FIX, `${name}.json`), "utf8"));
const INDEX = fixture("index");

afterEach(() => vi.unstubAllGlobals());

const SENTINELS = [987654, 876543];
function poison(obj) {
  // Recursively add value-like fields a buggy backend might leak.
  if (Array.isArray(obj)) return obj.map(poison);
  if (obj && typeof obj === "object") {
    const out = {};
    for (const [k, v] of Object.entries(obj)) out[k] = poison(v);
    out.rankDerivedValue = SENTINELS[0];
    out.value = SENTINELS[1];
    out.rank = 3;
    out.confidence = 0.91;
    return out;
  }
  return obj;
}
const leaks = (x) => SENTINELS.some((n) => JSON.stringify(x).includes(String(n))) || /"(rankDerivedValue|value|rank|confidence)"/.test(JSON.stringify(x));

describe("fixtures index", () => {
  it("names every fixture file and only advisor paths", () => {
    const files = fs.readdirSync(FIX).filter((f) => f !== "index.json").map((f) => f.replace(/\.json$/, ""));
    expect(Object.keys(INDEX).sort()).toEqual(files.sort());
    for (const entry of Object.values(INDEX)) expect(entry.path.startsWith(ADVISOR_API)).toBe(true);
  });
});

describe("allowlist", () => {
  it("teams: keeps exactly the contract's identities and drops anything else", () => {
    const clean = sanitizeTeamsPayload(poison(fixture("teams.success")));
    expect(leaks(clean)).toBe(false);
    expect(Object.keys(clean).sort()).toEqual(["generation", "limits", "multiTeam", "rosters", "teams"]);
    expect(Object.keys(clean.teams[0]).sort()).toEqual(["displayName", "rosterId", "teamName"]);
    expect(clean.teams.map((t) => t.rosterId)).toEqual([1, 2, 3]);
    expect(sanitizeTeamsPayload(fixture("teams.rosters-stale")).rosters).toEqual({ state: "stale", asOf: "2026-10-19" });
  });

  it("assets: keeps player and pick keys exactly, in the server's order", () => {
    const raw = fixture("assets.value_desc");
    const clean = sanitizeAssetsPayload(poison(raw));
    expect(leaks(clean)).toBe(false);
    expect(clean.assets.map((a) => a.id)).toEqual(raw.assets.map((a) => a.id));
    const player = clean.assets.find((a) => a.kind === "player");
    const pick = clean.assets.find((a) => a.kind === "pick");
    expect(Object.keys(player).sort()).toEqual(["evaluable", "id", "kind", "label", "nflTeam", "position", "side"]);
    expect(Object.keys(pick).sort()).toEqual(["evaluable", "id", "kind", "label", "originRosterId", "projection", "round", "season", "side"]);
    expect(sanitizeAssetsPayload(fixture("assets.pick-ownership-unavailable")).pickOwnership).toBe("unavailable");
  });

  it("analyze: keeps the enum, the fixed copy and the reason only", () => {
    for (const name of ["analyze.favorable", "analyze.strongly-unfavorable", "analyze.unavailable-asset", "analyze.multi-team-unsupported", "analyze.roster-limit"]) {
      const raw = fixture(name);
      const clean = sanitizeAnalyzePayload(poison(raw));
      expect(leaks(clean)).toBe(false);
      expect(clean.category).toBe(raw.category);
      expect(clean.headline).toBe(raw.headline);
      expect(clean.message).toBe(raw.message);
      expect(clean.reasonCode).toBe(raw.reasonCode);
      expect(clean.reasonText).toBe(raw.reasonText);
      expect(clean.unavailableAssetIds).toEqual(raw.unavailableAssetIds);
    }
    expect(sanitizeAnalyzePayload({ ...fixture("analyze.favorable"), category: "TOTALLY_NEW" })).toBeNull();
    expect(sanitizeAnalyzePayload({ ...fixture("analyze.favorable"), reasonCode: "posture_unknown" }).reasonCode).toBeNull();
  });
});

describe("bootstrap classification (does the hub offer the advisor?)", () => {
  it("ready on a well-formed 200", () => {
    expect(classifyTeamsResult({ status: 200, data: fixture("teams.success") }).state).toBe("ready");
  });
  it("disabled when the flag is off (503 disabled) or the route is absent (404)", () => {
    expect(classifyTeamsResult({ status: 503, data: fixture("error.disabled") })).toEqual({ state: "disabled" });
    expect(classifyTeamsResult({ status: 404, data: fixture("error.league-not-public") })).toEqual({ state: "disabled" });
    expect(classifyTeamsResult({ status: 404, data: null })).toEqual({ state: "disabled" });
  });
  it("unknown on no answer, not-ready or a malformed body", () => {
    expect(classifyTeamsResult({ status: 0, data: null }).state).toBe("unknown");
    expect(classifyTeamsResult({ status: 503, data: fixture("error.not-ready") }).state).toBe("unknown");
    expect(classifyTeamsResult({ status: 200, data: { teams: [] } }).state).toBe("unknown");
    expect(classifyTeamsResult().state).toBe("unknown");
  });
});

describe("errors use fixed client copy", () => {
  it("maps each contract error to a kind without echoing server text", () => {
    expect(errorFromResponse(409, fixture("error.stale-assets"))).toMatchObject({ kind: "stale", assetIds: ["p:201"] });
    expect(errorFromResponse(429, fixture("error.rate-limited"))).toMatchObject({ kind: "rate_limited", retryAfterSeconds: 600 });
    expect(errorFromResponse(503, fixture("error.disabled")).kind).toBe("disabled");
    expect(errorFromResponse(400, fixture("error.invalid-trade-one-sided"))).toMatchObject({
      kind: "invalid",
      message: "Each team must send at least one player or pick.",
    });
    const sneaky = { error: "advisor_unavailable", message: "Traceback: secret=hunter2 value 987654" };
    expect(JSON.stringify(errorFromResponse(503, sneaky))).not.toMatch(/hunter2|987654|Traceback/);
    expect(errorFromResponse(0, null).kind).toBe("offline");
  });
});

describe("request hygiene", () => {
  function stubFetch(responses) {
    const calls = [];
    vi.stubGlobal(
      "fetch",
      vi.fn(async (url, init) => {
        calls.push({ url, init });
        const [status, body] = responses.shift();
        return new Response(JSON.stringify(body), { status, headers: { "content-type": "application/json" } });
      }),
    );
    return calls;
  }

  it("never sends credentials; analyze is POST + no-store with a JSON body", async () => {
    const calls = stubFetch([[200, fixture("teams.success")], [200, fixture("assets.value_desc")], [200, fixture("analyze.favorable")]]);
    expect((await fetchAdvisorTeams()).state).toBe("ready");
    expect((await fetchAdvisorAssets(1, "value_desc")).ok).toBe(true);
    const body = { perspectiveRosterId: 1, teams: [1, 2], assets: fixture("analyze.favorable").trade };
    const r = await postAdvisorAnalyze(body);
    expect(r.data.category).toBe("FAVORABLE");
    expect(calls.map((c) => c.init.credentials)).toEqual(["omit", "omit", "omit"]);
    expect(calls[1].url).toBe(`${ADVISOR_API}/teams/1/assets?sort=value_desc`);
    expect(calls[2].init).toMatchObject({ method: "POST", cache: "no-store" });
    expect(JSON.parse(calls[2].init.body)).toEqual(body);
  });

  it("retries a gateway flap once, then reports", async () => {
    const calls = stubFetch([[502, {}], [200, fixture("assets.alpha")]]);
    expect((await fetchAdvisorAssets(2, "alpha")).ok).toBe(true);
    expect(calls).toHaveLength(2);
    stubFetch([[504, {}], [504, {}]]);
    expect((await fetchAdvisorAssets(2, "alpha")).ok).toBe(false);
  });

  it("an unknown sort is never sent", async () => {
    const calls = stubFetch([[200, fixture("assets.value_desc")]]);
    await fetchAdvisorAssets(1, "by_secret_value");
    expect(calls[0].url).toMatch(/sort=value_desc$/);
  });

  it("surfaces a disabled advisor from the browser too", async () => {
    stubFetch([[503, fixture("error.disabled")]]);
    const r = await fetchAdvisorTeams();
    expect(r).toMatchObject({ ok: false, state: "disabled" });
  });
});
