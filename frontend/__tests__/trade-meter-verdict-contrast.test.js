// The /trade meter's verdict pill (FAIR / SLIGHT EDGE / UNFAIR / LOPSIDED)
// must clear WCAG AA text contrast in every scope the meter renders in —
// computed from the stylesheets, never eyeballed.
//
// Why this exists (#1918): the UNFAIR pill wore a literal `#fb923c`, the one
// verdict colour that did not route through a theme token.  On the dark
// terminal surface it reads ~6.7:1; inside the cream `.psi-editorial` scope
// /trade renders in, it reads ~1.9:1.  The E2E TC-E journey's axe scan only
// meets it when the LIVE seeded board happens to produce an UNFAIR trade
// (it did on 2026-10-23: "color-contrast: .trade-meter-verdict"), so this
// pins the property deterministically instead.
import { describe, expect, it } from "vitest";
import fs from "node:fs";
import path from "node:path";

const root = path.resolve(__dirname, "..");
const strip = (text) => text.replace(/\/\*[\s\S]*?\*\//g, "");
const tokens = strip(fs.readFileSync(path.join(root, "app/tokens.css"), "utf8"));
const globals = strip(fs.readFileSync(path.join(root, "app/globals.css"), "utf8"));

function block(css, selector) {
  const start = css.indexOf(`${selector} {`);
  if (start === -1) throw new Error(`missing ${selector}`);
  return css.slice(start, css.indexOf("}", start));
}
function props(text) {
  const out = {};
  for (const m of text.matchAll(/(--[a-z0-9-]+)\s*:\s*([^;]+);/g)) out[m[1]] = m[2].trim();
  return out;
}
function decls(text) {
  const out = {};
  for (const m of text.matchAll(/(?:^|[;{\s])(color|background)\s*:\s*([^;]+);/g)) out[m[1]] = m[2].trim();
  return out;
}

// The dark terminal :root is globals.css's legacy palette over tokens.css's
// semantic layer; the cream scope re-maps both (tokens.css `.psi-editorial`).
const DARK = { ...props(block(tokens, ":root")), ...props(block(globals, ":root")) };
const SCOPES = { dark: DARK, cream: { ...DARK, ...props(block(tokens, ".psi-editorial")) } };

function resolve(scope, value, depth = 0) {
  const ref = value.match(/^var\((--[a-z0-9-]+)\)$/);
  if (!ref) return value;
  const next = SCOPES[scope][ref[1]];
  if (next === undefined) throw new Error(`${scope}: ${ref[1]} undefined`);
  return depth < 6 ? resolve(scope, next, depth + 1) : next;
}

const rgb = (hex) => [1, 3, 5].map((i) => parseInt(hex.slice(i, i + 2), 16) / 255);
const s2lin = (c) => (c <= 0.04045 ? c / 12.92 : ((c + 0.055) / 1.055) ** 2.4);
const lum = (hex) => {
  const [r, g, b] = rgb(hex).map(s2lin);
  return 0.2126 * r + 0.7152 * g + 0.0722 * b;
};
const ratio = (a, b) => {
  const [hi, lo] = [lum(a), lum(b)].sort((x, y) => y - x);
  return (hi + 0.05) / (lo + 0.05);
};
const toHex = (c) => `#${c.map((v) => Math.round(v * 255).toString(16).padStart(2, "0")).join("")}`;
function composite(value, bg) {
  if (value.startsWith("#")) return value;
  const m = value.match(/rgba\((\d+),\s*(\d+),\s*(\d+),\s*([\d.]+)\)/);
  if (!m) throw new Error(`unparsed colour ${value}`);
  const fg = [m[1], m[2], m[3]].map((n) => Number(n) / 255);
  const a = Number(m[4]);
  return toHex(fg.map((v, i) => v * a + rgb(bg)[i] * (1 - a)));
}

const VERDICTS = ["fair", "slight", "unfair", "lopsided"];
const TEXT_MIN = 4.5; // 0.78rem bold is not "large text"

describe("trade meter verdict pill contrast", () => {
  for (const verdict of VERDICTS) {
    const rule = decls(block(globals, `.trade-meter-verdict-${verdict}`));

    it(`${verdict}: text colour routes through a theme token`, () => {
      expect(rule.color).toMatch(/^var\(--[a-z0-9-]+\)$/);
    });

    for (const scope of Object.keys(SCOPES)) {
      it(`${verdict}: >= ${TEXT_MIN}:1 on the meter surface (${scope})`, () => {
        // `.trade-meter` sits on --surface-1; the pill's tint composites over it.
        const surface = resolve(scope, "var(--surface-1)");
        const bg = composite(resolve(scope, rule.background), surface);
        const fg = resolve(scope, rule.color);
        expect(ratio(fg, bg)).toBeGreaterThanOrEqual(TEXT_MIN);
      });
    }
  }
});
