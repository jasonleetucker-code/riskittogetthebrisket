import React from "react";
import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import EntriesExport from "@/components/dfs/EntriesExport";

beforeEach(() => {
  vi.stubGlobal("fetch", vi.fn());
  globalThis.URL.createObjectURL = vi.fn(() => "blob:x");
  globalThis.URL.revokeObjectURL = vi.fn();
});
afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});

function file(text) {
  const f = new File([text], "DKEntries.csv", { type: "text/csv" });
  f.text = async () => text;
  return f;
}

describe("EntriesExport", () => {
  it("reports assigned and untouched entries and states the layout is unverified", async () => {
    fetch.mockResolvedValue({
      ok: true,
      headers: new Headers({
        "x-dfs-entries-assigned": "2",
        "x-dfs-entries-untouched": "1",
        "content-disposition": 'attachment; filename="e.csv"',
      }),
      blob: async () => new Blob(["x"]),
    });
    render(<EntriesExport buildId="build_1" />);
    fireEvent.change(screen.getByLabelText(/Fill my existing entries/), { target: { files: [file("Entry ID,...")] } });
    expect(await screen.findByText(/Filled 2 entries\. 1 left untouched/)).toBeInTheDocument();
    expect(screen.getByText(/not yet verified against an official template/)).toBeInTheDocument();
    expect(JSON.parse(fetch.mock.calls[0][1].body).entriesCsv).toBe("Entry ID,...");
  });

  it("shows the server's refusal", async () => {
    fetch.mockResolvedValue({
      ok: false,
      json: async () => ({ error: "ENTRY_FILE_UNRECOGNISED", message: "This does not match the expected entry-file layout." }),
    });
    render(<EntriesExport buildId="build_1" />);
    fireEvent.change(screen.getByLabelText(/Fill my existing entries/), { target: { files: [file("x")] } });
    expect(await screen.findByText("This does not match the expected entry-file layout.")).toBeInTheDocument();
  });
});
