// The home page's three auth states. The resolving (null) state used
// to render the ~200px landing card, so every signed-in visit swapped
// it for the ~4000px terminal — the site's dominant layout shift (CLS
// 0.72 measured on /). It now holds a terminal-shaped skeleton shell,
// with a 4s cap that falls back to the navigable landing if the auth
// probe stalls.
//
// The landing marker is the BRAND (`Chase Upside`, the page's <h1>), not
// the sign-in button's label. This test originally asserted "Sign In" and
// broke the moment the landing copy was rewritten — the same brittleness
// #555 §5 records for `critical-smoke.spec.js`, whose `/Risk It/i` marker
// died to a wordmark rename. What these cases actually mean is "the
// landing rendered", so they assert the one string that survives copy
// changes and is absent from the skeleton shell (which renders no text).

import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { render, screen, act } from "@testing-library/react";

const mockAuthCtx = vi.fn();

vi.mock("@/app/AppShellWrapper", () => ({
  useAuthContext: () => mockAuthCtx(),
}));
vi.mock("@/components/terminal/TerminalLayout", () => ({
  default: () => <div data-testid="terminal" />,
}));

import HomePage from "@/app/page.jsx";

beforeEach(() => {
  vi.useFakeTimers();
});
afterEach(() => {
  vi.useRealTimers();
});

describe("home page auth shell", () => {
  it("renders the terminal for authenticated users", () => {
    mockAuthCtx.mockReturnValue({ authenticated: true });
    render(<HomePage />);
    expect(screen.getByTestId("terminal")).toBeTruthy();
  });

  it("renders the landing for signed-out users", () => {
    mockAuthCtx.mockReturnValue({ authenticated: false });
    render(<HomePage />);
    expect(screen.getByText("Chase Upside")).toBeTruthy();
  });

  it("holds a terminal-shaped skeleton while auth resolves", () => {
    mockAuthCtx.mockReturnValue({ authenticated: null });
    render(<HomePage />);
    expect(screen.getByLabelText("Loading dashboard")).toBeTruthy();
    expect(screen.queryByText("Chase Upside")).toBeNull();
  });

  it("falls back to the landing if the auth probe stalls past 4s", () => {
    mockAuthCtx.mockReturnValue({ authenticated: null });
    render(<HomePage />);
    expect(screen.getByLabelText("Loading dashboard")).toBeTruthy();
    act(() => {
      vi.advanceTimersByTime(4100);
    });
    expect(screen.getByText("Chase Upside")).toBeTruthy();
  });
});
