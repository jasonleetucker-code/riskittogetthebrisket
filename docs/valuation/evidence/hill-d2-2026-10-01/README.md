# Batch 3 Unit D2 — clean preregistered Hill rerun (2026-10-01)

**Status: evidence only.** No Hill constant, registry entry, flag, source role or served
value changed. No challenger was registered in `config/model_registry/` (the Autopilot
docs define no sanctioned shadow-registration path, and an extra entry could enter the
tournament). Nothing was promoted, and `--override-scope` was not used. **The champion is
unchanged: OFFENSE c 0.1100 / s 1.110 (registry `hill_scope_masters` v2).**

| file | what it is |
|---|---|
| [`PREREGISTRATION.md`](PREREGISTRATION.md) | arms, manifests, holdout, metric, horizons, bootstrap, verdict rule. Committed alone in **`ce66256c5`**, before the run script (`626a67413`) and before any result |
| [`run_d2.py`](run_d2.py) | the runner; refuses to score if any arm manifest differs from the preregistered hash |
| [`results.json`](results.json) | every verdict input, per horizon, band and secondary analysis; full pins |
| [`runs.jsonl`](runs.jsonl) | one pin summary per substrate-v2 fit (636): `challengerHash`, `manifestHash`, `codeHash`, `pinsHash`, `evidenceHash`, `inputsCommit`, cutoff, OFFENSE c/s |

Agent-OS-Receipt: cdca1dca8385f70c0989302dece8d1bd4ce4843c

## Pins

| pin | value |
|---|---|
| preregistration | `ce66256c57f6`, sha256 (LF) `8dec1cbf64b4…` |
| code | `626a67413` (clean tracked tree), run script sha256 (LF) `bae08e56e663…` |
| trainer code hash | `e7aa56d77885…` on every one of the 636 runs; substrate version 2 |
| manifests | default `1f31e6724c2b…`; arm manifests M1–M8 exactly as preregistered (asserted) |
| inputs | `commit_at_or_before(T 23:59:59Z)` on `origin/main` (`810445ed7` at run time; every cutoff is ≤ 2026-09-29, so the commits are the ones `3043d12b1` also reaches) |
| target | `CSVs/site_raw/otcffbSf.csv`, column `value`; 138 target days pinned by commit + blob sha in `results.json` |
| verification | every fit replayed twice from its pins: **636 / 636 identical `challengerHash` and parameters**, 0 non-promotable fits |
| P1 (`ktcSfTep` ≡ `ktcCrowdSfTep`) | **pass**: 22 / 22 overlap dates, 100% of matched players within 0.5 |
| bootstrap | circular moving-block, 28-day blocks, 4,000 resamples, seed 20261002; 98.75% = Bonferroni over 4 decisive comparisons |

## Holdout used, and why it is the only one

