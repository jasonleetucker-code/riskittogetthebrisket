/**
 * Hydration gate — server-rendered click-only ds controls must be
 * honestly NOT-YET-INTERACTIVE until React attaches their handlers.
 *
 * Real-user defect behind it: on /arbitrage the tool tabs and the
 * collapsed "Player-level market research" disclosure are in the
 * server-rendered HTML, visible and labelled, seconds before the page
 * JavaScript arrives on a slow network.  A click in that window lands on
 * markup with no listener and React never replays it — the control looks
 * live and does nothing.  PR #1867 taught the V1 specs to wait; this pins
 * the product half: until hydrated the control is `disabled` and
 * `aria-busy`, and it becomes live the moment hydration completes.
 *
 * Three render paths, because the gate must hold on exactly one of them:
 *   1. server render            → disabled + aria-busy (the gate);
 *   2. hydrateRoot of that HTML → live after hydration, no mismatch;
 *   3. plain client render      → live from the first paint (a soft
 *      navigation or lazily shown panel must never flicker busy).
 */
import fs from "node:fs";
import path from "node:path";
import { afterEach, describe, expect, it, vi } from "vitest";
import React, { useState } from "react";
import { renderToString } from "react-dom/server";
import { hydrateRoot } from "react-dom/client";
import { act, render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import {
  CollapsiblePanel,
  Panel,
  SegmentedControl,
  Tabs,
  useHydrated,
} from "@/components/ds";

const TABS = [
  { id: "golden", label: "Golden Upgrades" },
  { id: "scan", label: "Package Scan" },
];
const OPTIONS = [
  { value: "team", label: "Team context" },
  { value: "asset", label: "Asset only" },
];

function Harness() {
  const [tab, setTab] = useState("golden");
  const [mode, setMode] = useState("team");
  return (
    <div>
      <Tabs
        idPrefix="t"
        label="Tools"
        tabs={TABS}
        active={tab}
        onChange={setTab}
      />
      <p data-testid="tab">{tab}</p>
      <SegmentedControl
        label="Mode"
        options={OPTIONS}
        value={mode}
        onChange={setMode}
      />
      <p data-testid="mode">{mode}</p>
      <CollapsiblePanel
        title="Research"
        defaultCollapsed
        mountCollapsedChildren={false}
      >
        <p>research body</p>
      </CollapsiblePanel>
    </div>
  );
}

let container = null;
afterEach(() => {
  if (container) {
    container.remove();
    container = null;
  }
});

describe("server render — the pre-hydration markup", () => {
  const html = renderToString(<Harness />);
  const doc = new DOMParser().parseFromString(
    `<body>${html}</body>`,
    "text/html",
  );

  it("renders every tab disabled, with the tablist marked busy, selection intact", () => {
    const tablist = doc.querySelector('[role="tablist"]');
    expect(tablist.getAttribute("aria-busy")).toBe("true");
    const tabs = [...doc.querySelectorAll('[role="tab"]')];
    expect(tabs).toHaveLength(2);
    for (const t of tabs) expect(t.hasAttribute("disabled")).toBe(true);
    // Still announces WHICH tool is shown — busy is not "nothing selected".
    expect(tabs[0].getAttribute("aria-selected")).toBe("true");
  });

  it("renders the segmented options disabled under a busy radiogroup", () => {
    const group = doc.querySelector('[role="radiogroup"]');
    expect(group.getAttribute("aria-busy")).toBe("true");
    for (const r of doc.querySelectorAll('[role="radio"]')) {
      expect(r.hasAttribute("disabled")).toBe(true);
    }
  });

  it("renders the panel disclosure disabled + aria-busy, still collapsed", () => {
    const disclosure = doc.querySelector(".ds-panel__disclosure");
    expect(disclosure.hasAttribute("disabled")).toBe(true);
    expect(disclosure.getAttribute("aria-busy")).toBe("true");
    expect(disclosure.getAttribute("aria-expanded")).toBe("false");
  });
});

describe("hydrateRoot — the gate lifts once handlers are attached", () => {
  it("enables every control after hydration, with no hydration mismatch, and they act", async () => {
    const html = renderToString(<Harness />);
    container = document.createElement("div");
    container.innerHTML = html;
    document.body.appendChild(container);

    const errors = vi.spyOn(console, "error").mockImplementation(() => {});
    const recoverable = [];
    await act(async () => {
      hydrateRoot(container, <Harness />, {
        onRecoverableError: (e) => recoverable.push(e),
      });
    });
    expect(recoverable).toEqual([]);
    expect(errors).not.toHaveBeenCalled();
    errors.mockRestore();

    expect(screen.getByRole("tablist")).not.toHaveAttribute("aria-busy");
    for (const t of screen.getAllByRole("tab")) expect(t).toBeEnabled();
    expect(screen.getByRole("radiogroup")).not.toHaveAttribute("aria-busy");
    const disclosure = screen.getByRole("button", { name: "Research" });
    expect(disclosure).toBeEnabled();
    expect(disclosure).not.toHaveAttribute("aria-busy");

    const user = userEvent.setup();
    await user.click(screen.getByRole("tab", { name: "Package Scan" }));
    expect(screen.getByTestId("tab")).toHaveTextContent("scan");
    await user.click(screen.getByRole("radio", { name: "Asset only" }));
    expect(screen.getByTestId("mode")).toHaveTextContent("asset");
    await user.click(disclosure);
    expect(disclosure).toHaveAttribute("aria-expanded", "true");
    expect(screen.getByText("research body")).toBeInTheDocument();
  });
});

describe("client render — never busy", () => {
  it("is interactive from the first render (soft navigation / Testing Library)", () => {
    render(<Harness />);
    expect(screen.getByRole("tablist")).not.toHaveAttribute("aria-busy");
    for (const t of screen.getAllByRole("tab")) expect(t).toBeEnabled();
    for (const r of screen.getAllByRole("radio")) expect(r).toBeEnabled();
    expect(screen.getByRole("button", { name: "Research" })).toBeEnabled();
  });
});

describe("Panel stays a pure function of its props", () => {
  it("only gates the disclosure when told to (controlled consumers are unaffected)", () => {
    const { rerender } = render(
      <Panel
        title="Controlled"
        collapsible
        collapsed
        onToggleCollapsed={() => {}}
        bodyId="b"
      >
        x
      </Panel>,
    );
    const button = screen.getByRole("button", { name: "Controlled" });
    expect(button).toBeEnabled();
    expect(button).not.toHaveAttribute("aria-busy");
    rerender(
      <Panel
        title="Controlled"
        collapsible
        collapsed
        onToggleCollapsed={() => {}}
        bodyId="b"
        disclosurePending
      >
        x
      </Panel>,
    );
    expect(button).toBeDisabled();
    expect(button).toHaveAttribute("aria-busy", "true");
  });
});

describe("one owner", () => {
  // The gate is useHydrated's; a primitive must not grow a private copy
  // (a second useSyncExternalStore / mounted-flag variant drifts).
  const DS = path.resolve(__dirname, "../../../components/ds");
  for (const file of [
    "Tabs.jsx",
    "SegmentedControl.jsx",
    "CollapsiblePanel.jsx",
  ]) {
    it(`${file} reads the gate from useHydrated`, () => {
      const src = fs.readFileSync(path.join(DS, file), "utf8");
      expect(src).toContain('import { useHydrated } from "./useHydrated";');
      expect(src).not.toMatch(/useSyncExternalStore/);
    });
  }

  it("useHydrated is false on the server and true on a client render", () => {
    function Probe() {
      return <span data-testid="probe">{String(useHydrated())}</span>;
    }
    expect(renderToString(<Probe />)).toContain(">false<");
    render(<Probe />);
    expect(screen.getByTestId("probe")).toHaveTextContent("true");
  });
});
