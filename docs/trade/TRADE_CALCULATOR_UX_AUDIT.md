# Trade Calculator: current-page UX audit (TC-0)

**Batch.** TC-0, "Establish the truth" (`docs/trade/TRADE_CALCULATOR_COMPLETION_WORKSTREAM.md`). Read-only: no code was
changed.
**Companion records.**

- `docs/trade/TRADE_DECISION_ENGINE_AUDIT.md`: the verdict inventory V1–V12. This audit reuses its V-numbers.
- `docs/trade/TRADE_CALCULATOR_FEATURE_MATRIX.md`.

**Design authority.**

- `docs/ui/CALCULATOR_UI_IMPLEMENTATION_CONTRACT.md` (PSI Direction A).
- `docs/ui/UI_PARALLEL_LEDGER.md`: the `/trade` row.
- `docs/DESIGN-SYSTEM.md`.

**Evidence.** 24 screenshots in `docs/trade/ux-audit-2026-10-17/`, referenced as `[NN]` below.

> **Rule followed.** Every rendering claim below was captured in a real browser against the real local stack. Claims
> taken from code alone are marked **(code-read)**. Numbers are the live board's values on 2026-10-17. They are evidence
> of behaviour, not acceptance values.

---

## 1. Method and environment

| Item | Value |
|---|---|
| Code under audit | branch `claude/trade-calculator-completion`. `frontend/`, `src/` and `server.py` are byte-identical to `origin/main` `0b3194f190` plus docs-only commits (`695fc26c37`, then `acd02e958a`, then `db7b928277`; none touch code) |
| Backend | `python -m uvicorn server:app --port 8010`, with the env the E2E config uses (`ALLOW_DEFAULT_LOGIN_DEV=1`, `E2E_TEST_MODE=1`, `E2E_TEST_SECRET`, `E2E_TEST_USERNAME=e2e-test-user`, `RATE_LIMIT_BYPASS_IPS`, and an empty `PLAYWRIGHT_BROWSERS_PATH` so no scrape runs). Committed board, `contractVersion 2026-03-10.v2`, board date 2026-10-17. At startup the backend fetched live Sleeper rosters; the two tracked files that wrote were restored afterwards |
| Frontend | `next build --webpack` (the same as `build:nocheck`) then `next start -p 3011`, with `BACKEND_API_URL=http://127.0.0.1:8010` |
| Routing | A 15-line Node proxy on `:3010` stands in for nginx: `/api/*` goes to the backend, everything else to Next. This is the production topology (`deploy/nginx/chaseupside-proxy.conf`), so no Next bridge-route gaps distort the request audit |
| Session | `POST /api/test/create-session` (the E2E fixture path) |
| Browser | Playwright 1.63, Chromium `/opt/pw-browsers/chromium-1243`, service workers blocked. Desktop at DPR 1. Mobile with `isMobile` + `hasTouch`, DPR 2 (screenshots downscaled to 1x) |
| Viewports | 1366×900, 1920×1080, 390×844, 360×780 |
| Team | `Jason` (`dynasty_main`), selected through the page's own `#suggest-team` control. **No team is auto-selected for the test user** (§3, P1-1) |
| Measurement | per step: `document.scrollHeight`; `scrollWidth` vs `clientWidth`; the y-offset and height of every heading/panel; interactive elements under 44 px; every `/api/*` request (`page.on('request')`); resource-timing JS bytes; axe-core 4.13 (`wcag2a/aa`, `wcag21a/aa`) over `main` |
| Local-only limitations | 1. BDVM answers `no_projection_snapshot` (no `data/bdvm/projections/` on this box), so the BDVM panel is absent. 2. Recent real trades and the War Room comparable-trades row say the trade ledger is unavailable. 3. No projection snapshot, so the War Room roster lens is unavailable everywhere. 4. Timings are warm loopback timings, not production network timings. Production rendering was **not** verified (`docs/trade/V1_45_*` records the production L4 method) |
| Package model in effect | KTC (`ktc_2026_04`, labelled INCUMBENT in the `/api/trade/simulate-mc` response). #1771 (`geom_q078_v1`) is not on this HEAD, which is why the UI copy says "KTC Value Adjustment" |

**Journeys captured.** At every viewport unless noted:

- **J1:** empty.
- **J2:** 1-for-1, Pickens ↔ Kyren Williams.
- **J3:** 1-for-2, Jefferson ↔ Love + DJ Moore.
- **J4:** elite for four, Bowers ↔ K. Williams + B. Hall + D. Smith + M. Golden.
- **J5:** offense for IDP, Egbuka ↔ Fred Warner + Jihaad Campbell.
- **J6:** picks only:
  - slot `2027 Pick 1.05`;
  - tier `2028 Mid 1st`;
  - generic `2029 Round 1`;
  - tier `2028 Early 2nd`.
- **J7:** three teams, Pickens / K. Williams / Nico Collins.

