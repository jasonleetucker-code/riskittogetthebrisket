/**
 * The command palette's admin filter is only as good as its wiring: the
 * shell must hand the viewer's admin flag from the auth context through
 * AppShell to CommandPalette, or `paletteTargets` fails closed and an admin
 * loses the Ops pages (or, if someone "fixes" that with a default of true,
 * a non-admin gains them).  CommandPalette's own behaviour is pinned in
 * components/shell/CommandPalette.test.jsx; this pins the hand-off.
 */
import fs from "node:fs";
import path from "node:path";
import url from "node:url";
import { describe, expect, it } from "vitest";

const ROOT = path.resolve(path.dirname(url.fileURLToPath(import.meta.url)), "..");
const read = (rel) => fs.readFileSync(path.join(ROOT, rel), "utf8");

describe("palette admin flag wiring", () => {
  it("AppShellWrapper passes the authoritative admin flag to AppShell", () => {
    expect(read("app/AppShellWrapper.jsx")).toMatch(
      /<AppShell[\s\S]*?isAdmin=\{auth\.authenticated === true && auth\.isAdmin === true\}[\s\S]*?>/,
    );
  });

  it("AppShell threads it to both shells, InnerAppShell and the palette", () => {
    const src = read("components/AppShell.jsx");
    expect(src).toMatch(/export default function AppShell\(\{[^}]*isAdmin = false[^}]*\}\)/);
    expect(src).toMatch(/<PrivateAppShell[^>]*isAdmin=\{isAdmin\}/);
    expect(src).toMatch(/<NoPlayerDataAppShell[^>]*isAdmin=\{isAdmin\}/);
    expect((src.match(/<InnerAppShell[\s\S]*?isAdmin=\{isAdmin\}[\s\S]*?>/g) || []).length).toBe(2);
    expect(src).toMatch(/<CommandPalette[\s\S]*?isAdmin=\{isAdmin\}[\s\S]*?\/>/);
  });
});
