/**
 * V1-131 readiness contract for the "/" search shortcut.
 *
 * The shell shows its "Search" button (TopBar desktop, MobileTopBar phone)
 * under `authenticated && searchEnabled`, and AppShell wires the "/" and
 * Cmd/Ctrl+K listener under the same `searchEnabled`.  The listener must be
 * attached in a LAYOUT effect, in the same commit as the button, before the
 * browser paints it.  As a passive effect it ran after paint: the Search
 * button was on screen while "/" still did nothing, and the E2E that waits on
 * that button (tests/e2e/specs/nav-capability-shell.spec.js) would be racing
 * again.  jsdom cannot observe paint order, so this pins the structure.
 */
import fs from "node:fs";
import path from "node:path";
import { describe, expect, it } from "vitest";

const read = (rel) => fs.readFileSync(path.resolve(__dirname, "..", rel), "utf8");

describe("search shortcut readiness (V1-131)", () => {
  it("AppShell attaches the keydown shortcut in a layout effect gated on searchEnabled", () => {
    const src = read("components/AppShell.jsx");
    const at = src.indexOf('document.addEventListener("keydown", onKeyDown)');
    expect(at).toBeGreaterThan(-1);
    // The hook call that owns this listener is the nearest one above it.
    const before = src.slice(0, at);
    const layout = before.lastIndexOf("useLayoutEffect(() => {");
    const passive = before.lastIndexOf("useEffect(() => {");
    expect(layout).toBeGreaterThan(-1);
    expect(layout).toBeGreaterThan(passive);
    const body = src.slice(layout, at);
    expect(body).toMatch(/if \(!searchEnabled\) return undefined;/);
    expect(body).toMatch(/e\.key === "\/"/);
  });

  it("both Search buttons render under the same authenticated && searchEnabled condition", () => {
    for (const rel of ["components/shell/TopBar.jsx", "components/shell/MobileChrome.jsx"]) {
      expect(read(rel), rel).toMatch(/\{authenticated && searchEnabled && \(/);
    }
  });
});
