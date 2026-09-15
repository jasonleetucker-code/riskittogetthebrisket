import React from "react";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import { act, fireEvent, render, screen, waitFor } from "@testing-library/react";

const route = vi.hoisted(() => ({ pathname: "/rankings" }));
vi.mock("next/navigation", () => ({ usePathname: () => route.pathname }));
vi.mock("@/components/useSettings", () => ({ useSettings: () => ({ settings: {}, hydrated: true }) }));
vi.mock("@/components/PlayerPopup", () => ({ default: ({ row }) => <div data-testid="full-popup">{row.name} {row.raw.sourceAudit?.reason} {row.values.full}</div> }));
vi.mock("@/components/shell/CommandPalette", () => ({ default: ({ rows, onSelect, loading }) => <div data-testid="palette">{loading ? "Loading catalog" : `${rows.length} players`}<button onClick={() => onSelect(rows[0])}>Select player</button></div> }));

import AppShell, { useApp } from "@/components/AppShell";
import { useDynastyData } from "@/components/useDynastyData";
import { _resetBaseContractCache, buildRows } from "@/lib/dynasty-data";
import { resetPreparedDetails } from "@/lib/prepared-player-detail";
import { SourceAuditPanel } from "@/app/rankings/board-sections";

const player = (name = "Player A") => ({ readModelKey: "key-a", playerId: "10", displayName: name, position: "WR", team: "KC", canonicalConsensusRank: 2, rankDerivedValue: 9500 });
const board = (generation = "gen-a", name = "Player A") => ({ schemaVersion: 1, meta: { readModelGeneration: generation, leagueKey: "league-a" }, playersArray: [player(name)], sleeper: { teams: [] } });
const ok = (data) => ({ ok: true, json: async () => data });
const full = (generation = "gen-a", name = "Player A") => ok({ schemaVersion: 1, generation, player: { ...player(name), rankDerivedValue: 5000, sourceAudit: { reason: "Full source details" } } });

function Controls() {
  const app = useApp();
  return <><div data-testid="shell-row">{app.rows[0]?.name || "No board"}</div>
    <button onClick={app.openSearch}>Search</button><button onClick={() => app.openPlayerPopup(app.rows[0])}>Open player</button></>;
}
function PageHook() {
  const data = useDynastyData({ readModel: route.pathname === "/rankings" ? "rankings" : "trade" });
  return <div data-testid="page-row">{data.rows[0]?.name || "No board"}</div>;
}

beforeEach(() => { vi.stubEnv("NEXT_PUBLIC_PREPARED_READ_MODELS", "1"); route.pathname = "/rankings"; _resetBaseContractCache(); resetPreparedDetails(); localStorage.clear(); });
afterEach(() => { vi.unstubAllGlobals(); vi.unstubAllEnvs(); vi.restoreAllMocks(); });

it("shell and actual page hook make one prepared GET, then change representation on navigation", async () => {
  const fetcher = vi.fn(async (url) => ok(board("gen-a", url.includes("trade/context") ? "Trade row" : "Rankings row")));
  vi.stubGlobal("fetch", fetcher);
  const view = render(<AppShell authenticated><Controls /><PageHook /></AppShell>);
  await waitFor(() => expect(screen.getByTestId("page-row")).toHaveTextContent("Rankings row"));
  expect(screen.getByTestId("shell-row")).toHaveTextContent("Rankings row");
  expect(fetcher).toHaveBeenCalledTimes(1);
  expect(fetcher.mock.calls[0][0]).toBe("/api/read-models/rankings");
  route.pathname = "/trade";
  view.rerender(<AppShell authenticated><Controls /><PageHook /></AppShell>);
  expect(screen.getByTestId("shell-row")).toHaveTextContent("No board");
  await waitFor(() => expect(screen.getByTestId("page-row")).toHaveTextContent("Trade row"));
  expect(fetcher).toHaveBeenCalledTimes(2);
  expect(fetcher.mock.calls[1][0]).toBe("/api/read-models/trade/context");
});

it.each(["/bdvm", "/game-day", "/league-comparison"])("%s fetches its search catalog only on first intent", async (pathname) => {
  route.pathname = pathname;
  const fetcher = vi.fn(async () => ok(board())); vi.stubGlobal("fetch", fetcher);
  render(<AppShell authenticated><Controls /></AppShell>);
  await act(async () => {});
  expect(fetcher).not.toHaveBeenCalled();
  fireEvent.click(screen.getByText("Search"));
  await waitFor(() => expect(screen.getByTestId("palette")).toHaveTextContent("1 players"));
  expect(fetcher).toHaveBeenCalledTimes(1);
  expect(fetcher.mock.calls[0][0]).toBe("/api/read-models/players/catalog");
});

it("public league never hydrates private search or prepared data", async () => {
  route.pathname = "/league";
  const fetcher = vi.fn(); vi.stubGlobal("fetch", fetcher);
  render(<AppShell authenticated><Controls /></AppShell>);
  fireEvent.click(screen.getByText("Search"));
  await act(async () => {});
  expect(fetcher).not.toHaveBeenCalled();
  expect(screen.queryByTestId("palette")).toBeNull();
});

