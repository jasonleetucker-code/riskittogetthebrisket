# Low-value-asset research — preregistration (frozen 2026-10-20, before any confirmatory evaluation)

**Authority.** Owner directive 2026-10-20 (`docs/owner/LOW_VALUE_ASSET_RESEARCH_2026-10-20.md`).

**What is unchanged.** Research and isolated shadow experiments only. `geom_q078_v1` (q = 0.78), the canonical
values, the source weights, the fairness classification, every recommendation and the public calculator's
methodology are all unchanged. Phase 3's evidence and its frozen conclusions are preserved
(`../package_model_phase3_2026-10-20/`).

**Freeze rule.** This document and `scripts/low_value_asset_treatments.py` at the commit that adds this file
define the protocol. Any later change is a dated amendment at the bottom.

**What counts as confirmatory.** The confirmatory evidence is:
- the box run described in §5;
- the prospective population after 2026-10-20.

Everything run locally before that is **exploratory**:
- the lineup-utility lane;
- the value-dynamics lane;
- the shadow replay;
- the filler-flip study.

The criteria below were written before any of those lanes reported results.

Agent-OS-Receipt: cb64f74cf4d2763aa16d55ba0d6350f585a2a42f

## 1. Competing hypotheses

- **H-A, canonical value curve.** Low-value assets are over-valued **as holdings**. Their canonical value exceeds
  what they deliver in lineup utility and in future value, so the low end of the scale is miscalibrated
  everywhere: rankings, 1-for-1 trades and packages.
- **H-B, trade currency.** Low-value assets are valued correctly as holdings. As **extra pieces in a package**,
  however, they buy less than their value, because the receiver must find roster room and rarely starts them.
  Only package (n > 1 side) trades are affected; 1-for-1 trades are not.
  - **H-B0, already covered.** The existing Team Context, forced-drop and replacement logic already prices this
    on the team-aware surfaces. A further adjustment there would double-count.
- **H-C, convention only.** The Phase 3 market discount is a trading convention, not a utility fact. A
  low-value asset that is usable depth is worth roughly its value. The market discount should be disclosed,
  not applied.

These hypotheses are not exclusive. The recommendation (§6) may combine them, for example "B on context-free
surfaces, H-B0 on team-aware ones".

## 2. Treatments (frozen in `scripts/low_value_asset_treatments.py`)

**Currency curve.** `g(v; c) = v² / (v + c)`. It is smooth and has no threshold.

**Treatments:**

| treatment | form | changes 1-for-1 trades? |
|---|---|---|
| GEOM_78 | the incumbent | no |
| A_curve_{market, replacement} | every asset passes through `g`, then the incumbent shape | **yes** |
| B_currency_{market, replacement} | `U(S) = max_j [v_j + OWA_0.78(g(v_k; c_k) : k ≠ j)]` | no |
| C_informational | GEOM_78 numbers, plus a disclosure whenever B_currency_replacement would change the fairness level | no |

**Anchors:**

| anchor | definition | role |
|---|---|---|
| market | c = 2,000, the Phase 3 market level | a comparator only, not a presumption |
| replacement (primary) | c_pos = the league's own **waiver value at that position**: `src/draft/displacement.waiver_values_by_position`, the best unrostered `rankDerivedValue`, on the newest board for `dynasty_main`. This is the same quantity the cut ladder and forced-drop cost already use. `*` (unknown position, and picks) = the league-wide FAAB `V_repl` (`src/trade/faab_engine.resolve_anchors`). | primary |

The replacement anchor values used in every run are written into each evidence file.

## 3. Asset classification (no single global threshold)

| class | definition |
|---|---|
| genuine starter | in the canonical optimal lineup of a `dynasty_main` roster; for an unrostered or external asset, value at or above the lowest starter value at its position across the 12 optimal lineups |
| usable depth | not a starter, and value at or above its position's replacement anchor |
| expendable filler | value below its position's replacement anchor |

Picks are classified by value against `*`. Rookie picks are reported separately and never pooled with players.

## 4. Exploratory evidence lines (local)

