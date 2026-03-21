# Design System Direction (Modern but Useful)

Last updated: 2026-03-19

## Product Aesthetic Direction
**Sharp Sports Intelligence Console**

Intent:
- High-signal, data-dense, premium clarity.
- Confident, not flashy.
- Mobile-usable without dumbing down desktop power.

## What to Avoid
- Generic SaaS gradients and soft card spam.
- Low-contrast text in dense tables.
- Over-animated novelty interactions.
- Large decorative elements that slow comprehension.

## Typography System
- Primary UI: `Sora` (clean, strong hierarchy, modern sports-tech tone)
- Data/metrics: `IBM Plex Mono`
- Rules:
  - Use mono for values, tiny labels, diagnostics, and chips.
  - Keep heading rhythm tight and intentional.
  - Avoid collapsing everything into similar size/weight.

## Color System
- Base: deep navy neutrals for trust and contrast.
- Accent: cyan for interaction + signal, orange for brand energy, green/red for valuation direction.
- Rules:
  - Accent use must convey action/state, not decoration.
  - Error and warning states must remain obvious in dense tables.

## Spacing + Rhythm
- Use compact-but-readable rhythm tuned for data interfaces.
- Default spacing tiers:
  - micro: 4px
  - tight: 8px
  - default: 12px
  - section: 18–24px
- Keep vertical rhythm consistent between cards, table headers, and action rows.

## Component Style Guidelines

### Cards
- Strong edge definition, subtle depth, restrained radius.
- Never use cards as generic wrappers without semantic purpose.

### Tables
- Prioritize scanning speed:
  - sticky context where useful
  - clear hover/focus states
  - compact row height
  - predictable numeric alignment

### Controls
- Primary/secondary/ghost hierarchy must be visually obvious.
- Mobile controls should preserve key actions in thumb zone.

### State Surfaces
- Loading: quick readable placeholders, no spinner abuse.
- Empty: actionable, specific, non-generic copy.
- Error: explain what failed and what user can do next.

## Interaction Style
- Motion should communicate state change, not showmanship.
- Prefer subtle transitions on tab/surface swaps.
- Keep animations short and interruptible.

## Mobile Direction
- Keep ranking/trade workflows fully usable on phone.
- Preserve quick actions persistently where context-switch cost is high.
- Avoid horizontal overflow and tiny tap targets.

## Trust Signals
- Always show source freshness/context where relevant.
- Use consistent value formatting and confidence markers.
- Keep runtime authority and auth boundary behaviors transparent.

## Implementation Notes (current pass)
- Next shell now uses Sora + IBM Plex Mono tokens and stronger hierarchy scaffolding in `frontend/app/layout.jsx` + `frontend/app/globals.css`.
- This is foundational direction-setting; live private authority still runs through static runtime path today.
