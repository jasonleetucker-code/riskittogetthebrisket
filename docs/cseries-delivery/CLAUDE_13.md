# Claude 13 — C8/C9/C10 Delivery Log

**This branch (`claude/psi-reference-routes`) carries PR A/PR B (the PSI reference-route
migration) only.** Batches 1–3 of the earlier campaign (Chase Upside Market Ticker, franchise
continuity repair, dead-code census) are recorded in this same file's copy on
`claude/cseries-premium-public-closure` (PR #965), which this branch was deliberately **not**
based on (see below). **When both PRs merge, Claude 5 should reconcile these into one file** —
noted here rather than silently produced as a merge surprise.

## PR A / PR B authorization (governance record)

The owner explicitly authorized a real, production-capable migration of two reference routes —
Dynasty Rankings and a new Universal Player Profile — onto the "Premium Sports Intelligence"
editorial visual direction (`docs/PREMIUM_SPORTS_INTELLIGENCE_DESIGN_NORTH_STAR.md`), using two
attached reference screenshots as the visual source of truth. This supersedes the direction's
previous "preparation only" posture and is an explicit continuation of the owner override already
recorded for the broader C8/C9/C10 campaign earlier this session.

**Governance gap, recorded honestly.** As of this session's most recent check of the canonical
docs: `docs/VERSION_1_COMPLETION_CONTRACT.md` still lists `C8-PSI-02` / `R-PREMIUM` ("Premium
migration of the high-use routes") as `NOT STARTED`, and `docs/EXECUTION_PLAN.md` §6 still names
"Premium route migration" under "do not opportunistically begin." Unlike the earlier C8/C9/C10
authorization (found already reconciled into `EXECUTION_PLAN.md` §0 before that work began), **this
specific authorization has not yet been written into the canonical record.** The owner's
instruction directly anticipates this ("Claude 5 will reconcile the canonical execution/governance
record. Do not independently rewrite the V1 completion contract") — I am proceeding on that basis
per explicit instruction, not editing either canonical doc myself, and recording the exact delta
here for Claude 5.

**PR #965 stays frozen.** This work started on a fresh branch, `claude/psi-reference-routes`, off
`origin/main` — not off `claude/cseries-premium-public-closure` — per explicit instruction not to
keep piling unrelated work onto #965.

## Design decisions made during implementation (not verbatim from the brief)

- **Font**: the brief asked for "major serif editorial display typography" but also "do not add an
  external font dependency merely to imitate a screenshot unless the repository already has a
  supported/legal mechanism for it." The app's only font mechanism is `next/font/local` with
  checked-in `woff2` assets, specifically because the build environment can't reach
  `fonts.googleapis.com`. **Decision: the new `--font-display` token is a system serif stack**
  (`Georgia, Cambria, "Times New Roman", Times, serif`) — no new asset, no license risk. This is a
  real, visible gap versus the screenshot's distinctive display serif, and is called out here
  rather than silently accepted — swappable later via the same mechanism if the owner
  supplies/approves a licensed font file.
- **Token scoping mechanism**: rather than a whole-app theme flip or an all-new token namespace,
  the editorial palette is a new `.psi-editorial` CSS class that re-maps the SAME semantic alias
  names (`--surface-0`, `--text-primary`, `--accent`, etc.) every `ds/` component already consumes
  exclusively — the same mechanism `[data-theme="light"]` already uses, just scoped to a class
  instead of the whole document. Every existing `ds/` primitive (Panel, DataTable, Button, Badge…)
  therefore renders correctly in the new palette with zero component changes, and a migrated route
  reverts to the terminal palette instantly by removing one class — matching the north star's own
  "route-by-route, reversible" migration method (§8) exactly.
- **Every color WCAG-computed, not eyeballed** (matching this file's own existing discipline):
  text ≥4.5:1 on every surface (worst case, the nested `surface-2`), accent/market-direction marks
  ≥3:1, the screenshot's visible "thin black rule" separators get a genuinely near-ink
  `--border-strong` rather than a token reused from elsewhere at the wrong weight. The existing
  `--data-up`/`--data-down` terminal values were validated only against dark surfaces and measured
  below the 3:1 mark floor on this scope's nested surface (2.75/2.94:1) — re-derived rather than
  inherited, darker blue/orange in the same CVD-safe hue family, verified ≥4.5:1+ everywhere.
  22 tests in `tokens-contract.test.js` (8 new) pin these ratios so a future edit can't silently
  regress them.

## Batch log

### Setup — done

- Branch `claude/psi-reference-routes` created from `origin/main`.
- This delivery doc created (fresh copy — see the note at the top about reconciling with #965's
  copy at merge time).
- `docs/WORK_CLAIMS.md` row added for PR A.

### Batch A1 (C8-PSI-02) — Editorial token layer — done

**What shipped:**
- `frontend/app/tokens.css`: new additive `.psi-editorial` scope (see "Design decisions" above for
  the mechanism and the exact palette). Does not touch any existing dark/light token or
  `globals.css` — purely additive, verified by the existing "stays additive" contract test plus a
  new one scoped to this block.
- `frontend/components/ds/token-contract.js`: new `PSI_EDITORIAL_REQUIRED` export listing the
  tokens this scope must define, mirroring `LIGHT_THEME_REQUIRED`'s existing pattern.
- `frontend/__tests__/components/ds/tokens-contract.test.js`: 8 new tests — required-token
  presence, no-primitives-redefined, additive-only, and 5 WCAG contrast assertions (accent on
  worst surface, text-on-accent, text-primary on all 4 surfaces, data-up/data-down mark floor on
  all 4 surfaces, border-strong reads as a real rule).

**Verified:**
- `tokens-contract.test.js`: 22/22 passing (14 pre-existing + 8 new).
- Full frontend suite: 142 test files / 2,243 tests passing, zero regressions.

**Deliberately NOT claiming:**
- A licensed display serif font (system stack used instead — see "Design decisions").
- Any component/page actually USING the new scope yet — that's Batch A2 (shell) and A3
  (Rankings). This batch is tokens only, so it's inert until a page opts in via the class.
