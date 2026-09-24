"""Temporary #1421 application helper; removed before the integration PR.

Only the named branch and inspected governance files may be changed. Existing
content is retained; replacements are anchored and assertions fail closed.
No backend, frontend runtime, model, main ref or deployment is touched.
"""
from pathlib import Path
import os
import subprocess
import textwrap

ROOT = Path.cwd()
BRANCH = "codex/calculator-ui-parallel-contract"
CONTRACT = "docs/ui/CALCULATOR_UI_IMPLEMENTATION_CONTRACT.md"
LEDGER = "docs/ui/UI_PARALLEL_LEDGER.md"
POLICY = "UI policy: ALWAYS_PARALLEL_UNTIL_UI_COMPLETE"
BATCHING = "UI batching: INCLUDE_OR_REFERENCE_ACTIVE_LANE"
RECEIPT = "cdca1dca8385f70c0989302dece8d1bd4ce4843c"
BASE = "a3c29639aeb61c2af4fd169b75ccb9429011109b"


def git(*args):
    return subprocess.check_output(["git", *args], text=True).strip()


def put(path, content):
    target = ROOT / path
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text("\n".join(line.rstrip() for line in textwrap.dedent(content).strip().splitlines()) + "\n", encoding="utf-8")


def read(path):
    return (ROOT / path).read_text(encoding="utf-8")


def prepend(path, content):
    title, rest = read(path).split("\n", 1)
    # Preserve existing bytes, including historical Markdown hard breaks.
    (ROOT / path).write_text(title + "\n\n" + textwrap.dedent(content).strip() + "\n" + rest, encoding="utf-8")


def replace(path, old, new):
    text = read(path)
    if old not in text:
        raise RuntimeError(f"Required inspected anchor changed in {path}: {old[:80]}")
    (ROOT / path).write_text(text.replace(old, new, 1), encoding="utf-8")


if os.environ.get("GITHUB_REF_NAME") != BRANCH:
    raise SystemExit("Wrong branch: no writes permitted")
if os.environ.get("GITHUB_REPOSITORY") != "jasonleetucker-code/riskittogetthebrisket":
    raise SystemExit("Wrong repository")

# Hash the current bytes before applying compact edits to large shared files.
expected = {
    "ASSISTANT_COORDINATION.md": "348683a0b5c6822f2eb8ef60d04f2d5a4cc82c6b",
    "CLAUDE.md": "75833ad99d196aa8c983e35a31e970a7bbaf9fb9",
    "docs/BRISKET_IDEAS.md": "f266119f2d589fc4fff85408e7c0eff4488dada3",
    "docs/C_SERIES_EXECUTION_MAP.md": "a56ea10a7e1fffb205eb7893b090b507ee51b1ea",
    "docs/C_SERIES_SCOPE_MANIFEST.md": "d5b818c91a86740c3ab56a5b4da21a9746f60d7f",
    "docs/DESIGN-SYSTEM.md": "9ca1595e5b732f0b91e0b0c44d09fb31ffb53de0",
    "docs/EXECUTION_PLAN.md": "31dd9e256dcf9a29e0d213835f4171589f7d853e",
    "docs/MASTER_PRODUCT_PLAN.md": "28accf6673540059116a4b86daf7ab8125cb625e",
    "docs/OWNER_REQUESTED_TODO.md": "8a5ad9891ac8bbcfd395dbdec007ca88dc56d467",
    "docs/PLANNING_DOCUMENT_STATUS.md": "3fef788f8062c3aced2024e5d1d17e4894337771",
    "docs/PREMIUM_SPORTS_INTELLIGENCE_DESIGN_NORTH_STAR.md": "9c1bea8cca3064b5ea987337dfaccee2d136ff10",
    "docs/WORK_CLAIMS.md": "f20ddd4ce842e51a08c4ac3c5c461badb6b1f20e",
    "scripts/check_planning_integrity.py": "d645907b29056dfc632655056993c004d282fad6",
}
for path, wanted in expected.items():
    if git("hash-object", path) != wanted:
        raise SystemExit(f"Inspected content changed: {path}; reconcile rather than overwrite")
if (ROOT / CONTRACT).exists() or (ROOT / LEDGER).exists():
    raise SystemExit("Canonical UI file now exists; reconcile instead of creating a competitor")

# Claim first, before the substantive governance commit.
claim = (
    "| **Calculator permanent parallel UI governance (#1421).** Existing Lane 6 / C8 only; no new design direction. "
    "| `docs/ui/`, bounded UI amendments in `docs/EXECUTION_PLAN.md`, `docs/C_SERIES_EXECUTION_MAP.md`, "
    "`docs/C_SERIES_SCOPE_MANIFEST.md` (C8 status cells only), `docs/MASTER_PRODUCT_PLAN.md`, "
    "`docs/BRISKET_IDEAS.md`, `docs/OWNER_REQUESTED_TODO.md`, `docs/PLANNING_DOCUMENT_STATUS.md`, "
    "`docs/DESIGN-SYSTEM.md`, `docs/PREMIUM_SPORTS_INTELLIGENCE_DESIGN_NORTH_STAR.md`, "
    "`ASSISTANT_COORDINATION.md`, `CLAUDE.md`, `.github/pull_request_template.md`, "
    "`scripts/check_planning_integrity.py`, `tests/docs/test_ui_parallel_governance.py`, `docs/WORK_CLAIMS.md` "
    "| #1421 | `codex/calculator-ui-parallel-contract` "
    f"| open — bounded governance writer; reconcile append/section overlaps #1416/#1419/#1344 through Integration. "
    f"No backend/frontend runtime files claimed. Temporary application helpers removed before PR. Agent-OS-Receipt: {RECEIPT} |\n"
)
claims = read("docs/WORK_CLAIMS.md")
marker = "|---|---|---|---|---|\n"
start = claims.index(marker, claims.index("## Open claims")) + len(marker)
(ROOT / "docs/WORK_CLAIMS.md").write_text(claims[:start] + claim + claims[start:], encoding="utf-8")
git("add", "docs/WORK_CLAIMS.md")
git("commit", "-m", "chore(governance): claim bounded Calculator UI directive #1421")

