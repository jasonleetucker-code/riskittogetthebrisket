/**
 * ds Panel + CollapsiblePanel — the container primitive and the folding
 * variant (R3 review, P2-2).
 *
 * ScoutingIntel shipped `collapsible defaultCollapsed` on main;
 * migrating it to ds Panel silently dropped the toggle because the
 * primitive had no such prop.  The behaviour is restored, but the STATE
 * lives in CollapsiblePanel rather than Panel: Panel must stay hook-free
 * so it can still be rendered from a React Server Component (see
 * panel-server-safe.test.js for why that matters).
 *
 * Split of responsibility pinned below:
 *   Panel             renders the disclosure, CONTROLLED
 *                     (collapsible / collapsed / onToggleCollapsed / bodyId)
 *   CollapsiblePanel  owns the state and supplies all four
 */
import { describe, it, expect } from "vitest";
import React from "react";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { CollapsiblePanel, Panel } from "@/components/ds";

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

describe("CollapsiblePanel — owns the folded state", () => {
  it("exposes a labelled disclosure wired to the body region", () => {
    render(
      <CollapsiblePanel title="Scouting" subtitle="intel">
        diagnostics
      </CollapsiblePanel>,
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
      <CollapsiblePanel title="Scouting" footer="footnote">
        diagnostics
      </CollapsiblePanel>,
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
      <CollapsiblePanel defaultCollapsed title="Scouting">
        diagnostics
      </CollapsiblePanel>,
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
      <CollapsiblePanel title="Scouting">
        diagnostics
      </CollapsiblePanel>,
    );
    const toggle = screen.getByRole("button", { name: /Scouting/ });
    toggle.focus();
    await user.keyboard("{Enter}");
    expect(toggle).toHaveAttribute("aria-expanded", "false");
    await user.keyboard(" ");
    expect(toggle).toHaveAttribute("aria-expanded", "true");
  });

  it("no-ops without a title — a disclosure with no label is unusable", () => {
    render(<CollapsiblePanel>body</CollapsiblePanel>);
    expect(screen.queryByRole("button")).toBeNull();
    expect(screen.getByText("body")).toBeVisible();
  });
});

describe("Panel — the disclosure is CONTROLLED", () => {
  it("reflects the collapsed prop and calls onToggleCollapsed", async () => {
    // Panel must not own this state; if it ever starts to, it needs a
    // hook and stops being server-renderable.
    const user = userEvent.setup();
    const calls = [];
    render(
      <Panel
        collapsible
        collapsed
        bodyId="b1"
        onToggleCollapsed={() => calls.push(1)}
        title="Scouting"
      >
        diagnostics
      </Panel>,
    );
    const toggle = screen.getByRole("button", { name: /Scouting/ });
    expect(toggle).toHaveAttribute("aria-expanded", "false");
    expect(screen.getByText("diagnostics")).not.toBeVisible();

    await user.click(toggle);
    // The parent owns the state, so nothing changes here on its own.
    expect(calls).toHaveLength(1);
    expect(toggle).toHaveAttribute("aria-expanded", "false");
  });

  it("uses the supplied bodyId for aria-controls", () => {
    render(
      <Panel collapsible collapsed={false} bodyId="scouting-body" title="S">
        diagnostics
      </Panel>,
    );
    expect(screen.getByRole("button", { name: "S" })).toHaveAttribute(
      "aria-controls",
      "scouting-body",
    );
    expect(document.getElementById("scouting-body")).toHaveTextContent(
      "diagnostics",
    );
  });
});
