/**
 * FailureState renders a classified failure — and refuses to say things
 * the classification does not support.
 */
import { describe, it, expect, vi } from "vitest";
import { render, screen } from "@testing-library/react";
import { FailureState } from "@/components/ds/FailureState";

describe("FailureState", () => {
  it("renders nothing when there is no failure", () => {
    const { container } = render(<FailureState failure={null} />);
    expect(container).toBeEmptyDOMElement();
  });

  it("does not voice an empty board as a fault", () => {
    // `empty` is a backend that has not finished its first scrape. Both
    // the words and the live-region urgency have to match that: `Banner`
    // maps info -> role="status", warning/negative -> role="alert", so
    // getting the tone wrong interrupts a screen reader for a
    // non-problem.
    render(<FailureState failure={{ kind: "empty", message: "" }} />);
    const region = screen.getByRole("status");
    expect(region).toHaveTextContent(/No data yet/i);
    expect(region.textContent).not.toMatch(/error|failed|unavailable/i);
    expect(screen.queryByRole("alert")).toBeNull();
  });

  it("announces a real failure assertively", () => {
    render(<FailureState failure={{ kind: "unavailable", message: "" }} />);
    expect(screen.getByRole("alert")).toHaveTextContent(/Service unavailable/i);
  });

  it("offers no retry on a permissions answer", () => {
    // Retrying cannot change a 403, and a button implies it might.
    render(
      <FailureState failure={{ kind: "forbidden", message: "" }} onRetry={() => {}} />,
    );
    expect(screen.queryByRole("button", { name: /try again/i })).toBeNull();
  });

  it("offers a retry where retrying can help, and calls it", async () => {
    const onRetry = vi.fn();
    render(<FailureState failure={{ kind: "offline", retryable: true }} onRetry={onRetry} />);
    const btn = screen.getByRole("button", { name: /try again/i });
    btn.click();
    expect(onRetry).toHaveBeenCalledTimes(1);
  });

  it("leads with the server's own words, not ours", () => {
    // A stated reason is more use than a generic sentence, and replacing
    // it with a friendlier one is how a degraded state stops being
    // distinguishable from an outage.
    render(
      <FailureState
        failure={{ kind: "degraded", message: "Leagues do not share proven scoring." }}
      />,
    );
    expect(screen.getByRole("alert")).toHaveTextContent(/do not share proven scoring/i);
  });

  it("names what failed when given a context", () => {
    render(<FailureState failure={{ kind: "server" }} context="rankings" />);
    expect(screen.getByRole("alert")).toHaveTextContent(/rankings/i);
  });

  it("falls back to a generic kind rather than rendering nothing", () => {
    // An unknown kind must not silently disappear — a failure the reader
    // cannot see is what the fail-fast convention forbids.
    render(<FailureState failure={{ kind: "something-new", message: "odd" }} />);
    expect(screen.getByRole("alert")).toHaveTextContent(/odd/);
  });
});
