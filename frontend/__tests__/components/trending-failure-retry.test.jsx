// /trending — a failed contract load is a CLASSIFIED failure with a retry
// (X-FRONTEND-FAILURE-SW), not an EmptyState printing the raw error string.
// "Try again" is AppShell's `retry`, the refetch useDynastyData exposes
// (pinned in contract-fetch-resilience.test.jsx).
import { describe, expect, it, vi } from "vitest";
import { fireEvent, render, screen } from "@testing-library/react";

const retry = vi.fn();
vi.mock("@/components/AppShell", () => ({
  useApp: () => ({
    rows: [],
    loading: false,
    error: "Request timed out",
    failure: {
      kind: "timeout",
      code: "client_timeout",
      message: "The server took too long to answer.",
      retryable: true,
    },
    retry,
    openPlayerPopup: () => {},
  }),
}));

import TrendingPage from "@/app/trending/page.jsx";

describe("/trending contract failure", () => {
  it("renders the classified failure, and Try again re-invokes the contract fetch", () => {
    render(<TrendingPage />);
    expect(screen.getByText("Request timed out — rank history")).toBeInTheDocument();
    expect(screen.queryByText("Couldn't load data")).toBeNull();
    fireEvent.click(screen.getByRole("button", { name: "Try again" }));
    expect(retry).toHaveBeenCalledTimes(1);
  });
});
