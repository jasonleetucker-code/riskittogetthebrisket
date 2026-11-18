/**
 * Error boundaries (audit remediation, Task 9): themed, retryable, and never
 * printing raw error text.
 */
import React from "react";
import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import RouteError from "@/app/error.jsx";
import GlobalError from "@/app/global-error.jsx";
import NotFound from "@/app/not-found.jsx";

const SECRET = "TypeError: cannot read 'rosterId' of undefined at /srv/app/internal.js:42";

describe("app/error.jsx", () => {
  it("shows a safe message, no raw error text, and Retry calls reset()", () => {
    const spy = vi.spyOn(console, "error").mockImplementation(() => {});
    const reset = vi.fn();
    const err = Object.assign(new Error(SECRET), { digest: "abc123" });
    const { container } = render(<RouteError error={err} reset={reset} />);
    expect(container.textContent).not.toContain("rosterId");
    expect(container.textContent).not.toContain("internal.js");
    expect(screen.getByText("Something went wrong")).toBeTruthy();
    fireEvent.click(screen.getByRole("button", { name: /try again/i }));
    expect(reset).toHaveBeenCalledOnce();
    expect(screen.getByTestId("error-reference").textContent).toContain("abc123");
    // the real error still reaches the console for debugging
    expect(spy).toHaveBeenCalled();
    spy.mockRestore();
  });

  it("omits the reference line when there is no digest", () => {
    const spy = vi.spyOn(console, "error").mockImplementation(() => {});
    render(<RouteError error={new Error("x")} reset={() => {}} />);
    expect(screen.queryByTestId("error-reference")).toBeNull();
    spy.mockRestore();
  });

  it("offers a way home", () => {
    const spy = vi.spyOn(console, "error").mockImplementation(() => {});
    render(<RouteError error={new Error("x")} reset={() => {}} />);
    expect(screen.getByRole("link", { name: /go home/i }).getAttribute("href")).toBe("/");
    spy.mockRestore();
  });
});

describe("app/global-error.jsx", () => {
  it("renders its own document shell, hides the message, wires Retry", () => {
    const spy = vi.spyOn(console, "error").mockImplementation(() => {});
    const reset = vi.fn();
    // <html> inside a div is a validateDOMNesting warning in jsdom only.
    const warn = vi.spyOn(console, "warn").mockImplementation(() => {});
    const { baseElement } = render(
      <GlobalError error={Object.assign(new Error(SECRET), { digest: "d1" })} reset={reset} />,
    );
    expect(baseElement.textContent).not.toContain("rosterId");
    fireEvent.click(screen.getByRole("button", { name: /try again/i }));
    expect(reset).toHaveBeenCalledOnce();
    spy.mockRestore();
    warn.mockRestore();
  });
});

describe("app/not-found.jsx", () => {
  it("says the page is missing and links home", () => {
    render(<NotFound />);
    expect(screen.getByText("Page not found")).toBeTruthy();
    expect(screen.getByRole("link", { name: /go home/i }).getAttribute("href")).toBe("/");
  });
});
