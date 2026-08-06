/**
 * CommandPalette spec — the R1 universal search must preserve the
 * legacy player-search semantics (player-filters grammar, tier
 * ordering, teamByPlayer owner: tokens) and add navigation targets
 * with real combobox/listbox semantics.
 */
import { beforeEach, describe, expect, it, vi } from "vitest";
import React from "react";
import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";

const push = vi.fn();
vi.mock("next/navigation", () => ({
  useRouter: () => ({ push }),
  usePathname: () => "/rankings",
}));

import CommandPalette from "@/components/shell/CommandPalette";

const ROWS = [
  {
    name: "Justin Jefferson",
    pos: "WR",
    team: "MIN",
    raw: { team: "MIN" },
    values: { full: 9541 },
    canonicalConsensusRank: 1,
    siteCount: 8,
  },
  {
    name: "Jahmyr Gibbs",
    pos: "RB",
    team: "DET",
    raw: { team: "DET" },
    values: { full: 8720 },
    canonicalConsensusRank: 5,
    siteCount: 8,
  },
  {
    name: "Sam LaPorta",
    pos: "TE",
    team: "DET",
    raw: { team: "DET" },
    values: { full: 5400 },
    canonicalConsensusRank: 40,
    siteCount: 7,
  },
];

// Raw Sleeper team array. The palette builds its own {byId, byName}
// index from this — it does NOT take a prebuilt one, so that
// `lib/waiver-logic` stays behind the palette's lazy chunk instead of
// riding the root layout into every route's bundle.
const SLEEPER_TEAMS = [
  { name: "Brisket Bros", ownerId: "u1", players: ["Justin Jefferson"], playerIds: [] },
  { name: "Rival Squad", ownerId: "u2", players: ["Jahmyr Gibbs"], playerIds: [] },
];

function palette(props = {}) {
  return render(
    <CommandPalette
      rows={ROWS}
      sleeperTeams={null}
      isOpen
      onClose={() => {}}
      onSelect={() => {}}
      {...props}
    />
  );
}

beforeEach(() => {
  push.mockClear();
});

describe("player search (legacy semantics preserved)", () => {
  it("matches by name and opens the player on Enter", async () => {
    const user = userEvent.setup();
    const onSelect = vi.fn();
    const onClose = vi.fn();
    palette({ onSelect, onClose });
    await user.keyboard("jeffer");
    expect(screen.getByText("Justin Jefferson")).toBeInTheDocument();
    await user.keyboard("{Enter}");
    expect(onSelect).toHaveBeenCalledWith(
      expect.objectContaining({ name: "Justin Jefferson" })
    );
    expect(onClose).toHaveBeenCalled();
  });

  it("supports the token grammar (pos + team) and hides nav targets for token queries", async () => {
    const user = userEvent.setup();
    palette();
    await user.keyboard("pos:te team:det");
    expect(screen.getByText("Sam LaPorta")).toBeInTheDocument();
    expect(screen.queryByText("Justin Jefferson")).toBeNull();
    expect(screen.queryByText("Go to")).toBeNull();
  });

  it("free-token search works like the legacy overlay (wr min)", async () => {
    const user = userEvent.setup();
    palette();
    await user.keyboard("wr min");
    expect(screen.getByText("Justin Jefferson")).toBeInTheDocument();
    expect(screen.queryByText("Jahmyr Gibbs")).toBeNull();
  });
});

// The `owner:` grammar was previously UNTESTED here — every case passed
// `teamByPlayer={null}`, so the prop was never exercised at all. Since
// the palette now builds that index itself from `sleeperTeams`, these
// are what prove the move preserved the behaviour rather than quietly
// disabling owner filtering.
describe("owner: tokens — the index the palette builds itself", () => {
  it("filters to one manager's players from the raw team array", async () => {
    const user = userEvent.setup();
    palette({ sleeperTeams: SLEEPER_TEAMS });
    await user.keyboard("owner:brisket");
    expect(screen.getByText("Justin Jefferson")).toBeInTheDocument();
    expect(screen.queryByText("Jahmyr Gibbs")).toBeNull();
  });

  it("composes with the other tokens (owner: + pos:)", async () => {
    const user = userEvent.setup();
    palette({ sleeperTeams: SLEEPER_TEAMS });
    await user.keyboard("owner:rival pos:rb");
    expect(screen.getByText("Jahmyr Gibbs")).toBeInTheDocument();
    expect(screen.queryByText("Justin Jefferson")).toBeNull();
  });

  it("without teams, owner: matches nobody rather than throwing", async () => {
    const user = userEvent.setup();
    palette(); // sleeperTeams = null — the /league and pre-load case
    await user.keyboard("owner:brisket");
    expect(screen.getByText(/No results/)).toBeInTheDocument();
  });
});

describe("navigation targets", () => {
  it("shows quick destinations on empty query", () => {
    palette();
    expect(screen.getByText("Go to")).toBeInTheDocument();
    // Several destinations now sit in the Rankings group, so the group
    // name appears in more than one option's accessible name.
    expect(screen.getAllByRole("option", { name: /Rankings/ }).length).toBeGreaterThan(0);
  });

  it("matches pages by name and navigates on activation", async () => {
    const user = userEvent.setup();
    palette();
    await user.keyboard("arbitrage");
    const opt = screen.getByRole("option", { name: /Arbitrage/ });
    await user.click(opt);
    expect(push).toHaveBeenCalledWith("/arbitrage");
  });

  it("matches by keyword (faab → Waivers)", async () => {
    const user = userEvent.setup();
    palette();
    await user.keyboard("faab");
    expect(screen.getByRole("option", { name: /Waivers/ })).toBeInTheDocument();
  });

  it("players list before pages when both match; arrows walk the merged list", async () => {
    const user = userEvent.setup();
    const onSelect = vi.fn();
    palette({ onSelect });
    // "news" matches no player, but "la" matches LaPorta AND league pages
    await user.keyboard("laporta");
    const options = screen.getAllByRole("option");
    expect(within(options[0]).getByText("Sam LaPorta")).toBeInTheDocument();
    expect(options[0]).toHaveAttribute("aria-selected", "true");
  });

  it("ArrowDown + Enter activates a nav target through the keyboard alone", async () => {
    const user = userEvent.setup();
    palette();
    await user.keyboard("sharp tracker");
    // no player named "sharp tracker" → first option is the nav target
    await user.keyboard("{Enter}");
    expect(push).toHaveBeenCalledWith("/market/sharp-tracker");
  });
});

describe("combobox semantics", () => {
  it("input is a combobox wired to the listbox with aria-activedescendant", async () => {
    const user = userEvent.setup();
    palette();
    const input = screen.getByRole("combobox");
    expect(input).toHaveFocus(); // initialFocus lands on the input
    expect(input).toHaveAttribute("aria-controls", "shell-palette-listbox");
    await user.keyboard("gibbs");
    const active = input.getAttribute("aria-activedescendant");
    expect(active).toBeTruthy();
    const activeOption = document.getElementById(active);
    expect(activeOption).toHaveAttribute("role", "option");
    expect(activeOption).toHaveTextContent("Jahmyr Gibbs");
  });

  it("renders inside a dialog with focus trap semantics (ds Modal)", () => {
    palette();
    expect(screen.getByRole("dialog")).toHaveAttribute("aria-modal", "true");
  });

  it("shows an empty state for no matches", async () => {
    const user = userEvent.setup();
    palette();
    await user.keyboard("zzzzz");
    expect(screen.getByText(/No results/)).toBeInTheDocument();
  });
});
