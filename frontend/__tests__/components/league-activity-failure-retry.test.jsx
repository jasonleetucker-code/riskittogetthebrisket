// /league/activity — a failed public-feed fetch is a CLASSIFIED failure with a
// retry (X-FRONTEND-FAILURE-SW).  It used to print the thrown message
// ("Public league fetch failed (503) for /api/public/league/activity") in an
// EmptyState, with no way to try again short of reloading the page.
import { afterEach, describe, expect, it, vi } from "vitest";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";

const mockFetchPublicSection = vi.fn();

vi.mock("@/components/useUserState", () => ({ useUserState: () => ({ state: {} }) }));
vi.mock("@/components/useNews", () => ({
  useNews: () => ({ items: [], unavailable: false, reason: null }),
}));
vi.mock("@/lib/public-league-data", () => ({
  fetchPublicSection: (...args) => mockFetchPublicSection(...args),
}));

import ActivityClient, { activityFailure } from "@/app/league/activity/ActivityClient";

afterEach(() => mockFetchPublicSection.mockReset());

describe("/league/activity failure", () => {
  it("a 503 reads as unavailable, and Try again re-invokes the feed fetch", async () => {
    mockFetchPublicSection
      .mockRejectedValueOnce(
        new Error("Public league fetch failed (503) for /api/public/league/activity"),
      )
      .mockResolvedValueOnce({ data: { feed: [] } });
    render(<ActivityClient />);
    expect(await screen.findByText("Service unavailable — league activity")).toBeInTheDocument();
    expect(screen.queryByText(/Public league fetch failed/)).toBeNull();
    fireEvent.click(screen.getByRole("button", { name: "Try again" }));
    await waitFor(() => expect(mockFetchPublicSection).toHaveBeenCalledTimes(2));
    expect(mockFetchPublicSection).toHaveBeenLastCalledWith("activity");
    await waitFor(() =>
      expect(screen.queryByText("Service unavailable — league activity")).toBeNull(),
    );
  });

  it("classifies each way the public reader can fail", () => {
    expect(activityFailure(new TypeError("Failed to fetch")).kind).toBe("offline");
    expect(
      activityFailure(new DOMException("Public league request timed out.", "TimeoutError")).kind,
    ).toBe("timeout");
    expect(
      activityFailure(new Error("Public league fetch failed (404) for /api/public/league/activity"))
        .kind,
    ).toBe("error");
    expect(activityFailure(new SyntaxError("Unexpected token <")).kind).toBe("no_data");
    // An unknown exception is reported plainly, never guessed into a cause.
    const unknown = activityFailure(new Error("boom"));
    expect(unknown.kind).toBe("error");
    expect(unknown.message).toBe("Could not load league activity.");
  });
});