> **Post-hoc invalidation (2026-10-01, PR #1599).** Multi-snapshot re-measurement
> (`docs/sources/integrity/OTC_LINEAGE_REMEASURE_2026-10-01.md`) records positive measured
> dependence of OTC on base KTC (+0.45 rank, +0.44 shape-removed value, 21/21 weekly
> snapshots), on Dynasty Daddy (+0.69) and on Yahoo/Boone (+0.42). Under this
> preregistration's own §5 rule, OTC is therefore not an eligible holdout for any arm, and
> **no ancestry-safe board holdout exists**. The verdicts below stand as a record of the
> frozen run. They measure closeness to a board that depends on the arms' trainers, not to an
> independent market, and they must not be cited as evidence for promotion. The earlier "not
> reproduced" result (−0.204 / −0.146) was a depth and TE-basis artifact. The production
> `independentCriterion` (`holdout.py`) still treats OTC as independent until
> `_MEASURED_DEPENDENCES` is reconciled.

**OTC (`otcffbSf`) alone.** The preregistered rule excludes any board with a proven,
suspected, or currently-positive measured relation (per `config/sources/source_lineage.json`
and the 2026-10-01 integrity sweep) to a board whose spacing either compared arm uses:

- **PFK** — +0.687 residual vs KTC Crowd (+ suspected ancestry); every arm uses KTC → out.
- **FantasyCalc** — +0.635 vs Dynasty Daddy, which trains C0, M1 and M3 → out.
- **Fantasy Navigator** — `ktcCrowd` family → out.
- **OTC** — its only current dependence is on FantasyCalc (+0.511), which no arm uses; the
  recorded OTC↔KTC relation is *not reproduced* (−0.204 / −0.146). Under a strict reading
  that counts the stale relation, **no** ancestry-safe holdout exists at all.

  **Thin basis (post-hoc review note, 2026-10-01).** OTC was cleared on ONE snapshot
  (2026-10-01), measured against KTC Crowd and KTC Trades only. Base `ktc` — the board that
  carried the recorded +0.891 and that trains C0, M1 and M2 — was not re-measured as a named
  pair (only lagged value identity was checked), and OTC was never measured as a named pair
  against Dynasty Daddy, Dynasty Nerds, Yahoo/Boone, Fitzmaurice or Draft Sharks, so "no
  relation" there means *unmeasured*, not *measured independent*; an indirect
  OTC → FantasyCalc → Dynasty Daddy path also exists. The lineage owner is half-updated:
  `config/sources/source_lineage.json` still carries `statistics.residualRho` 0.891
  (`otc-ktc-dependence`) and 0.329 (`otc-fc-dependence`) beside refreshed summaries. If a
  refreshed measurement against base KTC comes back positive, every verdict below loses its
  holdout.

Audit C20 (holdout boards still vote in the live blend) is unaffected and stays OPEN.

## Verdicts (primary: h = 7 days, OTC curve RMSE, Δ = RMSE_ref − RMSE_arm, > 0 ⇒ arm closer)

Origins 2026-05-15 → 2026-09-22: **131 origins over 131 days** (minimum 84 / 84 met).

*OTC is no longer an eligible holdout: see the post-hoc invalidation above. These verdicts are a record of the frozen run, not promotion evidence.*

| arm pair | question | mean RMSE ref → arm | **Δ [98.75% CI]** | h = 0 / h = 28 Δ | bands 1–50 / 51–100 / 101–200 / 201–400 | **verdict** |
|---|---|---|---|---|---|---|
| **KTC native → KTC c3** (Q1) | c3 (KTC players vote Hill at players-only rank) vs value-direct | 1711.0 → 1402.9 | **+308.0 [+298.8, +315.9]** | +306.8 / +310.7 | **−297.6** / +369.9 / +517.8 / +400.8 | **BETTER** (margin 85.5) |
| champion C0 → **M1** (Q2) | repaired substrate-v2 refit vs champion | 1402.9 → 690.9 | **+712.1 [+674.2, +736.4]** | +717.4 / +708.6 | +804.6 / +1065.2 / +829.7 / +519.4 | **BETTER** (margin 70.1) |
| M1 → **M3** (Q3, H1) | KTC Crowd TE++ trains instead of KTC base | 690.9 → 711.1 | **−20.2 [−24.4, −15.7]** | −20.3 / −21.2 | all four negative | **WORSE** (small: ~3%) |
| M1 → **M2** (Q4, H3) | rank-voter native values stop training (KTC base alone) | 690.9 → 1579.2 | **−888.3 [−913.8, −852.5]** | −892.0 / −888.2 | all four negative | **WORSE** |
| **DLF Rank → DLF native spacing** | | — | — | — | — | **BLOCKED** (preregistered §6) |

Sensitivity S3 (origins ≥ 2026-07-30, after OTC was used once to select C0; n = 55):
Q1 +297.1 [+292.9, +301.3], Q2 +698.9 [+657.8, +740.0], Q3 −18.9 [−22.1, −15.7],
Q4 −861.3 [−891.6, −831.0]. Same verdict pattern.

**Champion lookahead (post-hoc review note).** S3 addresses the *selection* exposure only.
Champion v2 was fitted on 2026-07-28, so for 74 of the 131 origins C0 (and therefore the
c3 arm in Q1, which composes on C0) uses data dated after the origin. OTC's spacing barely
moves day to day, so selecting on the 07-29 OTC board is close to selecting on every OTC
board and a post-selection window cannot remove that bias. It inflates Q1 toward c3 and
makes Q2 conservative. Q1's *direction* is supported independently by S1 (c3 under M1,
which was never selected on OTC: +1020).

