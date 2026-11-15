# Forced-drop fix — verdict-change analysis (LOCAL replay, not production)

**Status:** evidence summary for the owner's activation decision on `forced_drop_cheapest_legal` (default **OFF**;
nothing here changes what is served). Linked from [`FORCED_DROP_FIX_2026-10-20.md`](FORCED_DROP_FIX_2026-10-20.md) (§8,
§10 item 2). Machine-readable aggregates:
[`evidence/forced_drop_fix_2026-10-20/verdict_change_analysis.json`](evidence/forced_drop_fix_2026-10-20/verdict_change_analysis.json).

> **LOCAL replay, NOT the production-box replay.** Scarcity resolves inert (1.0) locally, Component B (the roster
> utility lens) abstains for lack of a projection snapshot, and posture is unknown for some teams. Every number below
> is Component A + feasibility + posture on one board. The box replay
> ([`FORCED_DROP_BOX_REPLAY_RUNBOOK_2026-10-21.md`](FORCED_DROP_BOX_REPLAY_RUNBOOK_2026-10-21.md)) has **not been run**
> and needs owner authorization. Aggregate counts and statistics only: no league, user, roster, transaction, team or
> manager identifiers (NFL player names are used in the two illustrations).

**Pins.** Code `f7b72d709` (before the independent-review fixes F1–F8; see §9), archive
`dynasty_export_20261020_052241`, CSV tree `d5236546f`, built-board hash `eed8df11…`, `fairness_bands_v2`,
`geom_q078_v1`. Designs: **War Room** (WR) 45 sampled trades × k = 0..3 fillers = 180 steps (135 at the 58 cap needing a
cut); **Census** 278 seeded 1-for-2 / 2-for-1 / 1-for-3 trades over all 12 rosters (166 at or under the cap needing a
cut); **EXT** 284 extra-shape trades (2-for-3, 3-for-2, 1-for-4, pick-for-2), *not* one of the owner's designs, used for
the overstatement and sensitivity checks only. "Category" is `team_verdicts.team_category` applied to the **private**
War Room decision, as in the record's §8. V5 = the shipped default (package-consistent), V5-R = the alternative
(roster-rational); both are reported, the owner's V5-vs-V5-R decision is separate (record §3a).

## 1. How large is the incumbent's charge?

| (trades that need a cut) | War Room | Census |
|---|---:|---:|
| incumbent median forced-release charge | 3,128 | 2,156 |
| … as a share of the fairness band base | 54.5% | 60.0% |
| incumbent charge exceeds the **whole** package gap (net negative) | 130 of 135 | 159 of 166 |
| flag-ON median charge (V5 · V5-R) | 873 · 873 | 468 · 468 |
| … as a share of the band base (V5) | 17.1% | 13.5% |
| median absolute charge change, as a share of the band base (p10 – p90) | 38.9% (24.1 – 63.8) | 46.9% (20.8 – 72.4) |

The band edges on that base are slight 3.5%, unfair 9%, lopsided 18%: the typical change is two to three times the
lopsided edge. This is why 105–127 category changes is not a surprise: a charge that large decided the verdict for
the great majority of full-roster trades with a cut.

## 2. Where the change comes from (Census, V5, total charge change −282,481 over 174 changed trades)

| component | sum | share of total | trades |
|---|---:|---:|---:|
| **selection**: cheapest legal cut instead of the first name among cost-tied sub-waiver players | −144,576 | 51% | 158 |
| **unpriced displaced**: the unpriced cut (charged at the 1,918 – 2,156 waiver ceiling) is no longer the cut | −136,416 | 48% | 61 |
| over-cap roster now charged the marginal cleanup (incumbent charged 0) | +12,568 | −4.4% (raises the charge) | 15 |
| charge basis: an acquired cut charged its package credit forgone, not its full value | −7,474 | 2.6% | 34 |
| V5 currency: selection in package-credit units (V5 cut set vs V5-R cut set) | −6,583 | 2.3% | 36 |

