/**
 * Token-contract test — pins frontend/app/tokens.css to the documented
 * contract in components/ds/token-contract.js.
 *
 * Guards three invariants:
 *   1. Every documented token is actually defined in :root.
 *   2. The layer is ADDITIVE: it never (re)defines a legacy globals.css
 *      token, so importing it cannot change any existing style.
 *   3. The light-theme scaffold re-maps the required semantic aliases,
 *      and ds.css never hardcodes a hex color (tokens only).
 */
import { describe, expect, it } from "vitest";
import fs from "node:fs";
import path from "node:path";
import {
  CHART_SERIES_TOKENS,
  LIGHT_THEME_REQUIRED,
  REQUIRED_TOKENS,
} from "@/components/ds/token-contract";

/** Remove CSS comments so doc text never pollutes parsing. */
function stripComments(css) {
  return css.replace(/\/\*[\s\S]*?\*\//g, "");
}

const tokensCss = stripComments(
  fs.readFileSync(path.resolve(__dirname, "../../../app/tokens.css"), "utf8")
);
const dsCss = stripComments(
  fs.readFileSync(path.resolve(__dirname, "../../../app/ds.css"), "utf8")
);

/** Extract custom-property NAMES defined (assigned) in a css block. */
function definedProps(css) {
  return [...css.matchAll(/(--[a-z0-9-]+)\s*:/gi)].map((m) => m[1]);
}

/** Split tokens.css into the base :root block (before the reduced-motion
 * override, which legitimately re-zeroes motion tokens) and the light block. */
function splitBlocks(css) {
  const reducedStart = css.indexOf("@media (prefers-reduced-motion");
  const lightStart = css.indexOf(':root[data-theme="light"]');
  const darkEnd =
    reducedStart === -1 ? (lightStart === -1 ? css.length : lightStart) : reducedStart;
  return {
    dark: css.slice(0, darkEnd),
    light: lightStart === -1 ? "" : css.slice(lightStart),
  };
}

const { dark, light } = splitBlocks(tokensCss);
const darkProps = definedProps(dark);
const lightProps = definedProps(light);

// The legacy globals.css tokens this layer must never touch.
const LEGACY_TOKENS = [
  "--bg",
  "--bg-soft",
  "--card",
  "--card-hover",
  "--text",
  "--subtext",
  "--muted",
  "--cyan",
  "--green",
  "--red",
  "--amber",
  "--border",
  "--border-bright",
  "--blush",
  "--vikings-purple",
  "--vikings-gold",
  "--vikings-blush",
  "--space-xs",
  "--space-sm",
  "--space-md",
  "--space-lg",
  "--space-xl",
  "--radius-sm",
  "--radius",
  "--radius-lg",
  "--font",
  "--mono",
  "--shell-max",
  "--topbar-h",
  "--mobile-topbar-h",
  "--mobile-nav-h",
];

describe("tokens.css contract", () => {
  it("defines every documented token in :root", () => {
    const missing = REQUIRED_TOKENS.filter((t) => !darkProps.includes(t));
    expect(missing).toEqual([]);
  });

  it("defines no token twice in :root", () => {
    const seen = new Set();
    const dupes = darkProps.filter((t) => {
      if (seen.has(t)) return true;
      seen.add(t);
      return false;
    });
    expect(dupes).toEqual([]);
  });

  it("stays additive — never defines a legacy globals.css token", () => {
    const collisions = [...darkProps, ...lightProps].filter((t) =>
      LEGACY_TOKENS.includes(t)
    );
    expect(collisions).toEqual([]);
  });

  it("documents every token it defines (no undocumented dark tokens)", () => {
    const undocumented = darkProps.filter((t) => !REQUIRED_TOKENS.includes(t));
    expect(undocumented).toEqual([]);
  });

  it("scaffolds the light theme for all required semantic aliases", () => {
    expect(tokensCss).toContain(':root[data-theme="light"]');
    const missing = LIGHT_THEME_REQUIRED.filter((t) => !lightProps.includes(t));
    expect(missing).toEqual([]);
  });

  it("light theme only re-maps semantic aliases, never primitives", () => {
    const primitives = lightProps.filter(
      (t) => /^--neutral-\d+$/.test(t) || t.startsWith("--brand-")
    );
    expect(primitives).toEqual([]);
  });

  it("defines all six chart series slots", () => {
    const missing = CHART_SERIES_TOKENS.filter((t) => !darkProps.includes(t));
    expect(missing).toEqual([]);
  });

  it("zeroes motion durations under prefers-reduced-motion", () => {
    const reduced = tokensCss.slice(
      tokensCss.indexOf("prefers-reduced-motion")
    );
    expect(reduced).toContain("--motion-fast: 0ms");
    expect(reduced).toContain("--motion-base: 0ms");
    expect(reduced).toContain("--motion-slow: 0ms");
  });
});

describe("ds.css discipline", () => {
  it("contains no raw hex colors — tokens only", () => {
    const hexes = dsCss.match(/#[0-9a-fA-F]{3,8}\b/g) || [];
    expect(hexes).toEqual([]);
  });

  it("namespaces every class as .ds-*", () => {
    const classes = [...dsCss.matchAll(/\.([a-zA-Z][a-zA-Z0-9_-]*)/g)]
      .map((m) => m[1])
      .filter((c) => !c.startsWith("ds-"));
    expect([...new Set(classes)]).toEqual([]);
  });
});