At 1366 and 390, the J4-shaped state (plus Ladd McConkey) was then used to exercise:

- War Room details, Second opinions, Recent real trades;
- Monte Carlo, Simulate impact, the suggestions desk;
- KTC-URL import and screenshot import;
- value override, Raw mode, the My league toggle and Swap Sides;
- forced analyze failure, keyboard tab order and axe.

---

## 2. Section inventory in render order

`page.jsx:1893-2481` is the render tree. Offsets are the top of each section in document coordinates, for J2 (1-for-1,
team selected) unless noted.

### 2.1 Desktop, 1366×900 (`[02]`, `[03]`, `[04]`, `[05]`)

| # | Section (owner) | Purpose | J2 y / height | Conditional on | Notes |
|---|---|---|---|---|---|
| 0 | App header (`AppShell`) with **nav team switcher "Pick your team ▾" / "Jason ▾"** | global nav, league + team | sticky, 53 px | always | The team control the War Room needs is here, but the page never points to it |
| 1 | PageHeader "Trade Calculator", **Market / My league** segmented control | identity, value basis | 93 | always | "My league" is a withdrawn lens; §3 P1-5 |
| 2 | Proactive suggestions rail "Recommended right now" (`trade-sections.jsx:258`) | the top idea per suggestion category | 200 / **213** | team selected and suggestions > 0 | sits **above the builder**; one card in a 1,280-wide panel `[02]` |
| 3 | Controls toolbar (`page.jsx:2009`) | value mode, swap, clear, reset, add team, import, share, KTC URL, CSV, JSON, **Simulate impact** | 429 / 110 | always | 12 controls; Simulate impact wraps to a second row |
| 4 | Share / import status banners | feedback | (none) | after an action | |
| 5 | **Simulation panel "Impact on Jason"** (`trade-simulation-panel.jsx`) | before/after roster, positions, roster fit, capacity, lineup, NFL exposure | inserted at 555; **1,235 + 100** tall | after Simulate impact | **pushes the builder down about 1,250 px** `[10]` |
| 6 | KTC import panel / screenshot dialog | import | inline panel / modal | menu action | the KTC panel appears in this slot, below any simulation panel `[11]` `[12]` |
| 7 | Draft-capital stacks (`PickTeamSelectors`) | team per side for the stack note | 555 / 194 (J6) | picks in the trade | J6 auto-inferred **Side A = "Ty"** while the War Room analysed Side A as Jason `[04]` |
| 8 | Side cards A/B (`SideCard`): totals (`Raw · + VA`), search, asset rows, quantity −/+, value override, balancer list | **the builder** | 555; A 180, B 370 | always | the balancer adds up to 5 rows (≈190 px) inside the card |
| 9 | **Trade War Room** (`TradeWarRoom.jsx`): recommendation, Market / Roster / Feasibility, Why / Against / Uncertain, "How this was decided" | the decision (V1) | **1,019** / 497 (990 with details open) | **2 sides only** | below the fold at 900 px |
| 10 | "How the verdict works" help link | help | ≈1,540 | always | |
| 11 | **TradeMeter** (V2/V3), with **Monte Carlo** (V5) inside it | package comparison | **1,574** / 169 (362 with MC open) | always | the "immediate result" sits two screens below the builder |
| 12 | Draft-capital stack note | experimental context | (none) | picks with teams set | |
| 13 | Fairness explanation (V4) | plain-English reading of the meter | ≈1,750 / ≈50 | assets present | 💡 emoji |
| 14 | **Second opinions** (collapsed): per-source table (V6), ROS fit, BDVM panel (V10), delta chart, multi-team flow (3+ sides) | alternative currencies | 1,863; **1,550 when open** | always | `[08]` |
| 15 | Recent real trades (collapsed) | comparable trades | 1,929; 235 when open | always | ledger unavailable locally |
| 16 | **Trade suggestions desk** (`trade-suggestions-desk.jsx`): team select `#suggest-team`, roster textarea, Get suggestions, tabs (V8) | trade ideas, **and the only on-page team picker** | 1,995 / 431 | always | the War Room tells the user to "Pick your team" from 1,000 px above this |
| 17 | Sticky verdict tray (V9) | persistent totals + verdict | fixed, bottom 78 px | 2 sides only | shows "FAIR" on an empty trade `[01]` |
| 18 | Global Screenshot FAB "SAVE" (`ScreenshotFab.jsx`) | page image | fixed, bottom-right | always | overlaps the meter's "Side B" label and trade rows `[01]` `[06]` |

**Document height.**

| Journey | Height (px) |
|---|---|
| J1 | 1,313 |
| J2 | 2,446 |
| J3 | 2,523 |
| J4 | 2,500 |
| J5 | 2,483 |
| J6 | 2,766 |
| J7 | 1,920 |
| J4 + McConkey, every panel open and simulation run | **6,024** |

