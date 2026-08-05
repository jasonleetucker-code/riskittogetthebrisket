/**
 * The Value Adjustment tooltip must describe the number beside it.
 *
 * W08-F002. The `/trade` side header renders "Raw N + VA M" with a
 * tooltip that read: "the side with fewer pieces frees a roster spot,
 * so KTC-style math adds this bonus on top of the raw total."
 *
 * `ktcAdjustPackage` does not choose a side by piece count. It chooses
 * by raw-adjustment INTENSITY — `e / team1Total` vs `a / team2Total`,
 * i.e. which side's value is concentrated in its biggest pieces.
 * Piece count enters only through the per-item progressive nerf and the
 * 1-for-1 suppression. Over 50,000 sampled 1-4 vs 1-4 trades built from
 * the live board the VA fired 21,610 times: 53.3% to the side with
 * fewer pieces, 31.5% on equal counts, and 15.1% to the side with MORE.
 *
 * This is the same class of defect as R28's field-name collisions: a
 * label asserting a property the number does not have. The fix is the
 * label, not the algorithm — `ktc_va.py` / `ktcAdjustPackage` are a
 * deliberate verbatim port of KTC's own client-side code, and changing
 * the arithmetic would break the parity that makes our meter match the
 * site a counterparty is checking.
 */
import { describe, expect, it } from "vitest";
import fs from "node:fs";
import path from "node:path";
import { ktcAdjustPackage } from "@/lib/trade-logic";

const SECTIONS = path.join(
  process.cwd(),
  "app",
  "trade",
  "trade-sections.jsx",
);

function vaTooltip() {
  const src = fs.readFileSync(SECTIONS, "utf8");
  const match = src.match(/title="([^"]*\bVA\b[^"]*|[^"]*premium[^"]*)"/);
  expect(match, "the VA tooltip is no longer findable in the source").toBeTruthy();
  return match[1];
}

describe("the VA tooltip describes what ktcAdjustPackage actually does", () => {
  it("the bonus can land on the side with MORE pieces", () => {
    // The live case from the finding, board values verbatim:
    // A = Bijan Robinson + Tyjae Spears + Jessie Bates + Kyle Hamilton
    //     (4 pieces)
    // B = Jadarian Price + Dak Prescott + 2028 Late 1st (3 pieces)
    const a = [9706, 2121, 1707, 3062];
    const b = [4286, 5519, 4079];
    const out = ktcAdjustPackage(a, b);
    expect(out.displayed).toBe(true);
    expect(out.value).toBe(3815);
    // side 1 is `a` — the side with MORE pieces.
    expect(out.side).toBe(1);
    expect(a.length).toBeGreaterThan(b.length);
  });

  it("the tooltip does not claim the bonus goes to the side with fewer pieces", () => {
    expect(vaTooltip()).not.toMatch(/side with fewer pieces frees/i);
  });

  it("the tooltip names concentration, which is what actually selects the side", () => {
    expect(vaTooltip()).toMatch(/concentrat/i);
  });
});
