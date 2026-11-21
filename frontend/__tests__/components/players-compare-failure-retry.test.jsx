// /players/compare — a failed contract load is a CLASSIFIED failure with a
// retry (X-FRONTEND-FAILURE-SW), not `EmptyState title="Error"` printing the
// raw error string.  "Try again" is useDynastyData's own `retry` (its refetch
// is pinned in contract-fetch-resilience.test.jsx).
import { describe, expect, it, vi } from "vitest";
import React from "react";
import { fireEvent, render, screen } from "@testing-library/react";

vi.mock("next/navigation", () => ({
  useRouter: () => ({ push: vi.fn(), replace: vi.fn() }),
  usePathname: () => "/players/compare",
  useSearchParams: () => new URLSearchParams(""),
}));

const retry = vi.fn();
vi.mock("@/components/useDynastyData", () => ({
  useDynastyData: () => ({
    loading: false,
    error: "Could not reach the server.",
    failure: { kind: "offline", code: "", message: "Could not reach the server.", retryable: true },
    rows: [],
    rawData: null,
    retry,
  }),
}));

import ComparePlayersPage from "@/app/players/compare/page";

describe("/players/compare contract failure", () => {
  it("renders the classified failure, and Try again re-invokes the contract fetch", async () => {
    render(<ComparePlayersPage />);
    expect(await screen.findByText("Could not reach the server — player pool")).toBeInTheDocument();
    expect(screen.queryByText("Error")).toBeNull();
    fireEvent.click(screen.getByRole("button", { name: "Try again" }));
    expect(retry).toHaveBeenCalledTimes(1);
  });
});