**1920×1080 (`[06]`).** The layout is identical to 1366: the content column is capped at 1,280 px and every y-offset
matches 1366. The 320 px gutters on each side render as near-black bars outside the cream shell. At 1080 px the War Room
starts at y=1,019, so **no decision content is visible above the fold** except the tray.

### 2.2 Mobile, 390×844 and 360×780 (`[16]`, `[17]`, `[18]`, `[20]`, `[21]`)

| # | Section | 390: J2 y / height | 360: J2 y / height | Notes |
|---|---|---|---|---|
| 0 | Mobile top bar (league pill, team pill, search) | sticky 46 | sticky 46 | |
| 1 | PageHeader + Market/My league | 72 | 72 | |
| 2 | **MobileQuickAddBar** ("A ⇄ Quick add to Side A…") | ≈230, then **sticky at 44, 62 px** | same | a third search box beside the two side searches `[16]` |
| 3 | Suggestions rail | 313 / 212 (**484** before the first edit) | 313 / 212 | |
| 4 | Controls toolbar | 541 / **233** (12 controls over 5–6 rows) | 541 / 233 | `[16]` |
| 5 | Side A / Side B cards | 790 / 195; 1,001 / 385 | 790 / 195; 1,001 / 385 | the **builder starts at y=790**, below the fold on 360×780 |
| 6 | Trade War Room | **1,480** / 872 | 1,480 / 872 | |
| 7 | TradeMeter + Monte Carlo | **2,410** / 194 | 2,410 / 194 | about three screens down |
| 8 | Second opinions / Recent real trades | 2,794 / 2,860 | 2,812 / 2,878 | |
| 9 | Suggestions desk | 2,926 / 556 | 2,944 / 572 | |
| 10 | Sticky tray + tab bar | fixed 74 + 53 | fixed 74 + 53 | |

**Mobile document height.**

| Journey | 390 (px) | 360 (px) |
|---|---|---|
| J1 | 1,854 | 1,854 |
| J2 | 3,548 | 3,582 |
| J4 | 3,808 | 3,907 |
| J6 | 4,032 | 4,135 |
| J7 | 3,096 | 3,146 |
| Every panel open, simulation run | **8,861** (≈10.5 screens) | not captured |

**Fixed chrome on mobile.** Top bar 46 + quick-add bar 62 + tray 74 + tab bar 53 = **235 px**. That is **30% of a
360×780 viewport** and 28% of 390×844 (measured on computed `position: fixed | sticky`).

---

## 3. Issues by severity

Evidence references are screenshots `[NN]`, file:line, or the captured request or measurement.

### P0: correctness and trust

**P0-1. The meter and the Monte Carlo panel disagree about the same trade, in the same widget.** `[09]`

- State: A = Bowers + McConkey, B = K. Williams + B. Hall + D. Smith + M. Golden. No overrides; value mode "Our Value".
- The meter reads **20,497 vs 20,508, Gap 11, FAIR / Even**.
- The Monte Carlo panel inside the meter reads **"Side B's package is clearly worth more… bigger in 98% of 40,000
  simulations… beat Side A's by 3,957 points."**
- The captured `/api/trade/simulate-mc` response explains the gap:
  - `vaAdjustment: {value: 5806, effectiveValue: 1879}`;
  - `adjustedDelta: -3938`;
  - `packageModel: ktc_2026_04`.
- So MC applies a Value Adjustment of 1,879 where the meter applies 5,806, under the same model and the same inputs. This
  is a different defect from the override/Raw-mode basis gap the engine audit records for V5. TC-A's cross-surface
  parity test must cover `src/trade/monte_carlo.py::_apply_consolidation_adjustment`.
- Smaller point: the request sends `nSims: 20000` and the copy says "40,000 simulations" (the response echoes 40,000).

**P0-2. Stale results stay on screen after the trade changes.** `[24]`

- Before the edit, Pickens ↔ K. Williams, both MC and Simulate impact run:
  - meter: **SLIGHT EDGE, Side A 6% more**;
  - MC: "Side A's package is probably worth more (64%)";
  - simulation: "CHANGE −353".
- After adding Breece Hall to B:
  - the meter reads **LOPSIDED, Side B 46% more**;
  - MC **still says Side A is probably worth more**;
  - the simulation **still says −353**.
- Neither carries a stale marker. In code, `MonteCarloButton` and `useTradeSimulator` reset only on a manual "Clear"
  (`page.jsx:288`, `:2125`) **(code-read)**.

**P0-3. Six or more simultaneous verdicts for one trade, and they contradict.** The same J4 + McConkey state shows:

- War Room **LEAN PASS, low confidence**;
- meter **FAIR / Even**;
- tray **FAIR, "Gap −11"** (the meter says "Gap: 11");
- fairness explanation "within 3%";
- Second Opinions tally **"Side A 3 · Side B 10"**;
- delta chart "Balanced (Δ 11)";
- MC "Side B clearly worth more (98%)";
- Simulate impact **"ROSTER FIT lean decline"**, plus "CHANGE +5,817" on raw totals.

