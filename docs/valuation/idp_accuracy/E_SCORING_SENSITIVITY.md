# IDP accuracy — Deliverable E: scoring sensitivity (PRE-REGISTRATION)

**Lane:** E. **Authority:** `docs/owner/IDP_VALUATION_ACCURACY_DIRECTIVE_2026-10-25.md` section 10 (scoring
sensitivity) and section 13 (production safety). **Status:** research only. Production scoring is unchanged and
no served value, rank, flag, weight, source, threshold or verdict is read or written by this lane.
Agent-OS-Receipt: cb64f74cf4d2763aa16d55ba0d6350f585a2a42f

This page is the pre-registration commit. It is replaced, in the same pull request, by the results write-up once
the experiment has run. The machine-readable specification is
`config/idp_accuracy/scoring_sensitivity_cards.json`; it fixes, before any result exists:

* the perturbation grid (eleven directive keys, each multiplied alone by 0, 0.5, 1.5 and 2.0 around the actual
  2026 card), eight documented joint cards, and four reference cards (the league's own 2025 and 2024 cards, which
  are real, and two constructed cards, which are not any platform's default);
* the player pools (at least 4 played games of 6; sensitivity at 3 and 5), the tiers (1-12 elite, 25-36 average
  starter, 37-48 first bench, 1-36 starters), the two replacement definitions, and the predictability, weekly
  variance, best-ball and cross-position metrics;
* the bootstrap design (week resampling within player for levels, player resampling for reliability, week blocks
  for best ball), basic 95 percent intervals, and Bonferroni-adjusted intervals within each question's family;
* the four question families and their contrasts (Q1 TFL, Q2 PD, Q3 LB, Q4 best ball).

Scoring is a dot product of stat counts and card rates, so stacking (a sack play paying sack, TFL and QB hit
together) is reproduced exactly by rescoring the stat counts Sleeper publishes and is never modelled.

Nothing in this experiment optimises a card toward equal position totals. The directive forbids it; the results
state trade-offs instead.