put(CONTRACT, '''
# Calculator — UI Implementation Contract

**Status:** binding implementation contract for existing Lane 6 / Premium UI.
**Owner directive:** 2026-09-24, #1421.
**Design authority:** `docs/PREMIUM_SPORTS_INTELLIGENCE_DESIGN_NORTH_STAR.md`.
**Execution authority:** `docs/EXECUTION_PLAN.md`; this is not a second authorization record.
**Completion front door:** Calculator Ideas, `docs/BRISKET_IDEAS.md`.
**Operational ledger:** `docs/ui/UI_PARALLEL_LEDGER.md`.

UI policy: ALWAYS_PARALLEL_UNTIL_UI_COMPLETE

The North Star defines what the product should look/feel like. This implementation
constitution defines how agents realize that already-approved decision. No design
exploration is authorized. Keep the historical BRISKET_IDEAS.md filename; the project
is Calculator and its owner-facing full completion portfolio is Calculator Ideas.

## 1. Continuous parallel execution

**Lane 6 / Premium UI is an always-active parallel lane through Calculator completion.**
Preserve its UI, frontend, performance and accessibility ownership and existing C8-U1
(performance), C8-U2 (premium design system / migration) and C8-U3 (accessibility).
Do not create a duplicate program or change unrelated scope or completion denominators.

Every substantial implementation batch, next reasonable batch, next ten Calculator
Ideas, parallel-batch recommendation and fresh-session prompt must include useful UI
work or explicitly reference an adequately staffed active UI lane. Backend-heavy new
ideas cannot make UI disappear from the full completion portfolio.

The batch shape is FOUNDATION / BACKEND (canonical data/model/feature owners) + UI
(dependency-safe foundation or frontend consumer) + INTEGRATION (stable contract
connection, E2E and production proof). UI need not touch the same feature when that
would cause rework. Where the frontend contract is stable, advance it with the feature.

When an existing lane covers the batch, say `UI lane already active: <issue/PR/work claim>`
and explain coverage. An old branch, queued handoff or historical dispatcher snapshot
is not evidence of an active worker. Label queued reservations honestly.

A sufficiently stable canonical contract is required for a route's final migration.
An unstable route contract blocks only that route's final wiring, not the UI program.
Move to shared tokens/primitives, shell/navigation, mobile, accessibility, performance,
tables/search/filters/charts/player identity, loading/error/stale/empty/partial states,
visual testing, migration inventory, proven legacy retirement or another stable route.
Do not say all UI is blocked unless every remaining task has an evidenced unresolved
owner/external blocker. Name the individual blocker and select the next safe ledger unit.

## 2. Locked authority / no aesthetic discretion

For UI decisions use, in order: newest explicit owner UI instruction; PSI North Star;
this contract; approved PSI production reference routes; DESIGN-SYSTEM.md and semantic
token contract; current ds primitives; legacy implementation. Current code can disprove
stale implementation-status claims but cannot override a newer owner design decision.
Historical freeze records remain traceable with dated supersession pointers.

Agents must not independently choose palette, fonts/type scale, radii, shadows, spacing,
breakpoints, chart palette, navigation, density, card-versus-table philosophy, movement
colors, buttons, badges, player presentation or mobile information architecture.

Decision tree: implement the explicit owner instruction; otherwise the North Star;
otherwise this contract; otherwise the closest approved PSI reference; otherwise the
applicable shared primitive. If a genuinely new visual decision remains, mark
**OWNER UI DECISION REQUIRED** and stop only that decision, continuing other safe work.
Engineering problem solving is allowed; becoming the art director is not. “I thought
this looked cleaner” does not justify deviation or a new design language.

## 3. Product feel and absolute anti-goals

Every migrated surface must feel like a premium football personnel and market-
intelligence system for serious dynasty managers: professional-sports identity,
editorial authority, front-office credibility, dense but calm information, strong
numerical/type hierarchy, tabular numerals, restrained chrome, thin rules/alignment,
minimal radii, disciplined color, purposeful player imagery, explainability and speed.
It is an application, not a sports-news site, generic SaaS/AI dashboard or KTC clone.
Do not copy KTC's visual design.

Do not introduce excessive/nested rounded cards, large radii, ubiquitous pills, default
shadcn/Tailwind dashboard styling, glassmorphism, purple/blue AI gradients, glow, blobs,
decorative shadows, icon saturation, one tile per number, manufactured whitespace,
marketing heroes inside tools, card grids replacing desktop tables for convenience,
generic startup visuals or superficial recoloring of unchanged legacy composition.
Organize with typography, rules, alignment, grouping, spacing rhythm and restrained
surface differences. Use desktop space efficiently without hiding useful information.

## 4. Exact semantic styling owner

Use the existing `.psi-editorial` scope in `frontend/app/tokens.css`, not a second DS or
an indiscriminate whole-app theme flip. Approved values belong only in that token owner:

| Role | Token | Approved value |
|---|---|---|
| Page canvas | --surface-0 | #f2ebdd |
| Panel | --surface-1 | #faf6ec |
| Nested / input / raised | --surface-2 | #e9dfca |
| Overlay | --surface-3 | #ffffff |
| Primary ink | --text-primary | #1c1712 |
| Secondary ink | --text-secondary | #4a4136 |
| Tertiary ink | --text-tertiary | #6b6151 |
| Strong structural rule | --border-strong | #1c1712 |
| Identity / interactive accent | --accent | #a3341c |
| Hover | --accent-hover | #8c2c17 |
| Pressed | --accent-pressed | #752312 |

Components consume semantic --surface-*, --text-*, --border-*, --accent* and state tokens.
Never copy raw colors into component/page CSS. No arbitrary spacing/radii/shadows,
new breakpoints, z-index values, type sizes or page-local semantic colors.

Burnt red is the single identity/interactive accent: primary action, selected state,
eyebrow, active sort and intentional emphasis. Not decorative washes or every border,
icon and number. Movement is not success/failure: preserve --data-up* blue + up arrow
and --data-down* orange + down arrow, never color alone. Genuine positive/negative
system states retain their state semantics; falling dynasty value is not an error.

Use --radius-1/2/3 for approximately 2px controls/tiles and 3px panels/modals. Full circle
is for real dots/round indicators. No new 8/12/16px card variants. Shadows belong to
actual overlays (popover, modal, drawer, elevated menu); normal sections/tables/panels/
stat regions rely on surfaces, borders, spacing and typography.

Canonical breakpoints are 480, 768, 1024 and 1320. These documented media-condition
literals are allowed; do not invent 640/900/1180 or copy legacy exceptions merely to
avoid responsive composition. Fixed plot/image geometry is not a breakpoint.

## 5. Typography, density, hierarchy and desktop tables

Use existing editorial/display authority, legible UI typography and tabular numerical
roles. --font-display already exists: no new/downloaded font without a newer owner
instruction. Reuse the approved token scale/reference routes, not stale values in old
docs. Comparable numbers use tabular numerals and consistent alignment, normally
right-aligned in numerical table columns rather than centered for symmetry.

Dense but calm is the requirement. Hierarchy comes from typography, grouping, rules,
alignment and restrained surfaces, not giant gaps. A data-heavy private page generally
orders page identity/context -> primary decision/key state -> primary workflow -> why/
explainability -> supporting market/roster/source evidence -> secondary detail. Do not
bury the action under analytics or a marketing introduction.

Rankings, source comparisons, player lists, transaction ledgers and trade assets belong
in dense tables/aligned rows, compact identity and expandable detail, not huge card grids.

## 6. Mobile parity and unambiguous identity

Mobile is the same product, not a summary-only version. Preserve canonical calculations
and core workflows: asset search, trade construction, player/pick selection, totals,
Value Adjustment, balance suggestions, real-trade comparisons, charts/analytics,
before/after roster impact, filters/sorting, explainability, source states and actions.
Presentation may change; capabilities may not silently disappear.

Keep identity, the key decision number, verdict/state and primary action immediately
visible. Secondary fields remain accessible through expansion, secondary rows,
controlled horizontal table regions or drilldown drawers. Do not hide important columns
without a path to them. Do not clip player names into ambiguity. Owned picks preserve
owner/year/round identity where needed; generic quantities remain understandable.

## 7. One navigation model / correct app shell

`frontend/lib/nav-model.js` remains the single IA. Desktop top nav and mobile top bar,
tab bar and menu/drawer render the same product with shared route/capability gating,
not two products. Preserve skip-to-content, main landmark, route focus management,
auth-aware navigation, public/private boundaries, command/search, mobile chrome and
stale-data communication. Visual simplification cannot weaken auth or accessibility.

## 8. Shared primitives, charts, imagery and gallery

Reuse existing shared buttons/inputs/selects/segmented controls/tabs/panels/tables,
player rows, badges, movement/confidence/freshness, loading/empty/error states,
modals/drawers, charts/tooltips/filters/pagination. Extend an approved shared primitive
under a claim rather than fork a page-local version. Portals must retain the approved
scope; do not assume a page-root scope reaches body-level overlays.

Charts preserve existing semantic palette, fixed CVD-safe series order, labels/tooltips,
accessible descriptions and responsive rendering. No rainbow charts or color-only
critical meaning. Preserve the supported categorical limit/Other grouping; do not
repaint surviving series after filters. Verify contrast on actual plot surfaces rather
than repurpose a dark-theme validation claim for every light plot.

Player imagery is selective, purposeful and subordinate to data/identity/hierarchy,
not decorative wallpaper or giant cutouts everywhere. Follow approved reference use.

`/design` is a living implementation/test reference, not a product page. Keep it current
for every introduced primitive, variant/state, type role, table/movement/confidence,
loading/empty/error and responsive pattern. Isolated deterministic gallery/test fixtures
are allowed and labelled; they must not become fake production decision data.

## 9. Visible speed and truthful data states

Keep useful current content while refreshing, use local pending states, skeletons only
without useful prior content, progressive sections and stable dimensions. Avoid global
spinners for local changes, flash-to-empty, jumping layouts or blocking an entire route
on a secondary request. Do not make a fast application feel slow.

MISSING IS NEVER ZERO. Distinguish loading, unavailable, missing, stale, degraded,
partial coverage and actual zero. A clean component is not a reason to hide source
limitations or present a stale source as current. Fetch freshness is not content freshness.
No production route may use hardcoded fake data to look finished: use an honest
unavailable/degraded state or an appropriate feature gate when a live contract is absent.

## 10. Explainability and canonical ownership

Calculator must be fast, clear, actionable, explainable, consistent and mobile-friendly.
Values, ranks, edge, confidence, verdicts, adjustments and recommendations need a path
to meaning, movement reasons, contributing evidence and missing/degraded inputs. Use
progressive disclosure, not permanent diagnostic clutter.

The UI consumes/displays/interacts/explains and filters/sorts only where semantically
safe. It must not create parallel owners for player/pick valuation, trade math, Value
Adjustment, Team Strength/Weakness, lineup/replacement/scoring, FAAB, projections,
freshness, confidence or market verdicts. Connect canonical owners rather than recompute.

## 11. Trade Calculator — locked workflow

Trade is a primary private workflow. Its mature experience supports clear Side A/B,
optional supported 3+ participant/destination identity, players, owned picks, repeatable
generic assets, duplicate-looking uniquely owned picks, raw/adjusted totals, amount-to-
even, fairness/verdict, balance suggestions, real-trade comps, before/after roster and
position impact, uncertainty/risk, market/source context and shareable state. Do not
scatter the evidence for one proposed trade across unrelated pages.

Asset selection distinguishes player, unique owned pick, generic pick and repeated
asset. Two distinct owned picks may both say Mid 2027 1st; both remain selectable.
Generic assets may repeat, but the same unique owned pick cannot accidentally count
twice. Do not use display label or asset type as unique identity. Removing one generic
copy leaves the other; share/persistence/equalizer integration preserves every valid
quantity/identity. Quantity UX cannot hide ownership. Canonical math counts copies;
the UI must not introduce a replacement valuation or serialization owner.

Prioritize who gains/whether balanced, totals, delta/amount-to-even, applicable Value
Adjustment, roster impact and confidence. Sources/comps/charts/secondary analytics go
below or behind disclosure. Preserve latest owner override/reset privacy requirements
where applicable, without corrupting canonical value or pretending edited values are
canonical source observations.

Backend trade engine and Trade UI are distinct parallel lanes. Asset picker/quantity
UX/owned-pick identity/mobile/hierarchy can advance on stable contract portions and
shared primitives before every trade feature is complete. Final connection belongs to
Integration with canonical contract and E2E proof.

## 12. Rankings, universal player, Waivers and league state

Rankings and Universal Player Profile are early canonical PSI reference experiences.
Reuse their typography, spacing, surface/rules, headers, identity, controls and responsive
philosophy. If they disagree, audit against owner/North Star/this contract; personal
preference does not resolve authority.

Rankings retains a real dense sortable table: player identity, rank, canonical value,
position/tier/movement, meaningful confidence/coverage, search/filters and explanation.
Mobile retains identity/rank/primary value/essential movement and access to other detail.

Every player click converges on one canonical experience, not ten competing popups.
Its hierarchy ultimately includes identity, value/rank/tier/confidence, market/history,
BDVM/fundamentals, projections/stats/PAR, roster context, acquisition/holding history,
Sharp, manager/Insider, Analyst Intelligence and factual news through disclosure.

Waivers must relate to Trade: team selection, value-sorted roster, waiver pool,
filters/search/position controls, add/drop selection, clear result/value impact, sources
and FAAB where available. Coordinated desktop panes are allowed; mobile uses intentional
tabs/stacking rather than crammed panes. Preserve workflows and canonical calculations.

League switching/toggles must unmistakably show ON/OFF and stay consistent across
Rankings, Trade, Waivers, profiles, rosters, Finder and future tools. Consume the shared
canonical state/value owner; never secretly fall back to another mode or recalculate
league adjustments in a page.

## 13. Accessibility and performance are shipping gates

Preserve keyboard navigation, visible focus, semantic controls/labels, table/dialog
semantics, aria-current, route focus, reduced motion, non-color cues, accessible charts
and sufficient contrast. C8-U3 requires axe-based CI coverage for migrated references.
A screenshot alone cannot establish accessibility or PSI completion. Test meaningful
populated/interactive states, not only loading skeletons.

Premium UI must not make the app slower. Retain owner targets: useful warm/cached data
<=1s target; normal production p95 <=2s where architectural; supported cold useful path
<=3s preferred; <=5s absolute useful-interactive failure ceiling. Loaded interactions
should feel immediate/local where safe. Inspect JS bundle impact, extra requests, image
size, chart/table rendering, layout shift, hydration and mobile polling. Use code
splitting, pagination/virtualization, prepared imagery, stable skeletons and local
sorting/filtering only when canonical-safe. Measure rather than infer performance.

## 14. Claims, parallel dispatch and required preimplementation audit

Before edits inspect current main, open PR changed files, issues/active branches,
WORK_CLAIMS and canonical planning/contracts, current design implementation/reference
routes and legacy. Claim exact frontend/docs/ui/tests/evidence paths. Do not have two
writers on globals.css, package.json, data_contract.py or server.py; shared edits need
custodian/Integration coordination. Backend agents coordinate UI coverage, not invade
another lane's files. Prefer separate UI branches and disjoint paths.

Before substantive code, report current PSI foundation, active work/PRs/claims,
migrated/partial/legacy routes, DS/mobile/a11y/performance gaps, Trade state, governance
files and the next safe unit. Evidence reconciles decisions versus implementation;
it is not a request to reopen the art direction.

After governance is committed, identify actual UI staffing/claims and start the highest-
priority dependency-safe unit if none is active. Prefer broadly unlocking foundations,
legacy-debt retirement, Trade UX, stable major routes or broad mobile/a11y/performance,
not issue-number order. If separate workers are supported, dispatch a separate branch.
Otherwise supply an exact issue, queued work claim, branch and fresh-session prompt;
never say a queued handoff is running. Documentation alone does not complete delivery.

## 15. Migration order, ledger and legacy retirement

Preserve the approved order unless dependencies justify a bounded reorder: shared PSI
foundation; shell/navigation; Rankings; Universal Player Profile; universal search/
command; Market + Sharp/Insider; Trade Analyzer/Finder/Package Builder/Trade Desk;
Team Strength/Weakness/roster/league intelligence; Draft/Waivers/Game Day/probability/
remaining tools; final legacy retirement. Independent stable routes may run concurrently.

No big-bang 150-file redesign or blind globals.css rewrite. Migrate route by route,
reviewable and reversible during development, responsive from day one, with data/
behavior parity, measured performance/a11y, visual evidence and explicit retirement.
Move consumers to tokens/DS, prove parity, then remove unreachable legacy selectors.
Do not delete styles before consumer retirement or add fresh legacy selectors to PSI.

The UI Parallel Ledger tracks route/surface, family, canonical backend owner, contract
stability, PSI migration state, desktop, mobile, accessibility, performance, legacy CSS,
visual proof, active claim/PR, dependency and next action. Map to existing planning/
integration taxonomy; never create a competing completion scoreboard. Source code is
not production/visual proof, and absence of fresh evidence is recorded as unverified.

## 16. Verification and completion

Governance: run current planning integrity, docs tests, WORK_CLAIMS checks and L0.
Frontend: current Vitest, build/bundle gates, lint only if actually enforced, route E2E,
axe/keyboard, visual review, responsive viewports and appropriate performance checks.
Read current repository commands rather than inventing outdated ones.

Every migrated production route needs desktop and phone screenshots. Add tablet,
interaction/loading/error/stale states where useful. Use existing Playwright/evidence
conventions and record exact SHA, URL, viewport, state, timestamp and result. DOM tests
are not visual verification; local/CI screenshots are not production verification.

After deployment inspect the actual production route: desktop/mobile, navigation,
primary workflow, canonical data, loading/refresh, stale/error, keyboard/focus, console,
layout shift and public/private gates. Respect credentials and protected deployment;
unavailable access is an explicit unverified gate, not inferred success.

PSI-complete requires correct canonical data and behavior, faithful visuals/shared
primitives, desktop/mobile parity, keyboard/a11y, loading/empty/error/stale/degraded
states, measured performance, no duplicate business math or needless requests, actual
deployment, screenshots/owner-review evidence and legacy-path retirement. Right colors
alone are not completion. Backend complete / UI incomplete = product incomplete.
Calculator Ideas tracks capability and UI as two dimensions of one product, without
double-counting scope; major legacy routes prevent declaring the full site complete.

## 17. Durable enforcement and handoff

Extend scripts/check_planning_integrity.py with small structural checks for this
contract/ledger, active planning pointers and the UI-batching rule; deletion/mutation
tests must prove these guards fail. Do not build a fragile prose-regex system. Such
checks cannot prove actual worker activity, aesthetics or deployed acceptance.

Use docs/ui/UI_IMPACT_TEMPLATE.md and the PR template for material product changes:
UI impact, existing lane or new parallel unit, route blocker/other active task, PSI
reference, mobile, accessibility, performance and visual evidence. Tiny maintenance
may explain no UI impact without paperwork; substantial planning still covers Lane 6.

Final report: governance files; permanent rule; contract; ledger; enforcement; current
migration status; active lane issue/branch/claim/dependency; next unit; exact tests;
PR/deployment status. Distinguish selected, implemented, tested, merged, deployed and
verified. Keep the UI program active until genuine completion is evidenced.
''')