In J4 (Bowers alone), the War Room says **LEAN MAKE** while the meter badge is a red **LOPSIDED** pill and the tray
says "LOPSIDED (23%)" in red `[03]`. Package-direction colour reads as "bad" on a trade the decision says to make. The
full map is in §4.

**P0-4. "Raw" value mode is not the "Raw" shown on the side cards, and it is not canonical.**

- The Value mode select offers "Our Value" / "Raw" (`trade-logic.js:26-29`).
- "Raw" resolves to `values.raw`, which is `_rawComposite`, the legacy scraper composite (`dynasty-data.js:163-175`).
- Captured with Raw mode on J2: totals **5,914 vs 5,808**, while the side card meta reads "Raw 6,052" / "Raw 5,699"
  (canonical, pre-VA).
- So the meter and tray then grade a non-canonical number, while the War Room ignores the mode.
- This breaks the CLAUDE.md rule "Never publish a VA-adjusted number under a raw-value field name, or vice versa" in
  spirit: the same word names two different quantities on one screen.

**P0-5. The War Room analyses "you" with no roster evidence, and side identity disagrees across three places.** `[04]`
In J6 (picks only, team Jason):

- No side card carries the "You · Jason" badge: `mySideIdx` is −1 (`page.jsx:903-920`).
- The War Room analyses **"For Jason… PASS"** with Side A as Jason. `tradeRequestForTeam` breaks a 0–0 tie to side 0
  (`trade-war-room.js:54`).
- The Draft-capital stacks control auto-selected **Side A = "Ty"**.
- The War Room's own uncertainty list admits "Counted as sent, but not taken off this roster because no specific owned
  pick was chosen".

**P0-6. An empty trade renders a verdict.** `[01]` `[16]` With no assets:

- the meter shows **FAIR / Even** on a full green/red bar;
- the sticky tray shows **FAIR, Gap 0**.

"Nothing to evaluate" is presented as an evaluation. MISSING IS NEVER ZERO applies to the verdict, not only to values.

**P0-7. Value overrides change the meter but not the War Room, with nothing on screen to say so.**

- Overriding Bowers to 9,500 (J4) moves the side total to 14,547 and the meter to **LOPSIDED 29%** `[13]`.
- The War Room still reads **"+4,726 … you give 9,981"** and LEAN MAKE.
- The only explanation is inside the collapsed "How this was decided" ("value overrides … are not applied here").
- The overridden row shows the edited number in a borderless dashed input plus a "Reset" link. There is no "edited"
  marker on the total, which still reads as canonical.

### P1: comprehension

- **P1-1. The team picker is undiscoverable.**
  - The War Room says "Pick your team to see what this trade does to your roster", but has no control.
  - The two pickers are the nav pill and `#suggest-team` at the bottom of the suggestions desk (y=981 empty, 1,995 in
    J2).
  - For the test user nothing auto-selected, so the War Room, the "You" badge, Simulate impact and the rail stayed off
    until a team was chosen at the bottom of the page.
- **P1-2. The answer sits below the question.**
  - At 1366×900 the War Room starts at 1,019 and the meter at 1,574.
  - At 390×844 they start at 1,480 and 2,410.
  - At 1920×1080 nothing of the decision is above the fold `[06]`.
  - Above them sit the rail (213 px), the 12-button toolbar and, once run, the 1,235 px simulation panel `[10]`.
- **P1-3. Absolute verdict bands mislabel large trades.**
  - `meterVerdict` uses 350 / 900 / 1,800 absolute points (`trade-logic.js:1783`).
  - With a 70,000 vs 68,100 pair (built with overrides), the badge reads **LOPSIDED** next to **"3% more"** `[15]`.
  - J2's 6% gap reads SLIGHT EDGE.
  - So a smaller relative gap gets the harsher label.
- **P1-4. Three different "gaps" for one 3-team trade.** J7 `[05]`:
  - the meter shows C at **−709** with "Worst gap: **+709**" (positive sign for a loss);
  - the balancer label says **"SIDE C LOSES 1,065"** (`page.jsx:1878`, `multiBalancers.gap`).
- **P1-5. "My league" is a dead control.**
  - Clicking it selected the segment, fired **zero requests** and showed no banner. The lens is withdrawn server-side
    (CLAUDE.md, "`valuation_mode`: accepted, ignored").
  - So a control promising league adjustment does nothing visible.
- **P1-6. Vendor and internal terms leak into the decision copy.**
  - "after **KTC** Value Adjustment" and "Net **KTC** equity +5817" (raw canonical sum).
  - "BIGGEST UNCERTAINTY Roster impact not available (**projection_basis_no_projection_snapshot**)", an internal code.
  - "No league-scored projection snapshot yet" printed **twice** in the Roster lens `[02]`.
  - Source abbreviations "DS", "FC", "PFK", "DD", "FN", "OTC", "DN SF-TEP" in the explanation and table.
