import React from "react";
import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import ResultsImport from "@/components/dfs/ResultsImport";

function csvFile(text) {
  const f = new File([text], "contest-standings.csv", { type: "text/csv" });
  f.text = async () => text;
  return f;
}

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});

const RESULT = {
  evaluation: {
    ownership: { n: 40, bias: 2.1, mae: 3.4, rmse: 4.2 },
    projection: null,
    ownershipBands: [{ band: "20–30%", n: 6, meanForecast: 24.1, meanRealized: 19.8 }],
    notInResults: 3,
    note: "Evaluation only: nothing is reweighted or promoted.",
  },
  quarantined: [{ row: 5, name: "X", reason: "ambiguous_identity" }],
  duplication: { lineupsCompared: 900, distinctLineups: 850, entriesInDuplicatedLineups: 90, maxCopies: 7, histogram: {} },
  field: { unresolvedLineups: 12 },
};

describe("ResultsImport", () => {
  it("shows the evaluation the server computed, including what it left out", async () => {
    const fetchMock = vi.fn(async () => ({ ok: true, status: 201, json: async () => RESULT }));
    vi.stubGlobal("fetch", fetchMock);
    render(<ResultsImport snapshotId="snap_1" />);
    fireEvent.change(screen.getByLabelText("Contest standings file (from the platform)"), {
      target: { files: [csvFile("Rank,EntryId\n")] },
    });
    await screen.findByText(/40 players · average miss 3.4 pts · bias \+2.1 pts \(forecast too high\)/);
    expect(screen.getByText(/Projections: not available/)).toBeTruthy();
    expect(screen.getByText("20–30%")).toBeTruthy();
    expect(screen.getByText(/3 player\(s\) you forecast are not in the results file/)).toBeTruthy();
    expect(screen.getByText(/1 results row\(s\) could not be matched/)).toBeTruthy();
    expect(screen.getByText(/12 lineup\(s\) could not be read/)).toBeTruthy();
    expect(JSON.parse(fetchMock.mock.calls[0][1].body)).toEqual({ snapshotId: "snap_1", standingsCsv: "Rank,EntryId\n" });
  });

  it("surfaces a refusal", async () => {
    vi.stubGlobal("fetch", vi.fn(async () => ({ ok: false, status: 422, json: async () => ({ error: "NO_PLAYERS_MATCHED", message: "No player in the results file matched this slate." }) })));
    render(<ResultsImport snapshotId="snap_1" />);
    fireEvent.change(screen.getByLabelText("Contest standings file (from the platform)"), { target: { files: [csvFile("x")] } });
    await screen.findByText("No player in the results file matched this slate.");
  });
});
