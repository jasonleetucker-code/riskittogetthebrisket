import React from "react";
import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import SourcePulls from "@/components/dfs/SourcePulls";

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});

describe("SourcePulls", () => {
  it("pulls on request and says what was matched and that the owner's projections are untouched", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn(async () => ({
        ok: true,
        status: 200,
        json: async () => ({ matched: 80, slateAthletes: 84, rows: 435, quarantined: [{}, {}], fetchedAt: "2026-09-30T20:20:00Z", fromCache: false }),
      })),
    );
    render(<SourcePulls snapshotId="s1" sport="nfl" />);
    fireEvent.click(screen.getByRole("button", { name: /Pull Daily Fantasy Fuel/ }));
    await screen.findByText(/Matched 80 of 84 players/);
    expect(screen.getByText(/2 set aside as ambiguous or salary-mismatched/)).toBeTruthy();
    expect(screen.getByText(/your own projections are unchanged/)).toBeTruthy();
  });

  it("renders nothing for a sport the source does not cover", () => {
    const { container } = render(<SourcePulls snapshotId="s1" sport="mma" />);
    expect(container.innerHTML).toBe("");
  });
});