# Compact amendments preserve all historical body text and authority records.
prepend("docs/EXECUTION_PLAN.md", f'''## Permanent parallel Premium UI — owner directive, 2026-09-24 (#1421)

{POLICY}

**Lane 6 / Premium UI is an always-active parallel lane through Calculator completion.**
Preserve UI/frontend/performance/accessibility ownership and C8-U1/C8-U2/C8-U3.
Every substantial batch includes useful UI or explicitly references an adequately
staffed active issue/PR/work claim. UI foundation is always eligible when dependencies
and file claims permit; final route migration is individually canonical-contract gated.
A changing Trade contract may block Trade wiring, not all UI.

Implement locked PSI / Direction A under `{CONTRACT}`; use `{LEDGER}` and Calculator
Ideas (`docs/BRISKET_IDEAS.md`). This authorizes the bounded governance/enforcement
reconciliation and continuous execution of already-approved safe UI, not unrelated
scope, new design exploration, changed denominators, model/serving activation or bypassed
Integration. Historical freezes/first-migration timing below stay traceable but cannot
globally defer UI under this newer instruction. Backend complete / UI incomplete is
product incomplete. First safe unit: #1422 `/design`, on its own branch/claim.
''')
prepend("docs/MASTER_PRODUCT_PLAN.md", f'''## Continuous UI convergence — owner decision, 2026-09-24 (#1421)

{POLICY}

Calculator Ideas is the entire remaining completion portfolio, including UI, not just
recent intake. Backend completion without user-facing completion is not product
completion. Track capability and UI evidence as two dimensions of one product, not
separate products or new denominator rows. Keep existing Lane 6 active beside model/
feature/data work. A route blocker redirects the UI lane to another safe task.
Every substantial batch includes UI or names its adequately staffed active claim/PR.
Use `{CONTRACT}` and `{LEDGER}`; implementation authority remains EXECUTION_PLAN.md.
''')
text = read("docs/BRISKET_IDEAS.md").replace("Brisket Ideas", "Calculator Ideas").replace("Brisket list", "Calculator list")
text = text.replace("for **Risk It To Get The Brisket / Chase Upside**.", "for **Calculator**.")
text = text.replace("Brisket has many historical", "Calculator has many historical")
(ROOT / "docs/BRISKET_IDEAS.md").write_text(text, encoding="utf-8")
prepend("docs/BRISKET_IDEAS.md", f'''## Full completion portfolio / permanent UI batching — 2026-09-24 (#1421)

{POLICY}
{BATCHING}

Calculator Ideas represents the entire remaining master site completion plan. Keep this
legacy filename; it is a front door, not a competing backlog. Before next reasonable
batch / next ten / parallel batches / fresh-session dispatch, reconcile current main,
open PRs/branches/claims, Master Plan, Feature Inventory, Product Backlog/specs, C-Series
manifest/map, completion contracts, owner intake, issues, code/production evidence and
the combined-phase replan. Remove completed/superseded/rejected work, group shared
foundations, respect dependencies and avoid active-file conflicts. Preserve #1419's
related full-portfolio reconciliation during integration, not one or the other.

Every substantial batch explicitly evaluates backend completion, UI completion, actual
UI staffing, stable routes, file/branch conflicts and integration order. Consult
`{CONTRACT}` and `{LEDGER}`. Required response shape:

- FOUNDATION / BACKEND: bounded authorized unit, canonical owner, dependencies.
- UI: safe unit/claim/branch, or `UI lane already active: <issue/PR/work claim>` with
  adequate coverage. Queued handoffs/old branches are not running workers. An unstable
  route contract blocks only its final wiring; select other useful UI work.
- INTEGRATION: contract connection, ordering, E2E and production proof. Backend complete
  / UI incomplete = product incomplete, without double-counting scope.

Use `docs/ui/UI_IMPACT_TEMPLATE.md` for material feature plans. Tiny maintenance need
not manufacture UI edits; substantial planning still names Lane 6 coverage.
''')
prepend("ASSISTANT_COORDINATION.md", f'''## Permanent parallel UI coordination — 2026-09-24 (#1421)

{POLICY}

Every substantial Calculator feature session asks: Does this affect frontend? Is its
route contract stable enough for parallel UI? If yes, where is the UI claim/PR? If no,
what other UI work stays active? Foundation remains eligible when dependencies/file
claims permit; instability gates only that route's final integration.

Use `{CONTRACT}` and `{LEDGER}`; keep Lane 6 in Calculator Ideas batching. PSI /
Direction A is locked, not an invitation to invent styling. Material plans use
`docs/ui/UI_IMPACT_TEMPLATE.md`. Backend writers coordinate coverage, not invade UI
files. Shared globals.css/package.json/server.py/data_contract.py edits require the
existing custodian/Integration process. Separate branches/claims; no safe worker runtime
means exact issue, queued claim, branch and fresh-session handoff, not a claimed running
worker. Existing protected integration/release authority below is unchanged.
''')
replace("CLAUDE.md", "## What this document is — and is not", f'''## Calculator Premium UI — permanent parallel rule

PSI / Direction A is the permanent design north star. Do not invent styling. Read
`{CONTRACT}` and `{LEDGER}`; keep Lane 6 active in substantial batches or name its
already-active claim/PR. Route instability blocks that route, not all UI. Coordination
owns dispatch; this is a universal rule for every model, not a Claude-only instruction.

## What this document is — and is not''')
prepend("docs/C_SERIES_EXECUTION_MAP.md", f'''## Current parallel-UI amendment — 2026-09-24 (#1421)

C8-U1 / C8-U2 / C8-U3 are the existing always-active Lane 6 program, not a late sequential
phase. Shared performance/design/accessibility foundation can run in parallel when
its dependencies/file claims permit. Consumer routes join migration individually as
canonical contracts stabilize; final legacy removal waits for replacement parity.
Use `{CONTRACT}` and `{LEDGER}`. Every substantial Calculator Ideas batch includes or
references active UI. Historical freeze records remain; EXECUTION_PLAN.md is current
authority. No IDs, census totals, methodology or dependency owners are changed.
''')
replace("docs/C_SERIES_EXECUTION_MAP.md", "a structural ratchet exists today but no axe-core.", "the structural ratchet and axe E2E exist; populated reference-route coverage remains.")
replace("docs/C_SERIES_EXECUTION_MAP.md", "**Parallel-safe (any time):** C0-U2 · C0-U3 · C1-U1 · C4-U1 · C8-U1 · C5-U6", "**Parallel-safe (when dependencies/file claims permit):** C0-U2 · C0-U3 · C1-U1 · C4-U1 · C8-U1 · C5-U6; shared C8-U2/C8-U3 foundation is also parallel-eligible. Final consumer wiring is individually contract-gated under the 2026-09-24 amendment.")
prepend("docs/PREMIUM_SPORTS_INTELLIGENCE_DESIGN_NORTH_STAR.md", f'''> **CURRENT EXECUTION AMENDMENT — 2026-09-24 (#1421).** PSI / Direction A remains the
> permanent owner-approved design. Historical preparation/wait/trigger records below
> are traceability, not a current global UI blocker. Lane 6 stays active in parallel:
> foundation is eligible when dependencies/claims permit; final route wiring is
> individually contract-gated. No aesthetic exploration or replacement direction.
> Implementation: `{CONTRACT}`; queue/evidence: `{LEDGER}`; execution authority:
> `docs/EXECUTION_PLAN.md`.
''')
prepend("docs/DESIGN-SYSTEM.md", f'''## Current PSI authority — 2026-09-24 (#1421)

PSI / Direction A is locked. Migrated surfaces use `.psi-editorial` in tokens.css:
warm cream, near-black ink, one burnt-red identity/interactive accent, --font-display,
2/2/3px radii, thin rules and shadows only for actual overlays. Use `{CONTRACT}` and
`{LEDGER}`. Gold/black terminal reasoning and measurements below describe the retained
legacy theme, not new PSI authority. Preserve correct token/component machinery, not
that obsolete aesthetic. Dark-theme chart validation does not prove every editorial
plot surface. Compatibility aliases are migration debt, not new-consumer permission.
No new palette/font/type scale/radius/breakpoint or page-local visual language.
''')
replace("docs/DESIGN-SYSTEM.md", '## 1. Visual direction: "War-room terminal"', '## 1. Historical retained theme: "War-room terminal" (not current PSI authority)')
replace("docs/DESIGN-SYSTEM.md", "11 / 12 / 13 / 14 / 16 / 20 / 24 / 32 px", "11 / 12 / 13 / 14 / 16 / 18 / 22 / 28 px")
replace("docs/DESIGN-SYSTEM.md", "`--radius-1` 4px (inputs, badges) · `--radius-2` 8px (buttons, tiles) · `--radius-3` 12px (panels, modals)", "`--radius-1` 2px (inputs, badges) · `--radius-2` 2px (buttons, tiles) · `--radius-3` 3px (panels, modals)")
replace("docs/DESIGN-SYSTEM.md", 'Dark is default. `:root[data-theme="light"]`', 'The retained unmigrated theme defaults to dark; `.psi-editorial` is the approved migration scope. `:root[data-theme="light"]`')
replace("docs/C_SERIES_SCOPE_MANIFEST.md", "PARTIAL — 24 ds components, token contract test, per-page bundle budgets, a11y ratchet; **no axe-core**; live tokens contradict the north star", "PARTIAL — DS, PSI editorial tokens, shell, bundle gates and axe E2E exist; gallery/docs drift and per-route proof remain (`docs/ui/UI_PARALLEL_LEDGER.md`, 2026-09-24)")
replace("docs/C_SERIES_SCOPE_MANIFEST.md", "| `C8-PSI-02` | Reference route migration (Rankings first) | `frontend/app/rankings/` | ABSENT |", "| `C8-PSI-02` | Reference route migration (Rankings first) | `frontend/app/rankings/` | PARTIAL — Rankings and Player File PSI code exists; current full proof/legacy retirement not certified (`docs/ui/UI_PARALLEL_LEDGER.md`) |")
replace("docs/C_SERIES_SCOPE_MANIFEST.md", "| `C8-PSI-03` | Route-by-route migration | frontend | ABSENT |", "| `C8-PSI-03` | Route-by-route migration | frontend | PARTIAL — several PSI-scoped routes exist, including merged Trade #1294; remaining parity/evidence in `docs/ui/UI_PARALLEL_LEDGER.md` |")
replace("docs/C_SERIES_SCOPE_MANIFEST.md", "PARTIAL — structural ratchet exists, no axe-core", "PARTIAL — structural ratchet and axe E2E exist; populated reference-route coverage and current production proof remain")
replace("docs/OWNER_REQUESTED_TODO.md", "## Brisket Ideas shorthand and intake discipline — owner decision 2026-09-24", f'''## Permanent parallel Premium UI / locked PSI — owner directive 2026-09-24

Binding owner instruction #1421 is incorporated in `{CONTRACT}`; queue/evidence:
`{LEDGER}`. This is the live intake pointer, not a second ledger. Existing Lane 6 /
C8-U1/U2/U3 stays active in parallel until genuine UI/product completion. Every substantial
Calculator Ideas batch includes useful UI or names adequate active coverage. A route's
unstable contract blocks its final integration, never all UI. Locked Direction A,
semantic DS/reference reuse, mobile parity, honest data, a11y/performance, desktop/phone
and production proof apply. Backend complete / UI incomplete is product incomplete.

The owner authorizes this bounded governance/enforcement reconciliation and continuation
of already-approved safe UI; `docs/EXECUTION_PLAN.md` records current authority. No
unrelated scope, model/serving activation or denominator change. First safe unit: #1422
`/design`, separate `codex/psi-design-reference` branch/claim; exact dispatch in
`docs/ui/PSI_DESIGN_REFERENCE_HANDOFF.md`. Queued is not running. Integration reconciles
#1416/#1419/#1344 without discarding their work. No deployment/completion is asserted.

## Calculator Ideas shorthand and intake discipline — owner decision 2026-09-24''')
replace("docs/OWNER_REQUESTED_TODO.md", "**Friendly owner-facing name:** **Brisket Ideas**. When the owner says “add this to Brisket Ideas,” “put this on the Brisket list,”", "**Friendly owner-facing name:** **Calculator Ideas**. When the owner says “add this to Calculator Ideas,” “put this on the Calculator list,”")