### What each verdict means, and what it does not

- **KTC c3 is BETTER than KTC native at describing OTC's future spacing**, on every
  horizon and in 3 of 4 rank bands — but **not at the top**: in ranks 1–50 KTC's native
  values are *closer* to OTC than the master (−297.6). That matches the alignment audit,
  where KTC's top end is the one band that sits below the master.
  - Player-matched (S5; 50,187 player-origins; both arms at KTC's players-only rank): mean
    |ln v − ln v_OTC| 1.258 native vs 1.099 c3, Δ +0.159 [+0.146, +0.165]. c3 is closer for
    QB +0.120, RB +0.168, WR +0.162, TE +0.176 (basis-confounded: KTC TE++ vs OTC base),
    rookies +0.184 (n = 7,110) and veterans +0.154.
  - S1 (c3 under the substrate-v2 master M1 instead of C0): +1020.1 [+980.7, +1045.0]. The
    substrate effect and the c3 effect point the same way and add.
  - S4 (the live `ktcCrowdSfTep` file itself, 2026-09-09+, 14 origins, < 1 block):
    +288.9, descriptive only, consistent with Q1 on the `ktcSfTep` carrier.
- **The repaired substrate (M1) is BETTER than the champion** by about half its error, on
  every horizon and band. M1's OFFENSE master over the window: c 0.066–0.077, s 1.10–1.18;
  on 2026-09-29 it is (0.067, 1.105), close to the pending pre-repair v171 (0.066, 1.085)
  that the Autopilot board-impact gate blocked. This is evidence for the methodology, not a
  constant to install.
- **H1: keep KTC base as the KTC trainer (do not switch to Crowd TE++).** M3 is worse than
  M1 at every horizon and band, but by ~20 points, below the 34.5-point materiality margin.
  The interval excludes zero, so the rule says WORSE; practically it is a small effect.
- **H3: keep training on rank-voter native values.** Restricting training to value-signal
  lineages leaves KTC base alone (c ≈ 0.105–0.109, s ≈ 0.925–0.945), which is far flatter
  than OTC and loses by ~888 points.

**One-target caveat (stated in the preregistration, and decisive for interpretation).**
Every verdict ranks spacing functions by closeness to **one** independent market. OTC's
own spacing is steeper than KTC's (09-30 audit fit: OTC c 0.041 / s 1.01 vs KTC Crowd
0.112 / 0.91), so the more KTC-like an arm is, the worse it scores here: M1 (steeper) beats
C0, which beats KTC-only masters and KTC native. The 98.75% intervals are narrow because
they capture **day-to-day sampling only**; they say nothing about how a *different*
independent market would rank the arms. With n = 1 target market, "closer to the
independent market" is the claim, not "more correct". That KTC is the flattest of 13
native boards in the 09-30 audit is consistent context, not additional evidence here.

### Descriptive only (insufficient history, preregistered §6 — no verdict)