it("shows a pending drawer until full details arrive and retains the board value", async () => {
  let resolveDetail;
  const fetcher = vi.fn((url) => url.includes("/players/key-a") ? new Promise((r) => { resolveDetail = r; }) : Promise.resolve(ok(board())));
  vi.stubGlobal("fetch", fetcher);
  render(<AppShell authenticated><Controls /></AppShell>);
  await waitFor(() => expect(screen.getByTestId("shell-row")).toHaveTextContent("Player A"));
  fireEvent.click(screen.getByText("Open player"));
  await screen.findByText("Loading player details…");
  expect(screen.queryByTestId("full-popup")).toBeNull();
  await act(async () => resolveDetail(full()));
  expect(await screen.findByTestId("full-popup")).toHaveTextContent("Full source details 9500");
  expect(fetcher.mock.calls[1][0]).toContain("generation=gen-a&leagueKey=league-a");
});

it("409 refreshes the board and reopens the selected player from the new generation", async () => {
  let gets = 0, detailGets = 0;
  const fetcher = vi.fn(async (url) => {
    if (!url.includes("/players/key-a")) return ok(board(++gets === 1 ? "gen-a" : "gen-b"));
    if (++detailGets === 1) return { ok: false, status: 409, json: async () => ({ error: "generation_changed" }) };
    return full("gen-b");
  });
  vi.stubGlobal("fetch", fetcher);
  render(<AppShell authenticated><Controls /><PageHook /></AppShell>);
  await waitFor(() => expect(screen.getByTestId("shell-row")).toHaveTextContent("Player A"));
  fireEvent.click(screen.getByText("Open player"));
  expect(await screen.findByTestId("full-popup")).toHaveTextContent("Full source details");
  expect(gets).toBe(2); expect(detailGets).toBe(2);
  expect(fetcher.mock.calls.at(-1)[0]).toContain("generation=gen-b");
});

it("does not publish old-league detail after a switch", async () => {
  let resolveDetail;
  const fetcher = vi.fn((url) => url.includes("/players/key-a") ? new Promise((r) => { resolveDetail = r; }) : Promise.resolve(ok(board())));
  vi.stubGlobal("fetch", fetcher);
  render(<AppShell authenticated><Controls /></AppShell>);
  await waitFor(() => expect(screen.getByTestId("shell-row")).toHaveTextContent("Player A"));
  fireEvent.click(screen.getByText("Open player"));
  await screen.findByText("Loading player details…");
  await act(async () => { localStorage.setItem("next_active_league_v1", "league-b"); _resetBaseContractCache(); window.dispatchEvent(new Event("league:changed")); });
  await act(async () => resolveDetail(full()));
  expect(screen.queryByTestId("full-popup")).toBeNull();
  expect(screen.queryByRole("dialog")).toBeNull();
  expect(fetcher.mock.calls.at(-1)[0]).toContain("leagueKey=league-b");
});

it("bounds automatic generation recovery when the board keeps returning the same stale generation", async () => {
  let gets = 0, detailGets = 0;
  vi.stubGlobal("fetch", vi.fn(async (url) => {
    if (!url.includes("/players/key-a")) { gets += 1; return ok(board()); }
    detailGets += 1;
    return { ok: false, status: 409, json: async () => ({ error: "generation_changed" }) };
  }));
  render(<AppShell authenticated><Controls /></AppShell>);
  await waitFor(() => expect(screen.getByTestId("shell-row")).toHaveTextContent("Player A"));
  fireEvent.click(screen.getByText("Open player"));
  await screen.findByText("Try again");
  await act(async () => {});
  expect(gets).toBe(2); expect(detailGets).toBe(2);
  expect(screen.queryByTestId("full-popup")).toBeNull();
});

it("a failed detail leaves the board usable and provides a retry", async () => {
  let count = 0;
  const fetcher = vi.fn(async (url) => {
    if (!url.includes("/players/key-a")) return ok(board());
    if (++count === 1) return { ok: false, status: 403, json: async () => ({ error: "forbidden" }) };
    return full();
  });
  vi.stubGlobal("fetch", fetcher);
  render(<AppShell authenticated><Controls /></AppShell>);
  await waitFor(() => expect(screen.getByTestId("shell-row")).toHaveTextContent("Player A"));
  fireEvent.click(screen.getByText("Open player"));
  fireEvent.click(await screen.findByText("Try again"));
  expect(await screen.findByTestId("full-popup")).toHaveTextContent("Full source details");
  expect(count).toBe(2);
});

it("expansion waits for full source audit before displaying source coverage", async () => {
  let resolveDetail;
  const fetcher = vi.fn(() => new Promise((resolve) => { resolveDetail = resolve; }));
  vi.stubGlobal("fetch", fetcher);
  const contract = board();
  const row = buildRows(contract)[0];
  render(<SourceAuditPanel row={row} rawData={contract} val={9500} edge={{}} confExplain="" />);
  expect(screen.getByText("Loading source details…")).toBeInTheDocument();
  expect(screen.queryByText("Source Audit: Player A")).toBeNull();
  await act(async () => resolveDetail(full()));
  expect(await screen.findByText("Source Audit: Player A")).toBeInTheDocument();
  expect(screen.getByText("Full source details")).toBeInTheDocument();
});
