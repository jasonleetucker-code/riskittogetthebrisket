/**
 * CQ-30 — the four axe findings that needed a VISUAL fix, pinned so the
 * cause cannot quietly return.  Each was held in the a11y-axe.spec.js
 * ratchet until fixed; the browser scan is the authority, these are the
 * cheap structural guards that fail first (no stack, no browser).
 *
 *   /draft                     the tag-tab count pill is not dimmed
 *   /league-comparison         the method toggle is the ds SegmentedControl,
 *                              not unstyled `btn btn-secondary` buttons
 *   /auction/notifications     auction table headers paint their own token
 *                              surface instead of the legacy navy `th` fill
 *   /league/franchise/[owner]  in-prose links carry the underlined .ds-link
 */
import fs from "node:fs";
import path from "node:path";
import React from "react";
import { describe, expect, it, vi } from "vitest";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";

import SummaryCards from "@/app/league-comparison/sections/SummaryCards.jsx";
import PositionalTable from "@/app/league-comparison/sections/PositionalTable.jsx";

const read = (p) => fs.readFileSync(path.resolve(__dirname, p), "utf8");
const stripComments = (css) => css.replace(/\/\*[\s\S]*?\*\//g, "");

/** Body of the first rule whose selector is exactly `sel`. */
function ruleBody(css, sel) {
  const esc = sel.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
  const m = stripComments(css).match(new RegExp(`(^|[}\\s])${esc}\\s*\\{([^}]*)\\}`, "m"));
  return m ? m[2] : null;
}

describe("/draft tag-tab count pill", () => {
  it("inherits the tab's token colour at full strength (no opacity dimming)", () => {
    const body = ruleBody(read("../../app/draft/draft.css"), ".draft-tag-tab-count");
    expect(body, ".draft-tag-tab-count rule not found").toBeTruthy();
    expect(body).not.toMatch(/opacity/);
  });
});

describe("/auction table headers", () => {
  it("paint the panel token surface, so the legacy globals `th` navy cannot show through", () => {
    const body = ruleBody(read("../../app/auction/auction.module.css"), ".table th");
    expect(body, ".table th rule not found").toBeTruthy();
    expect(body).toMatch(/background:\s*var\(--surface-1\)/);
    expect(body).toMatch(/color:\s*var\(--text-tertiary\)/);
  });
});

describe("/league/franchise/[owner] in-prose links", () => {
  const src = read("../../app/league/franchise/[owner]/page.jsx");

  it("the top-rival and Full draft center links are underlined (.ds-link)", () => {
    expect(src).toMatch(
      /href=\{`\/league\/franchise\/\$\{encodeURIComponent\(fr\.topRival\.ownerId\)\}`\}\s*className="ds-link"/,
    );
    expect(src).toMatch(/href="\/league\?tab=draft" className="ds-link"/);
  });

  it(".ds-link is defined in ds.css as a real underline", () => {
    const body = ruleBody(read("../../app/ds.css"), ".ds-link");
    expect(body, ".ds-link rule not found").toBeTruthy();
    expect(body).toMatch(/text-decoration-line:\s*underline/);
  });
});

describe("/league-comparison method toggle", () => {
  const DATA = { similarity: { score: 90 }, summary: {}, positions: {}, flex: {} };

  for (const [name, Component] of [
    ["SummaryCards", SummaryCards],
    ["PositionalTable", PositionalTable],
  ]) {
    it(`${name}: a named radiogroup with the active method checked, no unstyled btn classes`, async () => {
      const user = userEvent.setup();
      const setMethod = vi.fn();
      const { container } = render(
        <Component data={DATA} method="improved" setMethod={setMethod} />,
      );
      const group = screen.getByRole("radiogroup", { name: "Method" });
      const radios = Array.from(group.querySelectorAll('[role="radio"]'));
      expect(radios.map((r) => r.getAttribute("aria-checked"))).toEqual(["true", "false"]);
      expect(container.querySelector(".btn-secondary")).toBeNull();
      // No inline colour paint on the toggle: the checked state is token-styled.
      for (const r of radios) expect(r.getAttribute("style")).toBeNull();
      await user.click(radios[1]);
      expect(setMethod).toHaveBeenCalledWith("legacy");
    });
  }
});
