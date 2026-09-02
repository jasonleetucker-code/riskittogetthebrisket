/**
 * Regression contract for the installed-iPhone shell.
 *
 * `viewport-fit=cover` deliberately lets the page paint behind iOS chrome.
 * The active R1 shell therefore has to consume the safe-area inset itself.
 * The retired `.mobile-topbar` did; `.shell-mobile-topbar` initially did not,
 * which placed the team picker inside the status/Dynamic Island region and
 * made its trigger unreachable in the Home Screen app.
 */
import fs from "node:fs";
import path from "node:path";
import { describe, expect, it } from "vitest";

const ROOT = path.resolve(__dirname, "..");
const SHELL_CSS = fs.readFileSync(path.join(ROOT, "app/shell.css"), "utf8");
const GLOBALS_CSS = fs.readFileSync(path.join(ROOT, "app/globals.css"), "utf8");
const LAYOUT = fs.readFileSync(path.join(ROOT, "app/layout.jsx"), "utf8");

function rule(source, selector) {
  const escaped = selector.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
  const match = source.match(new RegExp(`${escaped}\\s*\\{([^}]+)\\}`));
  expect(match, `missing CSS rule: ${selector}`).toBeTruthy();
  return match[1];
}

describe("mobile shell iOS safe-area contract", () => {
  it("keeps the edge-to-edge viewport mode that makes inset handling explicit", () => {
    expect(LAYOUT).toMatch(/viewportFit:\s*["']cover["']/);
    expect(LAYOUT).toMatch(/statusBarStyle:\s*["']black-translucent["']/);
  });

  it("grows the live mobile header and moves its controls below the top inset", () => {
    const header = rule(SHELL_CSS, ".shell-mobile-topbar");
    expect(header).toMatch(
      /height:\s*calc\([^;]*--mobile-topbar-h[^;]*env\(safe-area-inset-top,\s*0px\)[^;]*\)/,
    );
    expect(header).toMatch(/padding-top:\s*env\(safe-area-inset-top,\s*0px\)/);
  });

  it("positions the mobile team menu below the complete safe-area-aware header", () => {
    const menu = rule(GLOBALS_CSS, ".team-switcher--mobile .team-switcher-menu");
    expect(menu).toMatch(
      /top:\s*calc\([^;]*--mobile-topbar-h[^;]*env\(safe-area-inset-top,\s*0px\)[^;]*\)/,
    );
    expect(menu).toMatch(/max-height:\s*calc\([^;]*100dvh[^;]*--mobile-nav-h/);
    expect(menu).toMatch(/env\(safe-area-inset-bottom,\s*0px\)/);
  });

  it("keeps every team-changing touch target at least 44px tall", () => {
    expect(rule(GLOBALS_CSS, ".team-switcher--mobile .team-switcher-toggle")).toMatch(
      /min-height:\s*44px/,
    );
    expect(rule(GLOBALS_CSS, ".team-switcher-option")).toMatch(/min-height:\s*44px/);
    expect(rule(SHELL_CSS, ".shell-icon-btn")).toMatch(/height:\s*44px/);
  });
});
