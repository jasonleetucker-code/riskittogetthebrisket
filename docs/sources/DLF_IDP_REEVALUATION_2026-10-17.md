# DLF IDP — re-evaluation of incremental evidence (2026-10-17)

Owner master package 2026-10-17, Workstream F.  The 2026-10-16 owner policy (DLF votes on offense
only, #1758) is **unchanged**.  This is the evidence for a possible reversal, presented for an
explicit decision — nothing here switches DLF IDP back on.

Method: the same raw payload (`exports/latest/dynasty_data_2026-10-17.json`) built twice through
`build_api_data_contract`, with the policy hold in force and with it off
(`RISKIT_FEATURE_DLF_OFFENSE_ONLY_VOTE=0`), plus pairwise rank agreement on the effective ranks the
pipeline actually uses.  Scripts are reproducible from that payload; no network.

## If DLF IDP voted again (today's board)

| measure | value |
|---|---|
| DLF IDP + rookie IDP observations on IDP rows | 197 |
| of those rejected as outliers (Hampel) | 1 (0.5%) |
| IDP rows whose value moves | 176 of 396 |
| relative value movement, median / p90 / max | 0.0% / 2.9% / 52.3% |
| by family p90 | DL 3.1%, LB 7.2%, DB 0.9% |
| consensus rank movement, median / p90 | 3 / 22 |
| IDP rows gaining an independent evidence family | 146 |
| confidence buckets changing | 55 |
| offense player rows moving | 1 (the two-way player, by the same mechanism as Signals) |
| pick rows moving (rookie-pool tether, allowed coupling) | 38 |

Freshness: DLF IDP's last broad change was 2026-10-09 (30 recorded changes since 2026-04-16); it is
not stale.  Identity: 172 rows on the CSV, 197 observations on board rows including rookie IDP.

## Independence — the open question

Spearman rank agreement on overlapping IDP players (effective ranks):

| pair | n | Spearman |
|---|---|---|
| **DLF IDP vs IDP Trade Calculator** | 168 | **0.881** |
| DLF IDP vs Draft Sharks IDP | 161 | 0.612 |
| DLF IDP vs FantasyPros IDP | 154 | 0.654 |
| IDP Trade Calculator vs Draft Sharks IDP | 303 | 0.647 |
| IDP Trade Calculator vs FantasyPros IDP | 241 | 0.630 |
| Draft Sharks IDP vs FantasyPros IDP | 230 | 0.523 |
| DLF IDP vs mean of the other three | 147 | 0.836 |

DLF IDP agrees with IDP Trade Calculator more than any other pair of IDP sources agrees with
each other.  Correlation is not copying, so the lead-lag test that settled the IDP Show question
was run over the full git history of both committed CSVs (37 DLF IDP and 51 IDP Trade Calculator
content versions, 2026-04-16 → 2026-10-17): at every change of one board, did its ordering move
toward the OTHER board's current ordering?

| at each change of… | events | moved toward the other (Δρ > 0.01) | moved away (Δρ < −0.01) | median Δρ |
|---|---|---|---|---|
| DLF IDP | 30 | 8 | 2 | +0.001 |
| IDP Trade Calculator | 50 | 2 | 1 | 0.000 |

* **No copying signature.**  Agreement never approaches identity (it ranges 0.69 → 0.89 and has sat
  near 0.87–0.89 since late July); a copied board jumps to near-identity right after its source
  moves, as IDP Trade Calculator did after The IDP Show's publications (`idptc-idpshow-dependence`).
* Agreement rose gradually from ~0.75 (May) to ~0.87 (late July), consistent with in-season
  convergence of independent rankers.  DLF's own updates drift slightly toward IDP Trade Calculator
  (8 of 30 events, +0.02 to +0.07), which is weak evidence of DLF consulting the market — not of
  shared data.
* One transient: a 2026-10-04 DLF update dropped to 0.816 and reverted within two hours (a partial
  publication or scrape), already absorbed by the next fetch.

## Recommendation (owner decision)

* The evidence supports **reversing the 2026-10-16 hold for DLF IDP and DLF Rookie IDP**: low value
  risk (IDP p90 movement 2.9%, one outlier drop in 197), +146 rows gaining an independent family,
  fresh data, and no measured lineage to IDP Trade Calculator — only correlation, with the
  dependence recorded as `measured` correlation rather than ancestry.
* The DLF provider keeps one family (`dlf`): `dlfIdp` and `dlfRookieIdp` share it, and the family
  cap already prevents a double vote on rookie IDP rows.  DLF Trade Analyzer Values stays separate
  and held.
* Reversal mechanism (needs explicit approval): `RISKIT_FEATURE_DLF_OFFENSE_ONLY_VOTE=0` + restart
  (the documented rollback flag), or removing the two keys from `POLICY_SOURCE_VOTE_HOLDS` in a PR.
