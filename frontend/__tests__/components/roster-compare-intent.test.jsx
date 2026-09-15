import { afterEach, beforeEach, expect, it, vi } from "vitest";
import { cleanup, fireEvent, render, screen } from "@testing-library/react";
const mocks = vi.hoisted(() => ({ authenticated: true, dynasty: vi.fn(), user: vi.fn() }));
vi.mock("@/app/AppShellWrapper", () => ({ useAuthContext: () => ({ authenticated: mocks.authenticated }) }));
vi.mock("@/components/useDynastyData", () => ({ useDynastyData: (...args) => mocks.dynasty(...args) }));
vi.mock("@/components/useUserState", () => ({ useUserState: (...args) => mocks.user(...args) }));
import RosterComparePanel from "@/components/RosterComparePanel";
beforeEach(() => {
  mocks.authenticated = true;
  mocks.dynasty.mockReset().mockReturnValue({ loading: false, rows: [
    { name: "My QB", pos: "QB", rankDerivedValue: 1000 },
    { name: "Their LB", pos: "LB", rankDerivedValue: 500 },
  ], rawData: { sleeper: { teams: [
    { ownerId: "me", name: "My team", players: ["My QB"] },
    { ownerId: "them", name: "Their team", players: ["Their LB"] },
  ] } } });
  mocks.user.mockReset().mockReturnValue({ state: { selectedTeam: { ownerId: "me" } } });
});
afterEach(cleanup);
it.each([null, false, true])("does not mount private hooks before intent for auth %s", (authenticated) => {
  mocks.authenticated = authenticated;
  render(<RosterComparePanel ownerId="them" />);
  expect(mocks.dynasty).not.toHaveBeenCalled();
  expect(mocks.user).not.toHaveBeenCalled();
  expect(screen.queryByRole("table")).toBeNull();
});
it("opens exact canonical comparison only on authenticated intent and hides it", () => {
  render(<RosterComparePanel ownerId="them" />);
  fireEvent.click(screen.getByRole("button", { name: "Compare to my roster" }));
  expect(mocks.dynasty).toHaveBeenCalled();
  expect(mocks.user).toHaveBeenCalled();
  expect(screen.getByRole("columnheader", { name: "My team" })).toBeTruthy();
  expect(screen.getByRole("columnheader", { name: "Their team" })).toBeTruthy();
  expect(screen.getAllByText("1,000").length).toBeGreaterThan(0);
  expect(screen.getAllByText("500").length).toBeGreaterThan(0);
  fireEvent.click(screen.getByRole("button", { name: "Hide" }));
  expect(screen.queryByRole("table")).toBeNull();
  const calls = mocks.dynasty.mock.calls.length;
  expect(screen.getByRole("button", { name: "Compare to my roster" })).toBeTruthy();
  expect(mocks.dynasty).toHaveBeenCalledTimes(calls);
});
it("requires fresh intent after authentication loss or owner navigation", () => {
  const view = render(<RosterComparePanel ownerId="them" />);
  fireEvent.click(screen.getByRole("button", { name: "Compare to my roster" }));
  mocks.authenticated = false;
  view.rerender(<RosterComparePanel ownerId="them" />);
  expect(screen.queryByRole("table")).toBeNull();
  mocks.authenticated = true;
  view.rerender(<RosterComparePanel ownerId="them" />);
  expect(screen.getByRole("button", { name: "Compare to my roster" })).toBeTruthy();
  fireEvent.click(screen.getByRole("button", { name: "Compare to my roster" }));
  view.rerender(<RosterComparePanel ownerId="other" />);
  expect(screen.queryByRole("table")).toBeNull();
  expect(screen.getByRole("button", { name: "Compare to my roster" })).toBeTruthy();
});
it("can close while private data is loading", () => {
  mocks.dynasty.mockReturnValue({ loading: true, rows: [], rawData: null });
  render(<RosterComparePanel ownerId="them" />);
  fireEvent.click(screen.getByRole("button", { name: "Compare to my roster" }));
  expect(screen.getByText("Loading rosters…")).toBeTruthy();
  fireEvent.click(screen.getByRole("button", { name: "Hide" }));
  expect(screen.queryByText("Loading rosters…")).toBeNull();
});
it.each(["self", "no-team", "unavailable"])("preserves truthful %s disposition after intent", (kind) => {
  if (kind === "no-team") mocks.user.mockReturnValue({ state: {} });
  if (kind === "unavailable") mocks.dynasty.mockReturnValue({ loading: false, rows: [], rawData: null });
  render(<RosterComparePanel ownerId={kind === "self" ? "me" : "them"} />);
  fireEvent.click(screen.getByRole("button", { name: "Compare to my roster" }));
  expect(screen.getByText(kind === "self" ? /own franchise/ : kind === "no-team" ? /Pick your team/ : /comparison unavailable/)).toBeTruthy();
  expect(screen.queryByRole("table")).toBeNull();
});