- **P1-7. Asset rows are hard to read.**
  - The asset's value appears only as the **placeholder of an editable number input** (dashed underline, no thousands
    separator: "6052" beside "6,052" totals).
  - "Consensus 37.5" is a decimal *rank* labelled like a value.
  - Picks show "#9.0" ranks and an unexplained "21"/"22" round glyph.
  - A generic pick shows "**0 src**" next to a price (4,102) `[04]`.
- **P1-8. Pick search behaves inconsistently.**
  - "2027 1st" and "2027 Mid" return **"No matches."**
  - "2027" returns slot rows ("2027 Pick 1.01"); "2029 1st" returns tiers; "Round 1" returns generics for 2028–2030 only.
  - The current-year tier rows are suppressed aliases by design, but there is no hint of how to find a 2027 first.
  - Owned picks are searchable only after a side's team is set, and that control appears only once a pick is already in
    the trade (`page.jsx:1070-1072`).
- **P1-9. Duplicate-looking balancer rows.** "2027 1st (PICK) · 4,774 → 78" ×3 (J4) and "2028 4th (PICK) · 1,674 → 533"
  ×4 (J7) show no origin or owner, so they cannot be told apart `[03]` `[05]`.
- **P1-10. Two "simulate" buttons mean different things.**
  - "Simulate impact" (toolbar, roster before/after, V7) vs "Simulate (Monte Carlo)" (inside the meter, value
    uncertainty, V5).
  - The first only exists for 2 sides with a team selected; the second renders as an unstyled browser button `[02]`.
- **P1-11. 3+ team trades lose the decision layer.**
  - With 3 sides, the War Room, Simulate impact, Monte Carlo and the sticky tray all disappear (`page.jsx:2276` War Room,
    `:2095` Simulate impact, `:2432` tray; MC renders only inside the 2-team meter).
  - At 1366 the side columns truncate player names to "George…" and "Nico C…" `[05]`, against contract §6 ("do not clip
    player names into ambiguity").
- **P1-12. Second Opinions promises what it does not show.**
  - The subtitle says "…fundamentals and the value split", but the BDVM panel silently vanished (`no_projection_snapshot`
    locally).
  - The delta chart duplicates the meter's two totals as two blue bars, with labels colliding ("20,497Balanced
    (Δ 11)20,508") `[08]`.
- **P1-13. The analyze error state never retries.** After a forced 500, the War Room says "Analysis unavailable right
  now (boom)". It **kept that error after the backend recovered** and value-mode changes, until the trade itself changed
  (the request key excludes them). There is no retry control `[14]`.
- **P1-14. The suggestions rail and desk duplicate each other.** The top rail (V8 input) and the bottom desk show the
  same `/api/trade/suggestions` payload in two places. The desk also holds a 58-line roster textarea.

### P2: polish and design-contract deviations

- **P2-1. The meter is legacy styling** (`globals.css:2964-3140`):
  - raw `rgba()` colours and 9 px / 999 px radii;
  - **green/red fills** for the two package shares, and green/amber/orange/red pill badges.
  - The multi-team meter (`TradeMeter.jsx:150-245`) uses inline `rgba(153,166,200,0.08)`, `borderRadius: 6/4` and
    `var(--green)` / `var(--red)`.
  - Contract §4: no raw colours, radius-1/2/3 only, and movement is not success/failure.
- **P2-2. Emoji as UI.** The 💡 in the fairness explanation is an anti-goal (§3).
- **P2-3. Off-scale breakpoints** in `trade.module.css`: `max-width: 420px`, `360px`, `width < 640px` (§4 allows only
  480 / 768 / 1024 / 1320).
- **P2-4. Shadows and rounding on non-overlays.** The mobile quick-add bar has a drop shadow and a large radius `[16]`.
  The delta chart uses non-PSI cyan/teal bars `[08]`.
- **P2-5. One tile per number.** The simulation panel shows BEFORE / AFTER / CHANGE and QB / RB / WR / TE as eight
  bordered tiles `[10]`.
- **P2-6. The global FAB overlaps content.** The "SAVE" camera button covers the meter's Side B label `[01]`, Side A's
  search on mobile `[16]` and suggestion chips `[21]`.
- **P2-7. Near-black page gutters.** At 1920 the gutters are black bars outside the cream shell `[06]`. A thin black
  strip shows at the left edge on 360 px `[21]`.
- **P2-8. Toolbar overload.** 12 equal-weight controls, including CSV / JSON / Copy KTC URL, as primary toolbar buttons.
  On mobile they take 233 px before the builder.
- **P2-9. Axe.**
  - Desktop, populated: **0 violations** in `main`.
  - Mobile 390, populated: **1 serious** `color-contrast` violation, the rail's accent badge at 4.48:1 (`#a3341c` on
    `#e2ceb9`, 11 px).
  - The keyboard order follows the DOM. Because the simulation panel and rail precede the builder, a keyboard user tabs
    through `Clear simulation` and `Show 23 teams that moved` before reaching the Side A search.

