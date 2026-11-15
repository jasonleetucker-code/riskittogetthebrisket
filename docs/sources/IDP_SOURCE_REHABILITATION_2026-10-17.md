# IDP source inventory and rehabilitation plan (2026-10-17)

Owner master package 2026-10-17, Workstreams B and J.  Production state of 2026-10-17, not
the 2026-10-13 audit.  Every IDP-relevant source gets a concrete disposition; each disposition is
also a machine-checked entry in `config/sources/rehabilitation.json`
(`tests/sources/test_rehabilitation_registry.py` fails if a held, shadow or non-voting source has
none; `scripts/check_source_health.py` warns when a plan passes its review date or a quarantined /
severely stale source has no plan).

## Current IDP voting picture

On the 2026-10-17 board, ranked IDP rows carry 1–3 evidence families: DL 4 / 28 / 87, LB 5 / 15 / 61,
DB 4 / 20 / 73 rows with 1 / 2 / 3 families (119 DL, 81 LB, 97 DB ranked).  The voting IDP
families are **IDP Trade Calculator, Draft Sharks IDP and FantasyPros IDP** (FantasyPros at reduced
freshness).  IDP Show is quarantined, DLF IDP is policy-held, and the Signals IDP boards run in
shadow.

## Source by source

| source (key) | positions / format | scope | rows today | voting state | blocker | class | next action / owner | activation condition |
|---|---|---|---|---|---|---|---|---|
| IDP Trade Calculator (`idpTradeCalc`) | offense + IDP + picks, one 0–9999 scale | dynasty | 900 (cap) | **votes**, full weight (freshness ≈0.95; pick subset decays between the vendor's ~43-day pick updates) | IDP board tracks The IDP Show's IDP-only board (lead-lag measured 2026-10-01, Spearman 0.998); offense half is a lagged KTC copy in some batches; one row (Dru Phillips) intermittently missing since 10-14 | methodological (lineage) + technical (one row) | investigate the intermittent row; owner decision on the pick-subset cadence prior | already voting |
| Draft Sharks IDP (`draftSharksIdp`) | DL/LB/DB, one combined rank list with offense | dynasty | 409 | **votes**, full weight | none | — | none | already voting |
| FantasyPros IDP (`fantasyProsIdp`) | DL/LB/DB consensus + per-family pages | dynasty | 299 (284 unique) | **votes**, freshness 0.61 (STALE) | vendor experts have not updated since 2026-09-04 (2 of 6 included); our clock reads 09-23 (an upstream revert counted as a change); 15 edge rushers duplicated across the DL and LB pages | upstream + technical | parser repairs (dedup, upstream clock evidence); owner decision on an explicit upstream clock (stricter) | full weight only when FantasyPros experts publish again |
| Signals DL / LB / DB (`signalsIdpDl/Lb/Db`) | per-family normalised values | dynasty | 158 / 104 / 147 on board | **shadow** | Candidate A failed round 1: IDP p90 movement 30% (gate 8%), one offense row moved, signed bias LB −6.24% / DB −9.95% (gate ±5%) | methodological | counts-only movement decomposition; owner decision on a coverage-corrected candidate; session state `renewal_due` | §10.6 gate, unchanged thresholds |
| The IDP Show combined (`idpShowCombined`) | offense + IDP | dynasty | 665 | **quarantined** (freshness 0) | vendor chart U8I37 unchanged since 2026-08-19 (v4); prod fetch failing since 10-07 | upstream + credential | owner re-mints the session; on-box verifier (#1770) | vendor republishes |
| The IDP Show IDP-only (`idpShow`) | DL/LB/DB, two-expert consensus | dynasty | 350 | non-voting (avoids double-counting the combined board) | post republished 2026-10-08 (content unverified without auth); **IDP Trade Calculator's IDP board appears to follow this board** (lineage above), so its independent information may be small | methodological | with a working session, compare content; lineage check vs IDP Trade Calculator | owner approval to make it the provider family's voting board, one family vote, only if it adds information beyond IDP Trade Calculator |
| DLF IDP (`dlfIdp`) | DL/LB/DB | dynasty | 172 | **policy held** (owner 2026-10-16) | owner policy | policy | evidence-based re-evaluation presented for decision; never reversed silently | explicit owner approval |
| DLF Rookie IDP (`dlfRookieIdp`) | rookie DL/LB/DB | dynasty | 29 | **policy held** | owner policy | policy | as DLF IDP | explicit owner approval |

## Future candidates (no paid subscriptions; unverified until measured)

* **Dynasty Nerds dynasty IDP rankings & tiers** — a free top-275 board (dynastynerds.com/idp).
  We already ingest Dynasty Nerds for offense (`dynastyNerdsSfTep`), so acquisition reuses an
  existing fetcher pattern; it would be a new IDP dataset of a provider already in the model
  (one provider, separate rows — no IDP double count).  Needs: dynasty game-type proof per
  endpoint, coverage / identity check, lineage check against IDP Trade Calculator and IDP Show,
  and owner approval to register.
* Dynasty Nerds "Glossery" mixed offense + IDP ranking — single-author, not a consensus; lower
  priority.

Sources for the candidates: [Dynasty Nerds IDP hub](https://www.dynastynerds.com/idp/),
[Dynasty Nerds dynasty IDP rankings & tiers](https://www.dynastynerds.com/idp/dynasty-idp-rankings-tiers/embed/).

## Independence notes

* IDP Trade Calculator ↔ The IDP Show IDP-only: measured near-identity with lead-lag (IDPTC follows
  IDP Show within hours at 3 of 5 publications).  Treat any IDP Show IDP-only vote as correlated with
  IDP Trade Calculator, not as independent confirmation.
* The IDP Show combined board is a vendor-declared aggregate of unnamed boards plus startup ADP.
* Signals is suspected to compose market values (FantasyCalc fallback in its app bundle); it sits in
  the `fantasyCalc` family.
* DLF and FantasyPros each publish several boards; each provider keeps one family.