The first two sum to ~99% and are order-dependent (both are "the incumbent picked an expensive cut"); War Room V5 is
51.3% / 38.6% / 3.0% / 7.1% (selection / unpriced / basis / currency; no over-cap trade there). **Selection alone**
(the cheapest legal cut at the incumbent's own charge, no package netting) reproduces **86% – 97%** of the median
shift (War Room −1,838 of −2,131 V5 and −1,888 V5-R; Census −1,602 of −1,691 and −1,664). The selection step is exact:
on all 174 changed Census trades the selected set equals the true minimum over every lineup-legal subset (132 needing
one release, 42 needing two; `d ≥ 3` was not brute-forced in this analysis, the unit tests do so up to `d = 4`). **The
flag never raised the charge at or under the cap**; all 15 increases are over-cap rosters (the marginal-cleanup
extension, §4 class D).

## 3. What the change in category is made of

| (category changes vs flag OFF) | WR V5 | WR V5-R | Census V5 | Census V5-R |
|---|---:|---:|---:|---:|
| total | 109 | 105 | 125 | 127 |
| of which the evidence gate lifted (UNAVAILABLE → decided) | 49 | 49 | 54 | 54 |
| decided → decided | 60 | 56 | 71 | 73 |

Gate lifts are 43–47% of the changes: the `forced_drop_unpriced` gap disappears because the unpriced player is no
longer the cut (49 War Room steps, 61 Census trades; on 7 of them `stale_values` remains and still withholds the
headline). Every decided → decided move is toward the more favourable category except the over-cap policy cases (2
Census V5, 4 V5-R): `UNFAVORABLE → FAVORABLE` 51/44/52/49, `UNFAVORABLE → APPROXIMATELY EVEN` 8/11/16/19, plus the
unavailable-to-decided families listed in the record's §8.

## 4. Clear correction vs modelling assumption vs sensitivity

Each changed category is assigned to exactly one class by replaying it with the cause isolated:

* **A — clear correction.** The cheapest legal cut at the incumbent's own charge (selection alone, no package netting,
  no V5 currency) reproduces the flag-ON category, and it is the same under the seven scarcity / waiver-anchor
  scenarios of §8 (the base and six scarcity / waiver-anchor scenarios).
* **B — modelling assumption.** The category depends on charging a received-and-released piece its package credit
  forgone (all modes) or on V5's mixed-currency selection (V5 only): selection alone gives another category.
* **C — scarcity / anchor sensitive.** The flag-ON category differs across the seven scenarios.
* **D — over-cap policy extension.** The incumbent charged 0 for an already-over-limit roster; the flag charges the
  marginal cleanup. This *raises* a charge and is a policy extension, not a correction of an over-charge.

| class | WR V5 | WR V5-R | Census V5 | Census V5-R |
|---|---:|---:|---:|---:|
| A clear correction | **71** | **66** | **98** | **92** |
| B modelling assumption | 26 | 5 | 11 | 5 |
| C scarcity / anchor sensitive | 12 | 34 | 14 | 26 |
| D over-cap policy | 0 | 0 | 2 | 4 |
| total | 109 | 105 | 125 | 127 |

Two cautions the table does not carry. (1) **Class A depends on the cheap tail being real.** Under the
single-source stress variant of §8 (every single-source player treated as unpriced, i.e. charged at the waiver ceiling),
59 of the 71 War Room V5 class-A changes and 81 of the 98 Census V5 class-A changes land in a different category.
(2) V5 puts 26 / 11 changes in class B (V5-R 5 / 5) — the V5/V5-R choice is mostly a choice about class B and C.

Illustration of an A-class change (NFL players only): a team at the cap sends Aidan Hutchinson (DL 4,737) for Jordyn
Tyson (WR 4,587) + Dohnte Meyers (WR 1,506). The incumbent cuts Aaron Donald (DL, unpriced, charged the 1,918 DL
waiver ceiling): net −893, headline withheld (`forced_drop_unpriced`). The cheapest legal cut is Quan Martin (DB, 227):
net +798, YES / FAVORABLE in V5, V5-R and the full-value benchmark alike. A B/C-class illustration is a 1-for-4 into
the same roster: V5 releases two just-received players at their package credit (716 / 786) and keeps two existing
players valued 1,197 / 1,223 (net +798, FAVORABLE); V5-R and the full-value benchmark cut the existing pair (net −120,
APPROXIMATELY EVEN). That 918-point swing is the package depth discount, not roster information.

