// PlayerPopup behavioral tests.
//
// PlayerPopup is wired through five context hooks + a network-fetching
// child chart. We mock the hooks to controlled defaults and stub the
// chart so the test exercises PlayerPopup's own behavior (render,
// close affordances, add-to-trade) and nothing downstream.
import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, fireEvent } from "@testing-library/react";
import { makePlayer } from "../fixtures/players";

vi.mock("@/components/AppShell", () => ({
  useApp: () => ({ rows: [], rawData: {} }),
}));
vi.mock("@/components/useTeam", () => ({
  useTeam: () => ({ selectedTeam: null }),
}));
vi.mock("@/components/useTerminal", () => ({
  useTerminal: () => ({ signals: [] }),
}));
vi.mock("@/components/useUserState", () => ({
  useUserState: () => ({
    state: {},
    toggleWatchlist: vi.fn(),
    serverBacked: false,
  }),
}));
vi.mock("@/components/useSettings", () => ({
  useSettings: () => ({ settings: {} }),
}));
// League context for the Sharp Tracker intel section — a stable key
// keeps the intel fetch deterministic in these tests.
vi.mock("@/components/useLeague", () => ({
  useLeague: () => ({ selectedLeagueKey: "dynasty_main", loading: false }),
}));
// Child chart fetches /api/data/player-source-history — stub it out.
vi.mock("@/components/PlayerRankHistoryChart", () => ({
  default: () => <div data-testid="rank-history-stub" />,
}));
// next/link needs the Next runtime; a plain anchor is enough here — but
// it must forward the rest of its props, or aria-labels set on a linked
// control silently vanish and the test asserts against a name the real
// component does not have.
vi.mock("next/link", () => ({
  default: ({ children, href, ...rest }) => (
    <a href={href} {...rest}>
      {children}
    </a>
  ),
}));

import PlayerPopup from "@/components/PlayerPopup";

beforeEach(() => {
  // PlayerPopup loads ROS values via fetch in an effect.
  vi.stubGlobal(
    "fetch",
    vi.fn().mockResolvedValue({ ok: true, json: async () => ({}) }),
  );
});

function renderPopup(extra = {}) {
  const onClose = vi.fn();
  const onAddToTrade = vi.fn();
  const row = makePlayer();
  render(
    <PlayerPopup
      row={row}
      siteKeys={["ktc", "fantasycalc"]}
      onClose={onClose}
      onAddToTrade={onAddToTrade}
      {...extra}
    />,
  );
  return { onClose, onAddToTrade, row };
}

describe("PlayerPopup", () => {
  it("renders the player and a close control", () => {
    const { row } = renderPopup();
    expect(screen.getAllByText(new RegExp(row.name, "i")).length).toBeGreaterThan(0);
    expect(
      screen.getByRole("button", { name: /close player details/i }),
    ).toBeInTheDocument();
  });

  it("closes on Escape", () => {
    const { onClose } = renderPopup();
    fireEvent.keyDown(document, { key: "Escape" });
    expect(onClose).toHaveBeenCalledTimes(1);
  });

  it("closes when the close button is clicked", () => {
    const { onClose } = renderPopup();
    fireEvent.click(
      screen.getByRole("button", { name: /close player details/i }),
    );
    expect(onClose).toHaveBeenCalled();
  });

  it("adds to trade then closes", () => {
    const { onClose, onAddToTrade, row } = renderPopup();
    fireEvent.click(
      screen.getByRole("button", { name: new RegExp(`add ${row.name} to trade`, "i") }),
    );
    expect(onAddToTrade).toHaveBeenCalledWith(row);
    expect(onClose).toHaveBeenCalled();
  });

  // /players/compare is URL-driven but nothing in the product linked to
  // it — it was a command-palette-only destination, so the only way to
  // reach it was to already know it existed.  The popup is where a user
  // is looking at one player and wondering how he stacks up.
  it("offers a Compare link seeded with this player", () => {
    const { row } = renderPopup();
    const link = screen.getByRole("link", {
      name: new RegExp(`compare ${row.name}`, "i"),
    });
    expect(link).toHaveAttribute(
      "href",
      `/players/compare?p1=${encodeURIComponent(row.name)}`,
    );
  });

  it("closes the popup when Compare is followed", () => {
    // Otherwise the overlay stays mounted over the page just navigated to.
    const { onClose } = renderPopup();
    fireEvent.click(screen.getByRole("link", { name: /compare/i }));
    expect(onClose).toHaveBeenCalled();
  });
});
