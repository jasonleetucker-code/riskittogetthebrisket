# Scope coordination — owner records added while B2 was in flight

**Written on `claude/dynasty-audit-consolidation-e75vdy` at B2 HEAD, deliberately
WITHOUT merging refreshed `main`.** Nothing in this file was implemented. It exists
so that none of it is lost between the B2 checkpoint and the next planning /
integration checkpoint.

**Why no merge.** `main` has moved from `a5ff76b09` to `a76b6f37e` and takes
automated refresh commits every ~2h that rewrite the CSVs the Hill fit trains on.
Merging mid-experiment to obtain documents would break the pinned B2 baseline
(`dynasty_data_2026-08-11.json` sha256₁₆ `a495c049fa69f141`) that every B2 number
is measured against. **Any re-measurement of B1 / B1.1 / B1.2 / B2 numbers after
such a merge is invalid unless the inputs are re-pinned and champion and
challenger are re-measured together.** Do not quietly refresh a number across a
data change.

**The repo records are authoritative.** The issues and the documents named below
are the requirement text; this file is a manifest plus the binding rules that are
decisions rather than pointers. The owner does not need to restate any of it.

---

## 1. B2 status

B2 is **complete and stopped at its checkpoint** (see
`docs/master-site-audit/evidence/W02/B2_CURVE_ROUTING_EVIDENCE.md`). W02-F001
repaired at the root cause; W02-F002 / W02-F003 re-measured rather than
pre-fixed; full gates green; PR [#787](https://github.com/jasonleetucker-code/riskittogetthebrisket/pull/787).
Hill-model promotion remains **NOT AUTHORIZED**; nothing was promoted or applied.
None of the scope below was started.

## 2. Competitive expansion — CONFIRMED AUTHORITATIVE

`docs/OWNER_FEATURE_INVENTORY.md` **§12 Competitive expansion — OTC Fantasy +
Play For Keeps** is intact on this branch and remains authoritative future scope.
Verified present, all 17 identifiers: **CE-01 … CE-16 including CE-14A**
(CE-14A "Personal Rankings Overlay", §12 line 289, Tier 4). They are approved
features to be implemented eventually per their recorded dependencies and
staging. Not implemented during B2; **not deferred away, not omitted.**

`main` additionally carries a Dynasty Daddy competitor audit and implementation
addendum under `docs/competitive/` which adds approved future scope **CE-17 …
CE-21** and enriches several existing CE features. Those documents must be
preserved and integrated at the competitive-reconciliation checkpoint. No
Dynasty-Daddy-derived CE work during B2.

The still-pending OTC / PFK competitive reconciliation documents and the
phase/dependency integration must be completed **before** CE production
implementation begins.

## 3. Immediate product items — next safe product-hotfix checkpoint

Authoritative: `docs/OWNER_REQUESTED_TODO.md` + the issues.

| # | item |
|---|---|
| 779 | `/admin` crashes — `fmtPassExpiry` undefined |
| 780 | repair and verify the existing configurable-hours temporary-password generator end to end |
| 781 | Trade Calculator manual value edits must be **visually silent** — no yellow edited state, no per-player override marker; one top-level **Reset Values** action; removing and re-adding an edited asset restores its canonical value |

Handle at the next safe product-hotfix checkpoint. Do not mix into an isolated
root-cause pass unless one directly blocks that pass's verification.

## 4. Owner feature addendum — `docs/OWNER_FEATURE_ADDENDUM_2026-08-11.md`

Binding; issues #782–#786. Must be reconciled into the authoritative feature
inventory and dependency plan and must not be lost.

**#782 — YouTube Dynasty Intelligence.** A major ingestion pipeline parallel to
Podcast Intelligence: ~50 researched reputable dynasty YouTube sources, current
video ingestion, reusing the canonical source/analyst identity, transcript
acquisition, take extraction, NO-SIGNAL semantics, independence/correlation
handling, freshness and provenance architecture. Feeds the same downstream
ecosystem (Consensus Edge / bounded intelligence, canonical Buy/Sell
reconciliation, player profiles, selected-team intelligence, news / Analyst
Pulse, buy/sell analysis, the personalized weekly brief).
**Binding constraints:** explicitly dedupe/exclude YouTube representations
already covered by the Podcast Intelligence registry — a podcast episode
uploaded to YouTube must not become a second independent opinion; and **do not
create a second Consensus Edge or ranking engine.**

**#783 — Unified Player Profile Intelligence.** The Universal Player Profile
carries a player-specific intelligence/news feed drawn from Podcast
Intelligence, future YouTube Intelligence, Sleeper news, RotoWire, RotoBaller
and every other canonical ingested source. Presentation may be short attributed
excerpts, source cards/summaries, a synthesized recent-intelligence summary, or
a hybrid — whichever is most useful.
**Binding constraints:** factual news and analyst opinion stay visibly distinct;
every item and summary carries source, as-of/publication time and provenance and
stays traceable to supporting evidence; syndicated/reposted material is deduped
and analyst/network independence preserved; **do not dump full copyrighted
articles or transcripts onto player pages**; build **one** canonical
player-intelligence feed/service, not one feed per provider.

**#784 — Homepage Consensus Edge / Buy-Sell ticker.** A horizontally moving
stock-market-style ticker of current actionable buy/sell intelligence, with
freshness, click-through to player intelligence, and appropriate
touch/keyboard/screen-reader/reduced-motion behavior.
**Binding constraints:** BUY items may come from the broader player universe;
**SELL items may ONLY include players currently rostered by the selected fantasy
team**; the ticker is a **presentation surface, not an independent signal
algorithm** — reconcile it with the planned Central Buy/Sell Tracker and the
current Consensus Edge architecture so the frontend does not invent another
threshold set or a circular signal.

**#785 — Two-TE / tight-end-premium valuation audit.** A model-quality
requirement, **not** a request to boost tight ends. Reuse the existing
`src/league_intel/te_premium.py` foundation rather than creating another TEP
engine. Derive the actual two-mandatory-TE roster demand, FLEX/SF eligibility
and exact scoring from canonical league settings; quantify TE production against
WR/RB under this exact league; inventory every source's TE basis (base / TEP /
TE++ / other) and which version we ingest; where a source publishes both
standard and TEP boards, **measure the actual player- and rank-dependent uplift
instead of assuming a blanket multiplier**; re-measure KTC base→TE-premium
behavior from fresh legitimate data, using KTC as a **diagnostic market
baseline, not an automatic truth target**; verify elite / mid / starter / TE2 /
fringe / deep ranges; prevent double counting — **source alignment and league
demand are separate axes and native TEP sources must not receive a second
premium**; compare against WR/RB/QB and league-specific
replacement/scarcity/realized-scoring evidence; run a **whole-tree search for
stale 1.15 factors, old TEP flags, duplicate multipliers, UI/config defaults and
bypass paths**, with every surviving multiplier justified, reconciled or
removed. **Success condition: evidence that our TE values are correct for this
actual two-TE league — not merely closer to KTC.** Schedule at the appropriate
Phase-B / league-value checkpoint.