---

## 4. Competing verdicts and duplicated information

V-numbers follow `TRADE_DECISION_ENGINE_AUDIT.md` §3.1. All rows were observed on `/trade`.

| Output | Location | Basis observed | J4 + McConkey reading | Duplicates or contradicts |
|---|---|---|---|---|
| V1 War Room recommendation + confidence | War Room | canonical + VA, roster, capacity; ignores overrides and Raw mode | **LEAN PASS, low** | contradicts V5 and V7; reads differently from V2's colour |
| War Room Market lens "+N after KTC VA, Favors / Neutral / Against" | War Room | VA gap | +11, Neutral | duplicates V2's gap |
| V2 meter badge | TradeMeter | absolute bands on overridden totals | FAIR | contradicts V6, V5 and V7 |
| V3 meter winner text "worth N% more" | TradeMeter | relative 3% | "Even" | can sit beside LOPSIDED `[15]` |
| V9 tray verdict + gap | sticky tray | same as V2, opposite sign convention | FAIR, "Gap −11" | duplicates V2 with a flipped sign |
| V4 fairness explanation | below the meter | adjusted totals + per-source raw gaps | "within 3%… DS values B 7,450 higher" | duplicates V2/V3; introduces a third quantity (per-source raw) |
| V6 Second Opinions tally | Second opinions | per-source totals with that source's VA | **A 3 · B 10** | contradicts V2 |
| Delta histogram | Second opinions | adjusted totals | "Balanced (Δ 11)" | a pure duplicate of V2 |
| V5 Monte Carlo headline | inside the meter | effective VA 1,879 vs 5,806 (P0-1); stale after edits (P0-2) | **B clearly, 98%** | contradicts V2 |
| V7 Simulate impact "ROSTER FIT lean decline" + CHANGE | simulation panel | raw equity + fit composite | lean decline; +5,817 | contradicts V1's numbers (+11 VA vs +5,817 raw) |
| Team Strength delta | War Room details **and** simulation panel | canonical sums | J4: −1,345 (War Room); J4 + McConkey: −1,022 (simulation) | the same concept twice in two panels |
| Roster capacity / forced drops | War Room Feasibility **and** simulation "Roster capacity" | `roster_capacity` | "2 cuts: Belton, Mukuba" in both | duplicated |
| Per-asset BUY / SELL n% badges | asset rows | edge signal | "BUY 6%", "SELL 18%" | a fourth market opinion with no link to the verdict |
| V8 suggestions fairness | rail + desk | VA gap | (not compared) | the rail and desk duplicate each other |
| Package totals | side card header, meter, tray, delta chart, War Room text | adjusted totals | 20,497 / 20,508 shown **5 times** | |

**Count.** In one state, **eight** independent final-sounding readings (V1, V2/V3, V9, V4, V6, delta chart, V5, V7). The
adjusted package totals are printed five times.

---

## 5. Mobile-specific failures

1. **Horizontal overflow with Second opinions open.**
   - At 390, `scrollWidth` reached **422** against `clientWidth` 390 (the full-page capture is 422 px wide `[23]`).
   - The cause is the per-source `table.ds-table--compact`.
   - The table also **clips its value columns**: only "raw 9,999 ·" shows; adjusted totals, leader and margin sit
     off-screen with no scroll affordance `[19]`.
   - In every *collapsed* journey, at both 390 and 360, `scrollWidth == clientWidth` (no overflow).
2. **30% fixed chrome** at 360×780 (235 px), and the sticky quick-add bar overlaps scrolled content `[20]` `[21]`.
3. **The builder starts at y=790** (below the fold at 360×780). Above it: page header, quick-add, the 212–484 px rail and
   the 233 px toolbar `[16]`. The quick-add bar is the only above-the-fold entry point.
4. **Three search boxes** (quick-add plus one per side) for one action.
5. **The decision is about three screens down** (War Room at 1,480, meter at 2,410). The tray shows only totals and the
   V9 band.
6. **Touch targets under 44 px** (390, J4: 43 elements):
   - Second opinions and Recent real trades disclosures are 16 px tall.
   - Player-name buttons are 17 px.
   - Value overrides are 52×22.
   - Market / My league and Team context / Asset only are 24 px.
   - The VA help icon is 24×24.
   - Balancer rows and suggestion tabs are 26 px.
   - Toolbar buttons and Get suggestions are 33 px; the Value mode select and team select are 35 px.
   - The quick-add side toggle is 56×40.
   - At 360 in 3-team mode, the destination selects are 93×35 and one player name is 34 px wide.
   - The −/+ quantity buttons do meet 44 px on mobile.
