# PSI PR A — browser verification performed at Integration, 2026-08-20

**Status: PR A is NOT mergeable yet.** One blocker, measured in a browser, stated in §4.
Everything else on the owner's PR A checklist that can be answered without production
is answered here and is clean.

Raised as issue **#986** so Claude 13 can fix it before opening the PR, rather than
after — the same edit either way, one merge cycle cheaper.

## 1. Why Integration ran this

The owner's PSI brief makes visual evidence a real gate and explicitly refuses
*"unit tests green, browser could not launch"* as completion, adding: *"if Claude 13's
environment cannot perform browser verification: perform the missing browser
verification at Integration or another approved environment."*

Claude 13's branch `claude/psi-reference-routes` existed at `11c69e7d0` with no PR
open. Its three inspectable gates (data truth, presentation-only, functional parity)
were already clean on the diff. The remaining gate needed a browser, so Integration
produced it.

## 2. Rig — stated so the numbers can be reproduced or disputed

| | |
|---|---|
| branch / head | `claude/psi-reference-routes` @ `11c69e7d0db1096e211e9a1a5d6631a15cf84b34` |
| backend | real `server.py` on `:8000`, contract seeded by `tests/e2e/preflight.py` from committed `exports/latest/` — 1,076 players, board scraped 14 min before capture |
| frontend | Next **production** build (`build:nocheck` + `start`) on `:3000`, `BACKEND_API_URL=http://127.0.0.1:8000` |
| auth | real session via `POST /api/test/create-session` (`E2E_TEST_MODE=1`) |
| browser | Chromium 1194 (`/opt/pw-browsers`), viewports `1366×768` and `390×844` (`isMobile`, `hasTouch`, DPR 2) |

A **production** build was used deliberately. A first pass on `next dev` never fired a
single `/api/*` request — the page rendered its skeleton forever — because the dev HMR
socket could not connect in this sandbox and the dev client kept reloading. That is a
rig artifact, and reporting a skeleton as "the board does not load" would have been a
fabricated regression. The production build is also what `playwright.config.js` boots,
so this matches the harness rather than inventing a second configuration.

Captures: `docs/psi/evidence/PR_A_2026-08-20/`.

## 3. What is right

**Data truth — clean.** Every number traces to the contract; nothing on the page is
invented. Rendered rows read `Josh Allen · BUF · 30 · QB1 · 1.5 · 9,991 · S+ · 14/15 ·
High · HOLD · Consensus asset`, `Brock Bowers · LV · 23 · TE1 · 9,970`,
`Bijan Robinson · ATL · 24 · RB1 · 9,703`. Summary tiles: 983 players / 265 high conf /
325 medium / 393 low / 882 multi-source / 36 quarantined. `UPDATED 14M AGO` resolves
from `dataFreshness.generatedAt || date` and the component returns `null` — renders
nothing — when the stamp is absent, so a missing timestamp cannot read as "just now".
No fabricated league sample size, value, rank, positional rank, confidence, movement,
age, quote, chart history, team, trade count or source statistic.

**Presentation only — clean.** No value, rank or ordering is computed in the page. The
diff is a global-class → CSS-module swap, the additive token layer, hero copy, and
`psi-editorial` scoping.

**Functional parity — clean at this level.** 32 desktop / 33 mobile rendered rows, tier
grouping and tier separator rows, position ranks, source counts (14/15, 13/15),
confidence, edge, signal, `Consensus asset` flags; full desktop nav (Rankings, News,
Trades, My Team, Market, League, league selector, team picker, search, System) and the
mobile top chrome plus bottom tab bar (Home, Ranks, Trade, News, Menu); search,
position filter, confidence filter, Tiers, Screens, Copy, Export CSV, Sources, Columns.
`200 of 983 shown · grouped by tier` is present, so Show All virtualization is reachable.

**Console — no page errors, no application errors.** The only console output is three
`404`s, for `/api/health` and `/api/user/state`. Those are this rig, not this branch:
neither path has a Next bridge route (`frontend/app/api/` contains no `health/` or
`user/`), so nginx serves them in production and Next answers them locally. The diff
touches no route file, so it reproduces on `main`.

## 4. The blocker — the light surface inherited the dark shell's badge colours

`tokens.css` is **additive by contract** and `tokens-contract.test.js` pins that it
never redefines a legacy `globals.css` token. That rule is right, and it is precisely
why this slipped: the *page* moved to a cream editorial surface while the legacy badge
and label colours — authored for the near-black terminal shell, and hardcoded hexes
rather than tokens — stayed exactly where they were. Nothing in the new layer was
allowed to re-map them.

Contrast measured in the browser: alpha-composited through the real ancestor background
stack, WCAG 2.x relative luminance, identical on both viewports.

| ratio | need | class | colour | example |
|---|---|---|---|---|
| **1.04 – 1.15** | 4.5 | `badge badge-amber` | `#c9a9ff` | `Med` confidence |
| 1.11 – 1.35 | 4.5 | `board_posRank` | `#ffc704` | `1` (QB1 / RB1 / WR1) |
| 1.14 – 1.38 | 4.5 | `edge-label edge-hold` | `#ffc704` | `HOLD` |
| 1.18 – 1.45 | 4.5 | `rankings-value-band vb-elite` | `#ffc704` | `S+` |
| 1.39 – 1.68 | 4.5 | `edge-label edge-buy` | `#5fcf9b` | `BUY` |
| 1.40 – 1.70 | 4.5 | `badge badge-green` | `#5fcf9b` | `High` confidence |
| 1.40 – 1.70 | 4.5 | `action-label action-consensus` | `#5fcf9b` | `Consensus asset` |
| 1.46 – 1.79 | 4.5 | `rankings-value-band vb-bluechip` | `#5fcf9b` | `S` |
| 1.65 – 2.02 | 4.5 | `rankings-tier-badge tier-1/2` | `#a8b0be` | `Tier 1` |
| 2.78 | 4.5 | `edge-label edge-none` | `#8b93a5` | `—` |
| 4.44 | 4.5 | `board_playerMeta` | `#6e6353` | `LV · 23` |

`#c9a9ff` on the old `#131519` was roughly 9:1 and perfectly legible. The colour is not
wrong; the surface changed underneath it. At 1.04:1 it is not "low contrast", it is
invisible — in `desktop-1366-board.png` the `Med` pill on rows 2, 8 and 18 renders as an
empty lavender lozenge.

This is a blocker rather than polish because of *which* vocabulary it hides. Confidence,
value band, edge signal and tier are how this board says how much to trust a number.
A migration that renders `Med` unreadable while `High` stays visible does not lose
decoration — it silently promotes every medium-confidence row to looking unlabelled.
`board_playerMeta` at 4.44 is a rounding-distance miss and belongs in the same pass.

## 5. What is deliberately NOT charged to PR A

- **Sticky column headers hide behind the top bar.** `th { position: sticky; top: 0 }`
  is untouched legacy in `globals.css`, and `shell.css`'s only change in this branch is
  the `CU` monogram block — the 53px fixed `.shell-topbar` predates it. Real, worth its
  own row, not a merge condition here.
- **Mobile hero button wrapping** (`Methodology charts / Copy / Export CSV`, then
  `Sources / Columns (off)`) is ragged but legible. Judgement, not a gate.
- **axe was not run.** These are direct computed-style measurements corroborated by the
  captures, not an axe report, and they are described as such.

## 6. What still cannot be answered here

Deployed behaviour. This rig proves the branch renders correctly against a real backend
and a real board; it says nothing about production. The post-deploy checklist stays
open, and no production claim is made from these captures.