put("docs/ui/UI_IMPACT_TEMPLATE.md", '''
# Calculator — UI impact for a material product change

Use for substantial feature plans/PRs. Tiny maintenance may state no UI impact and omit
irrelevant fields; substantial batching still names Lane 6 coverage. Read
`docs/ui/CALCULATOR_UI_IMPLEMENTATION_CONTRACT.md` and `docs/ui/UI_PARALLEL_LEDGER.md`.

```text
UI impact:
[ ] none — explain
[ ] existing active UI lane covers it — issue / PR / claim and coverage
[ ] parallel UI work included — bounded unit / branch / claim
[ ] route contract not stable — named ledger dependency;
    other active UI unit / claim:
Canonical backend owner / stable contract boundary:
UI paths / conflict check:
PSI reference used (route / primitive / spec):
Mobile verified (viewport / workflow / evidence, or not verified):
Accessibility verified (axe / keyboard / focus, or not verified):
Performance checked (command / measurements, or not measured):
Visual evidence (desktop / phone / states / exact SHA, or not captured):
Integration order / production verification owner:
```

Queued != running. Source styling != visual verification. Local/CI screenshots !=
production proof. Capability complete / UI incomplete remains product incomplete.
''')
put(".github/pull_request_template.md", '''
## Summary

Bounded outcome, authority, related issue and canonical owner.

## Validation and evidence

Exact commands, tested SHA, results and limitations. Separate local/CI from production.
Material agent work includes its `Agent-OS-Receipt`.

## UI impact (material product/UI changes only)

Tiny maintenance may explain none and omit irrelevant fields. Substantial batches
still include or reference active Lane 6 coverage.

- [ ] none — explain
- [ ] existing active UI lane covers it — issue / PR / work claim
- [ ] parallel UI work included — branch / claim
- [ ] route contract not stable — ledger dependency; name other active UI work

PSI reference used:
Mobile verified:
Accessibility verified:
Performance checked:
Visual evidence:

Details: `docs/ui/UI_IMPACT_TEMPLATE.md`,
`docs/ui/CALCULATOR_UI_IMPLEMENTATION_CONTRACT.md`, `docs/ui/UI_PARALLEL_LEDGER.md`.

## Integration / release

Dependencies, live-PR file overlap, rollout/rollback and outstanding production proof.
Do not equate code, tests, merge, deployment and verified acceptance.
''')

