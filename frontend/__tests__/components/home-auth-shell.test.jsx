// The home page's three auth states. The resolving (null) state used
// to render the ~200px landing card, so every signed-in visit swapped
// it for the ~4000px terminal — the site's dominant layout shift (CLS
// 0.72 measured on /). It now holds a terminal-shaped skeleton shell,
// with a 4s cap that falls back to the navigable landing if the auth
// probe stalls.

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
    expect(screen.getByText("Sign In")).toBeTruthy();
  });

  it("holds a terminal-shaped skeleton while auth resolves", () => {
    mockAuthCtx.mockReturnValue({ authenticated: null });
    render(<HomePage />);
    expect(screen.getByLabelText("Loading dashboard")).toBeTruthy();
    expect(screen.queryByText("Sign In")).toBeNull();
  });

  it("falls back to the landing if the auth probe stalls past 4s", () => {
    mockAuthCtx.mockReturnValue({ authenticated: null });
    render(<HomePage />);
    expect(screen.getByLabelText("Loading dashboard")).toBeTruthy();
    act(() => {
      vi.advanceTimersByTime(4100);
    });
    expect(screen.getByText("Sign In")).toBeTruthy();
  });
});
