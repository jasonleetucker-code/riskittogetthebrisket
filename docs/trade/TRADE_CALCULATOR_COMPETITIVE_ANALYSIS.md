# Trade Calculator: competitive analysis

**What this is.** Deliverable 2 of TC-0 in `docs/trade/TRADE_CALCULATOR_COMPLETION_WORKSTREAM.md`. It compares the
leading public fantasy-football trade calculators with Chase Upside's `/trade`, and recommends how the TC-D redesign
should lay out `/trade`.

**What this is not.** It is not product authority, and it does not decide methodology. The four kinds of
recommendation below feed TC-B, TC-C and TC-D, and each passes through `docs/EXECUTION_PLAN.md` and the gates that
batch already has:

- patterns to adapt;
- features to implement;
- patterns to avoid;
- information-architecture rules.

**Ground rules followed.**

- Only public, permitted evidence was used. No account was created, and no login, paywall or bot check was bypassed.
- Competitors are functional and UX benchmarks only. No code, copy, layout assets, icons or branding are reused.
- The screenshots in `docs/trade/competitive-2026-10-17/` are internal evidence captures, not design assets.
- Every claim gives its URL and the retrieval date, **2026-10-17**.
- Anything not observed directly is marked **UNVERIFIED**. A claim that comes only from a vendor's own marketing is
  marked **(vendor claim)**.

---

## 1. Method and sources

### 1.1 How each tool was examined

