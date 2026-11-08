import { describe, expect, it } from "vitest";
import fs from "node:fs";
import path from "node:path";

const read = file => fs.readFileSync(path.resolve(__dirname, "..", file), "utf8").replace(/\/\*[\s\S]*?\*\//g, "");
const tokens = read("app/tokens.css"), globals = read("app/globals.css");
const block = (css, selector) => {
  const start = css.indexOf(`${selector} {`);
  expect(start).toBeGreaterThanOrEqual(0);
  return css.slice(start, css.indexOf("\n}", start));
};
const properties = text => Object.fromEntries([...text.matchAll(/(--[\w-]+)\s*:\s*([^;]+);/g)].map(m => [m[1], m[2].trim()]));
const defaults = properties(block(tokens, ":root"));
const luminance = hex => {
  const channels = [1,3,5].map(i => parseInt(hex.slice(i,i+2),16)/255).map(c => c<=0.04045?c/12.92:((c+0.055)/1.055)**2.4);
  return channels[0]*0.2126+channels[1]*0.7152+channels[2]*0.0722;
};
const ratio = (a,b) => {const [hi,lo] = [luminance(a),luminance(b)].sort((x,y)=>y-x);return (hi+.05)/(lo+.05);};

describe("Sports Network foundation on active and legacy surfaces", () => {
  it("keeps normal text readable across the default and compatibility canvases", () => {
    for (const selector of [":root", ':root[data-theme="light"]', ".psi-editorial"]) {
      const scope={...defaults,...properties(block(tokens,selector))};
      for(const text of ["--text-primary","--text-secondary","--text-tertiary"])
        for(const surface of ["--surface-0","--surface-1","--surface-2","--surface-3"])
          expect(ratio(scope[text],scope[surface]),`${selector} ${text} on ${surface}`).toBeGreaterThanOrEqual(4.5);
    }
  });
  it("uses a readable navy/coral control pair, rather than coral small text on cream", () => {
    expect(ratio(defaults["--sn-navy"],defaults["--sn-coral"])).toBeGreaterThanOrEqual(4.5);
    expect(ratio(defaults["--accent"],defaults["--surface-2"])).toBeGreaterThanOrEqual(4.5);
  });
  it("protects raw-table headers and frozen columns from dark-theme literals", () => {
    const header=block(globals,"th"), frozen=block(globals,".sticky-name");
    expect(header).toContain("background: var(--surface-2)");
    expect(header).toContain("color: var(--text-secondary)");
    expect(frozen).toContain("background: var(--surface-1)");
    expect(ratio(defaults["--text-secondary"],defaults["--surface-2"])).toBeGreaterThanOrEqual(4.5);
  });
  it("gives legacy profit/loss copy the same semantic text colors as current components", () => {
    const aliases=properties(block(globals,":root"));
    expect(aliases["--success"]).toBe("var(--positive-text)");
    expect(aliases["--danger"]).toBe("var(--negative-text)");
    expect(aliases["--text-muted"]).toBe("var(--text-tertiary)");
    expect(ratio(defaults["--positive-text"],defaults["--surface-1"])).toBeGreaterThanOrEqual(4.5);
    expect(ratio(defaults["--negative-text"],defaults["--surface-1"])).toBeGreaterThanOrEqual(4.5);
  });
});
