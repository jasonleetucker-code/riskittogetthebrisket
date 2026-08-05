/**
 * The measured TE-basis curve must be reachable from a browser.
 *
 * `config/weights/te_premium_curve.json` is a curve fitted from KTC's own
 * base vs TE++ boards (floor 1.2092 at the top of the board rising toward
 * 2.0531 down it, n=73, r²=0.941). The backend applies it via
 * `convert_te_value` — but only when the operator has NOT typed an
 * explicit slider value, which is the right rule: a number someone chose
 * is a decision, not a measurement to overrule.
 *
 * The defect was that the frontend always claimed to have chosen one.
 * `SETTINGS_DEFAULTS.tepMultiplier` was a concrete `1.15` and
 * `tepMultiplierIsCustomized` counts ANY finite number as a choice, so
 * every page load posted `{tep_multiplier: 1.15}`, the backend took its
 * override branch, and the curve never ran for real traffic. Because the
 * flat 1.15 sits BELOW the curve's measured floor, every TE from a
 * non-TEP source was under-lifted at every point on the board.
 *
 * Nothing asserted any of this — there was no test anywhere on what the
 * DEFAULT does, only on what explicit values do. That gap is why a
 * one-literal defect survived in the settings a user never touches.
 */

import { describe, it, expect } from "vitest";
import { SETTINGS_DEFAULTS } from "../components/useSettings.js";
import {
  tepMultiplierIsCustomized,
  tepNativeMultiplierIsCustomized,
} from "../lib/dynasty-data.js";

describe("the TEP default is auto, not a number", () => {
  it("SETTINGS_DEFAULTS.tepMultiplier is nullish", () => {
    // The whole defect in one assertion.
    expect(SETTINGS_DEFAULTS.tepMultiplier ?? null).toBeNull();
  });

  it("default settings are not 'customized', so no override is posted", () => {
    // `fetchDynastyData` stamps `body.tep_multiplier` only when this is
    // true, and routes to the plain cached contract when nothing is
    // customized. False here IS "the backend gets to apply the curve".
    expect(tepMultiplierIsCustomized(SETTINGS_DEFAULTS.tepMultiplier)).toBe(false);
    expect(tepNativeMultiplierIsCustomized(SETTINGS_DEFAULTS.tepNativeMultiplier)).toBe(false);
  });

  it("still treats an explicitly chosen number as an override", () => {
    // The fix must not make deliberate overrides unreachable — including
    // an explicit 1.15, which is indistinguishable from the old default
    // by value and distinguishable only by being nullish or not.
    for (const chosen of [1.0, 1.15, 1.25, 1.3, 1.5]) {
      expect(tepMultiplierIsCustomized(chosen)).toBe(true);
    }
  });

  it("matches the native knob, which always had the sentinel", () => {
    // tepNativeMultiplier was the working reference implementation of
    // this pattern the whole time; the two should now be symmetrical.
    expect(SETTINGS_DEFAULTS.tepMultiplier ?? null).toBe(
      SETTINGS_DEFAULTS.tepNativeMultiplier ?? null,
    );
  });
});

describe("the auto-restore migration", () => {
  it("declares a NEW one-shot key rather than reusing the old one", () => {
    // `tepDefaultV3Applied` is already true in every install that has
    // ever loaded the site — the old migration set it unconditionally.
    // Reusing it would make the restore a no-op on exactly the installs
    // that need it, which is the trap this asserts against.
    expect(SETTINGS_DEFAULTS.tepAutoRestored).toBe(false);
    expect(SETTINGS_DEFAULTS.tepDefaultV3Applied).toBeUndefined();
  });
});