| comparison | window | Δ (h = 7 unless stated) |
|---|---|---|
| H2: M5 (KTC Trades + five) vs M1 | 2026-09-09 → 09-22, 14 origins | −57.6 |
| H2: M7 (Crowd TE++ + Trades as two families + five) vs M1 | same | −184.0 |
| H2: M6 / M8 (Trades / Crowd+Trades alone) vs M1 | same | −1238.1 / −1123.1 |
| KTC Trades native (N2) → C0 | same | +502.5 (c3-style spacing closer) |
| DLF native spacing vs C0, **h = 0** | 2026-09-25 → 09-29, 5 origins | **−836.9** (DLF native RMSE 670 vs C0 1507: DLF's own spacing is closer to OTC than the master) |

Under one block, these are point estimates with no interval. The DLF row is notable and
consistent with the one-target caveat (DLF Values is the steepest native board); it is
**not** a verdict, and DLF native values remain unregistered and non-voting.

## Blocked or not applicable (decided before computation)

- **DLF native spacing — BLOCKED.** 7 committed days (2026-09-25 → 10-01); not in
  `_SOURCE_CSV_PATHS`, so the manifest refuses it as a trainer; census non-voting. Needs
  `docs/sources/DLF_VALUES_GATE_2026-09-25.md`, a registry entry with game-type evidence,
  and ≥ 84 days of history (~2026-12-18) before a decision-eligible rerun.
- **DLF Rank** has no evaluable challenger; its spacing is the master's, and it stays.
- **H2 (KTC Trades as trainer)** — 22 days of history (from 2026-09-09); decision-eligible
  from ~2026-12-02.
- **Board-level c3** (leave-family-out future consensus on rebuilt boards) — not run: the
  KTC Crowd/Trades voters only exist from 2026-09-09, so before then a today's-code replay
  has no KTC vote and native ≡ c3. The `src/source_quality/` movement targets measure an
  observation's order/level, which c3 does not change.
- **IDP and picks** — not applicable: no arm changes IDP spacing, and c3 keeps pick votes
  value-direct. Rookies are reported in S5.

## Deviations from the preregistration

None in the definitions or the rule. Implementation notes: (1) the runner skips a fit whose
OFFENSE scope is non-promotable (Autopilot's own exclusion); this was not in the
preregistration and **never fired** (0 of 636). (2) `docs/WORK_CLAIMS.md` was edited in the
working tree while the run was in progress; it is not an input to any computation, and the
tracked-tree check ran clean at start.

## What the champion is after D2, and what would be needed next

**Champion unchanged** (c 0.1100 / s 1.110). D2 authorizes nothing:

- **Q2 (substrate)**: the evidence favours the repaired trainer methodology, which is
  already what Autopilot refits use. A new champion still needs Autopilot's own gates on
  fresh substrate-v2 challengers: 3 stable fits over ≥ 5 days, forward persistence, the
  3-board breadth gate, and the board-impact rails (which blocked the similar v171). There
  is no manual path from this document.
- **Q1 (c3)**: BETTER makes c3 *eligible to be considered*. It still needs the owner
  source-role decision, a Lane C default-OFF flag-gated implementation (players-only rank
  pool, picks value-direct, E2 fixed), explicit decisions on the tail past rank 400, the
  rookie ladder and TE, and the top-50 band where native KTC is closer.
- **H1 / H3**: the evidence supports the current manifest (KTC base trains; rank-voter
  natives train). No manifest change is indicated.

Evidence that would strengthen or overturn this:

1. **A second ancestry-safe independent target.** The completed-trade ledger (Unit I) as a
   transaction-fit target is the strongest candidate, because it is not any board's
   spacing convention.
2. A board-level leave-family-out evaluation of c3 once the KTC Crowd/Trades voters have
   ≥ 84 days (~2026-12-02), or a Lane C flag-on shadow.
3. Decision-eligible reruns of H2 (~2026-12-02) and DLF native spacing (after its gate,
   registration and ~2026-12-18).

## Reproduce

```bash
# Windows: set PYTHONUTF8=1
python docs/valuation/evidence/hill-d2-2026-10-01/run_d2.py \
  --out docs/valuation/evidence/hill-d2-2026-10-01 --workers 16
```

About 45 minutes on 16 workers: 636 replays, each run twice for verification. Every fit is
deterministic from its `runs.jsonl` row: `training_run.replay(commit=inputsCommit,
cutoff=trainingCutoff, manifest=run_d2.arm_manifest(arm))`.