7. **Name and meta truncation.** "Consensus 7.6…" is cut, and the position label is replaced by the confidence badge on
   some rows (Kyren Williams `[17]`).
8. **The simulation panel on mobile is 1,972 px** and inserts above the builder. With every panel open the page is
   8,861 px.
9. **The screenshot import dialog is a full-height right drawer** with the primary action wrapped under the secondary
   ones `[22]`. It works, but the hierarchy is inverted.

---

## 6. Measured performance and request audit

| Metric | 1366 | 1920 | 390 | 360 |
|---|---|---|---|---|
| DOMContentLoaded | 233–345 ms | 145 ms | 120 ms | 193 ms |
| First builder input visible (from navigation) | 1.08–1.51 s | 0.87 s | 0.69 s | 1.03 s |
| "Loading player pool" gone | 1.12–1.57 s | 1.00 s | 0.75 s | 1.11 s |
| JS at builder-ready (resource timing) | 22 scripts, **253 KB transferred** / 779 KB decoded | 27 / 273 KB | 31 / 307 KB | 28 / 276 KB |
| JS after 5 s idle | 36 scripts, **348 KB** / 1,039 KB decoded | (not captured) | (not captured) | (not captured) |
| Total requests in the first ≈6 s | 88 (36 script, 23 fetch, 10 css, 2 font) | (not captured) | 73 | (not captured) |

- The extra idle JS is Next `<Link>` prefetch of `/`, `/rankings`, `/news`, `/rosters`, `/edge`, `/league` and `/dfs`:
  16 RSC fetches plus their page chunks.
- Build budget (`frontend/scripts/check-bundle-sizes.mjs`): **`/trade/page` 85.7 KB of a 93 KB budget** (7.3 KB
  headroom).
- CLS on reload with a team selected (rail placeholder path): **0.041**.

**Search latency.** Local filtering, 27–90 ms from keystroke to the first result. The only network traffic is player
thumbnails (16 images per query).

**API calls on load** (team not yet selected):

- `GET /api/dynasty-data?view=compact`;
- `GET /api/health` (503, degraded offline: expected);
- `GET /api/auth/status`, `GET /api/user/state`, `GET /api/leagues`;
- **`GET /api/draft-capital` twice**, without and then with `?leagueKey=dynasty_main`, on a trade with no picks.

**Selecting a team** fires `POST /api/trade/suggestions` automatically (the rail).

**Per edit:**

| Action | Requests |
|---|---|
| Add the first asset (one side only) | none |
| Each edit once both sides are non-empty, ≥0.7 s apart | 1 × `POST /api/trade/analyze` (700 ms debounce, `TradeWarRoom.jsx:53`; edits <0.7 s apart coalesce to one) |
| Type a 4-digit value override | none (the War Room ignores overrides: P0-7) |
| Open Second opinions | `GET /api/second-opinion/signals`, `GET /api/public/league/rosTradeDeadline`, `GET /api/ros/player-values?limit=2000`, `POST /api/bdvm/trade-eval` |
| Each edit with Second opinions open | `POST /api/bdvm/trade-eval` **+** `POST /api/trade/analyze` |
| Open Recent real trades | `GET /api/market/trades/reference?…` |
| Monte Carlo / Simulate impact | `POST /api/trade/simulate-mc` / `POST /api/trade/simulate`, user-initiated only; **never re-run on edit, and never invalidated** (P0-2) |
| Get suggestions | `POST /api/trade/suggestions` |

**Do expensive calls fire on every edit?**

- Analyze does, debounced and abort-guarded (`controllerRef`).
- BDVM trade-eval does while Second opinions is open.
- Simulate and MC do not. The defect is the opposite one: their results go stale silently.

---

## 7. Proposed information architecture: hypothesis for TC-D

This is input to TC-D, not a design decision. It keeps every capability (contract §6: mobile is the same product) and
consumes canonical owners only. Verdict consolidation itself is TC-C (engine audit §7.8). This section only places the
outputs.

### 7.1 Layers and mapping

