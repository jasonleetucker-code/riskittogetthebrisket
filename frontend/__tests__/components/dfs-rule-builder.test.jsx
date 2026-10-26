import React from "react";
import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import RuleBuilder from "@/components/dfs/RuleBuilder";
import { rulesToConstraints } from "@/lib/dfs";
import { ruleError } from "@/lib/dfs-rules";

afterEach(cleanup);

const ATHLETES = [
  { player_id: "1", name: "Syn QB", positions: ["QB"], team: "AAA" },
  { player_id: "2", name: "Syn WR", positions: ["WR"], team: "AAA" },
  { player_id: "3", name: "Syn TE", positions: ["TE"], team: "BBB" },
];

describe("rule helpers", () => {
  it("maps every rule type to the backend's hard constraints", () => {
    const out = rulesToConstraints([
      { type: "at_least", n: "1", players: ["1", "2"], label: "a" },
      { type: "at_most", n: "1", players: ["2", "3"], label: "b" },
      { type: "exactly", n: "2", players: ["1", "2", "3"], label: "c" },
      { type: "if_then", when: ["1"], then: ["2"], label: "d" },
      { type: "if_not", when: ["1"], then: ["3"], label: "e" },
      { type: "if_then_n", n: "2", when: ["1"], then: ["2", "3"], label: "f" },
    ]);
    expect(out.groups).toEqual([
      { label: "a", players: ["1", "2"], min: 1 },
      { label: "b", players: ["2", "3"], max: 1 },
      { label: "c", players: ["1", "2", "3"], min: 2, max: 2 },
    ]);
    expect(out.conditionals).toEqual([
      { label: "d", when: ["1"], then: ["2"], thenMin: 1 },
      { label: "e", when: ["1"], then: ["3"], thenMax: 0 },
      { label: "f", when: ["1"], then: ["2", "3"], thenMin: 2 },
    ]);
  });

  it("refuses incomplete or self-referential rules", () => {
    expect(ruleError({ type: "at_least", n: "x", players: ["1"] })).toBeTruthy();
    expect(ruleError({ type: "at_least", n: "1", players: [] })).toBeTruthy();
    expect(ruleError({ type: "if_then", when: ["1"], then: [] })).toBeTruthy();
    expect(ruleError({ type: "if_not", when: ["1"], then: ["1"] })).toBeTruthy();
    expect(ruleError({ type: "if_then", when: ["1"], then: ["2"] })).toBe(null);
  });
});

describe("RuleBuilder", () => {
  it("adds an if-then-not rule from keyboard-native pickers and can remove it", () => {
    const onChange = vi.fn();
    const { rerender } = render(<RuleBuilder athletes={ATHLETES} rules={[]} onChange={onChange} />);
    fireEvent.change(screen.getByLabelText("Rule"), { target: { value: "if_not" } });
    const a = screen.getByLabelText("A (if any of these)");
    a.options[0].selected = true;
    fireEvent.change(a);
    const b = screen.getByLabelText("B");
    b.options[2].selected = true;
    fireEvent.change(b);
    fireEvent.click(screen.getByRole("button", { name: "Add rule" }));
    const added = onChange.mock.calls.at(-1)[0];
    expect(added).toHaveLength(1);
    expect(added[0]).toMatchObject({ type: "if_not", when: ["1"], then: ["3"] });
    rerender(<RuleBuilder athletes={ATHLETES} rules={added} onChange={onChange} />);
    expect(screen.getByText(/If Syn QB, then not Syn TE/)).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: /Remove rule: If Syn QB, then not Syn TE/ }));
    expect(onChange.mock.calls.at(-1)[0]).toEqual([]);
  });

  it("explains why a rule was not added", () => {
    render(<RuleBuilder athletes={ATHLETES} rules={[]} onChange={() => {}} />);
    fireEvent.click(screen.getByRole("button", { name: "Add rule" }));
    expect(screen.getByText("Choose at least one player.")).toBeInTheDocument();
  });
});
