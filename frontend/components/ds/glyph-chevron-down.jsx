/**
 * The chevron-down glyph, as its OWN module.
 *
 * Why this exists rather than `<Icon name="chevron-down" />`:
 *
 * `Icon` is one module holding every glyph in a single `PATHS` object
 * literal, looked up at runtime by `name`. Three things make that
 * impossible to tree-shake — the object literal, the runtime lookup
 * (a bundler cannot know which `name` a caller passes), and
 * `ICON_NAMES = Object.keys(PATHS)`, which hard-references the whole
 * map. `sideEffects` is also absent from package.json. So any module
 * importing `Icon` ships the entire set.
 *
 * That was fine while every `Icon` consumer was a page already using
 * several glyphs. It stopped being fine when `Panel` — THE container
 * primitive — imported it for one disclosure chevron: every Panel
 * consumer paid ~2.2 KB for a glyph most of them never render.
 * Measured on `/league`, which uses Panel and no other icon: 171.0 KB
 * with the `Icon` import, 169.0 KB with this module.
 *
 * The fix is module granularity, NOT export granularity — splitting the
 * file is what lets the bundler drop the rest, and no amount of
 * renaming exports inside `Icon.jsx` would have achieved it.
 *
 * `Icon`'s public API is unchanged: app code still writes
 * `<Icon name="chevron-down" />` and `Icon` sources its geometry from
 * the same constant here, so there is exactly one definition of the
 * path. Only ds primitives that need a single glyph import it directly.
 */
"use client";

import React from "react";

/** Path geometry — the single source of truth, shared with `Icon`. */
export const CHEVRON_DOWN_D = "M3.5 6 8 10.5 12.5 6";

export function ChevronDown({ size = 16, className }) {
  return (
    <svg
      width={size}
      height={size}
      viewBox="0 0 16 16"
      fill="none"
      stroke="currentColor"
      strokeWidth="1.6"
      strokeLinecap="round"
      strokeLinejoin="round"
      className={className}
      aria-hidden="true"
    >
      <path d={CHEVRON_DOWN_D} />
    </svg>
  );
}
