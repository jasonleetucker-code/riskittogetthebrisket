/**
 * ds Panel — container primitive, plus the `collapsible` ADDITION
 * (R3 review, P2-2).
 *
 * The terminal's ScoutingIntel shipped `collapsible defaultCollapsed`
 * on main; migrating it to ds Panel silently dropped the toggle
 * because the primitive had no such prop.  `collapsible` is additive —
 * every existing call site keeps its behaviour untouched — which is
 * what the frozen-contract rule permits (mutating the existing API is
 * not).  These tests pin both halves of that: the default path is
 * unchanged, and the new path is a real, announced disclosure.
 */
import { describe, it, expect } from "vitest";
import React from "react";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { Panel } from "@/components/ds";

describe("Panel — unchanged default behaviour", () => {
  it("renders title, subtitle, body and footer with no disclosure", () => {
    render(
      <Panel title="Portfolio" subtitle="Positional allocation" footer="as of today">
        body content
      </Panel>,
    );
    expect(screen.getByRole("heading", { name: "Portfolio" })).toBeInTheDocument();
    expect(screen.getByText("Positional allocation")).toBeInTheDocument();
    expect(screen.getByText("body content")).toBeInTheDocument();
    expect(screen.getByText("as of today")).toBeInTheDocument();
    // no toggle unless asked for
    expect(screen.queryByRole("button")).toBeNull();
  });

  it("honours flush/dense/className without collapsing anything", () => {
    const { container } = render(
      <Panel flush dense className="panel--scouting" title="T">
        body
      </Panel>,
    );
    const panel = container.querySelector(".ds-panel");
    expect(panel).toHaveClass("ds-panel--flush", "ds-panel--dense", "panel--scouting");
    expect(panel).not.toHaveClass("ds-panel--collapsed");
    expect(screen.getByText("body")).toBeVisible();
  });
});

describe("Panel — collapsible (additive)", () => {
  it("exposes a labelled disclosure wired to the body region", () => {
    render(
      <Panel collapsible title="Scouting" subtitle="intel">
        diagnostics
      </Panel>,
    );
    const toggle = screen.getByRole("button", { name: /Scouting/ });
    expect(toggle).toHaveAttribute("aria-expanded", "true");
    // the control points at the region it governs
    const bodyId = toggle.getAttribute("aria-controls");
    expect(bodyId).toBeTruthy();
    expect(document.getElementById(bodyId)).toHaveTextContent("diagnostics");
  });

  it("folds and unfolds on click, hiding the body from the a11y tree", async () => {
    const user = userEvent.setup();
    render(
      <Panel collapsible title="Scouting" footer="footnote">
        diagnostics
      </Panel>,
    );
    expect(screen.getByText("diagnostics")).toBeVisible();

    await user.click(screen.getByRole("button", { name: /Scouting/ }));
    expect(screen.getByRole("button", { name: /Scouting/ })).toHaveAttribute(
      "aria-expanded",
      "false",
    );
    // hidden via the [hidden] attribute, not merely un-styled: the node
    // stays queryable but is out of the a11y tree, which toBeVisible()
    // is the matcher that actually checks.
    expect(screen.getByText("diagnostics")).not.toBeVisible();
    expect(screen.queryByText("footnote")).toBeNull();
    // the title stays reachable so the panel can be reopened
    expect(screen.getByRole("button", { name: /Scouting/ })).toBeVisible();

    await user.click(screen.getByRole("button", { name: /Scouting/ }));
    expect(screen.getByText("diagnostics")).toBeVisible();
  });

  it("seeds the folded state from defaultCollapsed", () => {
    render(
      <Panel collapsible defaultCollapsed title="Scouting">
        diagnostics
      </Panel>,
    );
    expect(screen.getByRole("button", { name: /Scouting/ })).toHaveAttribute(
      "aria-expanded",
      "false",
    );
    expect(screen.getByText("diagnostics")).not.toBeVisible();
  });

  it("is keyboard-operable", async () => {
    const user = userEvent.setup();
    render(
      <Panel collapsible title="Scouting">
        diagnostics
      </Panel>,
    );
    const toggle = screen.getByRole("button", { name: /Scouting/ });
    toggle.focus();
    await user.keyboard("{Enter}");
    expect(toggle).toHaveAttribute("aria-expanded", "false");
    await user.keyboard(" ");
    expect(toggle).toHaveAttribute("aria-expanded", "true");
  });

  it("no-ops without a title — a disclosure with no label is unusable", () => {
    render(<Panel collapsible>body</Panel>);
    expect(screen.queryByRole("button")).toBeNull();
    expect(screen.getByText("body")).toBeVisible();
  });
});
