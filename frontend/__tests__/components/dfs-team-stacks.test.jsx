import React, { useState } from "react";
import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it } from "vitest";
import TeamStacks from "@/components/dfs/TeamStacks";

const ATHLETES = [
  { player_id: "1", name: "A C", positions: ["C"], team: "AAA" },
  { player_id: "2", name: "B W", positions: ["W"], team: "AAA" },
  { player_id: "3", name: "C G", positions: ["G"], team: "BBB" },
];

function Harness({ singleGame = false, onValue }) {
  const [stacks, setStacks] = useState([]);
  onValue?.(stacks);
  return <TeamStacks stacks={stacks} onChange={setStacks} athletes={ATHLETES} slotCount={9} singleGame={singleGame} />;
}

afterEach(cleanup);

describe("TeamStacks", () => {
  it("adds a position-filtered stack as a validated entry and can remove it", () => {
    let value = [];
    render(<Harness onValue={(v) => (value = v)} />);
    fireEvent.click(screen.getByLabelText("C"));
    fireEvent.click(screen.getByLabelText("W"));
    fireEvent.click(screen.getByRole("button", { name: "Add stack" }));
    expect(value).toEqual([{ label: "3-player team stack (C/W)", scope: "team", size: 3, count: 1, positions: ["C", "W"] }]);
    fireEvent.click(screen.getByRole("button", { name: "Remove 3-player team stack (C/W)" }));
    expect(value).toEqual([]);
  });

  it("refuses a stack that cannot fit the lineup and says why", () => {
    render(<Harness />);
    fireEvent.change(screen.getByLabelText("Players per stack"), { target: { value: "5" } });
    fireEvent.change(screen.getByLabelText("Number of stacks"), { target: { value: "2" } });
    fireEvent.click(screen.getByRole("button", { name: "Add stack" }));
    expect(screen.getByText(/more than a 9-player lineup/)).toBeTruthy();
  });

  it("offers neither game scope nor a position filter on a single-game slate", () => {
    render(<Harness singleGame />);
    expect(screen.queryByText("Game")).toBeNull();
    expect(screen.queryByLabelText("C")).toBeNull();
  });
});