## 5. Who is affected

* **Private, team-aware surfaces only** (War Room / Trade Calculator, Trade Finder, Best Offers). The public advisor is
  unaffected by construction.
* **Receivers whose roster is full** and who take back more players than they send. 181 of the 278 Census trades
  require a release; all 159 charge decreases are at or under the cap. The deeper the incoming package the larger the
  change (§6).
* **All 15 charge increases are one over-cap roster** (the incumbent charged nothing for any trade from an
  over-limit roster; the flag charges the marginal cleanup). Class D: 2 / 4 category changes, to be accepted or
  rejected as a policy, not as a correction.
* A receiver with a thin cheap tail is affected most: the cheap legal cuts are single-source values of 226 – 440, and
  the unpriced cuts the incumbent used are charged 1,918 – 2,156.

## 6. Headline and confidence effects

| (stated both with the flag OFF and ON) | War Room | Census |
|---|---:|---:|
| decision confidence level changed | **0** of 108 | **0** of 183 |
| confidence null → MEDIUM (exactly the gate lifts) | 49 | 54 |
| confidence stated → withheld | 0 | 0 |
| asset-evidence / coverage axis changed | 0 | 0 |
| **margin** axis changed (HIGH → MEDIUM) | 33 – 34 | 30 – 34 |
| "tied cut" uncertainty note on the packet | 90 → 0 | 94 → 0 |
| packet recommendation or confidence changed | 0 | 0 |
| new evidence gap introduced by the flag, any trade (180 + 278 + 284 = 742) | **0** | **0** |

The confidence effects are limited to a decision that was withheld now having a stated level and the margin axis
re-reading the changed net. The flag never adds an evidence gap.

## 7. Overstatement test: does package netting flatter the receiver?

The V5/V5-R charge nets a released just-received piece out of the package (charging the credit forgone, 22% – 52% below
the piece's value for a package's later pieces: credit ÷ value is 0.78 for the 2nd of two, 0.61 for the 3rd of three,
0.475 for the 4th of four) instead of its full value. If the geometric depth discount does not describe the real cost of
a roster spot, the receiver's net is overstated by exactly that gap. Measured against charging every cut at full value
over 523 trades (Census 181 + EXT 207 + War Room 135, all that need a cut):

| | V5-R | V5 |
|---|---:|---:|
| trades that release a just-received piece | 113 | 245 |
| mean net overstatement, all 523 trades | **+65** (median 0, max 1,091) | **+159** (median 0, max 1,106) |
| … 4-piece receiving packages (115 trades) | +185 | +504 (p90 20% of the band base, max 27.8%) |
| … 1-for-2 packages (131) · 1-for-3 (140) | +3 · +64 | +7 · +133 |
| trades one category **higher** than the full-value benchmark | 36 | 79 |
| trades one category **lower** | **0** | **0** |

V5's overstatement is 2.4× V5-R's (V5 also selects in credit units, §3a). It is concentrated in three- and four-piece
receiving packages, is never in the unfavourable direction, and is at most one category. It is the quantified price of
accepting the package model's discount inside a roster-spot calculation; V5-R roughly quarters it.

## 8. Scarcity and anchor sensitivity, and the reverse-anomaly argument

Eight scenarios, injected locally (`ScarcityComponents`, waiver anchors): the base; uniform scarcity 0.85 and 1.15; two
IDP/offense mixes (IDP 0.85 / offense 1.15 and the reverse); waiver anchors ±15%; and the **single-source stress**
(every single-source player treated as unpriced).

| category changes vs OFF (WR V5 · V5-R \| Census V5 · V5-R) | |
|---|---|
| base | 109 · 105 \| 125 · 127 |
| scarcity 0.85 uniform | 111 · 109 \| 123 · 123 |
| scarcity 1.15 uniform | 109 · 105 \| 129 · 127 |
| IDP 0.85 / offense 1.15 | 112 · 108 \| 125 · 130 |
| IDP 1.15 / offense 0.85 | 109 · 107 \| 128 · 127 |
| waiver anchor +15% | 109 · 105 \| 125 · 127 |
| waiver anchor −15% | 104 · 100 \| 126 · 127 |
| single-source stress | 100 · 95 \| 128 · 122 |

