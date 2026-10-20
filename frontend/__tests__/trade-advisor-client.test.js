/**
 * Brisket Trade Advisor — public client against the spec §4 fixtures
 * (produced by the backend lane from real responses and consumed here
 * byte-for-byte).  Pins: the allowlist (a non-contract field — a value, a
 * rank, a gap — never survives into the client), the fairness-only result
 * shape (every team's result + the overall result in one response), the
 * bootstrap classification that decides whether the hub offers the advisor
 * at all, the fixed error copy, and the request hygiene (no credentials,
 * analyze never cached, one retry on a gateway flap, one value-free sort).
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
    out.gap = 1234;
    out.category = "FAVORABLE";
    return out;
  }
  return obj;
}
const leaks = (x) =>
  SENTINELS.some((n) => JSON.stringify(x).includes(String(n))) ||
  /"(rankDerivedValue|value|rank|confidence|gap|category)"/.test(JSON.stringify(x));

describe("fixtures index", () => {
  it("names every fixture file and only advisor paths", () => {
    const files = fs
      .readdirSync(FIX)
      .filter((f) => f !== "index.json")
      .map((f) => f.replace(/\.json$/, ""));
    expect(Object.keys(INDEX).sort()).toEqual(files.sort());
    for (const entry of Object.values(INDEX)) expect(entry.path.startsWith(ADVISOR_API)).toBe(true);
  });
});

describe("allowlist", () => {
  it("teams: keeps exactly the contract's identities and drops anything else", () => {
    const clean = sanitizeTeamsPayload(poison(fixture("teams.success")));
    expect(leaks(clean)).toBe(false);
    expect(Object.keys(clean).sort()).toEqual(["generation", "limits", "rosters", "teams"]);
    expect(Object.keys(clean.teams[0]).sort()).toEqual(["displayName", "rosterId", "teamName"]);
    expect(clean.teams.map((t) => t.rosterId)).toEqual([1, 2, 3, 4]);
    expect(clean.limits).toEqual({ minTeams: 2, maxTeams: 4, maxLegs: 128 });
    expect(sanitizeTeamsPayload(fixture("teams.rosters-stale")).rosters).toEqual({
      state: "stale",
      asOf: fixture("teams.rosters-stale").rosters.asOf,
    });
  });

  it("assets: keeps player and pick keys exactly, in the server's order", () => {
    const raw = fixture("assets.position_alpha");
    const clean = sanitizeAssetsPayload(poison(raw));
    expect(leaks(clean)).toBe(false);
    expect(clean.assets.map((a) => a.id)).toEqual(raw.assets.map((a) => a.id));
    const player = clean.assets.find((a) => a.kind === "player");
    const pick = clean.assets.find((a) => a.kind === "pick");
    expect(Object.keys(player).sort()).toEqual(["evaluable", "id", "kind", "label", "nflTeam", "position", "side"]);
    expect(Object.keys(pick).sort()).toEqual([
      "evaluable",
      "id",
      "kind",
      "label",
      "originRosterId",
      "projection",
      "round",
      "season",
      "side",
    ]);
    expect(clean.sort).toBe("position_alpha");
    expect(sanitizeAssetsPayload(fixture("assets.pick-ownership-unavailable")).pickOwnership).toBe("unavailable");
    // A value order is not a public order (spec §4.2).
    expect(sanitizeAssetsPayload({ ...raw, sort: "value_desc" }).sort).toBeNull();
  });

  const ANALYZE = [
    "analyze.fair-two-team",
    "analyze.not-fair-two-team",
    "analyze.three-team-fair",
    "analyze.four-team-mixed",
    "analyze.unable-asset",
    "analyze.unable-stale-rosters",
  ];

  it.each(ANALYZE)("analyze %s: keeps every team's result enum + fixed copy and the overall result only", (name) => {
    const raw = fixture(name);
    const clean = sanitizeAnalyzePayload(poison(raw));
    expect(leaks(clean)).toBe(false);
    expect(Object.keys(clean).sort()).toEqual([
      "generation",
      "overall",
      "perspectiveRosterId",
      "rosters",
      "teamCount",
      "teams",
      "trade",
    ]);
    expect(clean.overall).toEqual({
      result: raw.overall.result,
      label: raw.overall.label,
      reasonCode: raw.overall.reasonCode,
      reasonText: raw.overall.reasonText,
      note: raw.overall.note,
    });
    expect(clean.teams).toEqual(
      raw.teams.map((t) => ({
        rosterId: t.rosterId,
        result: t.result,
        label: t.label,
        reasonCode: t.reasonCode,
        reasonText: t.reasonText,
        unavailableAssetIds: t.unavailableAssetIds,
      })),
    );
    expect(clean.trade).toEqual(raw.trade);
    expect(clean.teamCount).toBe(raw.teams.length);
  });

  it("analyze: an unknown result enum anywhere makes the payload unusable (never guessed)", () => {
    const raw = fixture("analyze.four-team-mixed");
    expect(sanitizeAnalyzePayload({ ...raw, overall: { ...raw.overall, result: "ACCEPT" } })).toBeNull();
    expect(
      sanitizeAnalyzePayload({ ...raw, teams: [{ ...raw.teams[0], result: "FAVORABLE" }, ...raw.teams.slice(1)] }),
    ).toBeNull();
    expect(sanitizeAnalyzePayload({ ...raw, teams: raw.teams.slice(0, 1) })).toBeNull();
    expect(sanitizeAnalyzePayload({ ...raw, status: "error" })).toBeNull();
    // Unknown reason codes are dropped, not shown.
    const odd = sanitizeAnalyzePayload({
      ...raw,
      teams: raw.teams.map((t) => ({ ...t, reasonCode: "posture_unknown" })),
    });
    expect(odd.teams.every((t) => t.reasonCode === null)).toBe(true);
  });

  it("no fixture carries the retired vocabulary", () => {
    for (const name of Object.keys(INDEX)) {
      const text = JSON.stringify(fixture(name));
      expect(text, name).not.toMatch(/ACCEPT|DECLINE|FAVORABLE|multi_team_unsupported|value_desc|roster_limit/);
    }
  });
});

describe("bootstrap classification (does the hub offer the advisor?)", () => {
  it("ready on a well-formed 200", () => {
    expect(classifyTeamsResult({ status: 200, data: fixture("teams.success") }).state).toBe("ready");
  });
  it("disabled when the flag is off (503 disabled) or the route is absent (404)", () => {
    expect(classifyTeamsResult({ status: 503, data: fixture("error.disabled") })).toEqual({ state: "disabled" });
    expect(classifyTeamsResult({ status: 404, data: fixture("error.league-not-public") })).toEqual({
      state: "disabled",
    });
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
    expect(errorFromResponse(429, fixture("error.rate-limited"))).toMatchObject({
      kind: "rate_limited",
      retryAfterSeconds: 600,
    });
    expect(errorFromResponse(503, fixture("error.disabled")).kind).toBe("disabled");
    // The same fixed wording as the server's copy table (spec §4.4).
    for (const name of [
      "error.invalid-trade-one-sided",
      "error.invalid-trade-duplicate-asset",
      "error.invalid-trade-perspective",
    ]) {
      const body = fixture(name);
      expect(errorFromResponse(400, body)).toMatchObject({ kind: "invalid", message: body.message });
    }
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
    const calls = stubFetch([
      [200, fixture("teams.success")],
      [200, fixture("assets.position_alpha")],
      [200, fixture("analyze.not-fair-two-team")],
    ]);
    expect((await fetchAdvisorTeams()).state).toBe("ready");
    expect((await fetchAdvisorAssets(1)).ok).toBe(true);
    const body = { perspectiveRosterId: 1, teams: [1, 2], assets: fixture("analyze.not-fair-two-team").trade };
    const r = await postAdvisorAnalyze(body);
    expect(r.data.overall.result).toBe("NOT_FAIR");
    expect(calls.map((c) => c.init.credentials)).toEqual(["omit", "omit", "omit"]);
    expect(calls[1].url).toBe(`${ADVISOR_API}/teams/1/assets?sort=position_alpha`);
    expect(calls[2].init).toMatchObject({ method: "POST", cache: "no-store" });
    expect(JSON.parse(calls[2].init.body)).toEqual(body);
  });

  it("retries a gateway flap once, then reports", async () => {
    const calls = stubFetch([
      [502, {}],
      [200, fixture("assets.pick-ownership-unavailable")],
    ]);
    expect((await fetchAdvisorAssets(2)).ok).toBe(true);
    expect(calls).toHaveLength(2);
    stubFetch([
      [504, {}],
      [504, {}],
    ]);
    expect((await fetchAdvisorAssets(2)).ok).toBe(false);
  });

  it("only the value-free sort is ever sent", async () => {
    const calls = stubFetch([[200, fixture("assets.position_alpha")]]);
    await fetchAdvisorAssets(1, "value_desc");
    expect(calls[0].url).toMatch(/sort=position_alpha$/);
  });

  it("surfaces a disabled advisor from the browser too", async () => {
    stubFetch([[503, fixture("error.disabled")]]);
    const r = await fetchAdvisorTeams();
    expect(r).toMatchObject({ ok: false, state: "disabled" });
  });
});
