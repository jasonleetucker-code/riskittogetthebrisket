# R5 phase A — staged, ready to run the moment #551 merges

One file. 70 call sites converted, **none of them edited**. This is the
whole diff, pre-derived so phase A is merge-and-run rather than a fresh
analysis.

**Prerequisite:** #551 must be merged, because phase A depends on
`0b36074c` (Panel restored to hook-free / server-safe). Running it
before that puts `useState` into seven Server Components. Confirm with:

```
grep -c "useState\|useId" frontend/components/ds/Panel.jsx   # must be 0
npx vitest run __tests__/components/ds/panel-server-safe.test.js
```

---

## The change

`frontend/app/league/shared-server.jsx`, the `Card` export:

```jsx
// BEFORE
export function Card({ title, subtitle, action, children, id }) {
  return (
    <div className="card" id={id} style={{ marginTop: "var(--space-md)" }}>
      {(title || action) && (
        <div style={{ display:"flex", justifyContent:"space-between",
                      alignItems:"baseline", marginBottom:10, gap:8,
                      flexWrap:"wrap" }}>
          <div>
            {title && <div style={{ fontWeight: 700 }}>{title}</div>}
            {subtitle && <div style={{ fontSize:"0.72rem",
                          color:"var(--subtext)", marginTop:2 }}>{subtitle}</div>}
          </div>
          {action}
        </div>
      )}
      <div>{children}</div>
    </div>
  );
}

// AFTER
export function Card({ title, subtitle, action, children, id }) {
  return (
    <Panel
      className="league-card"
      id={id}
      title={title}
      subtitle={subtitle}
      actions={action}
    >
      {children}
    </Panel>
  );
}
```

Plus the import — and note it must come from the **module**, not the
barrel: `@/components/ds` re-exports `CollapsiblePanel`, which carries a
client directive, and pulling the barrel into a server module drags that
into the server graph for no reason.

```jsx
import { Panel } from "@/components/ds/Panel";
```

Prop mapping is 1:1 except `action` → `actions` (ds pluralises it), and
`id` which rides `...rest`.

---

## The two deltas that need handling, not discovering

### 1. The margin

`Card` hardcodes `style={{ marginTop: "var(--space-md)" }}`. `Panel`
sets no margins by design — its docblock names this exact inline style,
"pasted 26×", as the anti-pattern. The `/league` sections render
sequential `<Card>`s with no stack container, so dropping it collapses
spacing on 70 sites.

Interim, in `globals.css` beside `.card`:

```css
/* Interim: /league sections have no stack container, so the Card→Panel
   migration keeps its own vertical rhythm until phase B gives each
   section a real gap. Delete with the last `.card` consumer. */
.league-card { margin-top: var(--space-md); }
```

Preserves spacing exactly, gets it off the inline style, deletes in one
line later. **Label it interim or it becomes permanent.**

### 2. The heading

`Card` renders its title as a bare `<div style={{fontWeight:700}}>`;
`Panel` renders a real `<h2>` with the ds uppercase micro-label
treatment. Semantically an improvement — these *are* section headings —
but it is a visible type change across 70 sites and it alters the
document outline.

**Checked already — `h2` is safe.** A depth scan of every `<Card>` /
`</Card>` pair across `app/league` found **no nesting anywhere** (max
depth 1), so 70 sibling `h2`s under each page's `h1` is a correct
outline. `Panel` takes `headingLevel` if that ever changes.

Count confirmed at **exactly 70** `<Card` usages across
`app/league` + `app/league-comparison`:

```
grep -rho "<Card\b" frontend/app/league frontend/app/league-comparison --include=*.jsx | wc -l   # 70
```

---

## Verify, in this order

1. `npx vitest run` — expect green; `panel-server-safe` especially.
2. `npm run build`.
3. **Measure `/league` immediately** — this is the budget probe, and the
   reason phase A lands alone rather than bundled with phase B:

   ```
   /league/page  167.8 KB / 170 KB budget   (2.2 KB headroom before)
   ```

   R2/R3/R4 each came in *under* their pre-migration size as legacy CSS
   and components dropped out, and the same should happen here — one
   component replaces hand-rolled markup at 70 sites. But `/league` is
   the tightest page in the app after `/trade`, so this is measured, not
   assumed. **If it goes over, stop and report before starting phase B**
   rather than rebuilding 31 more files on a budget that no longer fits.
4. Spot-check the seven Server Components render — they are the reason
   the blocker existed:
   `/league/player/[playerId]`, `/league/franchise/[owner]`,
   `/league/week/[season]/[week]`, `/league/rivalry/[pair]`,
   `/league/weekly/…`, `/league/articles/…` (×2).
   **This needs a backend with data** — it could not be done in the
   scoping container, which is exactly why the blocker was reasoned
   rather than reproduced.
5. `.card` count should drop by ~70 while the raw-`className="card"`
   count is unchanged at 85 — phase A touches only component usages.

---

## What phase A does NOT do

- The 85 raw `className="card"` sites (that is phase B, page by page).
- The view-switcher fixes (§3 / §3a of `R5-LEAGUE-MIGRATION.md`).
- Deleting `.card` from `globals.css` — it still has 85 consumers, and
  the de-seam means it no longer looks foreign in the meantime.
