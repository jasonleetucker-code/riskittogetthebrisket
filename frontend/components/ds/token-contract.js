/**
 * Token contract — the machine-readable list of custom properties that
 * frontend/app/tokens.css MUST define. This is the single source of truth
 * for "which tokens exist"; docs/DESIGN-SYSTEM.md documents the same list
 * for humans, and __tests__/components/ds/tokens-contract.test.js pins
 * tokens.css against it (missing token = failing test).
 *
 * When adding a token: add it to tokens.css AND here AND the docs table.
 * When removing one: grep components/ds + ds.css for consumers first.
 */

export const REQUIRED_TOKENS = [
  // Neutral ramp (primitives)
  "--neutral-0",
  "--neutral-50",
  "--neutral-100",
  "--neutral-200",
  "--neutral-300",
  "--neutral-400",
  "--neutral-500",
  "--neutral-600",
  "--neutral-700",
  "--neutral-750",
  "--neutral-800",
  "--neutral-850",
  "--neutral-900",
  "--neutral-950",
  "--neutral-1000",
  // Brand primitives: REMOVED with the Terminal direction. The accent is
  // structural now, not a franchise colour, and the old names are deleted
  // rather than aliased so a stray reference fails instead of rendering
  // something plausible.
  // Surfaces
  "--surface-0",
  "--surface-1",
  "--surface-2",
  "--surface-3",
  "--surface-hover",
  "--surface-active",
  "--surface-inverse",
  "--backdrop",
  "--surface-veil",
  "--surface-veil-raised",
  // Text
  "--text-primary",
  "--text-secondary",
  "--text-tertiary",
  "--text-disabled",
  "--text-inverse",
  // Borders
  "--border-subtle",
  "--border-default",
  "--border-strong",
  // Accent
  "--accent",
  "--accent-hover",
  "--accent-pressed",
  "--accent-muted",
  "--accent-border",
  "--text-on-accent",
  // Market direction — deliberately separate from good/bad state
  "--data-up",
  "--data-up-text",
  "--data-up-muted",
  "--data-down",
  "--data-down-text",
  "--data-down-muted",
  // Semantic state
  "--positive",
  "--positive-text",
  "--positive-muted",
  "--negative",
  "--negative-text",
  "--negative-muted",
  "--warning",
  "--warning-text",
  "--warning-muted",
  "--info",
  "--info-text",
  "--info-muted",
  "--neutral-signal",
  "--neutral-signal-muted",
  // Focus
  "--focus-ring",
  "--focus-ring-color",
  // Charts
  "--chart-1",
  "--chart-2",
  "--chart-3",
  "--chart-4",
  "--chart-5",
  "--chart-6",
  "--chart-grid",
  "--chart-axis",
  // Typography
  "--font-ui",
  "--font-data",
  // The prose exception — see tokens.css for which routes qualify
  "--font-prose",
  "--font-size-prose",
  "--font-size-prose-lead",
  "--line-height-prose",
  "--measure-prose",
  "--font-size-2xs",
  "--font-size-xs",
  "--font-size-sm",
  "--font-size-md",
  "--font-size-lg",
  "--font-size-xl",
  "--font-size-2xl",
  "--font-size-3xl",
  "--font-weight-regular",
  "--font-weight-medium",
  "--font-weight-semibold",
  "--font-weight-bold",
  "--line-height-tight",
  "--line-height-snug",
  "--line-height-normal",
  "--tracking-wide",
  "--tracking-tight",
  // Row rhythm — the terminal's defining measurement
  "--row-h",
  "--row-h-comfortable",
  // Spacing
  "--space-0",
  "--space-1",
  "--space-2",
  "--space-3",
  "--space-4",
  "--space-5",
  "--space-6",
  "--space-7",
  "--space-8",
  "--space-9",
  "--space-10",
  // Radii
  "--radius-1",
  "--radius-2",
  "--radius-3",
  "--radius-full",
  // Shadows
  "--shadow-1",
  "--shadow-2",
  "--shadow-3",
  // Z-index
  "--z-raised",
  "--z-sticky",
  "--z-header",
  "--z-dropdown",
  "--z-overlay",
  "--z-modal",
  "--z-toast",
  "--z-tooltip",
  // Motion
  "--motion-fast",
  "--motion-base",
  "--motion-slow",
  "--ease-out",
  "--ease-in-out",
  // Breakpoints
  "--breakpoint-sm",
  "--breakpoint-md",
  "--breakpoint-lg",
  "--breakpoint-xl",
];

/**
 * Semantic tokens the future light theme must re-map. The light-theme
 * block in tokens.css must define at least these (it may define more).
 */
export const LIGHT_THEME_REQUIRED = [
  "--surface-0",
  "--surface-1",
  "--surface-2",
  "--surface-3",
  "--text-primary",
  "--text-secondary",
  "--text-tertiary",
  "--border-default",
  "--accent",
  "--positive",
  "--negative",
  "--warning",
  "--info",
  "--focus-ring",
];

/**
 * Semantic tokens the `.psi-editorial` migration scope (C8-PSI-02, the
 * Premium Sports Intelligence reference-route direction) must re-map, plus
 * the one token it alone defines (`--font-display` has no terminal
 * equivalent — see tokens.css). Mirrors LIGHT_THEME_REQUIRED's role: this
 * scope must define at least these (it may define more).
 */
export const PSI_EDITORIAL_REQUIRED = [
  "--surface-0",
  "--surface-1",
  "--surface-2",
  "--surface-3",
  "--text-primary",
  "--text-secondary",
  "--text-tertiary",
  "--border-default",
  "--border-strong",
  "--accent",
  "--positive",
  "--negative",
  "--warning",
  "--info",
  "--data-up",
  "--data-down",
  "--focus-ring",
  "--font-display",
];

/** Chart series slots in their validated fixed order. Never cycle. */
export const CHART_SERIES_TOKENS = [
  "--chart-1",
  "--chart-2",
  "--chart-3",
  "--chart-4",
  "--chart-5",
  "--chart-6",
];
