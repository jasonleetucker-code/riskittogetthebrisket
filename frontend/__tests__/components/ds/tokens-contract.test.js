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
  PSI_EDITORIAL_REQUIRED,
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

/** The `.psi-editorial` migration scope (C8-PSI-02) — everything from its
 * selector to end of file, since it's declared last. */
const psiStart = tokensCss.indexOf(".psi-editorial");
const psiEditorial = psiStart === -1 ? "" : tokensCss.slice(psiStart);
const psiProps = definedProps(psiEditorial);

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

  it("the psi-editorial migration scope defines every required token", () => {
    expect(tokensCss).toContain(".psi-editorial");
    const missing = PSI_EDITORIAL_REQUIRED.filter((t) => !psiProps.includes(t));
    expect(missing).toEqual([]);
  });

  it("psi-editorial only re-maps semantic aliases, never primitives", () => {
    const primitives = psiProps.filter(
      (t) => /^--neutral-\d+$/.test(t) || t.startsWith("--brand-")
    );
    expect(primitives).toEqual([]);
  });

  it("psi-editorial stays additive — never defines a legacy globals.css token", () => {
    const collisions = psiProps.filter((t) => LEGACY_TOKENS.includes(t));
    expect(collisions).toEqual([]);
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

describe("light-theme accent contrast", () => {
  const srgb = (c) => {
    c /= 255;
    return c <= 0.04045 ? c / 12.92 : ((c + 0.055) / 1.055) ** 2.4;
  };
  const luminance = (hex) => {
    const h = hex.replace("#", "");
    const [r, g, b] = [0, 2, 4].map((i) => parseInt(h.slice(i, i + 2), 16));
    return 0.2126 * srgb(r) + 0.7152 * srgb(g) + 0.0722 * srgb(b);
  };
  const contrast = (a, b) => {
    const [hi, lo] = [luminance(a), luminance(b)].sort((x, y) => y - x);
    return (hi + 0.05) / (lo + 0.05);
  };
  const lightHex = (name) => {
    const m = light.match(new RegExp(`${name}:\\s*(#[0-9a-fA-F]{6})`));
    return m ? m[1] : null;
  };

  it("accent-as-small-text clears 4.5:1 on surface-1 and surface-2", () => {
    const accent = lightHex("--accent");
    const s1 = lightHex("--surface-1");
    const s2 = lightHex("--surface-2");
    expect(accent).toBeTruthy();
    expect(contrast(accent, s1)).toBeGreaterThanOrEqual(4.5);
    expect(contrast(accent, s2)).toBeGreaterThanOrEqual(4.5);
  });

  it("text-on-accent clears 4.5:1 against the accent (primary buttons)", () => {
    const accent = lightHex("--accent");
    const onAccent = lightHex("--text-on-accent");
    expect(onAccent).toBeTruthy();
    expect(contrast(onAccent, accent)).toBeGreaterThanOrEqual(4.5);
  });
});

describe("psi-editorial accent + market-direction contrast", () => {
  const srgb = (c) => {
    c /= 255;
    return c <= 0.04045 ? c / 12.92 : ((c + 0.055) / 1.055) ** 2.4;
  };
  const luminance = (hex) => {
    const h = hex.replace("#", "");
    const [r, g, b] = [0, 2, 4].map((i) => parseInt(h.slice(i, i + 2), 16));
    return 0.2126 * srgb(r) + 0.7152 * srgb(g) + 0.0722 * srgb(b);
  };
  const contrast = (a, b) => {
    const [hi, lo] = [luminance(a), luminance(b)].sort((x, y) => y - x);
    return (hi + 0.05) / (lo + 0.05);
  };
  const psiHex = (name) => {
    const m = psiEditorial.match(new RegExp(`${name}:\\s*(#[0-9a-fA-F]{6})`));
    return m ? m[1] : null;
  };

  it("accent clears 4.5:1 on the worst (nested) surface", () => {
    const accent = psiHex("--accent");
    const s2 = psiHex("--surface-2");
    expect(accent).toBeTruthy();
    expect(s2).toBeTruthy();
    expect(contrast(accent, s2)).toBeGreaterThanOrEqual(4.5);
  });

  it("text-on-accent clears 4.5:1 against the accent", () => {
    const accent = psiHex("--accent");
    const onAccent = psiHex("--text-on-accent");
    expect(onAccent).toBeTruthy();
    expect(contrast(onAccent, accent)).toBeGreaterThanOrEqual(4.5);
  });

  it("text-primary clears 4.5:1 on every surface (worst = surface-2)", () => {
    const textPrimary = psiHex("--text-primary");
    for (const s of ["--surface-0", "--surface-1", "--surface-2", "--surface-3"]) {
      expect(contrast(textPrimary, psiHex(s))).toBeGreaterThanOrEqual(4.5);
    }
  });

  it("data-up and data-down clear the 3:1 mark floor on every surface", () => {
    const dataUp = psiHex("--data-up");
    const dataDown = psiHex("--data-down");
    for (const s of ["--surface-0", "--surface-1", "--surface-2", "--surface-3"]) {
      expect(contrast(dataUp, psiHex(s))).toBeGreaterThanOrEqual(3);
      expect(contrast(dataDown, psiHex(s))).toBeGreaterThanOrEqual(3);
    }
  });

  it("border-strong reads as a real rule (>=3:1), not a hairline", () => {
    const borderStrong = psiHex("--border-strong");
    const s0 = psiHex("--surface-0");
    expect(contrast(borderStrong, s0)).toBeGreaterThanOrEqual(3);
  });
});

describe("ds.css discipline", () => {
  it("contains no raw hex colors — tokens only", () => {
    const hexes = dsCss.match(/#[0-9a-fA-F]{3,8}\b/g) || [];
    expect(hexes).toEqual([]);
  });

  it("styles aria-disabled buttons like natively disabled ones and excludes them from hover/active", () => {
    // link-rendered Buttons (as="a"/as={Link}) never match :disabled
    expect(dsCss).toContain('.ds-btn[aria-disabled="true"]');
    const hoverActive = dsCss.match(/\.ds-btn[^,{]*:(hover|active)[^,{]*/g) || [];
    expect(hoverActive.length).toBeGreaterThan(0);
    for (const sel of hoverActive) {
      expect(sel).toContain(':not([aria-disabled="true"])');
    }
  });

  it("defines the responsive column-hide rules DataTable's hideBelow emits", () => {
    for (const bp of ["sm", "md", "lg"]) {
      expect(dsCss).toContain(`.ds-col-hide-${bp}`);
    }
  });

  it("namespaces every class as .ds-*", () => {
    const classes = [...dsCss.matchAll(/\.([a-zA-Z][a-zA-Z0-9_-]*)/g)]
      .map((m) => m[1])
      .filter((c) => !c.startsWith("ds-"));
    expect([...new Set(classes)]).toEqual([]);
  });
});