# Each tuple records evidence, not inferred green checkmarks.
surfaces = [
    ("/design", "C8-U2/U3", "Static gallery / ds/token-contract.js; no private API", "STABLE foundation", "Legacy gallery; #1422 selected", "#1422 queued", "Governance contract / gallery claim", "Apply existing PSI scope including portals; fixtures/display roles; responsive/axe/screenshots"),
    ("tokens / ds primitives", "C8-U2/U3", "tokens.css + components/ds/*", "STABLE styling API; extensions separately claimed", "Editorial tokens/shared behaviors exist", "No new primitive writer confirmed", "Preserve owner values and actual surface contrasts", "Reconcile gallery/docs and state examples; legacy aliases remain debt"),
    ("shell / nav / command", "C8-U2/U3", "AppShell, AppShellWrapper, nav-model, auth owner", "Existing shared IA; serving files overlap", "Top/mobile chrome PSI-scoped", "#1346", "One IA; auth and public/private boundaries", "Re-certify focus/search/mobile parity; separately claim shared fixes"),
    ("/rankings", "C8-U2 reference", "useApp/useDynastyData -> canonical /api/data", "Existing consumer; #1411/#1346 upstream changes", "PSI reference code exists", "#1346 overlap", "Stable consumer boundary; no valuation duplication", "Re-certify dense table, filters, identity, populated axe and performance"),
    ("/players/[playerId]", "C8-U2 reference", "Canonical AppShell rows / player identity + player-file-model", "Existing contract; next feature boundary needs audit", "PSI reference code exists", "#1346 overlap", "One player experience; preserve identity", "Populated player-profile E2E/axe, mobile depth and convergence"),
    ("/trade", "C3 + C8-U2", "Existing trade-logic + /api/trade/* canonical owners", "CONDITIONAL: #1414/#1415 lifecycle/quantity/analysis", "PSI code; #1294 merged September 9", "#1346 overlap; #1294 stale claim corrected", "Per-unit canonical asset/analysis contract", "Identity/quantity/mobile UX beside engine work; no new math; nested-main/420/360 legacy debt remains"),
    ("/finder / /arbitrage / /trades", "C3 + C8-U2", "Existing finder/package/history owners; trace each endpoint", "NOT re-certified", "Mixed DS/legacy and redirects", "#1346 overlap", "C3 package/identity/decision substrate", "Audit destinations and reuse shared asset/result primitives"),
    ("/market/* / Sharp / Insider", "C4 + C8-U2", "Existing market/Sharp canonical endpoints", "Existing consumers; freshness semantics changed", "Partial DS/PSI family migration", "#1346 overlap", "Source/market separation; no frontend verdict engine", "Reference fidelity, honest coverage and mobile proof"),
    ("/rosters", "C2 + C8-U2", "/api/roster/intelligence -> src/roster_intel/strength.py", "Existing consumer; serving overlap", "DS-backed; not PSI-certified", "#1346", "Canonical strength/league state", "Shared table/identity and roster-context parity"),
    ("/phases", "C2 + C8-U2", "Existing canonical competitive-posture consumers", "NOT re-certified", "Partial DS/PSI work present", "#1346 overlap", "Canonical posture owner", "Presentation/mobile evidence; no posture recalculation"),
    ("/waivers", "C4 + C8-U2", "/api/waiver/suggestions + canonical FAAB/roster owners", "Existing consumer; exact boundaries need audit", "DS-backed partial migration", "#1346", "Canonical add/drop/FAAB/league context", "Coordinated desktop panes; deliberate mobile stack/tabs and results"),
    ("/draft", "C1/C5 + C8-U2", "/api/draft-capital + canonical pick lifecycle", "CONDITIONAL: #1414 and pick pipeline", "DS-backed partial migration", "#1346 / #1411", "Canonical active-pick lifecycle, not local calendar filter", "Safe controls/mobile first; integrate retired classes when stable"),
    ("/gameday", "C9 + C8-U2", "GameDayPanel / canonical matchup and season contracts", "CONDITIONAL by feature", "Legacy/partial; #1335 hierarchy remains", "No new UI writer confirmed", "Selected team / exact best-ball projection", "Matchup/verdict/slate first, deep details disclosed; do not invent visual direction"),
    ("/league and public subroutes", "C9 + C8-U2", "src/public_league/* / public semantic boundary", "Existing public contracts; route-specific evolution", "Mixed DS / legacy", "#1381 power/card overlap", "Never expose private intelligence publicly", "Audit hubs/franchise/articles/history per route and preserve parity"),
    ("/league-comparison", "C9 + C8-U2", "Existing LeagueComparison client/API owner", "CHANGING in #1399", "Existing UI; no PSI completion proof", "#1399 active", "Coordinate live consumer files/contract", "Avoid restyling claimed files; select another safe unit"),
    ("/news / /trending", "C4 + C8-U2", "Existing factual news/trending owners", "NOT re-certified", "DS-backed partial", "#1346 overlap", "Distinguish factual news and inference", "Audit prose/display, freshness and mobile identity"),
    ("/consensus-edge / /edge / /bdvm / /angle", "C1/C4 + C8-U2", "Existing canonical edge/BDVM/angle owners", "NOT re-certified", "Mixed DS/legacy", "#1346 overlap", "No UI model recomputation", "Hierarchy/explainability and missing-source semantics"),
    ("/login / home", "C8-U2 / auth", "Existing auth owner and public-safe shell", "Existing auth mechanics", "PSI-scoped code", "No new writer confirmed", "Auth/gating and focus remain intact", "Re-certify error/keyboard/mobile; no new marketing hero"),
    ("/settings / /more", "C8-U2 / context", "Settings/League providers + nav-model", "Existing consumers", "DS-backed partial", "#1346 overlap", "Clear canonical ON/OFF and selected league/team", "Verify one IA/context across workflows"),
    ("/admin / sharp-identities", "C8-U2 / operations", "Existing authenticated admin/identity owners", "NOT re-certified", "Mixed DS/legacy", "#1346 overlap on some files", "Sensitive auth/write controls", "Audit actions/failure states without public leakage"),
    ("/tools/source-health / ros-data-health / trade-coverage", "C8-U2 / diagnostics", "Existing source/ROS/trade coverage owners", "NOT re-certified; source semantics changed", "Mixed DS/legacy", "#1346 overlap", "Fetch freshness is not content freshness", "Shared honest states; preserve exempt-route request policy"),
    ("/players/compare / residual routes / aliases", "C8-U2", "Existing comparison/final destination owners", "NOT re-certified", "Residual legacy/details unclassified", "No new writer confirmed", "Inventory actual consumers before CSS deletion", "Audit final destinations; aliases are not separate products"),
]
ledger = f'''# Calculator — UI Parallel Ledger

**Program:** existing Lane 6 / C8-U1, C8-U2, C8-U3.
**Contract:** `{CONTRACT}`.
**Source audit:** 2026-09-24 main `{BASE}`.
**Evidence:** `docs/ui/UI_AUDIT_2026-09-24.md`.
Recheck current main, live PR files and `docs/WORK_CLAIMS.md` before dispatch.

## Status mapping and evidence limits

This is a UI dimension of Calculator Ideas, not a second backlog or denominator.
Planning remains NOW/NEXT/LATER/BLOCKED; concurrency remains SAFE_PARALLEL /
SERIAL_CANONICAL_OWNER / INTEGRATION_ONLY / DEPENDENCY_BLOCKED. Preserve existing
FEATURE_GREEN / READY_FOR_INTEGRATION / INTEGRATION_GREEN evidence standards.
Owner migration labels may refine this dimension: NOT_AUDITED, AUDITED,
FOUNDATION_READY, CONTRACT_BLOCKED, READY_TO_MIGRATE, MIGRATING, FEATURE_GREEN,
DEPLOYED, PSI_VERIFIED, LEGACY_RETIRED. They never auto-promote a completion-contract row.

Initial rows are AUDITED at source level. PSI-scoped means code consumes the scope,
not that behavior or production screenshots were re-certified. NV = not freshly
verified; NM = no current measurement from this audit. Existing axe is instrumentation,
not a passing populated-state scan for each listed route. Historical proof stays labelled.

## Active program / dispatch

#1346 `codex/performance-serving` is existing draft performance work (audit head
47b90cd412eeed8c8429487de8109823d82baac0), not a visual-completion or activation claim.
#1399 `codex/league-comparison-2026-live` is frontend consumer work. #1421 owns bounded
governance. #1422 `codex/psi-design-reference` is the selected NEXT/queued reference
unit until a worker starts; do not equate an issue/branch with a running session.
Exact dispatch is `docs/ui/PSI_DESIGN_REFERENCE_HANDOFF.md`. #1294 merged September 9;
its old open claim is not an active writer, but independent live overlaps still matter.

## Major surface inventory

| Route / surface | Family | Canonical owner | Contract stability | PSI state | Desktop | Mobile | Accessibility | Performance | Legacy CSS | Visual proof | Claim / PR | Hard dependency | Next action |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
'''
for route, family, owner, stability, state, active, dependency, action in surfaces:
    ledger += f"| `{route}` | {family} | {owner} | {stability} | AUDITED — {state} | Code inspected; NV | Parity NV | Existing suite; route NV | NM | Retirement not re-certified | No fresh production screenshots | {active} | {dependency} | {action} |\n"