| Step | What was done |
|---|---|
| Discovery | Web search for 2026 dynasty, redraft and IDP calculators, plus the FantasyPros 2026 round-up ([fantasypros.com/2026/08/best-dynasty-fantasy-football-trade-tools](https://www.fantasypros.com/2026/08/best-dynasty-fantasy-football-trade-tools/)). That round-up is self-promotional: it ranks FantasyPros' own tool first. |
| Live interaction | Headless Chromium (Playwright) loaded each public calculator page at **desktop 1366×900** and **mobile 390×844** (touch, iPhone UA), and built the same sample trade wherever the page allowed it without login. |
| Sample trade | **Team 1 receives:** Bijan Robinson.<br>**Team 2 receives:** Drake London + Garrett Wilson + a 2027 mid 1st.<br>On the IDP calculator, Fred Warner was swapped in for Wilson.<br>A 1-for-3 is used on purpose: it exercises consolidation / package adjustment, pick search and the balancer. |
| Balancer check | On KTC and FantasyCalc the first suggested balancer was added, to test whether the "add X to even it" advice actually lands near even once the package adjustment re-runs. |
| Docs | FAQ, help and methodology pages, rendered in a browser where they are client-side apps. |
| Our side | Read from the code in this worktree (HEAD `695fc26c37`) and `CLAUDE.md`. The production `/trade` route was probed anonymously; signed-in production behaviour is the UX audit's job (`TRADE_CALCULATOR_UX_AUDIT.md`). |

### 1.2 Access results

| Competitor | URL examined | Access on 2026-10-17 |
|---|---|---|
| KeepTradeCut (KTC) | https://keeptradecut.com/trade-calculator | Public. Trade built on desktop and mobile. |
| FantasyCalc | https://fantasycalc.com/trade-calculator | Public. Trade built on desktop. |
| Dynasty Daddy | https://dynasty-daddy.com/trade-calculator | Public ("Continue without account"). Trade built on desktop and mobile. |
| IDP Trade Calculator (The IDP Show) | https://idptradecalculator.com/ | Public. Trade built on desktop and mobile. |
| Draft Sharks | https://www.draftsharks.com/trade-calculator | Free single-trade analyzer. Trade built on desktop (Dynasty / Superflex). |
| RotoTrade | https://www.rototrade.com/fantasy-football-trade-analyzer | Public. Trade analyzed on desktop; result URL `rototrade.com/tr/3bef40f422`. |
| RotoWire | https://www.rotowire.com/fantasy/football/dynasty-trade-calculator | Public (calculator in an iframe). Trade built on desktop and mobile. |
| DynastyProcess | https://apps.dynastyprocess.com/calculator/ | **Down.** HTTP 522 (Cloudflare origin timeout) on four attempts, browser and curl. Profiled from its methodology page and GitHub repo. |
| Dynasty League Football (DLF) | https://dynastyleaguefootball.com/dynasty-trade-analyzer/ | Desktop got a Cloudflare challenge (403), which was not bypassed. The mobile load of the **public description page** returned 200. The analyzer itself is premium and was not used. |
| Dynasty Nerds | https://www.dynastynerds.com/dynasty-tools/trade-calculator/ | Account required even for 3 free trades a day. Layout observed behind the sign-up modal; no trade built. |
| FantasyPros Trade Analyzer | https://www.fantasypros.com/nfl/myplaybook/trade-analyzer.php | "Upgrade to Use this Tool". Profiled from its public FAQ only. |
| Others | Dynasty Trade Lab ([Product Hunt](https://www.producthunt.com/products/dynasty-trade-lab)); Dynastyzer ([stork.ai listing](https://www.stork.ai/en/dynastyzer), third party); ESPN Trade Analyzer ([IBM newsroom](https://newsroom.ibm.com/Putting-the-FAN-in-Fantasy-How-IBM-is-Using-Artificial-Intelligence-to-Enhance-the-ESPN-Fantasy-Football-Experience)); PlayerProfiler ([trade-finder page](https://www.playerprofiler.com/trade-finder/)); Sleeper, Yahoo. | No public, logged-out calculator was found, or the product sits behind a login or paywall. Not evaluated interactively; see §2.12. |

**Not found.** No standalone public tool called "DynastyGPT" turned up in search. The nearest AI products are Dynasty
Trade Lab and Dynastyzer. "Fantasy Footballers" and Underdog had no public trade calculator to evaluate.

### 1.3 Screenshots (captured by us, compressed PNG, all under 60 KB)

| # | File | Shows |
|---|---|---|
| 01 | `competitive-2026-10-17/01-ktc-desktop-verdict-value-adjustment.png` | KTC: value-adjustment line item, value bar with fair zone, verdict sentence, balancers |
| 02 | `…/02-ktc-desktop-recent-trades-value-bar.png` | KTC: recent real trades with format chips; "total absolute value exchanged" stacked bars |
| 03 | `…/03-ktc-mobile-verdict.png` | KTC mobile: stacked sides, then totals, bar and verdict |
| 04 | `…/04-fantasycalc-desktop-waiver-adjustment.png` | FantasyCalc: "Waiver Adjustment" line item, verdict, league-sync CTA |
| 05 | `…/05-dynastydaddy-desktop-market-verdicts.png` | Dynasty Daddy: 8-market "Market Verdicts" panel, balancers, value trend |
| 06 | `…/06-dynastydaddy-mobile-summary-overlap.png` | Dynasty Daddy mobile: permanent left rail; the totals text collides at 390 px |
| 07 | `…/07-idptc-mobile-hidden-adjustment.png` | IDP Trade Calculator mobile: verdict with an adjustment that is never shown |
| 08 | `…/08-draftsharks-desktop-trade-tax-grade.png` | Draft Sharks: "Reasonable / Actual Trade Tax", Overpay / Underpay grades |
| 09 | `…/09-rotowire-desktop-posture-balancers.png` | RotoWire: package-adjusted bars, "Uneven, 21% edge", Contending / Any / Rebuilding balancer filter |
| 10 | `…/10-rotowire-mobile-raw-vs-adjusted.png` | RotoWire mobile: side total with "raw 120.47" under the adjusted 111.83 |
| 11 | `…/11-rototrade-desktop-roster-spot-line.png` | RotoTrade: "Roster Spot" line item on the 1-piece side (cropped to exclude a reaction GIF of a real person) |
| 12 | `…/12-dynastynerds-desktop-gated-three-column.png` | Dynasty Nerds: Team 1 / Trade Analysis / Team 2 layout behind an account gate |

---

## 2. Competitor profiles

All observations are dated 2026-10-17. Values are quoted only to show *behaviour*; vendor numbers are never compared
on a common scale here.

### 2.1 KeepTradeCut (KTC): the market-reference calculator

Evidence: live session, screenshots 01–03, and the
[KTC FAQ](https://keeptradecut.com/frequently-asked-questions?open=value-adj).

**Valuation.** The user picks one of three value sources: Crowdsourced (27,915,121 data points, vendor claim),
Tradesourced (real dynasty trades) or Crowd + Trades.

- Settings: Superflex on/off and TE Premium levels.
- The header gives a format and freshness line: "Superflex / .5 PPR • Crowdsourced market values updated 3 minutes ago".
- "More controls" holds Acceptable Variance (default 5%), Future Pick Adjustment (default 0%) and startup-mode league
  size. The DOM tooltip says league size is for pick numbering only and does not change values.

**Construction.**

- One search field per side, with autocomplete covering players and picks ("2027 Mid 1st").
- Each asset row shows position rank, team, age and value, with an × to remove it.
- Two teams only: no third-team control in the DOM.
- The URL updates live as the trade is built: `?var=5&pickVal=0&teamOne=1414&teamTwo=1268|1270|1703&format=2&isStartup=0&tep=0`.
- Buttons: "Copy Trade URL" and "Clear Calculator".
- No league sync on the calculator (the FantasyPros round-up says the same).
- No IDP: KTC publishes offense only (`CLAUDE.md`, Trade Engines).

**Evaluation.**

- **Value Adjustment** appears as a line item in the side receiving the consolidated piece: Bijan 9,999 plus a
  hatched "Value Adjustment +4,300" row, side total 14,299, against 18,813.
- Method (FAQ): "reverse engineered from the player the lesser side needs to have added to even the trade". It exists
  to stop "12 third round picks" from equalling a stud.
- The value bar has a hatched fair zone.
- One verdict sentence: "Favors Team 2 → Add a player worth 4,514 to Team 1 to even trade".
- Five one-tap balancers follow.
- **Balancer check passed.** Adding the first suggestion (Bo Nix 4,570) re-ran the adjustment (+4,300 → +4,471) and
  the verdict became "Fair Trade" (19,040 vs 18,812).
- Below the fold:
  - "Recent Trades": real trades involving these assets, each with format chips (SF/1QB, TE+/TE++, team count,
    starters, PPR) and a link to the Trade Database;
  - "Total Absolute Value Exchanged" stacked bars per side;
  - a 6-month trend chart per asset.
- No roster awareness, recommendation, confidence or explanation beyond the sentence.

**UX.**

- Desktop is dense but legible. Verdict, bar and balancers sit within one viewport of the sides.
- On first load a "Your Thoughts?" keep/trade/cut crowdsourcing modal blocks the calculator until dismissed
  (screenshot taken before dismissal: `ktc-desktop`, not retained).
- Mobile stacks Team 1, then Team 2, then a two-number total row, the bar and the verdict. Readable at 390 px with no
  horizontal scroll (scrollWidth 390).

**Does well:**

- the fastest time-to-answer of any tool tested;
- the adjustment shown as a named line item;
- a live shareable URL;
- comparable real trades with format chips;
- freshness stamped in the header.

**Does poorly:**

- no roster or league context;
- 2 teams only;
- no IDP;
- an interrupting modal;
- the comparables are not classified by comparability (a 1QB trade is listed beside SF ones).

### 2.2 FantasyCalc: trade-derived values with a roster-spot adjustment

Evidence: live session, screenshot 04,
[FAQ](https://fantasycalc.com/frequently-asked-questions) (rendered).

**Valuation.**

- Values are solved from 7,919,714 real trades (vendor claim).
- The FAQ describes the pipeline: optimization, outlier-trade removal, a separate run for 1QB and Superflex, regression
  adjustment for TEP, PPR and team count, and recency weighting.
- The header says "Automatically updated 44 minutes ago".

**Construction.**

- Redraft/Dynasty toggle.
- Settings: League Size, PPR, TEP and Superflex.
- Two search fields.
- Picks: generic future rounds ("2029 1st…4th") plus tiered current-class options ("2027 1st (Early)").
- No IDP: "Fred Warner" returned 0 results.
- Two teams.
- A "Sync League" CTA leads to roster analysis; that path was not used.

**Evaluation.**

- **Waiver Adjustment** appears as a line item on the fewer-pieces side (+1,506 here).
- FAQ method: a bench-spot value assumed to be the ~300th-best player (~425), "increase[d] slightly for each
  additional player".
- Verdict: "Favors Players on Team Two by 3,216".
- "Players To Equalize Trade" sit in a table below.
- **Balancer check passed.** Adding De'Von Achane re-ran the adjustment (+1,506 → +753) and landed at a gap of 218.
- "Advanced Trade Analysis with fantasycalcAI (BETA)" requires league sync (UNVERIFIED beyond the label).

**UX.**

- Clean two-column layout.
- A large empty ad slot (about 110 px) sits above the calculator and pushes the builder down.
- The mobile run did not complete in automation, so mobile UX is UNVERIFIED.

**Does well:**

- the adjustment is explained publicly and concretely;
- one plain verdict;
- the equalizer simulates the post-add state.

**Does poorly:**

- the roster-spot cost is a **league-agnostic constant**: it assumes the average league in their database, not your
  roster;
- no IDP;
- no context on whether the trade helps *you*.

### 2.3 Dynasty Daddy: multi-market calculator with cross-market verdicts

Evidence: live session, screenshots 05 and 06.

**Valuation.**

- The default "Dynasty Daddy" market is solved from completed trades and draft results, recency-weighted, with ADP
  blended in for thin assets, outlier filtering and smoothing.
- The page says it is built to avoid "100 pennies for a dollar".
- A **Fantasy Market** selector switches the whole calculator to another vendor's values (KTC, DynastyProcess, …).

**Construction.**

- 1QB/Superflex toggle.
- The search dropdown shows each option's **value inline** ("Josh Allen QB - BUF 10,200").
- Picks have tiers through 2029. No 2030 picks; no IDP ("Fred Warner" returned 0).
- "Add team" icon for multi-team (UNVERIFIED depth).
- The URL updates with readable slugs: `?sideA=bijanrobinsonrb&sideB=drakelondonwr,garrettwilsonwr,2027mid1stpi`.
- "Share" and "Clear" buttons.
- League link for rosters (not used).

**Evaluation.**

- Verdict: "Favors Team 2 → Add a player with 3,141 value to even trade", plus a "FAIR TRADE" meter.
- "Players to Even the Trade" offers one-tap adds.
- No package adjustment line is visible. The FAQ says consolidation is built into the values.
- **"Market Verdicts"** lists eight vendors as rows, each with a slider and a side: Dynasty Daddy, KeepTradeCut,
  DraftSharks, DynastyProcess, Fantasy Navigator, Pro Football Network, RosterAudit and RotoTrade. In this trade, 7 said
  Team 2 and 1 said Team 1.
- A "Trade Value (past month)" chart per asset.
- "Vote 4 Trades" posts the trade for a community vote.

**UX.**

- Dark theme with a permanent icon left rail, which costs about 64 px at all widths.
- Large blank ad space between the intro and the builder on desktop.
- On mobile, the "Team 1: 9,819 / Team 2: 13,160" summary text **visibly overlaps itself** at 390 px (screenshot 06).

**Does well:**

- the multi-market view is the closest competitor analogue to our Second Opinions;
- values shown inside search results;
- a readable live URL.

**Does poorly:**

- **the eight markets are presented as eight independent votes.** Several are correlated (KTC data feeds other
  aggregators, and our own lineage file puts Fantasy Navigator in the KTC Crowd family, `CLAUDE.md` step 4), so 7–1
  overstates agreement;
- mobile text collision;
- ad whitespace;
- no roster context without a league link.

### 2.4 IDP Trade Calculator (The IDP Show): the IDP-native calculator

Evidence: live session, screenshot 07.

**Valuation.** A single 12-team / .5 PPR basis, "Updated: 10/10/2026", with Superflex and TEP toggles. It prices
offense, IDP and picks together. **It is also one of our own voting sources** (`idpTradeCalc`, `CLAUDE.md` step 4), so
it is a peer and an input at once.

**Construction.**

- Two bare text inputs with no placeholder or label.
- The autocomplete shows value inline ("Bijan Robinson (9875) - RB | ATL").
- Picks support both slots and tiers ("2027 Pick 1.01 (9504)", "2027 Early 1st (7160)") through 2029.
- Each asset gets a red "Remove" button.
- No URL state; the URL stayed `/`.
- No league sync.

**Evaluation.**

- Verdict: "The trade favors Team 2. Team 1's side needs approximately 3,224 additional points to even the trade."
- Raw totals were 9,875 vs 17,768. The calculator therefore applies a consolidation adjustment of roughly 4,670
  points that is **never shown or explained**.
- "Assets to Even Trade" shows five chips with a refresh (shuffle) icon. They looked random-order, no single one
  matched the stated gap, and their meaning is undocumented.

**UX.**

- Minimal single column; mobile and desktop are effectively the same layout.
- Toggle state reads ambiguously: the switches render in the "off" position while the page text says "Superflex: ON
  TEP: ON". Observed in an automated session.

**Does well:** IDP coverage, pick slots and tiers, values in search.

**Does poorly:**

- hidden adjustment;
- unexplained balancers;
- unlabeled inputs (accessibility);
- no share or URL state.

### 2.5 Draft Sharks: projection-driven values with a "trade tax"

Evidence: live session, screenshot 08, and the
[dynasty trade value KB](https://www.draftsharks.com/kb/dynasty-trade-value-charts).

**Valuation.** "3D Values", built from Draft Sharks' projections and expert rankings scaled to league scoring.

- Settings: Redraft/Dynasty, 1QB/Superflex, and scoring including TEP.
- Each asset shows 3D Value, Position Rank and 3D ROS.

**Construction.**

- The sides are labelled **"Trade Away (You)"** and **"Trade For (Them)"**.
- The "Them" side has position tabs: QB / RB / WR / TE / **IDP**.
- The free analyzer handles small trades. "Use Trade Builder for 3+ player trades" routes larger deals to a separate
  paid tool (UNVERIFIED pricing per tool).
- League sync and Trade Navigator are paid.

**Evaluation.** Per side: Trade 3D Value, **Reasonable Trade Tax** (a range, e.g. "0 – 5" or "45 – 55"), Actual Trade
Tax, and **Grade** (Overpay / Underpay).

- The KB defines trade tax as the overpayment the multi-piece side should make (heuristic: 30–50% for studs, 15–25%
  for starters).
- **Defect observed.** At 57.3 vs 57.1 (a 0.3% difference) the grades still read "Overpay" vs "Underpay". No fair band
  was shown, and "Actual Trade Tax" stayed "–".

**UX.** Article-style page with a large pricing block directly below the tool. Clear three-column desktop. Mobile not
captured in a usable state (UNVERIFIED).

**Does well:**

- user-perspective labels;
- the package premium expressed as a *range* (honest about uncertainty);
- IDP availability.

**Does poorly:**

- binary grades with no fair band;
- tool fragmentation across Analyzer, Partner Finder and Builder;
- heavy upsell.

### 2.6 RotoTrade: a "make it or not" verdict with player context

Evidence: live session, screenshot 11, and the
[analyzer page](https://www.rototrade.com/fantasy-football-trade-analyzer).

**Valuation.** One proprietary scale (about 0–100), separate for redraft and dynasty.

- Settings: PPR, 1QB/Superflex, TE premium, and a **"Package Adjust ON/OFF"** toggle.
- Picks: up to three future years, size-adjusted (vendor claim; our pick query did not match).

**Construction.**

- Giving / Getting search and an "Analyze this trade" submit. Results do **not** update live.
- Each result has a shareable URL (`/tr/<id>`), plus "Edit current trade", "Analyze a new trade" and "Share results".
- League import is separate (ESPN, Sleeper, MFL, CBS, Yahoo).

**Evaluation.**

- A settings-chip row: Dynasty · PPR · 12 Teams · Superflex ON · TE Prem OFF · Package Adj. ON.
- The package adjustment appears as a **"Roster Spot"** line on the 1-piece side (84.4 → 90.4).
- **Overall Assessment: "Yes, by all means"**, followed by a reason and a roster caveat ("if you … are desperately thin
  at RB … it might not make sense").
- "Value gap 18.2", with optional bridging players.
- Weekly schedule and projections, and pros and cons for every player.
- **"Chance the other team accepts: 27%"**, with no stated calibration.
- **"Recent related trades" were all REDRAFT** trades shown for a **DYNASTY** analysis: a comparability failure.

**UX.**

- Clear three-card top row: Assessment | Giving | Getting.
- A reaction GIF of a real person is on by default, which undercuts professional trust.
- The long scroll mixes analysis with schedules.

**Does well:**

- a direct yes/no recommendation;
- one reason and one caveat (the closest public analogue to our TC-C target);
- settings chips as a receipt;
- shareable result pages.

**Does poorly:**

- uncalibrated acceptance probability;
- comparables that do not respect format;
- gimmick visuals;
- a submit-then-scroll flow.

### 2.7 RotoWire: expert values, posture-aware balancing

Evidence: live session, screenshots 09 and 10, and the
[calculator page](https://www.rotowire.com/fantasy/football/dynasty-trade-calculator) (author Max Staley, updated
2026-10-07).

**Valuation.** Expert charts: Jagger, Theo or a "Consensus" of the two, on a 1–100 scale; SF/1QB format;
PPR/TEP under "Advanced". This is explicitly "what a dynasty expert would do", not the crowd.

**Construction.**

- 2-team or **3-team** toggle; up to 6 assets per side (page text).
- Sides are named "Team 1 / Team 2 RECEIVES", and each side can be **renamed**.
- A swap button sits between the sides.
- "Share Trade" and "Copy Trade" buttons.

**Evaluation.**

- Each side total shows the adjusted number with **"raw 120.47"** beneath it, and the asset count is tagged
  "package-adjusted".
- Bars are labelled "Trade value · adjusted for package quality".
- Verdict card: "**Uneven** — Team 2 gets +21.36 value (21% edge)". The gap is relative, not only absolute.
- **"To balance — add to Team 1"** has a **Contending / Any / Rebuilding** filter. A contender sees immediate
  contributors; a rebuilder sees youth and picks.

**UX.**

- Modern card UI, legible at 390 px.
- On desktop, the search dropdown stayed open over the result bars after the last add. This may be an artifact of
  automated focus (UNVERIFIED for human use).

**Does well:**

- raw and adjusted shown side by side;
- a relative gap;
- **a posture filter on balancer suggestions**;
- 3-team trades;
- team naming.

**Does poorly:**

- two-expert scale only;
- no roster context;
- an interpretive gap: "Consensus" averages just two people.

### 2.8 DynastyProcess: the open, customizable calculator (unavailable today)

Evidence: the app returned **HTTP 522** on 2026-10-17 (four attempts). Sources:
[methodology](https://dynastyprocess.com/values/) (2020-06-25), [site](https://dynastyprocess.com/) and the GitHub
repo [dynastyprocess/apps-calculator](https://github.com/dynastyprocess/apps-calculator) (R/Shiny, GPL-3.0,
"v3.0.0").

**Valuation.**

- `Value = 10500 × e^(ECR × −0.0235)` over FantasyPros dynasty consensus ranks.
- The **valuation factor** (the exponent) is user-tunable: smaller values make depth worth more, larger values favour
  studs. That *is* its package / consolidation model: concavity of the value curve, not an add-on.
- Rookie picks blend two GAM models (default 80%).
- Future picks are discounted to 80%.
- 2QB comes from a LOESS mapping.
- The app adds a startup mode and "wizard suggestions". The README notes a shinyMobile trade gauge.

**Assessment.** It is transparent and user-tunable. The value base is a single expert consensus that is now years
old, and the service is unreliable: unreachable at audit time. Its trade UX could not be verified.

### 2.9 Dynasty League Football (DLF): context-rich, explicitly *not* a yes/no tool

Evidence: the [description page](https://dynastyleaguefootball.com/dynasty-trade-analyzer/) (mobile render). The
analyzer itself is premium and behind a Cloudflare check; it was not used.

**Stated design (vendor claims).**

- Values are drawn from rankings, ADP and recent trade data, with 1QB or SF.
- League import from MFL, Fleaflicker, Sleeper, RTS and FFPC.
- A rookie-pick value slider for leagues or owners that over- or under-value picks, or for win-now vs rebuild.
- **"Package Value Adjustment"**: "the greater the asset differential, the larger the modifier".
- **"Related Dynasty Trades"**, keyed on the most valuable asset.
- The 5 latest news items and articles per player.
- Historical ADP trends.
- "Currently, IDP players and Devy Players are not available."
- Stated philosophy: "less about telling an owner 'Yes make this trade' … more about providing the owner with all of
  the info needed".

**Assessment.** It is the strongest *context* pitch. It deliberately avoids a decision and has no IDP. Its UX is
UNVERIFIED.

### 2.10 Dynasty Nerds: expert values, gated

Evidence: [calculator page](https://www.dynastynerds.com/dynasty-tools/trade-calculator/), screenshot 12.

**Offer.**

- Free account: 3 trades a day, "Expert-set values for 500+ players", "Instant verdict with point breakdown".
- Premium ($69.99–79.99 a year per search snippets): formats, pick analysis, league sync, custom values and a Trade
  Finder.
- "50,000+ dynasty managers" (vendor claim).

**Layout observed.** **Team 1 | Trade Analysis | Team 2** in three columns, with the analysis in the middle, and
position-filter tabs (All / QB / RB / WR / TE / Picks). No trade could be built without creating an account, so no
further evaluation was done.

### 2.11 FantasyPros Trade Analyzer: roster- and league-aware, paywalled

Evidence: [public FAQ](https://www.fantasypros.com/nfl/myplaybook/trade-analyzer.php). Everything else is behind
"Upgrade to Use this Tool".

**Vendor claims.**

- It analyzes "your entire roster, your league settings, and the rankings of more than 100 experts".
- It shows impact "this week and rest-of-season" and "how it affects your league's power rankings".
- Dynasty is supported, with **"we also sync every team's actual draft picks from your league site"**.
- It explicitly argues that calculators "look at the value of players in a vacuum".

**Assessment.** Its positioning is the nearest to our War Room (roster-aware, league-synced, picks owned). It is
unobservable without paying, so every capability is a vendor claim.

### 2.12 Others, briefly

| Product | What is publicly verifiable | Status |
|---|---|---|
| **Dynasty Trade Lab** | AI trade suggestions from a Sleeper/Fantrax roster, including **3-way deals**. Values from FantasyCalc adjusted to settings; 5 free credits ([Product Hunt](https://www.producthunt.com/products/dynasty-trade-lab), 2026). | Vendor claim; not tested |
| **Dynastyzer** | "Package Penalty", harsher in shallow leagues. **Flat positional multipliers** (QB ×1.5 SF, TE ×1.25 TEP, IDP ×1.5). $9 a month ([stork.ai](https://www.stork.ai/en/dynastyzer), third-party directory). | UNVERIFIED |
| **ESPN Trade Analyzer** | In-league tool. IBM Watson blends stats with NLP over news and expert commentary ([IBM newsroom](https://newsroom.ibm.com/Putting-the-FAN-in-Fantasy-How-IBM-is-Using-Artificial-Intelligence-to-Enhance-the-ESPN-Fantasy-Football-Experience), undated). | Login required; UNVERIFIED current form |
| **PlayerProfiler** | Trade Analyzer bundled in a paid "Dynasty Deluxe". Lifetime-value ratings from its own engine ([trade-finder page](https://www.playerprofiler.com/trade-finder/)). | Paywalled; UNVERIFIED |
| **Sleeper, Yahoo** | No public, logged-out trade calculator found. Native trade screens are in-app and in-league. | Not evaluated |
| **RotoWire, Draft Sharks (paid tiers)** | League-synced trade finders / "Trade Navigator". | Paywalled; not evaluated |

---

## 3. Comparison matrix

### Legend

- **Y** = observed.
- **P** = partial or limited.
- **N** = observed absent.
- **G** = gated (login/paywall), so a vendor claim only.
- **?** = UNVERIFIED.
- **—** = not applicable.

### Columns

- **CU** = Chase Upside `/trade`, from code at HEAD `695fc26c37`.
- **KTC** = KeepTradeCut.
- **FC** = FantasyCalc.
- **DDy** = Dynasty Daddy.
- **IDPTC** = IDP Trade Calculator.
- **DS** = Draft Sharks (free analyzer).
- **RT** = RotoTrade.
- **RW** = RotoWire.
- **DP** = DynastyProcess (app down; from docs).
- **DLF** = Dynasty League Football (description page).
- **DN** = Dynasty Nerds (gated).
- **FP** = FantasyPros (gated).

### 3.1 Trade construction

| Capability | CU | KTC | FC | DDy | IDPTC | DS | RT | RW | DP | DLF | DN | FP |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| Anonymous use (no login) | **N**¹ | Y | Y | Y | Y | Y | Y | Y | Y² | N | N | N |
| Per-side search with autocomplete | Y | Y | Y | Y | Y | Y | Y | Y | ? | G | G | G |
| Value shown inside search results | ?³ | N | N | Y | Y | Y | N | Y | ? | ? | ? | ? |
| Picks: generic + tier + exact slot | Y⁴ | P (tier; slot in Tradesourced) | P (round + current tiers) | P (tiers) | Y (slot + tier) | ? | P | ? | P | P | G | G (owned) |
| IDP players | Y⁵ | N | N | N | Y | Y (IDP tab) | ? | ? | ? | N (stated) | ? | ? |
| More than 2 teams | Y (5)⁶ | N | N | ? | N | P (paid Builder) | N | Y (3) | ? | ? | ? | ? |
| Remove / clear / swap sides | Y | P (no swap) | P | P | P | P | P | Y | ? | ? | ? | ? |
| URL updates live while building | N⁷ | Y | N | Y | N | N | — (result URL) | ? | ? | ? | ? | ? |
| Explicit share link | Y | Y | ? | Y | N | N | Y | Y | ? | ? | ? | ? |
| Import a trade (KTC URL / screenshot) | Y⁸ | N | N | N | N | N | N | N | N | N | N | N |
| League sync / own rosters | Y⁹ | N | G | G | N | G | P (league import) | N | N | G | G | G |
| Perspective labels ("You" / "Them") | P ("Your team" pill)¹⁰ | N | N | N | N | Y | Y (Giving/Getting) | P (rename teams) | ? | ? | ? | ? |
| User value overrides | Y¹¹ | P (pick adj. slider) | N | N | N | N | N | N | Y (valuation factor) | P (pick slider) | G (custom values) | N |

### 3.2 Trade evaluation

| Capability | CU | KTC | FC | DDy | IDPTC | DS | RT | RW | DP | DLF | DN | FP |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| Value base | multi-source canonical blend¹² | crowd / trades (own) | trades (own) | trades + ADP (own) or another vendor's | own | projections + experts | own | 2 experts | FP ECR (2020 method) | rankings + ADP + trades | experts | 100+ experts + roster |
| Package adjustment exists | Y¹³ | Y | Y | built into values | Y (hidden) | Y (trade tax range) | Y (toggle) | Y | via curve exponent | Y | ? | ? |
| …shown as its own number | Y ("Raw + VA" subtext) | Y (line item) | Y (line item) | N | **N** | Y (range) | Y (line item) | Y (raw vs adjusted) | — | ? | ? | ? |
| Fairness band is relative (%) | **N** (absolute 350/900/1800)¹⁴ | Y (5% variance) | N (absolute) | ? | N | N (no band) | N | Y (% edge) | ? | ? | ? | ? |
| Balancer suggestions | Y | Y | Y | Y | P (undocumented) | N | Y | Y | Y (wizard) | ? | ? | ? |
| …simulated through the adjustment | Y¹⁵ | Y (tested) | Y (tested) | ? | N | — | ? | ? | ? | ? | ? | ? |
| …drawn from the counterparty's actual roster | Y¹⁵ | N | N | N (w/o sync) | N | — | N | N | N | ? | ? | ? |
| …posture-filtered (contend / rebuild) | N | N | N | N | N | — | N | **Y** | N | P (pick slider) | ? | ? |
| Roster impact (lineup / starters) | Y¹⁶ | N | G (sync) | G (sync) | N | N | P (text caveat) | N | N | ? | ? | G |
| Roster capacity / forced drops | **Y**¹⁷ | N | P (constant waiver cost) | N | N | N | P (constant "roster spot") | N | N | N | ? | ? |
| Competitive posture (win-now / rebuild) | Y¹⁸ | N | N | N | N | N | N | P (balancer filter) | P (startup / wizard) | P (slider) | ? | G |
| Explicit recommendation (do it / don't) | Y (5-level War Room)¹⁹ | N | N | N | N | P (grade) | **Y** | N | N | **N (by design)** | ? | G |
| Reasons for / against | Y¹⁹ | N | N | N | N | N | P (one reason + caveat) | N | N | ? | ? | G |
| Confidence / uncertainty shown | Y (label + biggest uncertainty)¹⁹ | N | N | N | N | P (tax range) | **uncalibrated %** | N | N | ? | ? | ? |
| Cross-market second opinions | Y (family-collapsed tally)²⁰ | N | N | **Y (8 markets, uncollapsed)** | N | N | N | P (2 experts) | N | N | N | N |
| Comparable real trades | Y (comparability-labelled, collapsed)²¹ | **Y** (format chips) | P (DB page) | P (DB page) | N | N | Y (format ignored) | N | N | Y | N | ? |
| Per-asset value trend | N | Y (6 mo.) | P (risers/fallers) | Y (1 mo.) | N | N | N | N | N | Y (ADP history) | ? | ? |
| Fundamentals / projections lens | Y (BDVM, ROS fit)²² | N | N | N | N | Y (3D ROS) | Y (projections, schedule) | N | N | P | ? | G |
| Board freshness shown at the verdict | **N**²³ | Y | Y | N | Y (date) | Y (page date) | N | P (updated date) | — | ? | ? | ? |
| News / pros-cons per player | N | N | N | N | N | N | Y | N | N | Y | ? | ? |

### 3.3 UX

| Capability | CU | KTC | FC | DDy | IDPTC | DS | RT | RW |
|---|---|---|---|---|---|---|---|---|
| Single unambiguous verdict near the builder | **N** (War Room + meter + tray + explanation)²⁴ | Y | Y | Y | Y | P | Y | Y |
| Verdict within first viewport after building (desktop) | P²⁴ | Y | Y | P (ad space) | Y | Y | Y | Y |
| Sticky verdict while editing | P (2-team tray only)²⁵ | N | N | N | N | N | N | N |
| Controls count above the builder | ~12 buttons²⁶ | 2 + settings | settings | settings | 1 | settings | settings | 2 + settings |
| Mobile: no horizontal scroll at 390 px | ? (UX audit) | Y | ? | Y but text overlap | Y | ? | ? | Y |
| Mobile-specific construction aid | Y (sticky quick-add)²⁷ | N | ? | N | N | ? | ? | N |
| Interruptions (modal / ad / upsell) | none observed in code | modal on load | ad slot | ad space, rail | none | pricing block | GIF | none in widget |
| Inputs labelled for assistive tech | Y (aria labels in code) | Y | P ("aria-label: Number") | P | **N** | Y | Y | Y |

### Matrix notes (our side)

1. `/trade` answers anonymous requests with a 307 to `/login?next=%2Ftrade` (curl, 2026-10-17). The page gate is in
   `frontend/middleware.js` + `frontend/lib/public-routes.js`.
2. When reachable.
3. Search results render through the shared result row in `frontend/app/trade/trade-sections.jsx` (line 73). Whether
   values show inline belongs in the UX audit.
4. `src/api/pick_value_resolution.py` (slot / tier / generic grades, horizon current + 3) and
   `src/identity/picks.py` (owned-pick `assetId`).
5. The canonical board carries IDP (`CLAUDE.md` "Live Value Pipeline").
6. `MAX_SIDES = 5` (`frontend/lib/trade-logic.js:1517`), with a destination per asset for 3+ teams and the
   `MultiTradeFlow` visual (`page.jsx:148`).
7. The share link is explicit ("Copy share link") and restored from `?share=` on load (`page.jsx:625–636`). The URL
   does not update live.
8. `trade-ktc-import.jsx` and `trade-screenshot-import.jsx`.
9. The selected league and team drive the War Room request and roster-filtered balancers (`page.jsx`, `balancersForSide`
   at line 1862).
10. `mySideIdx` "Your team" pill (`page.jsx` around line 902).
11. `valueOverrides` / "Reset Values" (`page.jsx` around line 2026).
12. `src/api/data_contract.py::_compute_unified_rankings`: family-capped, freshness-weighted.
13. The active package model in this worktree is `ACTIVE_PACKAGE_MODEL_ID = KTC_2026_04` (`trade-logic.js:553`), with
    `geom_q078_v1` in shadow until #1771 merges. The side card shows "Raw X + VA Y" (`trade-sections.jsx`, SideCard).
14. `meterVerdict` (`trade-logic.js:1783`): FAIR below 350, SLIGHT EDGE below 900, UNFAIR below 1800, otherwise
    LOPSIDED, in absolute board units. The tray appends a %.
15. `findBalancers` rebuilds the trade per candidate and re-measures through `tradeImbalance`
    (`trade-logic.js:1400–1437`), over the counterparty's roster when a team is selected.
16. War Room roster lens: `src/trade/analyze_trade.py::_roster_lens` and `components/trade/TradeWarRoom.jsx`
    `RosterImpact`.
17. `src/trade/roster_capacity.py` (`CLAUDE.md` "Roster capacity and forced drops").
18. `src/roster_intel/window.py::competitive_posture` and Analyze Trade's `strategicPosture` lens (`votes=False`).
19. `RECOMMENDATION_LABELS` MAKE / LEAN_MAKE / TOO_CLOSE / LEAN_PASS / PASS (`frontend/lib/trade-war-room.js:20`),
    plus confidence, "Biggest uncertainty", and Why / Against / Uncertain lists (`TradeWarRoom.jsx` 560–577).
20. `components/trade/TradeSourceBreakdown.jsx` and `lib/second-opinions.js::tallyOpinions`: FULL_SOURCE rows vote
    once per correlation family; hybrid rows are labelled and do not vote.
21. `components/trade/RecentRealTrades.jsx`, in a collapsed panel (`page.jsx` around line 2395).
22. `BdvmTradePanel` and `RosTradeFitPanel`, inside the collapsed "Second opinions" (`page.jsx` 2347–2361).
23. A grep of `page.jsx`, `trade-sections.jsx` and `TradeMeter.jsx` for freshness, "updated" or asOf found no board
    freshness stamp on `/trade`.
24. In order: War Room, then TradeMeter, then TradeFairnessExplanation, then the collapsed second opinions, then the
    sticky tray (`page.jsx` 2253–2337 and 2430). The War Room recommendation and the meter verdict use different
    vocabularies. The workstream lists this "competing verdicts" defect for the UX audit.
25. `trade-sticky-tray`, rendered only when `sides.length === 2` (`page.jsx:2432`).
26. Value mode, Swap, Clear, Reset Values, Add Team, Import, Copy share link, Copy KTC URL, CSV, JSON and Simulate
    impact (`page.jsx` 2009–2108).
27. `MobileQuickAdd` (`trade-sections.jsx:137`).

---

## 4. Where Chase Upside is stronger, and where weaker

### 4.1 Stronger: the analytical depth is ahead of every observable public tool

| Area | Our evidence | Best public competitor |
|---|---|---|
| **Value quality.** Multi-source, family-capped, freshness-weighted, one 1–9999 scale for offense, IDP and picks. | `data_contract.py`, B10/B11 (`CLAUDE.md`) | Single-source boards: KTC, FC, DDy; experts only: RW, DN. IDPTC covers IDP but is one source (and one of our inputs). |
| **Roster consequence.** Forced drops priced from the team's own cut ladder; unknown cap is UNKNOWN; taxi bracketed. | `roster_capacity.py` | FC and RotoTrade charge a *constant* roster-spot cost (FC: the ~300th player, ~425, for an "average" 11.3-team league). |
| **Balancers that work on real rosters.** Simulated through the package model and drawn from the counterparty's roster. | `findBalancers`, `balancersForSide` | KTC and FC simulate correctly (tested) but suggest players the partner may not own. |
| **Recommendation with structure.** Five levels, confidence, Why / Against / Uncertain, separate Market / Roster / Feasibility lenses, Asset-Only vs Team Context. | `analyze_trade.py`, `TradeWarRoom.jsx` | RotoTrade gives one verdict, one reason and one caveat; FantasyPros claims roster-aware analysis (gated). |
| **Cross-market opinions done honestly.** One vote per correlation family; hybrid estimates are labelled and do not vote. | `second-opinions.js::tallyOpinions` | Dynasty Daddy shows eight markets as eight votes with no correlation handling. |
| **Comparables with format comparability.** | `RecentRealTrades.jsx` (Sharp ledger format captures) | KTC shows format chips without classifying them; RotoTrade showed redraft trades for a dynasty analysis. |
| **Multi-team.** Up to 5 sides, with destinations and a flow view. | `trade-logic.js:1517`, `MultiTradeFlow` | RW 3; Dynasty Trade Lab claims 3-way; KTC, FC and IDPTC 2. |
| **Import.** KTC URL and screenshot import, plus a "Copy KTC URL" export. | `trade-ktc-import.jsx`, `trade-screenshot-import.jsx` | None observed. |
| **Missing is never zero.** Unpriced assets are labelled and never valued at 0. | `CLAUDE.md` invariants | None states this. IDPTC hides its adjustment entirely. |

### 4.2 Weaker: the product shell loses to simpler tools on time-to-answer and clarity

| Gap | Evidence (ours) | Who does it better |
|---|---|---|
| **Several verdicts compete.** The War Room badge ("Lean make"), the meter (FAIR / SLIGHT EDGE / UNFAIR / LOPSIDED), the tray, the explanation text and the collapsed second opinions all answer "is it good?". | `page.jsx` 2253–2337, 2430; note 24 | KTC, FC, DDy and RW each show **one** sentence directly under the sides. |
| **Absolute fairness bands.** A 900-point gap is "slight" whether the deal is worth 3,000 or 30,000. | `meterVerdict`, `trade-logic.js:1783` | KTC ("acceptable variance" as a % of total, user-tunable); RW ("21% edge"). Feeds TC-A threshold recalibration. |
| **Control overload.** About 12 buttons before the first asset (exports, imports, mode). | `page.jsx` 2009–2108 | KTC: Copy URL and Clear, with settings tucked into "More controls". |
| **The verdict tray exists only for 2 teams,** and the multi-team verdict scrolls away. | `page.jsx:2432` | No competitor has sticky multi-team either; an open opportunity. |
| **Context hidden by default.** Comparables and second opinions are collapsed; there is no per-asset trend. | `page.jsx` 2347, 2395 | KTC shows comparables and a 6-month trend inline below the verdict; DDy shows a month of trend. |
| **No freshness or format receipt at the verdict.** | Note 23 | KTC ("updated 3 minutes ago"), FC ("44 minutes ago"), RotoTrade settings chips. |
| **"VA" jargon** in the side total. | SideCard "Raw X + VA Y" | KTC "Value Adjustment" with a "More on value adjustment" link; RW "package-adjusted". |
| **No live URL state.** | Note 7 | KTC and DDy update the URL as you build. |
| **Login wall.** No anonymous first answer. | 307 to `/login` | Every free competitor. This is an owner-level product choice (private, non-commercial site); it is recorded here, not recommended for change. |
| **No acceptance or partner signal yet.** | — | RotoTrade "chance accepts 27%" (uncalibrated, see §5.3). Ours waits on C6-MGR-02 / Manager Intelligence, as it should. |

---

## 5. Patterns to adapt, features to build, and patterns to avoid

### 5.1 UX patterns worth adapting

Each pattern names who demonstrates it and where it would land in our page.

| # | Pattern | Demonstrated by | Adaptation for `/trade` |
|---|---|---|---|
| U1 | **One verdict sentence directly under the sides,** with a direction arrow and an actionable clause: "Favors Team 2 → add ≈4,514 to Team 1". | KTC (01), DDy, FC, RW (09) | The Immediate Result line. It is the *package* answer only. The YES / NO / NOT ENOUGH EVIDENCE decision stays a separate, labelled block (TC-C). Both use one vocabulary per concept. |
| U2 | **The package adjustment as a named line item** inside the side that receives it, with a "how this works" link. | KTC "Value Adjustment +4,300", FC "Waiver Adjustment", RotoTrade "Roster Spot", RW "raw 120.47" | Replace the "Raw X + VA Y" subtext with a line row: "Package adjustment (+N)", plus an info link, written for whichever model is active (`packageModelReceipt`). |
| U3 | **Value bar with a visible fair zone.** | KTC (hatched centre zone), RW adjusted bars | The meter's bar uses a *relative* fair zone once TC-A recalibrates bands (the zone width comes from that work, not from here). |
| U4 | **Balancer chips with one-tap add, filtered by posture.** | RW Contending / Any / Rebuilding (09); KTC and DDy one-tap | Our balancers are already roster-aware and simulated. Add a posture filter fed by `competitive_posture` (inferred and user-adjustable). It filters *candidates* only and never changes the math. |
| U5 | **Freshness and format receipt at the result,** e.g. "Superflex · TEP · 12 teams · board updated 38 min ago · Package model: …". | KTC header line; FC "updated 44 minutes ago"; RotoTrade settings chips | One receipt row above the Immediate Result, from the contract's own metadata. Never a hard-coded label. |
| U6 | **Value and position shown inside search results.** | DDy ("QB - BUF 10,200"), IDPTC, RW | Show the canonical value (or "unpriced") in each result row, so builders can size a package before adding. |
| U7 | **Natural pick entry**: "2027 Mid 1st", "1.01", "2028 2nd". | IDPTC (slot + tier), KTC, DDy | Keep our `pick_value_resolution` grades, and make search accept all three spellings. Owned picks surface first when a team is selected. |
| U8 | **Live, readable URL state.** | KTC (ids), DDy (slugs) | Sync the existing share encoding to the URL on change (`replaceState`), keeping the explicit "Copy link". Supports TC-B "share and URL restore". |
| U9 | **Perspective labels** "You give / You get" when the team is known. | DS "Trade Away (You) / Trade For (Them)", RotoTrade Giving / Getting | Use them when `mySideIdx >= 0`. Fall back to neutral side names. The display side never changes objective math (workstream invariant). |
| U10 | **Comparable trades directly below the verdict,** with format chips. | KTC Recent Trades (02) | Surface the top 2–3 *comparable-labelled* real trades as a summary strip. Full list on demand. Our comparability classes are the differentiator. |
| U11 | **Mobile: sides stacked, then a compact totals + bar + verdict row.** | KTC mobile (03), RW mobile (10) | Our persistent bottom verdict bar should carry the same three things (both totals, the bar, the verdict word) and also work for 3+ sides. |
| U12 | **Center analysis column on wide desktop.** | Dynasty Nerds (Team 1 \| Analysis \| Team 2, screenshot 12) | Consider it only for two teams at ≥1280 px. The TC-D default (builder left, sticky result right) generalises to 3–5 sides; see §6. |

### 5.2 Analytical features genuinely worth implementing

These are filtered against our invariants, and each is routed to its batch.

| Feature | Seen at | Why it is worth it | Constraint / batch |
|---|---|---|---|
| **Posture-aware balancer filter** | RW | Turns "what balances it" into "what balances it *for a contender / rebuilder*". | Consumes `competitive_posture`; filter only. Picks still never become balancers (C7-PICKGEN-01 rule 5). **TC-B** |
| **Inline comparables strip** | KTC | Market evidence beside the verdict instead of behind a fold. | Reuses `RecentRealTrades` and its comparability labels; respects the evidence-kind rules (comparables are *market evidence*, counted once). **TC-B / TC-D** |
| **Per-asset value trend** | KTC (6 mo), DDy (1 mo), DLF (ADP history) | Answers "am I selling at a low?". | Read through `src/history` (as-of, no future observations, pre-floor gap permanent). Display only. **TC-B (supporting intelligence)** |
| **Relative fairness bands** | KTC, RW | Fixes scale dependence of the verdict. | The calibration belongs to TC-A, under the active package model. Unrecalibrated bands are labelled as PRIOR. **TC-A** |
| **Package-premium explanation as a range** | DS "Reasonable Trade Tax 45–55" | Honest about the uncertainty of a consolidation premium. | Only if the active model yields a defensible interval; otherwise explain the single number in words. Never a second package model. **TC-C explanation** |
| **Partner acceptance signal** | RotoTrade (27%) | A real user need. | **Only** from C6-MGR-02 partner intelligence, and **only** as a calibrated label until validated (workstream "Confidence" rule). Not before. **Later** |
| **Per-player news strip** | DLF, RotoTrade | Context before deciding. | Optional; existing news aggregation only; never moves the verdict (explanatory output). **Advanced / low priority** |

### 5.3 Patterns to deliberately avoid

| Anti-pattern | Observed at | Why we avoid it |
|---|---|---|
| **Correlated markets shown as independent votes** ("7 of 8 markets say Team 2") | Dynasty Daddy Market Verdicts (05) | Breaks *signal independence*. Ours already collapses by family; keep it that way and say so in the UI. |
| **A hidden package adjustment** | IDPTC (07): about 4,670 points applied, never shown | Users cannot reconcile totals and trust drops. Always show the adjustment (U2). |
| **A league-agnostic constant roster-spot cost** | FC (~425 for the ~300th player), RotoTrade "Roster Spot" | We already price forced drops from the real roster (`roster_capacity.py`). Never regress to a constant. |
| **Grades with no fair band** | DS: 57.3 vs 57.1 graded "Overpay / Underpay" | A near-tie must read as a tie. Our TOO_CLOSE level and a relative fair zone cover it. |
| **An uncalibrated probability** | RotoTrade "Chance the other team accepts: 27%" | Violates the workstream rule that numeric probabilities appear only once validated. |
| **Comparables that ignore format** | RotoTrade: redraft trades for a dynasty analysis | Our comparables carry format comparability and must keep displaying it. |
| **Balancer lists with no stated meaning, or shuffle buttons** | IDPTC "Assets to Even Trade" + refresh | Every suggestion states the post-add result (our `gapAfter`). |
| **Flat positional multipliers** | Dynastyzer (third-party listing: QB ×1.5, TE ×1.25, IDP ×1.5) | `CLAUDE.md` / BDVM: no positional multipliers; format effects come from exact scoring and replacement. |
| **Interrupting modals, ad gaps, upsell blocks inside the flow** | KTC first-load modal; FC and DDy ad whitespace; DS pricing block | Time-to-answer is the competitive axis where simple tools win. |
| **Permanent side rails and colliding totals on mobile** | DDy mobile (06) | Mobile is first-class: no fixed rail, totals that never overlap, 44 px targets. |
| **Gimmick reaction media** | RotoTrade reaction GIF (real person) | Professional trust; PSI Direction A. |
| **Submit-then-scroll analysis** | RotoTrade | The immediate result must update as you edit. Expensive analysis follows asynchronously (TC-E sequencing). |
| **Refusing to give an answer as a philosophy** | DLF ("less about … 'Yes make this trade'") | The owner directive requires one answer. DLF's lesson is the *context*, not the refusal. Our honest third state is NOT ENOUGH EVIDENCE, not silence. |

---

## 6. Recommendations for `/trade` information architecture (input to TC-D)

The workstream already fixes this order: Builder → Immediate Result → Final Decision → Supporting Intelligence →
Advanced Tools. The rules below make that order concrete, and each traces to evidence above. None of them changes any
number; they decide where numbers appear.

### 6.1 Rules for both layouts

1. **Exactly one package sentence and one decision block.**
   - The meter, the tray and the fairness explanation collapse into the **Immediate Result**: totals with the package
     adjustment line, a relative-zone bar, and one sentence plus the balance clause.
   - The War Room recommendation becomes the **Final Decision**: YES / NO / NOT ENOUGH EVIDENCE, confidence, primary
     reason, counterargument, and what would change it.
   - No other block may use verdict words.
   - Evidence: §4.2 row 1; KTC, FC and RW single sentence (U1).
2. **A receipt row** (format, team, board freshness, package model) sits above the Immediate Result. Evidence: U5.
3. **The package adjustment is a visible line item** in the side card, in plain words. Evidence: U2; IDPTC
   anti-pattern.
4. **Balancers live in the Immediate Result,** under the sentence, as one-tap chips.
   - Each chip shows its post-add gap.
   - A posture filter is pre-set from the inferred posture and is user-adjustable.
   - Evidence: U4; RW; our `findBalancers`.
5. **Controls move out of the header.**
   - Only Swap, Clear and Add team stay next to the builder.
   - Import (KTC URL / screenshot), Share, Copy KTC URL, CSV, JSON, value mode and Reset values go into one "Trade
     actions" menu.
   - "Simulate impact" is absorbed by the Final Decision, which already runs the analysis.
   - Evidence: KTC's two buttons; §4.2 control overload.
6. **Supporting Intelligence is a tabbed or sectioned area, not a stack of collapsed panels:** Value · Roster &
   lineup · Second opinions · Market & comparables · Risk · Reasoning.
   - Comparables and the per-asset trend get a summary strip that is visible without expanding (U10).
   - Evidence: KTC below-the-fold richness; DLF context pitch; our panels are currently collapsed.
7. **The URL reflects the trade** (U8), and restoring it reproduces the exact state.

### 6.2 Desktop (1024 px and up)

- **Two-column workspace.**
  - **Left (about 60%):** the builder (side cards; 2 sides side by side, 3–5 sides in a responsive grid), then
    Supporting Intelligence below.
  - **Right (about 40%, sticky):** receipt, then Immediate Result, then Final Decision.
- Why not KTC's single column: our decision content is too large to sit inline. Sticky keeps both answers on screen
  while editing, which no competitor does. This extends our existing 2-team tray to every side count.
- **Wide 2-team variant (1280 px and up, optional):** the Dynasty Nerds-style centre column (Side A | Result | Side B)
  can be evaluated against the measured layout in the UX audit. If adopted, the Decision block sits directly under the
  centre result. Evidence: U12.
- The verdict must be visible in the **first viewport after the first asset is added on each side**. That is the
  time-to-answer bar KTC, FC and RotoTrade meet (§3.3).

### 6.3 Mobile (below 768 px)

- **Builder first, as sheets.**
  - Each side is a compact card (asset rows with value and × to remove).
  - "Add asset" opens a bottom sheet with search, a picks shortcut (year → round → slot/tier, U7) and the team's
    roster when known.
  - The existing sticky quick-add folds into that sheet.
  - Evidence: KTC and RW stacked mobile; DDy's rail is the anti-pattern.
- **A persistent bottom verdict bar for every side count.**
  - It shows both totals (or the net for the user's team in 3+), the bar and the package verdict word, plus the
    decision badge once available.
  - Tapping it scrolls to the Result / Decision.
  - Evidence: KTC mobile summary row (03); our 2-team-only tray.
- **Contextual section navigation** (Result · Decision · Value · Roster · Market · Opinions · Advanced) appears as a
  horizontally scrollable chip row *inside* the page, not a fixed side rail. The page itself never scrolls
  horizontally (390 px check, as run on competitors here).
- **Touch targets of at least 44 px,** totals that never wrap into each other (DDy anti-pattern), and labelled inputs
  (IDPTC anti-pattern).

### 6.4 Explicitly unchanged

- Objective math, the package model and its q, the source votes, and the decision engine's ownership
  (`analyze_trade.py`): workstream rules.
- The private / login posture of `/trade`: owner-level, out of scope.
- Picks are never balancers; unpriced assets stay labelled, never zero.

---

## 7. Open items

| Item | Why open | Smallest next step |
|---|---|---|
| DynastyProcess live UX | App down (522) on 2026-10-17 | Retry once during TC-D. Methodology is already recorded. |
| Mobile capture for FantasyCalc and Draft Sharks | Automation did not complete those runs | Manual 390 px check if they become design references. |
| Gated tools (FantasyPros, DLF analyzer, Dynasty Nerds, PlayerProfiler, Sleeper, ESPN, Yahoo) | Login or paywall; not bypassed | Keep them as vendor claims; no action unless the owner provides legitimate access. |
| Our signed-in production UX | `/trade` is private | Covered by `TRADE_CALCULATOR_UX_AUDIT.md` (TC-0). |

```
STATUS: DONE
ACCEPTANCE: method and sources; per-competitor profiles with dated evidence; comparison matrix incl. Chase Upside;
  stronger/weaker with our code cited; patterns to adapt / features / anti-patterns with demonstrating competitor;
  desktop + mobile IA recommendations traced to evidence; screenshots ≤ 12, each ≤ 250 KB.
EVIDENCE: Playwright sessions 2026-10-17 (desktop 1366×900, mobile 390×844) on KTC, FantasyCalc, Dynasty Daddy,
  IDPTC, Draft Sharks, RotoTrade, RotoWire; balancer post-add checks on KTC and FantasyCalc; vendor FAQ and methodology
  pages; code reads at worktree HEAD 695fc26c37.
UNRESOLVED: DynastyProcess live UX (site down); FantasyCalc and Draft Sharks mobile captures; gated tools are vendor
  claims only (see §7). None of these block TC-0 acceptance for this deliverable.
BLOCKERS: none.
NEXT_ACTION: TC-D design consumes §6. TC-A consumes the relative-band finding (§4.2, §5.2). TC-B consumes U4, U7, U8
  and U10.
```
