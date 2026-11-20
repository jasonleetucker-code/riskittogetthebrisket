// /waivers — a failed contract load is a CLASSIFIED failure with a retry
// (X-FRONTEND-FAILURE-SW).  It used to print the raw error string in a red
// banner with nothing to do about it.  "Try again" is AppShell's `retry`, the
// refetch useDynastyData exposes (its own re-fetch is pinned in
// contract-fetch-resilience.test.jsx).

import { describe, expect, it, vi } from "vitest";
import { fireEvent, render, screen } from "@testing-library/react";

const retry = vi.fn();

vi.mock("@/components/useWaiverAnalysis", () => ({
  useWaiverAnalysis: () => ({
    analysis: null,
    faabIndex: null,
    loading: false,
    error: "Service unavailable",
    leagueMismatch: false,
    hasTeam: true,
    teamCount: 12,
    selectedLeagueName: "Main",
  }),
}));
vi.mock("@/components/AppShell", () => ({
  useApp: () => ({
    privateDataEnabled: true,
    rows: [],
    rawData: null,
    failure: {
      kind: "unavailable",
      code: "",
      message: "The server is restarting or briefly unavailable. Try again in a moment.",
      retryable: true,
    },
    retry,
  }),
}));
vi.mock("@/app/AppShellWrapper", () => ({ useAuthContext: () => ({ authenticated: true }) }));
vi.mock("@/components/useLeague", () => ({
  useLeague: () => ({ selectedLeague: { key: "dynasty_main", idpEnabled: true } }),
}));
vi.mock("@/components/useTeam", () => ({
  useTeam: () => ({ selectedTeam: { name: "Mine", players: [] }, loading: false }),
}));
vi.mock("@/components/useSettings", () => ({
  useSettings: () => ({ settings: {}, hydrated: true, update: vi.fn() }),
}));
vi.mock("@/components/waivers/ManualAddDrop", () => ({ default: () => null }));
vi.mock("@/components/waivers/BestAvailableIdps", () => ({ default: () => null }));
vi.mock("@/components/TeamSwitcher", () => ({ default: () => null }));
vi.mock("@/components/shell/RelatedLinks", () => ({ default: () => null }));

import WaiversPage from "@/app/waivers/page";

describe("/waivers contract failure", () => {
  it("renders the classified failure, and Try again re-invokes the contract fetch", () => {
    render(<WaiversPage />);
    expect(screen.getByText("Service unavailable — waiver analysis")).toBeInTheDocument();
    expect(screen.getByText(/restarting or briefly unavailable/)).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Try again" }));
    expect(retry).toHaveBeenCalledTimes(1);
  });
});