**#786 — Trade Simulator NFL-team exposure.** Before/after NFL-team exposure on
Simulate Impact. Primary exposure is **canonical-value-weighted, not raw player
count**; show each materially affected team as before % → after % with
percentage-point change (raw count secondary); use exact before/after roster
states after applying the transaction; **draft picks normally have no NFL-team
exposure and must not be assigned one artificially**; missing/unpriced players
stay explicit rather than silently becoming zero. **Informational only** — it
must not affect trade grade, package adjustment, Team Strength or Buy/Sell
unless the owner later explicitly authorizes concentration as a decision input.
Build **one reusable exposure primitive shared with CE-06 Dynasty Portfolio**,
not separate Trade Calculator and Portfolio formulas.

## 5. Longer-horizon owner scope

**#788 — Dynasty Analyst X feed. LONG-TERM / COST-GATED ONLY.** The owner likes
the concept of a curated ~500-analyst dynasty X feed, but current recurring X API
economics are too expensive for the present small/private site. **Do not
implement now.** Preserve for reconsideration if API economics improve or usage /
revenue justify the cost. Official API / authorized integration only; **no
scraping.**

**#789 — CE-20 Game Day Command Center. Approved real planned product scope**,
not an optional dashboard. Integrate into the authoritative inventory,
dependency graph and execution plan at the next planning-reconciliation
checkpoint; do not implement during B2.

