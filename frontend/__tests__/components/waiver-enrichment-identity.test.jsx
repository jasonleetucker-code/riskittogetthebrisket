import { afterEach, beforeEach, expect, it, vi } from "vitest";
import { act, cleanup, renderHook } from "@testing-library/react";
const input = vi.hoisted(() => ({ team: null, league: null }));
vi.mock("@/components/AppShell", () => ({ useApp: () => ({ rows: [], rawData: {}, loading: false, error: null }) }));
vi.mock("@/components/useLeague", () => ({ useLeague: () => ({ selectedLeague: input.league }) }));
vi.mock("@/components/useTeam", () => ({ useTeam: () => ({ selectedTeam: input.team, leagueMismatch: false, availableTeams: [] }) }));
import { useWaiverAnalysis } from "@/components/useWaiverAnalysis";
import { useBestAvailableIdp } from "@/components/useBestAvailableIdp";
import { waiverBidForRow } from "@/lib/waiver-faab";
let pending;
beforeEach(() => {
  input.team = { ownerId: "A", players: [], faabRemaining: 20 };
  input.league = { key: "league-a", idpEnabled: true };
  pending = [];
  vi.stubGlobal("fetch", vi.fn((url, options) => new Promise((resolve, reject) => pending.push({ url, options, resolve, reject }))));
});
afterEach(() => { cleanup(); vi.unstubAllGlobals(); });
const bid = (value) => ({ by_position: { WR: [{ name: "Player", position: "WR", bid: { reasonable: value, lowball: 0, aggressive: value } }] } });
const idp = (league) => ({ leagueKey: league, candidates: [{ name: "Defender", combinedScore: 0 }], sourceFreshness: { idpShowCombined: null } });
async function finish(index, payload, status = 200) {
  await act(async () => pending[index].resolve(new Response(JSON.stringify(payload), { status })));
}
const currentBid = (view) => waiverBidForRow(view.result.current.faabIndex, { name: "Player", pos: "WR" });

it("refuses explicitly mismatched suggestion league labels", async () => {
  const view = renderHook(() => useWaiverAnalysis());
  await finish(0, { ...bid(99), leagueKey: "league-b" });
  expect(view.result.current.faabIndex).toBeNull();
});
it.each(["league-b", "", null, 123])("refuses explicitly wrong IDP league label %s", async (leagueKey) => {
  const view = renderHook(() => useBestAvailableIdp({ leagueKey: "league-a" }));
  await finish(0, { ...idp("league-a"), leagueKey });
  expect(view.result.current.payload).toBeNull();
  expect(view.result.current.loading).toBe(false);
});
it("refuses malformed IDP array payloads", async () => {
  const view = renderHook(() => useBestAvailableIdp({ leagueKey: "league-a" }));
  await finish(0, []);
  expect(view.result.current.payload).toBeNull();
});
it("preserves missing league-label compatibility and server-selected default league", async () => {
  const legacy = renderHook(() => useBestAvailableIdp({ leagueKey: "league-a" }));
  const defaultLeague = renderHook(() => useBestAvailableIdp());
  const unlabeled = { candidates: [], sourceFreshness: {} };
  await finish(0, unlabeled);
  await finish(1, idp("server-default"));
  expect(legacy.result.current.payload).toEqual(unlabeled);
  expect(defaultLeague.result.current.payload).toEqual(idp("server-default"));
});

it.each([undefined, null, "", "   ", false, true, [], {}, NaN, Infinity])("omits unknown or nonnumeric remaining balance %s", (balance) => {
  input.team.faabRemaining = balance;
  renderHook(() => useWaiverAnalysis());
  expect(JSON.parse(pending[0].options.body)).not.toHaveProperty("faabRemaining");
});
it.each([[0, 0], [20, 20], ["20", 20]])("retains legitimate balance %s as %s", (balance, expected) => {
  input.team.faabRemaining = balance;
  renderHook(() => useWaiverAnalysis());
  expect(JSON.parse(pending[0].options.body).faabRemaining).toBe(expected);
});
it.each(["team", "league", "balance"])("hides accepted bids immediately after %s identity changes", async (kind) => {
  const view = renderHook(() => useWaiverAnalysis());
  await finish(0, bid(9));
  expect(currentBid(view).reasonable).toBe(9);
  if (kind === "team") input.team = { ...input.team, ownerId: "B" };
  if (kind === "league") input.league = { ...input.league, key: "league-b" };
  if (kind === "balance") input.team = { ...input.team, faabRemaining: 0 };
  view.rerender();
  expect(view.result.current.faabIndex).toBeNull();
  await finish(1, bid(0));
  expect(currentBid(view).reasonable).toBe(0);
});
it("does not let ignored-abort old bids replace the new team", async () => {
  const view = renderHook(() => useWaiverAnalysis());
  input.team = { ...input.team, ownerId: "B" };
  view.rerender();
  await finish(1, bid(0));
  await finish(0, bid(99));
  expect(currentBid(view).reasonable).toBe(0);
});
it("hides bids after team deselection and preserves optional failure", async () => {
  const view = renderHook(() => useWaiverAnalysis());
  await finish(0, bid(9));
  input.team = null;
  view.rerender();
  expect(view.result.current.faabIndex).toBeNull();
  input.team = { ownerId: "B", faabRemaining: null };
  view.rerender();
  await finish(1, { error: "unavailable" }, 503);
  expect(view.result.current.faabIndex).toBeNull();
  expect(view.result.current.error).toBeNull();
});
it("hides old IDP candidates on league change and retains exact new scores", async () => {
  const view = renderHook(({ leagueKey, enabled }) => useBestAvailableIdp({ leagueKey, enabled }), { initialProps: { leagueKey: "league-a", enabled: true } });
  await finish(0, idp("league-a"));
  view.rerender({ leagueKey: "league-b", enabled: true });
  expect(view.result.current.payload).toBeNull();
  expect(view.result.current.loading).toBe(true);
  await finish(1, idp("league-b"));
  expect(view.result.current.payload).toEqual(idp("league-b"));
  view.rerender({ leagueKey: "league-b", enabled: false });
  expect(view.result.current.payload).toBeNull();
  expect(view.result.current.loading).toBe(false);
});
it("rejects ignored-abort prior-league IDP completion and tolerates new failure", async () => {
  const view = renderHook(({ leagueKey }) => useBestAvailableIdp({ leagueKey }), { initialProps: { leagueKey: "league-a" } });
  view.rerender({ leagueKey: "league-b" });
  await finish(1, { error: "unavailable" }, 503);
  await finish(0, idp("league-a"));
  expect(view.result.current.payload).toBeNull();
  expect(view.result.current.loading).toBe(false);
});