| line | question | supports |
|---|---|---|
| U: lineup utility | Do low-value players start in `dynasty_main` (2026 weeks 1–6)? What marginal lineup points do they add over the best bench alternative, by class and band? | H-A if low-value *usable depth* still contributes little relative to its value; against H-A if it contributes in proportion |
| D: value dynamics | Do low-band canonical values decay or mean-revert faster than mid and high bands, on our pipeline (a sensitivity replay) **and** on raw vendor values? How freely are low-band players replaced on waivers? | H-A if low-band decay appears in both lanes; H-B / H-C if values are a martingale but waiver replacement is free |
| F: filler flips | On near-even base trades plus 1–4 sweeteners drawn from filler, usable depth or genuine starters, how many fairness flips does each treatment produce? | see criteria F1–F3 |
| T: Team Context | With Team Context on, at the 58-player cap, does the existing analyze verdict already discount filler sweeteners? | H-B0 |

### Criteria for a B treatment on the flip study (F)

| id | criterion | pass when |
|---|---|---|
| F1 | eliminates inappropriate flips | flips caused by expendable filler alone fall by ≥ 80% versus GEOM_78 |
| F2 | protects genuine starters | on base trades made only of genuine starters, fairness levels change on ≤ 2% of trades versus GEOM_78 |
| F3 | protects usable depth | flips caused by usable-depth sweeteners fall by ≤ 25% versus GEOM_78 (they are appropriate flips) |

All three are reported separately for offense, IDP, picks and mixed packages. A class with fewer than 100 flip
cases is labelled **insufficient** rather than passed.

## 5. Confirmatory evaluation (box, read-only, owner-run)

`scripts/low_value_asset_box.py --box` runs under the same read-only guard as Phase 3. It covers two
populations:
- the production market ledger, split league-disjoint by `sha256("lva-2026-10-20|" + league)`;
- a **prospective** population: trades after 2026-10-20, reported once there are ≥ 2,000 unequal-count trades.

It reports:
- **M1.** Market agreement per treatment, per bin and per asset class (player-only offense, IDP-involved,
  rookie-pick-involved, mixed), with league-clustered CIs. This is necessary, never sufficient: Phase 3 showed that
  agreement alone rewards imitation.
- **M2.** The implied credit of the extra piece in 1-for-2 trades, by its §3 class. Does the market credit usable
  depth more than expendable filler, and does it do so by position (an IDP starter-calibre piece vs a WR filler
  piece of the same value)?
- **M3.** Served-history value dynamics from the temporal ledger's `canonical_board` lane: 30- and 60-day
  retention by band and class. Drop-offs are reported separately and never counted as 0. Changes of
  pipeline version within a window are counted.
- **M4.** For pieces that were traded as extras: their 30-day retention against the consolidated pieces.

## 6. Decision rules (fixed in advance)

**R-A, recommend investigating a canonical-curve change** (value-pipeline owner; this program can only
recommend it). All of the following:
- D shows low-band decay in both our lane and the vendor lane;
- M3 confirms it on served history (low-band 60-day retention below the 3,000–6,000 band by more than its
  clustered CI);
- U shows low-band usable depth contributing little lineup value relative to its canonical value.

**R-B, recommend a specific B treatment for owner approval on context-free surfaces.** All of the following:
- it passes F1–F3 in offense and in mixed packages;
- M1: it does not lose market agreement against GEOM_78 on held-out leagues;
- M2: the market credits usable depth above filler in the direction the anchor predicts;
- T shows Team Context does not already absorb the effect on those surfaces;
- it keeps every §2 mathematical property except homogeneity, and that exception is disclosed.

**R-B0, Team Context is sufficient on team-aware surfaces.** No new adjustment on those surfaces, whatever R-B
says for context-free ones.

**R-C, informational only.** Applies when neither R-A nor R-B is met, or when IDP or picks are insufficient for
a class-wide change. Disclose the market's discount, with no number changed.

**Explicit non-conclusions.**
- Agreement with completed trades alone never decides anything.
- No threshold is chosen to maximise agreement.
- A class with insufficient data never receives a class-wide recommendation.
- Nothing activates without explicit owner approval.

## Amendments

None.