Central requirement: the Game Day system must **outperform generic Sleeper
matchup prediction for this league by correctly modeling both the exact custom
scoring system and the actual best-ball lineup rules.**

- The canonical matchup projection / win-probability engine **must not treat
  current starters or provisionally filled slots as final.** Every still-eligible
  rostered player who could displace another score stays in the outcome model,
  and each simulated outcome **resolves the final legal best-ball lineup using
  the canonical lineup/assignment semantics** rather than adding projections to a
  fixed starter list.
- Weekly projections convert through the league's **complete** scoring system.
  Audit every legitimate weekly projection source the repo has or can afford —
  raw stat fields, offense/IDP coverage, cadence, archives, licensing — before
  implementation.
- For scoring components vendors do not project (first downs, reception /
  catch-distance bands, big-play bonuses, unusual IDP subevents, other custom
  rules): **do not silently assign zero and do not guess blanket multipliers.**
  Build defensible derived-stat distributions from historical
  player/team/role/opponent information, carry uncertainty/confidence, and
  validate the derived components against actual outcomes.
- Pregame output: projected best-ball final scores, uncertainty distributions,
  win probability, player/slot contribution probabilities, expected
  contributions, highest-leverage swing players.
- Live output: continually condition on completed / in-progress / not-yet-started
  players, banked points, injuries and inactives where available, remaining
  outcome distributions and all still-possible best-ball displacements;
  recompute projected final score, win probability, likely final best-ball
  lineup, remaining upside/downside and the rooting/leverage guide as the week
  progresses.
- **Prediction accuracy is a product requirement.** Archive timestamped pregame
  and in-game forecasts; backtest final-score error, best-ball lineup prediction,
  uncertainty calibration and win probability with defensible metrics (MAE/RMSE,
  Brier, log loss where appropriate, reliability/calibration curves). **No
  temporal leakage.** Benchmark against Sleeper where practical; **do not copy
  Sleeper methodology.**
- UX (previously approved): Sunday console — current score, projected final,
  win probability, players/games remaining, personalized owner/opponent event
  stream, high-leverage panels, injury/status/news context, rooting guide,
  late-Sunday/Monday "what do I need?" analysis, mobile
  *For You | Matchup | Players | Games | News*, and a desktop/tablet TV mode
  meant to sit open beside a television.
- Differentiator: custom-scoring explanation — how an actual play generated
  fantasy points under this league's scoring. **If V1 data cannot support
  play-level decomposition honestly, do not fake it**; keep the architecture
  ready for a later paid-data enhancement.
- **Cost rule:** V1 must be genuinely useful **without** a paid real-time
  play-by-play contract. Low-cost/existing matchup state, weekly projections,
  canonical scoring, best-ball simulation, news/status feeds and responsible
  caching/polling first. Commercial second-by-second play-by-play is a later
  enhancement only if real usage proves the recurring cost.
- CE-20 is a **consumer/orchestrator of canonical systems, not another set of
  formulas in the frontend.** One reusable matchup projection / win-probability
  owner consuming canonical player identity, league scoring, best-ball
  assignment, projections and news/intelligence.
- Dependency order: scoring correctness → canonical best-ball assignment →
  projection-source audit → custom-stat projection layer → prediction
  snapshot/history → calibrated matchup simulation / win probability → low-cost
  live refresh → Game Day UI → optional paid play-by-play later.

> *Sleeper shows the matchup. Our Game Day Command Center models the actual
> best-ball outcome under the exact custom scoring system, continuously updates
> the outcome distribution, explains what is driving it, and tells the owner what
> matters next.*

## 6. Trade methodology — owner decision, binding

Authoritative: `docs/trade/TRADE_DECISION_SYNTHESIS_PLAN_2026-08-11.md`,
`docs/trade/MC_AUDIT_TODO.md`, `docs/trade/SECOND_OPINIONS_TODO.md`,
`docs/trade/ANALYZE_TRADE_TODO.md`,
`docs/trade/CURRENT_HEAD_MC_FINDINGS_2026-08-11.md`, issues #790–#792.