ledger += '''
## Updating a unit / safe sequence

Record exact claim/PR/head, stable contract boundary, viewports, keyboard/axe result,
performance command/measurements, screenshot paths/run, deployment SHA/URL/time,
unresolved defects and retired legacy selectors. A blocked route names the next safe
UI task. Local/CI images do not establish production verification.

First #1422 fixes the living /design reference without trade/backend dependencies.
Next complete the populated Rankings/Player File accessibility/visual matrix with
#1346/shared-test-owner coordination; then advance agreed Trade asset identity/quantity
presentation while final lifecycle/Analyze Trade wiring waits only on its own contract.
Continue high-value stable routes and verified legacy retirement, reprioritizing each
batch rather than waiting for every backend feature to finish.
'''
put(LEDGER, ledger)

put("docs/ui/UI_AUDIT_2026-09-24.md", f'''# Calculator — PSI and parallel-work source audit, 2026-09-24

Pinned main: `{BASE}`. Agent OS blob: `{RECEIPT}`.
This is source/coordination evidence, not browser/performance/production certification.

## Read scope and method

Inspected main, the owner/execution/intake/manifest/completion records, coordination,
CLAUDE/runbook, WORK_CLAIMS, tokens/ds/globals/shell, design gallery, ds/shell primitives,
AppShell/AppShellWrapper, nav-model and Rankings/Player File/Trade references.
Read-only Actions run 36014885952 collected paginated open PRs/issues/branches and each
open PR's changed-file list: 21 PRs, 96 issue/PR entries, 167 branch heads at snapshot.
New #1421/#1422 entries postdate it. Branch existence is not staffing proof. The temporary
source/application helpers must be absent from the final integration tree.

## Required preimplementation findings

| Area | Evidence / conclusion |
|---|---|
| Foundation | tokens.css already has exact owner PSI editorial palette, display token, 2/2/3px radii and canonical breakpoints; shared DS exists. |
| Active UI | #1346 draft performance/prepared-serving; #1399 League Comparison. No open PR changed the proposed #1422 gallery/test paths at audit. |
| PSI-scoped | Rankings, Universal Player File, Trade, login/home and top/mobile chrome contain PSI implementation, not a fresh completion certificate. |
| Partial | Market/Sharp, rosters, waivers, phases and tools use shared components with migration/evidence still incomplete. |
| Legacy | Public-league subroutes, diagnostics and comparison/residual surfaces retain mixed legacy presentation; see ledger. |
| DS conflicts | DS guide says gold/black current and 4/8/12 radii vs live 2/2/3; its upper type sizes 20/24/32 differ from live 18/22/28. Gallery lacked PSI scope/display example. Manifest incorrectly said no references/no axe. |
| Mobile gaps | Fresh workflow/identity/detail-access parity not established. Trade retained legacy 420/360 composition and nested main; do not copy those as new canonical conventions. |
| A11y gaps | Existing tests/e2e/specs/a11y-axe.spec.js has ten routes, omits /design and a populated Player File and uses a fixed delay. Structural tests are not populated-state proof. |
| Performance | #1346 remains unfinished; no fresh useful-data latency/runtime measurements established here. |
| Trade | Already PSI-scoped with DS/mobile quick-add. #1294 merged 2026-09-09 as 014722b9af0fa0e7473f133d115a17eec66ea887; its old claim was stale. #1414/#1415 lifecycle/quantity correctness remains distinct. |
| Governance | Contract/ledger, canonical planning/runbook pointers, owner intake/claims, templates, dated supersession, DS status corrections and focused integrity guards/tests. |
| Next safe unit | #1422 /design reference fidelity: existing static DS contracts, no changing trade dependency and no observed gallery-file overlap. |

## Coordination / engineering applicability

#1416 owns pick/quantity intake/C-Series changes; #1419 full-portfolio front door;
#1344 shared harness instructions. Preserve both their substance and this bounded UI
amendment when Integration reconciles exact heads. No backend high-conflict file,
frontend runtime/style owner, dependency manifest or serving activation is edited by
governance. Historical dispatcher snapshots are not current worker authority.

APPLY_NOW: structural invariants and deletion/mutation tests, explicit file boundaries
and truthful evidence. ALREADY_COVERED: DS/token architecture, axe/Playwright, bundle
gates. NOT_RELEVANT: new valuation/scoring/acquisition/persistence. DEFERRED_BY_AUTHORITY:
broad serving activation, all-route restyling and unrelated model changes.

## Current exact commands and evidence boundaries

Governance: python scripts/check_planning_integrity.py;
python scripts/check_product_plan_governance.py; python -m pytest tests/docs -q;
python scripts/check_work_claims.py --files <paths> --branch <branch>;
bash scripts/tiered_validate.sh l0. Python formatting uses the pinned Ruff 0.6.9 through
bash scripts/format_python_changes.sh. Local source-only testing lacks runtime data;
use complete CI and actual production evidence for their respective gates.

Frontend: npm test and npm run build in frontend (build includes bundle checks).
No separate lint script exists at audit. Playwright uses tests/e2e/playwright.config.js,
including desktop-1366 and mobile-chromium projects. Discover current harness conditions
before execution; record actual commands/results, not anticipated passes.
''')
put("docs/ui/PSI_DESIGN_REFERENCE_HANDOFF.md", f'''# Fresh-session handoff — #1422 /design PSI reference

Existing Lane 6 / C8-U2 + C8-U3, parent #1421.
Branch: `codex/psi-design-reference`, separate and stacked on the reviewable governance
head until Integration lands it. Initial status NEXT/queued, not running or verified.
Agent-OS-Receipt at audit: {RECEIPT}; regenerate for the implementation session.

## Copyable prompt

```text
Repo jasonleetucker-code/riskittogetthebrisket, project Calculator. Implement #1422.
Read AI_INSTRUCTIONS, current Agent OS, Execution Plan/active completion contract,
WORK_CLAIMS and live open PR changed files. Read PSI North Star,
docs/ui/CALCULATOR_UI_IMPLEMENTATION_CONTRACT.md, UI_PARALLEL_LEDGER.md and dated audit.
Recheck #1421 governance, #1346 performance and #1399; do not assume this audit is current.

Claim only frontend/app/design/DesignGallery.jsx, frontend/app/design/design.module.css,
frontend/app/design/page.jsx, frontend/__tests__/components/ds/psi-gallery.test.jsx,
tests/e2e/specs/psi-gallery.spec.js, bounded docs/ui evidence and WORK_CLAIMS updates.
Separate branch codex/psi-design-reference; stack on governance while it is unmerged.
No globals.css/tokens.css/ds.css/AppShell/nav-model/package.json/backend/math/deploy edits.

Audit Gallery/Modal/Drawer APIs. Apply existing psi-editorial scope, including portalled
examples. Demonstrate existing font-display; correct terminal/gold/historical contrast
labels. Explicitly label fixture values/actions as demonstrations, not live league data
or real offers. Preserve all useful examples and noindex/no-nav/private-request exemption.
Use current shared primitives, semantic tokens and canonical breakpoints. No new palette,
font, radius, type scale or visual language. A genuinely new visual decision is OWNER UI
DECISION REQUIRED for only that choice; continue other safe work.

Ensure desktop/phone access to controls, player identity and table detail. Test keyboard,
focus restoration, dialog/drawer and reduced motion. Add deterministic component and
Playwright/axe tests with meaningful readiness, not a sleep-only scan. Capture and inspect
desktop and phone screenshots plus overlays/states. Run current Vitest, build/bundle,
E2E/axe and L0 commands. Record failures, do not weaken checks. Shared primitive repairs
need a separate bounded claim rather than silent cross-lane editing.

Update ledger/claim with exact SHA/tests/evidence. Integration and actual production
verification remain separate required gates. Never call local/CI screenshots production
proof or self-merge. Route instability redirects UI work; it does not stop Lane 6.
```
''')

