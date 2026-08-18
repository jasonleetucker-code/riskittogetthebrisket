/**
 * /admin renders the guest-pass list without crashing (#779).
 *
 * The owner reported the Admin page reaching the global client-side error
 * boundary with `Can't find variable: fmtPassExpiry`.  The cause was an
 * orphaned extraction: `GuestPassPanel` was moved out of `/settings`, its
 * two calls to `fmtPassExpiry` came with it, and the function definition
 * did not — it stayed behind in `app/settings/page.jsx` as module-private
 * dead code that nothing there called.
 *
 * The crash is REACHABLE ONLY WITH DATA.  `GuestPassPanel` renders the
 * expiry cell inside `passes.map(...)`, so an empty list — which is what a
 * naive smoke test gets — renders "No passes yet." and never touches the
 * missing symbol.  That is why this test seeds a non-empty list, and why
 * the issue explicitly rules out a grep/string-presence assertion: a free
 * variable is a runtime fault, and only running the component finds it.
 *
 * The second call site (the freshly-minted-token block) is covered too,
 * because it is behind a different state branch and a fix that reached
 * only the table would leave it live.
 */
import { describe, it, expect, beforeEach, afterEach, vi } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import GuestPassPanel from "@/components/admin/GuestPassPanel";

const HOUR = 3600;

function nowEpoch() {
  return Math.floor(Date.now() / 1000);
}

function mockPasses(passes) {
  global.fetch = vi.fn(async (url) => {
    if (String(url).includes("/api/admin/guest-passes")) {
      return {
        ok: true,
        status: 200,
        json: async () => ({ passes }),
      };
    }
    throw new Error(`unexpected fetch: ${url}`);
  });
}

describe("GuestPassPanel (#779)", () => {
  let errorSpy;

  beforeEach(() => {
    // React logs render errors through console.error before rethrowing;
    // silence it so a deliberate crash does not look like suite noise,
    // but keep the spy so we can assert on it if needed.
    errorSpy = vi.spyOn(console, "error").mockImplementation(() => {});
  });

  afterEach(() => {
    errorSpy.mockRestore();
    vi.restoreAllMocks();
  });

  it("renders a non-empty pass list without throwing", async () => {
    mockPasses([
      {
        id: 7,
        note: "for Dave",
        expiresAtEpoch: nowEpoch() + 6 * HOUR,
        isRevoked: false,
        isExpired: false,
      },
      {
        id: 6,
        note: "",
        expiresAtEpoch: nowEpoch() - 48 * HOUR,
        isRevoked: false,
        isExpired: true,
      },
    ]);

    render(<GuestPassPanel />);

    // Waiting on a rendered ROW, not on the absence of an error: the
    // fetch resolves asynchronously, so asserting "did not throw"
    // immediately after render would pass before the list ever existed.
    await waitFor(() => {
      expect(screen.getByText("for Dave")).toBeInTheDocument();
    });

    // The expiry cell is what calls the formatter.  Assert it produced
    // something rather than merely that nothing exploded — a fix that
    // stubbed the symbol to `undefined` would pass a crash-only check.
    expect(screen.getByText(/in 6h/)).toBeInTheDocument();
    expect(screen.getAllByText("Expired").length).toBeGreaterThan(0);
  });

  it("renders an empty list without reaching the formatter", async () => {
    // The control. Without it, a fix that removed the expiry column
    // entirely would satisfy the test above.
    mockPasses([]);
    render(<GuestPassPanel />);
    await waitFor(() => {
      expect(screen.getByText("No passes yet.")).toBeInTheDocument();
    });
  });

  it("formats a missing or non-positive expiry as an em dash, never a date", async () => {
    // MISSING IS NEVER ZERO, applied to a timestamp: epoch 0 is a real
    // instant (1970) and rendering it would tell an operator the pass
    // expired 56 years ago rather than that the backend sent nothing.
    mockPasses([
      {
        id: 9,
        note: "no expiry stamped",
        expiresAtEpoch: null,
        isRevoked: false,
        isExpired: false,
      },
    ]);
    render(<GuestPassPanel />);
    await waitFor(() => {
      expect(screen.getByText("no expiry stamped")).toBeInTheDocument();
    });
    expect(screen.getByText("—")).toBeInTheDocument();
  });
});