**Current owner decision: KEEP exact KTC Value Adjustment. Build the deeper
canonical roster/package decision architecture AROUND it, not by pretending KTC
has already been replaced.**

**6.1 We have NOT established a proprietary VA superior to KTC.** `src/trade/ktc_va.py`
and its frontend counterpart exist to reproduce KTC's package-adjustment
behavior, and KTC parity is a useful market benchmark and an owner-facing lens.
Therefore: keep exact KTC VA available; preserve its parity semantics exactly;
**do not silently improve, clamp, normalize or monotonicize KTC behavior while
labeling it KTC**; preserve known KTC non-monotonicity in parity mode if that is
genuinely what KTC does; label it clearly as a KTC / market-consolidation lens;
**do not describe our canonical methodology as "better than KTC" unless evidence
establishes it**; do not remove KTC VA from the Trade Calculator or a future
Trade Desk without explicit owner approval.

This supersedes any reading of "canonical package methodology" as "we already
built a better KTC VA".

**6.2 The canonical methodology is a different question** — what a transaction
does to *this exact team's* roster and asset portfolio after outgoing assets are
removed, incoming added, the roster reranked, Top-N groups changed, weaknesses
changed, depth changed and future assets incorporated. It requires the approved
canonical player and pick values, package-generation owner, Team Strength, Team
Weakness, before → apply → rerank → after simulation, promotions and
displacements, positional construction, future-asset/pick context and
missing/unpriced handling. **Do not equate it with a second KTC-style scalar.**
**The existing shallow/heuristic roster-impact implementation must not become
canonical merely because it currently emits a verdict.**

**6.3 Do not invent an "Our VA" just to have a second number.** The preferred
architecture may be: canonical asset/package equity + exact KTC VA as a market
lens + canonical roster marginal impact + uncertainty/risk + independent market
corroboration = Analyze Trade recommendation. If a proprietary package
adjustment is ever proposed it needs a defined target and must earn its place
through evidence across at minimum 1-for-1, 2-for-1, 3-for-1, 4+-asset packages,
elite consolidation, elite breakup, player+pick, pick-heavy, offense, IDP, mixed,
near-equal, highly imbalanced and pathological/non-monotonic cases — benchmarked
against exact KTC VA, canonical raw values, contemporaneous real-market trade
evidence, actual package behavior on the site's leagues and downstream roster
marginal impact. **Do not tune until hand-picked examples look right. No temporal
leakage.**

**6.4 #790 — re-audit Monte Carlo against current HEAD.** Treat it as needing a
fresh methodology audit, not as correct because historical findings were closed.
Trace the whole current path (trade row → `effectiveValue` → request payload →
`TradePlayer` → p10/p50/p90 → package adjustment → correlation → simulation →
symmetry/enrichment → UI) and verify the MC center receives every relevant
upstream value **exactly once**: canonical value, TE-premium treatment,
legitimately-canonical IDP adjustments, future-pick discount, manual overrides,
current package-adjustment semantics. **Explicitly determine which package
adjustment the MC uses; if it is KTC VA, label the result accordingly and do not
let a KTC-adjusted MC masquerade as an independent canonical conclusion.**
Revalidate mean preservation, side-swap symmetry, ties, seed reproducibility,
convergence/error, 1–9999 endpoints, correlation assumptions and uncertainty-band
provenance. **Remeasure the historic ±15% synthetic uncertainty fallback on
current data and never call synthetic uncertainty "measured source
disagreement".** Investigate defensible player-specific uncertainty (normalized
source spread, coverage/confidence, historical value movement, source
disagreement, asset class, other justified predictors) and **handle source
correlation — fourteen source rows are not fourteen independent observations.**
Do not change the model merely because MC often favors the higher-centered side;
with similarly shaped distributions that is expected.

