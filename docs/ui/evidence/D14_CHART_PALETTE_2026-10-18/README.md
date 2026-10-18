# Owner Decision 14 — categorical chart palette evidence (2026-10-18)

Branch `claude/chart-palette-d14`, stacked on `integration/train-8-2026-10-18` (#1809).
Local production build (`npm run build:nocheck` + `next start`) against the local backend
serving the committed snapshot. This is **local evidence, not production proof**.

## Screenshots (Chromium, DPR 1)

| File | Viewport | Scope | Shows |
|---|---|---|---|
| `design-small-charts-desktop.png` | 1440x900 | cream `.psi-editorial` | Sparklines (slots 1 / 3 / 2) and Meters (slots 1 / 2 / 4) |
| `design-small-charts-mobile.png` | 375x812 | cream | same, phone layout |
| `design-chart-slots-desktop.png` | 1440x900 | cream | the six `--chart-*` swatches in order |
| `design-chart-slots-mobile.png` | 375x812 | cream | same, phone layout |
| `league-trade-flow-dark-desktop.png` | 1440x900 | dark terminal | `/league?tab=activity` trade-flow Sankey on the dark slots; 13 teams, so teams 7-13 fold to the neutral Other ink and are named by their node labels |
| `league-trade-flow-dark-mobile.png` | 375x812 | dark terminal | same, phone layout |

The dark-route PNGs are palette-reduced to 128 colours to keep them small.

Computed values read from the rendered page: inside `.psi-editorial`,
`--chart-1..6` = `#986400 #2264af #ac386a #6752b6 #087650 #aa3c17`; on the dark
`:root`, `#c98500 #3987e5 #d55181 #9085e9 #199e70 #d95926`.

The light theme scaffold (`[data-theme="light"]`) is not exposed to users, so it has
no screenshot. Its contrast is computed in the test below.

## Accessibility (local, axe via `tests/e2e/specs/a11y-axe.spec.js`)

Passing on desktop-1366: `/design`, `/rankings`, `/trade`, `/rosters`, `/league` and
`/players/[playerId]`. Passing on mobile-chromium: `/rankings`, `/trade`, `/rosters` and
`/league`. `tests/e2e/specs/psi-gallery.spec.js` also passes on both projects. In total,
14 tests passed. After the Meter fix, `/design`, `/league` and the gallery spec were run
again: 7 tests passed.

axe does not certify SVG chart contrast. The computed proof is
`frontend/__tests__/components/ds/chart-palette-contrast.test.js`.

## Defect found by ungating

`.ds-meter__fill` is a `<span>` without `display: block`, so its fill never painted.
The Meter's only consumer was the gated gallery, which is why nobody had seen it. It is
fixed in `frontend/app/ds.css`.
