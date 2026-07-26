/**
 * Button spec — variants render on a real <button>, and the `as`-link
 * escape hatch stays genuinely inert while disabled/loading: no
 * navigation, no consumer onClick, removed from the tab order
 * (WAI-ARIA disabled-link practice), aria-disabled stamped.
 */
import { describe, expect, it, vi } from "vitest";
import React from "react";
import { fireEvent, render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { Button } from "@/components/ds";

describe("Button (native)", () => {
  it("renders a real button with type=button by default", () => {
    render(<Button>Save</Button>);
    const btn = screen.getByRole("button", { name: "Save" });
    expect(btn.tagName).toBe("BUTTON");
    expect(btn).toHaveAttribute("type", "button");
  });

  it("disables natively when disabled or loading", () => {
    render(<Button loading>Saving</Button>);
    const btn = screen.getByRole("button");
    expect(btn).toBeDisabled();
    expect(btn).toHaveAttribute("aria-busy", "true");
  });

  it("fires onClick when enabled", async () => {
    const user = userEvent.setup();
    const onClick = vi.fn();
    render(<Button onClick={onClick}>Go</Button>);
    await user.click(screen.getByRole("button"));
    expect(onClick).toHaveBeenCalledTimes(1);
  });
});

describe("Button as link", () => {
  it("enabled link keeps href and fires onClick", async () => {
    const user = userEvent.setup();
    const onClick = vi.fn((e) => e.preventDefault());
    render(
      <Button as="a" href="/rankings" onClick={onClick}>
        Rankings
      </Button>
    );
    const link = screen.getByRole("link", { name: "Rankings" });
    expect(link).toHaveAttribute("href", "/rankings");
    await user.click(link);
    expect(onClick).toHaveBeenCalledTimes(1);
  });

  it("disabled link does not navigate, drops href, and skips consumer onClick", () => {
    const onClick = vi.fn();
    render(
      <Button as="a" href="/rankings" disabled onClick={onClick}>
        Rankings
      </Button>
    );
    const link = screen.getByText("Rankings");
    expect(link).not.toHaveAttribute("href");
    expect(link).toHaveAttribute("aria-disabled", "true");
    // fireEvent returns false when preventDefault was called
    const notCancelled = fireEvent.click(link);
    expect(notCancelled).toBe(false);
    expect(onClick).not.toHaveBeenCalled();
  });

  it("disabled link is removed from the tab order", () => {
    render(
      <Button as="a" href="/x" disabled>
        X
      </Button>
    );
    expect(screen.getByText("X")).toHaveAttribute("tabindex", "-1");
  });

  it("loading link is inert exactly like a disabled one", () => {
    const onClick = vi.fn();
    render(
      <Button as="a" href="/x" loading onClick={onClick}>
        X
      </Button>
    );
    const link = screen.getByText("X");
    expect(link).toHaveAttribute("aria-disabled", "true");
    expect(link).toHaveAttribute("tabindex", "-1");
    fireEvent.click(link);
    expect(onClick).not.toHaveBeenCalled();
  });

  it("custom link components keep their required href but activation is blocked", () => {
    const FakeLink = ({ href, children, ...rest }) => (
      <a href={href} {...rest}>
        {children}
      </a>
    );
    const onClick = vi.fn();
    render(
      <Button as={FakeLink} href="/x" disabled onClick={onClick}>
        X
      </Button>
    );
    const link = screen.getByText("X");
    expect(link).toHaveAttribute("href", "/x"); // component requires href
    expect(link).toHaveAttribute("tabindex", "-1");
    const notCancelled = fireEvent.click(link);
    expect(notCancelled).toBe(false); // navigation prevented
    expect(onClick).not.toHaveBeenCalled();
  });
});