**6.5 #791 — quick Second Opinions summary.** A one-glance line above the
detailed table, conceptually *Side A 5 · Side B 3 · Even 1 · Incomplete 2*.
**Count once per genuinely independent vendor/network, not per sub-board.** **Do
not count a vendor as an independent vote if missing assets were filled with our
own canonical value** — native and imputed coverage stay distinguishable, and a
vendor with material missing native coverage is PARTIAL / INCOMPLETE rather than
silently becoming a vote partly generated by our own model. Reuse the existing
per-vendor infrastructure; do not create another source-value engine.

**6.6 #792 — canonical Analyze Trade.** Deliberate **Analyze Trade** action from
the selected team's perspective, graded **MAKE THE TRADE / LEAN MAKE / TOO CLOSE
· DEPENDS / LEAN PASS / PASS**, returning confidence, strongest reasons for,
strongest reasons against, important uncertainty, meaningful model/source
disagreement and optionally "what would change the answer".

**6.7 Do not double count the same evidence.** The visible Trade Calculator
panels are **not independent voters**: canonical value already incorporates many
external sources; Second Opinions exposes those same sources individually; Monte
Carlo is centered on canonical value; KTC VA can already influence multiple
displays; roster impact re-uses canonical player values. **A weighted blend such
as 25% canonical + 20% Second Opinions + 20% MC + 15% KTC VA + 20% roster impact
is prohibited without lineage analysis** — it would count the same evidence
repeatedly and manufacture confidence. Organize instead around unique
information dimensions: canonical economic value; market corroboration /
disagreement from genuinely independent markets; uncertainty/risk (**Monte Carlo
should generally modify confidence/risk rather than become another vote for the
same p50**); roster marginal impact via true before → remove outgoing → add
incoming → rerank → recompute Top-N → measure promotions/displacements →
recompute weaknesses → after (**draft picks contribute zero current Team
Strength but retain future/asset value**); future/window context only where its
canonical methodology is trustworthy; and additional intelligence (trade comps,
Sharp, Insider, Consensus Edge, news, podcast/YouTube, manager intelligence)
only where genuinely incremental.

**6.8 KTC is a benchmark, not an enemy.** The objective is not to prove we are
smarter than KTC. When a canonical conclusion differs materially, explain why —
different underlying player values, exact league scoring, roster composition,
Team Strength displacement, positional weakness, future assets, or another
independently justified reason. A good UI may show canonical value, KTC market
adjustment, roster impact, external market split, uncertainty and the final
recommendation **without pretending these are independent votes.**

**6.9 Governance.** No "better than KTC" claim without measured evidence. No
promotion of current `team_impact` heuristics to canonical status merely because
the code exists. No duplicate value / package / Team Strength / Team Weakness /
source-consensus / Analyze-Trade engines. `/trade` and a future CE-05 Trade Desk
must consume the same canonical decision contract. **Missing information stays
missing / partial / insufficient rather than silently becoming zero.** Do not
begin a proprietary "Our VA" implementation without a separate evidence-backed
design checkpoint.

## 7. Integration checklist for the next planning checkpoint

1. Merge refreshed `main` into the branch (or rebase per repo convention) and
   **preserve every document listed here** — `docs/OWNER_REQUESTED_TODO.md`,
   `docs/OWNER_FEATURE_ADDENDUM_2026-08-11.md`, `docs/competitive/*`,
   `docs/trade/*`, `docs/OWNER_FEATURE_INVENTORY.md` §12.
2. Re-pin model inputs before any further B1/B2 measurement; champion and
   challenger re-measured together or not at all.
3. Reconcile into **one** canonical owner feature inventory, duplicate-risk map,
   canonical-owner map, dependency graph and phase plan: CE-01…CE-16 + CE-14A,
   CE-17…CE-21 (Dynasty Daddy), CE-20 elevated by #789, the addendum #782–#786,
   the trade items #790–#792, #788 as cost-gated, and #779–#781 as product
   hotfixes.
4. Reconcile the KTC clarification (§6 above) against
   `docs/OWNER_FEATURE_INVENTORY.md` item **2.2 Package Adjustment** and item
   **1.3 Roster-aware trade simulation**, explicitly distinguishing KTC parity,
   canonical package equity and canonical roster impact.
5. Report every existing duplicate package-adjustment implementation and the
   intended consolidation path.
6. **Do not silently omit or downgrade any owner-approved requirement.**
