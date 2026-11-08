/**
 * Owner directive 2026-11-08: product wording must not present a relative
 * ranking, a prior table or a threshold bucket as a calibrated probability,
 * certainty or proof that the market is wrong.  Display wording only.
 */
import { describe, expect, it } from "vitest";
import fs from "node:fs";
import path from "node:path";

import { _renderPlainSummary } from "@/components/ui/MonteCarloButton";
import { postureText } from "@/lib/waiver-advisor";
import { bdvmSignalLabel } from "@/lib/bdvm";
import { labelText, reasonText, labelTone } from "@/lib/consensus-edge";

const root = path.resolve(__dirname, "..");
const read = (p) => fs.readFileSync(path.join(root, p), "utf8");
const MEASURED = { stamped_value_band: 3 };
const sides = undefined;

describe("Monte Carlo reads as simulation frequency, not certainty", () => {
  it("never says winner/favored outside /trade", () => {
    for (const winProbA of [0.95, 0.7, 0.5, 0.3, 0.05]) {
      const s = _renderPlainSummary({ winProbA, nSims: 2000, bandSources: MEASURED }, sides);
      const text = `${s.headline} ${s.subline}`;
      expect(text).not.toMatch(/winner|favou?red|certain|guarantee/i);
      expect(s.subline).toMatch(/\d+% of 2,000 simulations|neither side led consistently/);
    }
    expect(_renderPlainSummary({ winProbA: 0.9, nSims: 2000, bandSources: MEASURED }, sides).headline).toBe(
      "Side A led in most simulations.",
    );
    expect(_renderPlainSummary({ winProbA: 0.1, nSims: 2000, bandSources: MEASURED }, sides).headline).toBe(
      "Side B led in most simulations.",
    );
  });
});

describe("posture share is not labelled confidence", () => {
  it("states a model share, uncalibrated", () => {
    const t = postureText({ state: "available", label: "PUSH", confidence: 0.61 });
    expect(t.note).toBe("61% model share (uncalibrated) · context only");
    expect(t.note).not.toMatch(/confidence/i);
    expect(postureText({ state: "available", label: "HOLD", confidence: null }).note).toBe(
      "no measured model share · context only",
    );
  });
});

describe("source-level wording guards", () => {
  it("/arbitrage: no STRONG BUY/SELL badge; Edge is defined", () => {
    const s = read("app/arbitrage/page.jsx");
    expect(s).not.toMatch(/STRONG BUY|STRONG SELL/);
    expect(s).toContain("BUY · LARGE GAP");
    expect(s).toContain("Edge % (board vs market)");
  });
  it("/draft: Hit % is marked as a prior, not a fitted probability", () => {
    const s = read("app/draft/page.jsx");
    expect(s).not.toContain("Probability the pick returns a startable player");
    expect(s).toContain("Hit % (prior)");
    expect(s).toContain("placeholder prior table");
  });
  it("no surface asserts 'market overvalues' as fact", () => {
    for (const f of [
      "components/PlayerPopup.jsx",
      "app/players/[playerId]/page.jsx",
      "app/rosters/page.jsx",
    ]) {
      const s = read(f);
      expect(s, f).not.toMatch(/market overvalues|Market overvalues|market is cheap|Market undervalues/);
    }
    expect(read("components/PlayerPopup.jsx")).toContain("a gap, not proof of mispricing");
  });
});

describe("STRONG_* bands are labelled as threshold bands", () => {
  it("BDVM signal display text names the gap band; enum untouched", () => {
    expect(bdvmSignalLabel("STRONG_BUY")).toBe("Buy · large gap");
    expect(bdvmSignalLabel("STRONG_SELL")).toBe("Sell · large gap");
    expect(bdvmSignalLabel("BUY")).toBe("Buy");
    expect(bdvmSignalLabel("NO_MARKET")).toBe("No market");
    expect(bdvmSignalLabel("")).toBe("");
    for (const s of ["STRONG_BUY", "STRONG_SELL", "BUY", "SELL", "HOLD", "NO_MARKET"]) {
      expect(bdvmSignalLabel(s)).not.toMatch(/strong/i);
    }
    expect(read("app/bdvm/page.jsx")).not.toMatch(/Strong (buy|sell)/);
    expect(read("app/rankings/page.jsx")).toContain("bdvmSignalLabel(entry.signal)");
    expect(read("app/draft/page.jsx")).toContain("bdvmSignalLabel(entry.signal)");
  });
  it("Consensus Edge badge/reason text names the score band; tone and API label untouched", () => {
    expect(labelText("Strong Buy")).toBe("Buy · large score");
    expect(labelText("Strong Sell")).toBe("Sell · large score");
    expect(labelText("Buy")).toBe("Buy");
    expect(labelText("Conflicted")).toBe("Conflicted");
    expect(reasonText("score reaches Strong Buy but confidence 69 < 70")).toBe(
      "score reaches large-score Buy but confidence 69 < 70",
    );
    expect(reasonText(null)).toBe(null);
    expect(labelTone("Strong Buy")).not.toBe(labelTone("Buy"));
    const page = read("app/consensus-edge/page.jsx");
    expect(page).not.toMatch(/Strong Buy|Strong Sell/);
    expect(page).toContain("labelText(row.label)");
  });
});
