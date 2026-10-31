// Owner recovery regression: auction users and the site owner have distinct
// identity paths. A Home Screen launch must not funnel the owner into a
// password form that their bridge account cannot authenticate with.
import { afterEach, describe, expect, it, vi } from "vitest";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";

vi.mock("@/lib/auction-client", () => ({
  auctionFetch: vi.fn(),
  AuctionRequestError: class AuctionRequestError extends Error {},
}));

import AuctionLobbyPage from "@/app/auction/page.jsx";
import { auctionFetch } from "@/lib/auction-client";

afterEach(() => {
  vi.clearAllMocks();
});

describe("auction login routes", () => {
  it("prominently routes a signed-out site owner through normal Chase Upside login", async () => {
    vi.mocked(auctionFetch).mockResolvedValue({ user: null, siteOwnerAvailable: false, rooms: [] });
    render(<AuctionLobbyPage />);

    const ownerLink = await screen.findByRole("link", { name: "Sign in to Chase Upside" });
    expect(ownerLink.getAttribute("href")).toBe("/login?next=%2Fauction");
    expect(screen.getByText("Site owner / commissioner")).toBeTruthy();
    expect(screen.getByText("Invited league member sign-in")).toBeTruthy();
    expect(screen.getByText(/Site-owner accounts do not have a separate auction password/)).toBeTruthy();
    expect(screen.getByRole("button", { name: "Sign in as league member" })).toBeTruthy();
  });

  it("uses the site-owner bridge instead of the member password endpoint when already site-authenticated", async () => {
    vi.mocked(auctionFetch).mockImplementation(async (path) => {
      if (path === "/auth/me") return { user: null, siteOwnerAvailable: true, rooms: [] };
      if (path === "/auth/site-owner") return { user: { handle: "commissioner", isSiteAdmin: true } };
      throw new Error("Unexpected auction endpoint");
    });
    render(<AuctionLobbyPage />);

    fireEvent.click(await screen.findByRole("button", { name: "Continue as site owner" }));
    await waitFor(() => {
      expect(auctionFetch).toHaveBeenCalledWith("/auth/site-owner", { method: "POST", body: {} });
    });
    expect(auctionFetch).not.toHaveBeenCalledWith("/auth/login", expect.anything());
  });
});
