/**
 * The contrast helper, and the 57 nodes it exists to fix.
 */
import { describe, it, expect } from "vitest";
import {
  readableTextOn,
  textSafe,
  contrastRatio,
  relativeLuminance,
} from "@/lib/contrast";
import { POS_GROUP_COLORS } from "@/lib/league-analysis";

const AA_TEXT = 4.5;

describe("readableTextOn", () => {
  it("clears WCAG AA on EVERY position colour", () => {
    // The assertion is over the real palette rather than a fixture, so a
    // colour added to POS_GROUP_COLORS tomorrow is covered the day it
    // lands — which is the failure mode a fixture would miss.
    for (const [group, bg] of Object.entries(POS_GROUP_COLORS)) {
      const fg = readableTextOn(bg);
      const ratio = contrastRatio(relativeLuminance(bg), relativeLuminance(fg));
      expect(ratio, `${group} (${bg}) on ${fg}`).toBeGreaterThanOrEqual(AA_TEXT);
    }
  });

  it("picks black where white was failing", () => {
    // The four worst offenders measured by axe on /rosters.
    expect(readableTextOn("#e67e22")).toBe("#000000"); // TE, was 2.85:1
    expect(readableTextOn("#27ae60")).toBe("#000000"); // RB, was 2.87:1
    expect(readableTextOn("#3498db")).toBe("#000000"); // WR, was 3.15:1
    expect(readableTextOn("#e74c3c")).toBe("#000000"); // QB, was 3.82:1
  });

  it("keeps white where white is already better", () => {
    // Not a blanket flip: two of the eight are dark enough that white
    // wins, and forcing black on them would create the same defect
    // pointing the other way.
    expect(readableTextOn("#8e44ad")).toBe("#ffffff"); // LB
    expect(readableTextOn("#9b59b6")).toBe("#ffffff"); // DL
  });

  it("handles 3-digit hex and is case-insensitive", () => {
    expect(readableTextOn("#FFF")).toBe("#000000");
    expect(readableTextOn("#000")).toBe("#ffffff");
    expect(readableTextOn("#E67E22")).toBe("#000000");
  });

  it("returns null luminance rather than a plausible zero", () => {
    // A 0 would read as "this colour is black" about a colour it could
    // not parse — missing is not zero, here either.
    expect(relativeLuminance("not-a-colour")).toBeNull();
    expect(relativeLuminance(null)).toBeNull();
    expect(relativeLuminance("#12345")).toBeNull();
    expect(contrastRatio(null, 1)).toBeNull();
  });

  it("falls back to white on an unreadable background", () => {
    // No worse than the behaviour it replaces.
    expect(readableTextOn("rgb(1,2,3)")).toBe("#ffffff");
    expect(readableTextOn(undefined)).toBe("#ffffff");
  });

  it("agrees with the known WCAG anchors", () => {
    expect(contrastRatio(relativeLuminance("#000"), relativeLuminance("#fff"))).toBeCloseTo(21, 1);
    expect(contrastRatio(relativeLuminance("#fff"), relativeLuminance("#fff"))).toBeCloseTo(1, 5);
  });
});

describe("textSafe", () => {
  // The surfaces a position label can land on: the page and the panel.
  // The PANEL is the lighter of the two, so a colour that clears the
  // floor there clears it everywhere — computing against the page was
  // the first pass's mistake and left LB at 4.36:1 on screen while the
  // arithmetic said it passed.
  const PAGE = "#0b0d10";
  const PANEL = "#131519";

  const ratio = (fg, bg) =>
    contrastRatio(relativeLuminance(fg), relativeLuminance(bg));

  it("clears AA on BOTH surfaces when derived against the lighter one", () => {
    for (const [group, mark] of Object.entries(POS_GROUP_COLORS)) {
      const text = textSafe(mark, PANEL);
      expect(ratio(text, PANEL), `${group} on panel`).toBeGreaterThanOrEqual(4.5);
      expect(ratio(text, PAGE), `${group} on page`).toBeGreaterThanOrEqual(4.5);
    }
  });

  it("leaves a colour that already passes completely alone", () => {
    // A floor, not a restyle: six of the eight position colours are
    // returned byte-identical, so this cannot quietly become a palette
    // change.
    const unchanged = Object.entries(POS_GROUP_COLORS).filter(
      ([, c]) => textSafe(c, PANEL) === c,
    );
    expect(unchanged.length).toBeGreaterThanOrEqual(6);
  });

  it("only lifts the two that were failing", () => {
    expect(textSafe("#9b59b6", PANEL)).not.toBe("#9b59b6"); // DL, was 3.91:1
    expect(textSafe("#8e44ad", PANEL)).not.toBe("#8e44ad"); // LB, was 3.11:1
  });

  it("darkens instead of lightening on a light surface", () => {
    // The direction is derived from the surface, not assumed dark — the
    // token layer ships a light-theme scaffold.
    const onLight = textSafe("#f39c12", "#ffffff");
    expect(ratio(onLight, "#ffffff")).toBeGreaterThanOrEqual(4.5);
    expect(relativeLuminance(onLight)).toBeLessThan(relativeLuminance("#f39c12"));
  });

  it("passes an unparseable input straight through", () => {
    expect(textSafe("var(--accent)", PANEL)).toBe("var(--accent)");
    expect(textSafe("#9b59b6", "not-a-colour")).toBe("#9b59b6");
  });
});
