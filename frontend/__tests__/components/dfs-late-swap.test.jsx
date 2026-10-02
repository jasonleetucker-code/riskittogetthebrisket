import React from "react";
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import LateSwap from "@/components/dfs/LateSwap";

const PLAN = {
  asOf: "2026-10-04T18:00:00+00:00",
  clockSource: "owner_supplied",
  methodNote: "Each entry is re-optimized on its own.",
  playersByLockState: { locked: 28, open: 56, unknown: 0 },
  counts: { swap_recommended: 1, entry_unresolved: 1 },
  submitted: false,
  entries: [
    { entryId: "7001", status: "swap_recommended", changes: [{ slot: "FLEX", out: "1", in: "2" }], openSlotGain: 4.5, reason: "higher projected points in the open slots" },
    { entryId: "7002", status: "entry_unresolved", changes: [], openSlotGain: null },
  ],
};

// jsdom's File has no text(); stub it as the entries-export test does.
function csvFile(text) {
  const f = new File([text], "DKEntries.csv", { type: "text/csv" });
  f.text = async () => text;
  return f;
}

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});

describe("LateSwap", () => {
  it("plans from an entry file, names the swap, and never claims to submit", async () => {
    const fetchMock = vi.fn(async () => ({ ok: true, status: 200, json: async () => PLAN }));
    vi.stubGlobal("fetch", fetchMock);
    render(<LateSwap snapshotId="snap_1" athletes={[{ player_id: "1", name: "Old WR" }, { player_id: "2", name: "New WR" }]} />);
    const file = csvFile("Entry ID,Contest Name\n");
    fireEvent.change(screen.getByLabelText("Entry file (from the platform)"), { target: { files: [file] } });
    await waitFor(() => expect(screen.getByRole("button", { name: "Plan late swap" }).disabled).toBe(false));
    fireEvent.click(screen.getByRole("button", { name: "Plan late swap" }));
    await screen.findByText("FLEX: Old WR → New WR");
    expect(screen.getByText("+4.50")).toBeTruthy();
    expect(screen.getByText("Entry unreadable — untouched")).toBeTruthy();
    expect(screen.getByText(/your chosen time/)).toBeTruthy();
    const sent = JSON.parse(fetchMock.mock.calls[0][1].body);
    expect(sent).toEqual({ snapshotId: "snap_1", entriesCsv: "Entry ID,Contest Name\n" }); // blank clock = server's
    expect(screen.queryByText(/submitted to/i)).toBeNull();
  });

  it("surfaces a server refusal instead of an empty plan", async () => {
    vi.stubGlobal("fetch", vi.fn(async () => ({ ok: false, status: 422, json: async () => ({ error: "ENTRY_FILE_UNRECOGNISED", message: "This does not match the expected entry-file layout." }) })));
    render(<LateSwap snapshotId="snap_1" athletes={[]} />);
    const file = csvFile("x");
    fireEvent.change(screen.getByLabelText("Entry file (from the platform)"), { target: { files: [file] } });
    await waitFor(() => expect(screen.getByRole("button", { name: "Plan late swap" }).disabled).toBe(false));
    fireEvent.click(screen.getByRole("button", { name: "Plan late swap" }));
    await screen.findByText("This does not match the expected entry-file layout.");
  });
});
