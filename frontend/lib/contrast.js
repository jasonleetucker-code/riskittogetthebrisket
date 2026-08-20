/**
 * Pick a foreground that is actually readable on a given background.
 *
 * WHY THIS IS NOT A STYLE CHOICE
 * ──────────────────────────────
 * `/rosters` renders its position filter as chips whose active state is a
 * saturated background with hardcoded white text. axe-core measured **57
 * nodes** below the WCAG AA 4.5:1 floor there, several badly:
 *
 *     TE  #e67e22 + white = 2.85:1
 *     RB  #27ae60 + white = 2.87:1
 *     WR  #3498db + white = 3.15:1
 *     QB  #e74c3c + white = 3.82:1
 *
 * The fix is deliberately NOT "darken the palette". Those hues also carry
 * meaning elsewhere as marks, where the bar is 3:1 and they pass; changing
 * them to satisfy a text rule would move a mark colour to fix a label. And
 * a fixed palette tweak would need redoing the moment the palette moves —
 * which is a live open decision (`OD-05`).
 *
 * So: compute it. `readableTextOn` returns whichever of black or white the
 * background actually supports, by WCAG relative luminance. Every current
 * position colour clears 4.5:1 under this rule (worst case DL at 4.67),
 * and any future colour is handled without anyone remembering to check.
 *
 * `contrastRatio` is exported because a rule you cannot measure is a rule
 * nobody can hold you to — the test asserts the real ratios.
 */

/** sRGB channel -> linear, per WCAG 2.x. */
function channelToLinear(value) {
  const c = value / 255;
  return c <= 0.03928 ? c / 12.92 : Math.pow((c + 0.055) / 1.055, 2.4);
}

/**
 * WCAG relative luminance of a `#rgb` or `#rrggbb` colour.
 * Returns null for anything it cannot parse — never a plausible 0, which
 * would silently claim "this is black" about a colour it did not read.
 */
export function relativeLuminance(hex) {
  if (typeof hex !== "string") return null;
  let h = hex.trim().replace(/^#/, "");
  if (h.length === 3) h = h.split("").map((c) => c + c).join("");
  if (!/^[0-9a-fA-F]{6}$/.test(h)) return null;
  const n = parseInt(h, 16);
  return (
    0.2126 * channelToLinear((n >> 16) & 255) +
    0.7152 * channelToLinear((n >> 8) & 255) +
    0.0722 * channelToLinear(n & 255)
  );
}

/** WCAG contrast ratio between two luminances (1..21). */
export function contrastRatio(lumA, lumB) {
  if (lumA == null || lumB == null) return null;
  const hi = Math.max(lumA, lumB);
  const lo = Math.min(lumA, lumB);
  return (hi + 0.05) / (lo + 0.05);
}

const BLACK = "#000000";
const WHITE = "#ffffff";

/**
 * The more readable of black or white on `background`.
 *
 * Falls back to white for an unparseable background — the previous
 * behaviour, so a colour this cannot read is no worse off than before.
 */
export function readableTextOn(background) {
  const lum = relativeLuminance(background);
  if (lum == null) return WHITE;
  return contrastRatio(lum, 1) >= contrastRatio(lum, 0) ? WHITE : BLACK;
}

/* ─────────────────────────────────────────────────────────────────────
 * Using a MARK colour as TEXT
 *
 * The design system already draws this distinction — "Base = marks
 * (>=3:1), `*-text` = copy (>=4.5:1)" — and the position palette does
 * not have the second half. So `/rosters`' legend renders DL at 3.91:1
 * and LB at 3.11:1 against the page, because a colour chosen to be
 * legible as a swatch was reused as a word.
 *
 * `textSafe` derives the missing half instead of asking someone to
 * hand-pick eight more hexes that would then need redoing when the
 * palette moves (`OD-05`). It walks the colour toward the far end of the
 * page's own luminance until it clears the ratio, so it LIGHTENS on a
 * dark surface and DARKENS on a light one, and the hue survives.
 * ───────────────────────────────────────────────────────────────────── */

function parseHex(hex) {
  if (typeof hex !== "string") return null;
  let h = hex.trim().replace(/^#/, "");
  if (h.length === 3) h = h.split("").map((c) => c + c).join("");
  if (!/^[0-9a-fA-F]{6}$/.test(h)) return null;
  const n = parseInt(h, 16);
  return [(n >> 16) & 255, (n >> 8) & 255, n & 255];
}

function toHex([r, g, bl]) {
  const clamp = (v) => Math.max(0, Math.min(255, Math.round(v)));
  return (
    "#" +
    [r, g, bl].map((v) => clamp(v).toString(16).padStart(2, "0")).join("")
  );
}

/**
 * A version of `color` that reaches `minRatio` against `background`,
 * keeping the hue.
 *
 * Returns `color` unchanged when it already passes — so a palette that
 * is already conformant is untouched, and this is a floor rather than a
 * restyle. Returns the plain black/white fallback if even the extreme is
 * not enough, which cannot happen for any real hue but is not worth
 * asserting away.
 *
 * @param {string} color       the mark colour
 * @param {string} background  the surface it will sit on
 * @param {number} [minRatio]  WCAG AA body text by default
 */
export function textSafe(color, background, minRatio = 4.5) {
  const rgb = parseHex(color);
  const bgLum = relativeLuminance(background);
  if (!rgb || bgLum == null) return color;
  if (contrastRatio(relativeLuminance(color), bgLum) >= minRatio) return color;

  // Move toward white on a dark surface, toward black on a light one.
  const towardWhite = bgLum < 0.5;
  const target = towardWhite ? 255 : 0;
  // 24 steps is finer than the eye resolves over this range and keeps the
  // search exact enough that the result is stable across renders.
  for (let step = 1; step <= 24; step += 1) {
    const t = step / 24;
    const candidate = toHex(rgb.map((c) => c + (target - c) * t));
    if (contrastRatio(relativeLuminance(candidate), bgLum) >= minRatio) {
      return candidate;
    }
  }
  return towardWhite ? WHITE : BLACK;
}