* The count is stable (95 – 112 War Room, 122 – 130 Census) in every scenario including the stress. The *composition*
  is not: V5 forward anomalies vary 41 – 53 (War Room) and 24 – 42 (Census) across the seven non-stress scenarios (95 /
  123 in the stress); V5-R is invariant to uniform scarcity.
* **The sign mix hinges on the cheap tail.** Under the stress variant the Census V5 trades ending FAVORABLE fall from
  111 to 12 (War Room 102 to 15): the single-source 226 – 440 values *are* what turns most verdicts favourable. If
  those values are not real, the flag mostly moves verdicts from withheld to UNFAVORABLE / APPROXIMATELY EVEN instead of
  FAVORABLE. This is the dominant uncertainty and only the production data can bear on it.
* **Reverse anomalies were 0 in all eight scenarios, both modes** (an existing player released while a cheaper-by-`c`
  acquired piece is kept). The structural reason: a reverse anomaly needs a kept acquired piece whose package credit
  exceeds its own `c`. For every piece ranked second or later in the package, provided the trade sends at least one priced asset (if the priced sending side is empty the package model gives no adjustment and every incoming piece's credit equals its full value, ratio 1.0, so even non-top pieces are not excluded when the scarcity multiplier is below 1; the replay's trades always send something), credit ÷ value is at most 0.782 (second of two
  0.778 – 0.782; third of three 0.61; fourth of four 0.475), below the smallest scarcity multiplier 0.85. **This is
  structural only for those pieces.** The top-ranked piece's ratio reaches 0.99 (two pieces), 0.94 (three) and 0.88 (four) — above 0.85 in each
  — and is 1.0 – 1.24 for a sole incoming piece, above `c` whenever the multiplier is lower than the ratio; there it is not
  structurally excluded (the record's review fix F4 now clamps the sole / kept-side-empty case at `c`). The box replay,
  with real multipliers, must count both directions and is the only test of the top-piece case.

## 9. What was and was not re-measured after the review fixes

The independent review's fixes F1–F8 (record §3, §3a, §9) changed no served-flag-OFF byte. Re-running
`scripts/forced_drop_fix_replay.py --csv-rev d5236546f` on the fixed branch (War Room + Census + Perfect Draft; the
Finder step was skipped for time) reproduces the committed `replay.json` aggregates **exactly** (zero differing
values: 109 / 105 and 125 / 127 category changes, anomaly censuses, V5-vs-V5-R, Perfect Draft 11 of 11). The
analysis tables above were derived at `f7b72d709` and were **not** re-derived; they are unchanged only to the extent
that the replay aggregates they are built from are.

## 10. Unresolved

1. **The production-box replay** (real scarcity, Component B voting, real posture, the full Finder) has not been run;
   it needs owner authorization ([runbook](FORCED_DROP_BOX_REPLAY_RUNBOOK_2026-10-21.md)).
2. **The true cost of the cheap tail** — are the single-source 226 – 440 values real? Class A, the favourable sign mix
   and every "net becomes positive" claim depend on it (§4 caution 1, §8).
3. **V5 versus V5-R** — an owner decision (record §3a); this analysis shows it matters for 26 / 11 (V5) against 5 / 5
   (V5-R) class-B changes and for 2.4× the overstatement of §7.
4. **Whether the package credit forgone is the right price of releasing a just-received piece** (class B; the
   modelling assumption behind both modes).
5. **Acceptance of the over-cap charging extension** (class D; 15 Census charge increases, one roster).
6. **Brute-force verification for `d ≥ 3`** on real rosters (done for `d ≤ 2` here; unit tests cover `d ≤ 4`).
7. The verdict-change tables were not re-derived after F1–F8 (§9); the analysis' segmentation view is intentionally not
   committed.
