// Categorical chart palette — contrast + colour-vision proof (Owner Decision
// 14, 2026-10-18, closing #1428).
//
// Reads the --chart-1..6 slots out of app/tokens.css for each theme scope
// (dark :root, the [data-theme="light"] scaffold, the .psi-editorial cream
// scope) and computes — never eyeballs — WCAG contrast against every surface
// a chart can sit on in that scope, for every mark treatment the token-routed
// charts actually use, plus CVD separation under the Machado-Oliveira-
// Fernandes (2009) severity-1.0 simulation, measured as OKLab ΔE × 100 (the
// same model and thresholds as the dataviz palette validator that produced
// docs/DESIGN-SYSTEM.md's original numbers).
//
// Targets are fixed, never weakened: marks >= 3:1, text >= 4.5:1.
import { describe, expect, it } from "vitest";
import fs from "node:fs";
import path from "node:path";

const root = path.resolve(__dirname, "..", "..", "..");
const css = fs
  .readFileSync(path.join(root, "app/tokens.css"), "utf8")
  .replace(/\/\*[\s\S]*?\*\//g, "");

function block(selector) {
  const start = css.indexOf(`${selector} {`);
  if (start === -1) throw new Error(`missing ${selector}`);
  return css.slice(start, css.indexOf("\n}", start));
}
function props(text) {
  const out = {};
  for (const m of text.matchAll(/(--[a-z0-9-]+)\s*:\s*([^;]+);/g)) out[m[1]] = m[2].trim();
  return out;
}
const DARK = props(block(":root"));
const SCOPES = {
  dark: DARK,
  light: { ...DARK, ...props(block(':root[data-theme="light"]')) },
  cream: { ...DARK, ...props(block(".psi-editorial")) },
};
function resolve(scope, name, depth = 0) {
  const v = SCOPES[scope][name];
  if (v === undefined) throw new Error(`${scope}: ${name} undefined`);
  const ref = v.match(/^var\((--[a-z0-9-]+)\)$/);
  return ref && depth < 5 ? resolve(scope, ref[1], depth + 1) : v;
}

// ── colour math ───────────────────────────────────────────────────────────
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
const over = (fg, alpha, bg) => toHex(rgb(fg).map((v, i) => v * alpha + rgb(bg)[i] * (1 - alpha)));
function composite(value, bg) {
  if (value.startsWith("#")) return value;
  const m = value.match(/rgba\((\d+),\s*(\d+),\s*(\d+),\s*([\d.]+)\)/);
  if (!m) throw new Error(`unparsed colour ${value}`);
  return over(toHex([m[1], m[2], m[3]].map((n) => Number(n) / 255)), Number(m[4]), bg);
}

const MACHADO = {
  protan: [[0.152286, 1.052583, -0.204868], [0.114503, 0.786281, 0.099216], [-0.003882, -0.048116, 1.051998]],
  deutan: [[0.367322, 0.860646, -0.227968], [0.280085, 0.672501, 0.047413], [-0.01182, 0.04294, 0.968881]],
  tritan: [[1.255528, -0.076749, -0.178779], [-0.078411, 0.930809, 0.147602], [0.004733, 0.691367, 0.3039]],
};
function oklab([r, g, b]) {
  const l = Math.cbrt(0.4122214708 * r + 0.5363325363 * g + 0.0514459929 * b);
  const m = Math.cbrt(0.2119034982 * r + 0.6806995451 * g + 0.1073969566 * b);
  const s = Math.cbrt(0.0883024619 * r + 0.2817188376 * g + 0.6299787005 * b);
  return [
    0.2104542553 * l + 0.793617785 * m - 0.0040720468 * s,
    1.9779984951 * l - 2.428592205 * m + 0.4505937099 * s,
    0.0259040371 * l + 0.7827717662 * m - 0.808675766 * s,
  ];
}
function linSim(hex, kind) {
  const c = rgb(hex).map(s2lin);
  if (!kind) return c;
  return MACHADO[kind].map((row) => Math.max(0, Math.min(1, row[0] * c[0] + row[1] * c[1] + row[2] * c[2])));
}
const deltaE = (a, b, kind) => {
  const [x, y] = [oklab(linSim(a, kind)), oklab(linSim(b, kind))];
  return 100 * Math.hypot(x[0] - y[0], x[1] - y[1], x[2] - y[2]);
};
const hue = (hex) => {
  const [, a, b] = oklab(linSim(hex));
  return ((Math.atan2(b, a) * 180) / Math.PI + 360) % 360;
};

// ── what is measured ─────────────────────────────────────────────────────
const D14 = ["#986400", "#2264af", "#ac386a", "#6752b6", "#087650", "#aa3c17"];
const slots = (scope) => [1, 2, 3, 4, 5, 6].map((i) => resolve(scope, `--chart-${i}`));
const surfaces = (scope) => [0, 1, 2, 3].map((i) => resolve(scope, `--surface-${i}`));
// Opacities the token-routed charts draw series marks at: 1 (Sparkline line +
// endpoint dot, Meter/source bars, every line chart), 0.9 (Hill/age-curve
// dots, Sankey nodes, multi-team flow links), 0.85 (Hill legend keys).
const MARK_ALPHAS = [1, 0.9, 0.85];
const MARK_MIN = 3;
const TEXT_MIN = 4.5;

function contrastTable() {
  return Object.fromEntries(
    Object.keys(SCOPES).map((scope) => [
      scope,
      Object.fromEntries(surfaces(scope).map((s) => [s, Math.min(...slots(scope).map((c) => ratio(c, s)))])),
    ]),
  );
}

describe("chart slots: Owner Decision 14 values and order", () => {
  it("reports the minimum slot contrast per surface and scope", () => {
    const table = contrastTable();
    if (process.env.CHART_CONTRAST_REPORT) console.log(JSON.stringify(table, null, 2));
    for (const [scope, row] of Object.entries(table)) {
      for (const [s, min] of Object.entries(row)) expect(min, `${scope} ${s}`).toBeGreaterThanOrEqual(MARK_MIN);
    }
  });

  it("cream and light scopes carry exactly the approved six, in categorical order", () => {
    expect(slots("cream")).toEqual(D14);
    expect(slots("light")).toEqual(D14);
  });

  it("reproduces the owner's figures on the nested cream surface #e9dfca", () => {
    expect(resolve("cream", "--surface-2")).toBe("#e9dfca");
    expect(D14.map((c) => Number(ratio(c, "#e9dfca").toFixed(2)))).toEqual([3.82, 4.52, 4.5, 4.59, 4.27, 4.71]);
  });

  it("dark keeps its own steps of the SAME hue family, in the same order", () => {
    const dark = slots("dark");
    // The light-surface steps fall to 2.5-3.1:1 on the dark surfaces…
    const worst = Math.min(...surfaces("dark").flatMap((s) => D14.map((c) => ratio(c, s))));
    expect(worst).toBeLessThan(MARK_MIN);
    // …so dark uses its validated variants; each within 10° OKLCH hue.
    dark.forEach((c, i) => {
      const d = Math.abs(hue(c) - hue(D14[i]));
      expect(Math.min(d, 360 - d), `slot ${i + 1}`).toBeLessThanOrEqual(10);
    });
  });

  it("never colours text with a series slot (text wears --text-*)", () => {
    const dirs = ["app", "components"].map((d) => path.join(root, d));
    const offenders = [];
    const walk = (dir) => {
      for (const e of fs.readdirSync(dir, { withFileTypes: true })) {
        const p = path.join(dir, e.name);
        if (e.isDirectory()) walk(p);
        else if (/\.css$/.test(e.name) && /(^|[\s;{])color:\s*var\(--chart-[1-6]\)/.test(fs.readFileSync(p, "utf8"))) {
          offenders.push(path.relative(root, p));
        }
      }
    };
    dirs.forEach(walk);
    expect(offenders).toEqual([]);
  });
});

describe.each(Object.keys(SCOPES))("%s scope contrast", (scope) => {
  it.each(MARK_ALPHAS)("every slot clears 3:1 on every surface at mark opacity %s", (alpha) => {
    for (const s of surfaces(scope)) {
      slots(scope).forEach((c, i) => {
        expect(ratio(over(c, alpha, s), s), `${scope} slot ${i + 1} @${alpha} on ${s}`).toBeGreaterThanOrEqual(MARK_MIN);
      });
    }
  });

  it("Meter / source-bar fills clear 3:1 against their --surface-active track", () => {
    const active = resolve(scope, "--surface-active");
    for (const s of surfaces(scope)) {
      const track = composite(active, s);
      slots(scope).forEach((c, i) => {
        expect(ratio(c, track), `${scope} slot ${i + 1} on track over ${s}`).toBeGreaterThanOrEqual(MARK_MIN);
      });
    }
  });

  it("the fold ink for a 7th+ series clears the TEXT floor everywhere", () => {
    const other = resolve(scope, "--text-tertiary");
    for (const s of surfaces(scope)) expect(ratio(other, s), `${scope} on ${s}`).toBeGreaterThanOrEqual(TEXT_MIN);
  });

  it("node labels on a series wash (multi-team flow) clear 4.5:1", () => {
    const ink = resolve(scope, "--text-primary");
    const panel = resolve(scope, "--surface-1");
    slots(scope).forEach((c, i) => {
      expect(ratio(ink, over(c, 0.14, panel)), `${scope} slot ${i + 1}`).toBeGreaterThanOrEqual(TEXT_MIN);
    });
  });
});

describe.each(["dark", "cream"])("%s scope colour-vision separation", (scope) => {
  const pal = () => slots(scope);
  const adjacent = (p) => p.slice(0, -1).map((c, i) => [c, p[i + 1]]);

  it("adjacent slots stay >= 15 ΔE under normal vision (hard floor)", () => {
    for (const [a, b] of adjacent(pal())) expect(deltaE(a, b), `${a}↔${b}`).toBeGreaterThanOrEqual(15);
  });

  it("adjacent slots stay >= 6 ΔE under protan / deutan / tritan simulation", () => {
    for (const kind of ["protan", "deutan", "tritan"]) {
      for (const [a, b] of adjacent(pal())) expect(deltaE(a, b, kind), `${kind} ${a}↔${b}`).toBeGreaterThanOrEqual(6);
    }
  });

  it("the first three slots are scatter-safe: all pairs >= 8 ΔE protan/deutan", () => {
    const p = pal().slice(0, 3);
    for (const kind of ["protan", "deutan"]) {
      for (let i = 0; i < 3; i++) {
        for (let j = i + 1; j < 3; j++) expect(deltaE(p[i], p[j], kind)).toBeGreaterThanOrEqual(8);
      }
    }
  });

  it("names the only pairs in the 6-8 floor band, which require secondary encoding", () => {
    const floor = [];
    for (const kind of ["protan", "deutan", "tritan"]) {
      adjacent(pal()).forEach(([a, b], i) => {
        if (deltaE(a, b, kind) < 8) floor.push(`${kind}:${i + 1}-${i + 2}`);
      });
    }
    // Cream: aqua↔orange for deutans, violet↔aqua for tritans (both 7.8).
    // Dark: none (worst 9.4). Every token-routed chart labels its series.
    expect(floor).toEqual(scope === "cream" ? ["deutan:5-6", "tritan:4-5"] : []);
  });
});