registry_rows = f'''
| `{CONTRACT}` | Binding implementation of locked PSI; existing Lane 6 parallel rule, not independent scope or authorization |
| `{LEDGER}` | Operational UI migration/claim/evidence dimension; no competing product denominator |
| `docs/ui/UI_AUDIT_2026-09-24.md` | Dated source and work-overlap audit; not current production proof |
| `docs/ui/UI_IMPACT_TEMPLATE.md` | Proportional material feature/PR handoff template |
| `docs/ui/PSI_DESIGN_REFERENCE_HANDOFF.md` | Bounded #1422 dispatch; recheck current claims before starting |
'''
replace("docs/PLANNING_DOCUMENT_STATUS.md", "| Document | Authority |\n|---|---|", "| Document | Authority |\n|---|---|" + registry_rows.rstrip())
text = read("docs/PLANNING_DOCUMENT_STATUS.md").replace("Brisket Ideas", "Calculator Ideas")
(ROOT / "docs/PLANNING_DOCUMENT_STATUS.md").write_text(text, encoding="utf-8")

# Small structural contract, not a fragile natural-language parser.
checker = '''
UI_CONTRACT = "docs/ui/CALCULATOR_UI_IMPLEMENTATION_CONTRACT.md"
UI_LEDGER = "docs/ui/UI_PARALLEL_LEDGER.md"
UI_POLICY = "UI policy: ALWAYS_PARALLEL_UNTIL_UI_COMPLETE"
UI_BATCHING = "UI batching: INCLUDE_OR_REFERENCE_ACTIVE_LANE"
UI_POLICY_DOCUMENTS = (
    "docs/EXECUTION_PLAN.md", "docs/MASTER_PRODUCT_PLAN.md",
    "docs/BRISKET_IDEAS.md", "ASSISTANT_COORDINATION.md",
)
UI_POINTER_DOCUMENTS = (*UI_POLICY_DOCUMENTS, "CLAUDE.md", "docs/C_SERIES_EXECUTION_MAP.md")


def check_ui_parallel_governance(f: Failures, root: Path | None = None) -> None:
    """Guard durable UI planning links, not worker activity or visual acceptance."""
    root = REPO if root is None else root
    texts = {}
    for relative in dict.fromkeys((UI_CONTRACT, UI_LEDGER, *UI_POINTER_DOCUMENTS)):
        try:
            text = (root / relative).read_text(encoding="utf-8")
        except (OSError, UnicodeError) as exc:
            f.add("ui-parallel", f"{relative}: required readable document missing ({exc})")
            continue
        if not text.strip():
            f.add("ui-parallel", f"{relative}: required document is empty")
            continue
        texts[relative] = text
    for relative in (UI_CONTRACT, *UI_POLICY_DOCUMENTS):
        if relative in texts and UI_POLICY not in {line.strip() for line in texts[relative].splitlines()}:
            f.add("ui-parallel", f"{relative}: missing operative field {UI_POLICY!r}")
    ideas = texts.get("docs/BRISKET_IDEAS.md")
    if ideas is not None and UI_BATCHING not in {line.strip() for line in ideas.splitlines()}:
        f.add("ui-parallel", "docs/BRISKET_IDEAS.md: active UI batching field is missing")
    links = {relative: (UI_CONTRACT, UI_LEDGER) for relative in UI_POINTER_DOCUMENTS}
    links[UI_CONTRACT] = ("docs/PREMIUM_SPORTS_INTELLIGENCE_DESIGN_NORTH_STAR.md", UI_LEDGER)
    links[UI_LEDGER] = (UI_CONTRACT, "docs/WORK_CLAIMS.md")
    for relative, targets in links.items():
        if relative in texts:
            for target in targets:
                if target not in texts[relative]:
                    f.add("ui-parallel", f"{relative}: missing canonical pointer {target}")

'''
replace("scripts/check_planning_integrity.py", "\ndef main() -> int:\n", "\n" + checker + "\ndef main() -> int:\n")
replace("scripts/check_planning_integrity.py", "        check_reserved_phrase(f)\n", "        check_reserved_phrase(f)\n        check_ui_parallel_governance(f)\n")
replace("scripts/check_planning_integrity.py", '    print("  V1 standing tally agrees with the V1 row table")', '    print("  V1 standing tally agrees with the V1 row table")\n    print("  UI contract, ledger, planning pointers and parallel batching policy remain connected")')
put("tests/docs/test_ui_parallel_governance.py", '''
"""Deletion/mutation tests for the durable Lane 6 planning contract."""
from __future__ import annotations
import ast
import tempfile
import unittest
from pathlib import Path
from scripts import check_planning_integrity as planning


class UIParallelGovernanceTests(unittest.TestCase):
    def setUp(self) -> None:
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.root = Path(directory.name)
        for relative in dict.fromkeys((planning.UI_CONTRACT, planning.UI_LEDGER, *planning.UI_POINTER_DOCUMENTS)):
            path = self.root / relative
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text("\\n".join((
                "# Minimal structural fixture", planning.UI_POLICY, planning.UI_BATCHING,
                planning.UI_CONTRACT, planning.UI_LEDGER,
                "docs/PREMIUM_SPORTS_INTELLIGENCE_DESIGN_NORTH_STAR.md", "docs/WORK_CLAIMS.md",
            )), encoding="utf-8")

    def failures(self, root: Path | None = None) -> planning.Failures:
        failures = planning.Failures()
        planning.check_ui_parallel_governance(failures, self.root if root is None else root)
        return failures

    def test_current_repository_and_minimal_tree_pass(self) -> None:
        self.assertEqual([], self.failures())
        self.assertEqual([], self.failures(planning.REPO))

    def test_deleting_each_required_document_fails(self) -> None:
        for path in list(self.root.rglob("*.md")):
            with self.subTest(document=str(path.relative_to(self.root))):
                text = path.read_text(encoding="utf-8")
                path.unlink()
                self.assertTrue(self.failures())
                self.assertIn(str(path.relative_to(self.root)), "\\n".join(self.failures()))
                path.write_text(text, encoding="utf-8")

    def test_empty_or_unreadable_contract_and_ledger_fail(self) -> None:
        for relative in (planning.UI_CONTRACT, planning.UI_LEDGER):
            path = self.root / relative
            original = path.read_bytes()
            for content in (b" \\n", b"\\xff"):
                with self.subTest(document=relative, content=content):
                    path.write_bytes(content)
                    self.assertTrue(self.failures())
            path.write_bytes(original)

    def test_each_front_door_pointer_is_required(self) -> None:
        for relative in planning.UI_POINTER_DOCUMENTS:
            path = self.root / relative
            original = path.read_text(encoding="utf-8")
            for target in (planning.UI_CONTRACT, planning.UI_LEDGER):
                with self.subTest(document=relative, target=target):
                    path.write_text(original.replace(target, "removed-pointer"), encoding="utf-8")
                    self.assertTrue(self.failures())
            path.write_text(original, encoding="utf-8")

    def test_policy_cannot_disappear_or_become_a_quoted_example(self) -> None:
        for relative in (planning.UI_CONTRACT, *planning.UI_POLICY_DOCUMENTS):
            path = self.root / relative
            original = path.read_text(encoding="utf-8")
            for replacement in ("", "UI policy: DEFER_UI_UNTIL_END", "> " + planning.UI_POLICY):
                with self.subTest(document=relative, replacement=replacement):
                    path.write_text(original.replace(planning.UI_POLICY, replacement), encoding="utf-8")
                    self.assertTrue(self.failures())
            path.write_text(original, encoding="utf-8")

    def test_explicit_ideas_batching_field_is_required(self) -> None:
        path = self.root / "docs/BRISKET_IDEAS.md"
        path.write_text(path.read_text(encoding="utf-8").replace(planning.UI_BATCHING, ""), encoding="utf-8")
        self.assertTrue(self.failures())

    def test_contract_and_ledger_authority_links_are_required(self) -> None:
        for relative, target in (
            (planning.UI_CONTRACT, "docs/PREMIUM_SPORTS_INTELLIGENCE_DESIGN_NORTH_STAR.md"),
            (planning.UI_CONTRACT, planning.UI_LEDGER), (planning.UI_LEDGER, planning.UI_CONTRACT),
            (planning.UI_LEDGER, "docs/WORK_CLAIMS.md"),
        ):
            with self.subTest(document=relative, target=target):
                path = self.root / relative
                original = path.read_text(encoding="utf-8")
                path.write_text(original.replace(target, ""), encoding="utf-8")
                self.assertTrue(self.failures())
                path.write_text(original, encoding="utf-8")

    def test_main_actually_invokes_the_guard(self) -> None:
        tree = ast.parse(Path(planning.__file__).read_text(encoding="utf-8"))
        main = next(node for node in tree.body if isinstance(node, ast.FunctionDef) and node.name == "main")
        calls = {node.func.id for node in ast.walk(main) if isinstance(node, ast.Call) and isinstance(node.func, ast.Name)}
        self.assertIn("check_ui_parallel_governance", calls)
''')

