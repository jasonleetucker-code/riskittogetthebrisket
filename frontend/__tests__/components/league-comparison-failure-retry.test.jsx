// /league-comparison — a failed comparison fetch is a CLASSIFIED failure with
// a retry (X-FRONTEND-FAILURE-SW).  It used to print the thrown message (the
// body's `detail`, or "HTTP 503") as a paragraph.
import { afterEach, describe, expect, it, vi } from "vitest";
import React from "react";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";

vi.mock("@/components/ui/SubNav", () => ({ default: () => null }));

import LeagueComparisonPage from "@/app/league-comparison/page";

afterEach(() => vi.unstubAllGlobals());

describe("/league-comparison failure", () => {
  it("a 503 from the backend reads as degraded, and Try again re-invokes the fetch", async () => {
    const fetchMock = vi.fn(async () => ({
      ok: false,
      status: 503,
      json: async () => ({ error: "data_not_ready" }),
    }));
    vi.stubGlobal("fetch", fetchMock);
    render(<LeagueComparisonPage />);
    expect(await screen.findByText("Serving degraded — league comparison")).toBeInTheDocument();
    expect(fetchMock).toHaveBeenCalledTimes(1);
    fireEvent.click(screen.getByRole("button", { name: "Try again" }));
    await waitFor(() => expect(fetchMock).toHaveBeenCalledTimes(2));
    expect(fetchMock.mock.calls[1][0]).toBe("/api/league-comparison");
  });

  it("no response at all reads as offline, never as the browser's raw TypeError", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn(async () => {
        throw new TypeError("Failed to fetch");
      }),
    );
    render(<LeagueComparisonPage />);
    expect(await screen.findByText("Could not reach the server — league comparison")).toBeInTheDocument();
    expect(screen.queryByText("Failed to fetch")).toBeNull();
  });
});
