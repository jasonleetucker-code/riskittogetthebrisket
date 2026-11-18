/**
 * /rankings must not offer operable source-mix controls or imply they work:
 * custom source mixes are switched off on the server
 * (`_SOURCE_OVERRIDES_DISABLED`, src/api/data_contract.py) and /settings says
 * so.  Copy/structure guard over the page source plus the explainer text.
 */
import { readFileSync } from "node:fs";
import { join } from "node:path";
import { describe, expect, it } from "vitest";
import { VALUE_EXPLAINERS } from "@/lib/value-explainers";

const page = readFileSync(join(process.cwd(), "app/rankings/page.jsx"), "utf8");

describe("rankings source-mix honesty", () => {
  it("states that custom source mixes are switched off", () => {
    expect(page).toContain("Custom source mixes are switched off.");
  });

  it("offers no include checkbox, reset or weight mutation in the Sources popover", () => {
    expect(page).not.toContain("Unchecking a source");
    expect(page).not.toContain("Re-include every source");
    expect(page).not.toContain("toggleSourceIncluded");
    expect(page).not.toContain("resetSiteWeights");
    expect(page).not.toContain("updateSiteWeight");
    const start = page.indexOf("<span>Sources in blend</span>");
    const end = page.indexOf("Columns popover");
    expect(start).toBeGreaterThan(0);
    expect(end).toBeGreaterThan(start);
    expect(page.slice(start, end)).not.toMatch(/<input|checkbox|<Button/);
  });

  it("does not tell the user to change the mix on Settings or claim it was applied", () => {
    expect(page).not.toContain("Change these on the Settings page");
    expect(page).not.toContain("Custom source configuration");
    expect(page).not.toContain("Your custom source mix could not be applied");
  });

  it("keys the badge on the same client-side stored-mix check as /settings", () => {
    expect(page).toContain("siteOverridesAreCustomized");
    expect(page).toContain("storedSiteWeights={settings?.siteWeights}");
    expect(page).toContain("Your saved source mix is stored but not applied; the board");
  });

  it("value explainer no longer says changed weights recompute the board", () => {
    const text = VALUE_EXPLAINERS.value.detail.join(" ");
    expect(text).not.toContain("recomputes the board with your weights");
    expect(text).toContain("switched off");
  });
});
