// /trades — a failed contract load is a CLASSIFIED failure with a retry
// (X-FRONTEND-FAILURE-SW).  It used to print the raw error string with
// nothing to do about it.  "Try again" is AppShell's `retry`, the refetch
// useDynastyData exposes (pinned in contract-fetch-resilience.test.jsx).

import { describe, expect, it, vi } from "vitest";
import { fireEvent, render, screen } from "@testing-library/react";

const mockUseApp = vi.fn();

vi.mock("@/components/AppShell", () => ({ useApp: () => mockUseApp() }));
vi.mock("@/components/useSettings", () => ({ useSettings: () => ({ settings: {} }) }));
vi.mock("@/components/useRankHistory", () => ({ useRankHistory: () => ({ history: null }) }));

import TradesPage from "@/app/trades/page";

describe("/trades contract failure", () => {
  it("a degraded backend reads as degraded, and Try again re-invokes the fetch", () => {
    const retry = vi.fn();
    mockUseApp.mockReturnValue({
      rows: [],
      rawData: null,
      loading: false,
      error: "The rankings board is not loaded on the server yet.",
      failure: {
        kind: "degraded",
        code: "data_not_ready",
        message: "The rankings board is not loaded on the server yet.",
        retryable: true,
      },
      retry,
    });
    render(<TradesPage />);
    expect(screen.getByText("Serving degraded — trade data")).toBeInTheDocument();
    expect(screen.getByTestId("failure-code").textContent).toBe("(data_not_ready)");
    fireEvent.click(screen.getByRole("button", { name: "Try again" }));
    expect(retry).toHaveBeenCalledTimes(1);
  });

  it("a 403 offers no retry — retrying cannot change a permissions answer", () => {
    mockUseApp.mockReturnValue({
      rows: [],
      rawData: null,
      loading: false,
      error: "This account cannot see this data.",
      failure: { kind: "forbidden", code: "", message: "This account cannot see this data.", retryable: false },
      retry: vi.fn(),
    });
    render(<TradesPage />);
    expect(screen.getByText("Not available to this account — trade data")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Try again" })).toBeNull();
  });
});