# Correct only the externally confirmed stale #1294 claim.
lines = read("docs/WORK_CLAIMS.md").splitlines()
for index, line in enumerate(lines):
    if "| `claude/psi-trade-page` |" in line:
        before, _ = line.rsplit(" | ", 1)
        lines[index] = before + f" | done — PR #1294 merged 2026-09-09 as 014722b9af0fa0e7473f133d115a17eec66ea887; prior evidence is historical, not fresh production proof. Agent-OS-Receipt: {RECEIPT} |"
claims = "\n".join(lines) + "\n"
queued = (
    "| **PSI gallery reference #1422, existing Lane 6 / C8-U2/U3.** See `docs/ui/PSI_DESIGN_REFERENCE_HANDOFF.md`. "
    "| `frontend/app/design/DesignGallery.jsx`, `frontend/app/design/design.module.css`, `frontend/app/design/page.jsx`, "
    "`frontend/__tests__/components/ds/psi-gallery.test.jsx`, `tests/e2e/specs/psi-gallery.spec.js`, bounded `docs/ui/` evidence and `docs/WORK_CLAIMS.md` "
    f"| #1422 | `codex/psi-design-reference` | queued — not a running worker; recheck current PRs/claims before starting. No backend/shared-style/dependency paths reserved. Agent-OS-Receipt: {RECEIPT} |\n"
)
start = claims.index(marker, claims.index("## Open claims")) + len(marker)
(ROOT / "docs/WORK_CLAIMS.md").write_text(claims[:start] + queued + claims[start:], encoding="utf-8")
print("Bounded governance application prepared; validation and cleanup run next. No production UI changed.")
