/**
 * Source Health → Freshness and weighting table.  The states that must not
 * blur: a real payload renders the backend's verdicts (including a
 * quarantined source), a 503 "no board loaded" is degraded with the
 * server's reason, and a 401 asks to sign in.
 */
import { afterEach, describe, expect, it, vi } from "vitest";
import React from "react";
import { render, screen, within } from "@testing-library/react";
import SourceWeightingTable from "@/components/SourceWeightingTable";
import fixture from "../fixtures/source-weighting-2026-10-13.json";

function respond(status, body) {
  globalThis.fetch = vi.fn(async () => ({
    ok: status >= 200 && status < 300,
    status,
    json: async () => body,
  }));
}

afterEach(() => {
  vi.restoreAllMocks();
});

describe("SourceWeightingTable", () => {
  it("renders the backend's freshness verdict per source", async () => {
    respond(200, fixture);
    render(<SourceWeightingTable />);

    const table = await screen.findByRole("table");
    expect(within(table).getByText("Quarantined")).toBeTruthy();
    expect(within(table).getAllByText("On schedule").length).toBeGreaterThan(0);
    expect(within(table).getByText("no vote")).toBeTruthy(); // KTC Market benchmark
    expect(globalThis.fetch).toHaveBeenCalledWith("/api/sources/weighting", expect.anything());

    const summary = screen.getByTestId("source-weighting-summary");
    expect(summary.textContent).toMatch(/1\s+quarantined/);
    expect(summary.textContent).toContain(fixture.asOf);
    expect(screen.getByText(/effective = base x freshness/)).toBeTruthy();
  });

  it("a board that is not loaded yet is degraded, with the server's words", async () => {
    respond(503, { error: "data_not_ready", message: "No board loaded yet." });
    render(<SourceWeightingTable />);
    expect(await screen.findByText(/No board loaded yet/)).toBeTruthy();
    expect(screen.queryByRole("table")).toBeNull();
  });

  it("signed out asks to sign in rather than showing an empty table", async () => {
    respond(401, { error: "unauthorized" });
    render(<SourceWeightingTable />);
    expect(await screen.findByText(/sign in/i)).toBeTruthy();
    expect(screen.queryByRole("table")).toBeNull();
  });
});
