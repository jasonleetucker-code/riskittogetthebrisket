/**
 * Tabs spec — instance-scoped ids: two tablists with identical logical
 * tab ids must emit zero duplicate DOM ids and keep aria-controls wired
 * to their own instance's panels.
 */
import { describe, expect, it } from "vitest";
import React from "react";
import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { Tabs, tabId, tabPanelId } from "@/components/ds";

const TABS = [
  { id: "overview", label: "Overview" },
  { id: "history", label: "History" },
];

describe("Tabs id scoping", () => {
  it("two instances with the same logical ids emit zero duplicate DOM ids", () => {
    const { container } = render(
      <>
        <Tabs label="A" tabs={TABS} active="overview" onChange={() => {}} />
        <Tabs label="B" tabs={TABS} active="overview" onChange={() => {}} />
      </>
    );
    const ids = [...container.querySelectorAll("[id]")].map((el) => el.id);
    expect(ids).toHaveLength(4);
    expect(new Set(ids).size).toBe(ids.length);
  });

  it("aria-controls stays wired within its own instance", () => {
    render(
      <>
        <Tabs label="A" tabs={TABS} active="overview" onChange={() => {}} />
        <Tabs label="B" tabs={TABS} active="overview" onChange={() => {}} />
      </>
    );
    for (const listName of ["A", "B"]) {
      const list = screen.getByRole("tablist", { name: listName });
      for (const tab of within(list).getAllByRole("tab")) {
        // panel id = tab id with "-tab-" swapped for "-panel-", same prefix
        expect(tab.getAttribute("aria-controls")).toBe(
          tab.id.replace("-tab-", "-panel-")
        );
      }
    }
    // and the two instances' controls never collide
    const all = screen.getAllByRole("tab").map((t) => t.getAttribute("aria-controls"));
    expect(new Set(all).size).toBe(all.length);
  });

  it("an explicit idPrefix produces the documented helper ids", () => {
    render(
      <>
        <Tabs
          idPrefix="league"
          label="League sections"
          tabs={TABS}
          active="overview"
          onChange={() => {}}
        />
        <div role="tabpanel" id={tabPanelId("league", "overview")} aria-labelledby={tabId("league", "overview")} />
      </>
    );
    const tab = screen.getByRole("tab", { name: "Overview" });
    expect(tab.id).toBe("league-tab-overview");
    expect(tab).toHaveAttribute("aria-controls", "league-panel-overview");
    // the helper-built panel is reachable from the tab's aria-controls
    expect(document.getElementById(tab.getAttribute("aria-controls"))).not.toBeNull();
  });
});

describe("Tabs behavior", () => {
  it("selects with arrow keys via roving tabindex", async () => {
    const user = userEvent.setup();
    let active = "overview";
    const onChange = (id) => {
      active = id;
    };
    const { rerender } = render(
      <Tabs label="A" tabs={TABS} active={active} onChange={onChange} />
    );
    screen.getByRole("tab", { name: "Overview" }).focus();
    await user.keyboard("{ArrowRight}");
    expect(active).toBe("history");
    rerender(<Tabs label="A" tabs={TABS} active={active} onChange={onChange} />);
    expect(screen.getByRole("tab", { name: "History" })).toHaveAttribute(
      "aria-selected",
      "true"
    );
  });
});