| Layer | Contents (existing owner) | Disposition |
|---|---|---|
| **1. Trade Builder** | SideCards (search, rows, quantity, destinations for 3+); team / "You" context (nav team switcher surfaced **in the builder header**, replacing the "Pick your team" dead end); import (KTC URL, screenshot) and share in one overflow "⋯" menu; value override per row (explicitly marked "edited"); Swap / Clear / Add team | **Keep, move to the top.** CSV / JSON / Copy KTC URL go into the overflow menu. The draft-capital stack team selectors fold into the side header. The rail moves out (layer 5) |
| **2. Immediate Result** | one compact package comparison: raw, VA, adjusted, net, a % gap, and a *package-only* band label (V2/V3/V9 unified and worded as package comparison, not a decision); balancer chips with origin identity | **Merge** V2, V3, V9 and the delta histogram into one strip. The tray becomes this strip on scroll. The fairness explanation becomes its one-line caption (no emoji). Never render a band on an empty trade |
| **3. Final Decision** | War Room headline (TC-C's YES / NO / NOT ENOUGH EVIDENCE + confidence + primary reason + counterargument) | **The only verdict.** Shown immediately below layer 2 (desktop: in the sticky right column). Available for 3+ teams once TC-C supports it; until then, an explicit "decision not available for 3+ teams" state |
| **4. Supporting Intelligence** (tabs / drilldowns) | **Value**: War Room Market lens + per-source table (Second Opinions V6 recast as evidence coverage, not a tally) + MC value uncertainty (relabelled, auto-invalidated). **Roster**: War Room Roster + Feasibility + Simulate impact (lineup, capacity, Team Strength; the V7 "roster fit" verdict retired, the duplicated capacity/Team Strength blocks merged) + NFL exposure. **Season**: ROS fit. **Fundamentals**: BDVM, with an explicit unavailable state instead of silent vanish. **Market**: Recent real trades / comparables. **Reasoning**: Why / Against / Uncertain + "How this was decided" + coverage | **Drilldowns.** Results are keyed to the trade state and marked stale or re-run on edit. Simulate impact stops inserting above the builder |
| **5. Advanced Tools** | Suggestions desk + rail (one surface, not two), balancer/equalizer list, Value mode (Raw relabelled as "legacy composite" or removed: P0-4), Team context / Asset only toggle, Market / My league (removed or disabled with a reason while the lens is withdrawn) | **Collapse** into an "Ideas & tools" section below the fold. The rail no longer precedes the builder |

**Removed or merged outright.**

- The delta histogram (a duplicate of V2).
- The second team picker (the desk's `#suggest-team` becomes the shared team state).
- The duplicate capacity and Team Strength blocks.
- "Simulate (Monte Carlo)" as a separate verdict-bearing control.
- The empty-trade verdict.
- The "My league" control (until a validated lens exists).

### 7.2 Desktop (≥1024; 1320 for the full two-column layout)

- **Left column, about 60%:** Builder (layer 1), then the Supporting Intelligence tabs (layer 4).
- **Right column, about 40%, sticky:** Immediate Result (layer 2) above the Final Decision (layer 3), with the primary
  next actions (balance, re-run, share).
- At 1920 the column cap should widen (or layer 4 should take a third column) instead of leaving 640 px of gutters.
- Measured target from today's layout: the decision visible without scrolling at 1366×900. Today it starts at y=1,019.

### 7.3 Mobile (<768)

- A single **persistent verdict bar** (adjusted totals + band + YES / NO) replaces both the tray and the sticky quick-add
  bar. Tapping it opens the decision sheet.
- The builder is first; "Add asset" opens a **bottom-sheet search** per side. That removes the three-search-box
  duplication and the 62 px sticky bar, bringing fixed chrome from 235 px down to about 150 px.
- Contextual section navigation (Value · Roster · Season · Market · Reasoning) as an in-page segmented control.
- Tables (per-source) become stacked rows or a controlled horizontal region with a visible affordance, so there is no
  page-level overflow (today 422/390).
- Every tap target ≥44 px: disclosures, player names, overrides, segmented controls, toolbar.
- Simulate impact and MC results render as drilldowns with stable dimensions and never above the builder.

### 7.4 Dependencies and order

- Layers 1, 2 and 5, and the mobile chrome, can start on stable contracts (TC-D after #1771).
- Layer 3 and the V5/V6/V7 relabelling depend on TC-C.
- P0-1 / P0-2 / P0-4 / P0-5 / P0-6 are TC-A / TC-E fixes that should precede the redesign so it does not re-skin wrong
  numbers.

---

## 8. Completion result

- `STATUS: DONE` (TC-0 UX audit deliverable).
- `ACCEPTANCE:` every section `/trade` renders on desktop and mobile, with screenshots; duplicates and competing
  verdicts; discoverability; scrolling; small-screen failures; performance and requests; an IA hypothesis for TC-D.
- `EVIDENCE:`
  - real local stack (§1), seven journeys × four viewports, panel interactions at 1366 and 390;
  - 24 screenshots in `docs/trade/ux-audit-2026-10-17/`;
  - request logs, layout measurements, axe and the bundle-check output quoted inline.
- `UNRESOLVED:`
  1. Production rendering is not verified (local only).
  2. BDVM, the trade ledger and projection-dependent War Room content could not render locally (environment), so their
     populated layouts are unaudited here.
  3. Keyboard order was sampled for the first 45 stops at 1366 only.
  4. 1920 and 360 panel interactions (Second opinions, simulation, imports) were not separately captured; their
     collapsed journeys were.
- `BLOCKERS:` none.
- `NEXT_ACTION:` feed P0-1, P0-2, P0-4, P0-5, P0-6 and P0-7 into TC-A (parity test incl. `monte_carlo`), and §7 into
  TC-D.
