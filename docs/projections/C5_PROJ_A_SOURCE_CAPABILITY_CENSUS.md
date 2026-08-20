# C5-PROJ-A — Projection-Source Capability / Access / Lineage Census

**Status:** DELIVERED 2026-08-20
**Unit:** `C5-PROJ-A`, first sub-unit of `C5-U1` (multi-source projection ensemble)
**Governing plan:** `docs/PROJECTION_ENSEMBLE_PLAN_2026-08-15.md`
**Owner (data + loader):** `config/projections/source_capability_census.json` + `src/ros/projection_source_census.py`
**Lane:** Claude 11 — C5, under the POST-V1 C-Series mass-build campaign (`docs/EXECUTION_PLAN.md` §0, owner directive 2026-08-20)

## What this unit is, and is not

This is the plan's own first instruction for `C5-U1`: *"source capability /
access / lineage census ... Record the authorized acquisition path before
automation. Flag any source that is rankings-only rather than a true
projection model."* It records facts. It builds no fetcher, parses nothing,
and authorizes no new automation — every entry's `accessPosture` is
evidence about what is currently recorded, not a permission grant.

## Findings

### The ensemble already has two real, live PROJECTION_MODEL sources

`clayProjections` (Mike Clay / ESPN) and `idpShowProjections` (The IDP Show)
are not greenfield — they already exist as working code inside
`src/bdvm/`, built for BDVM's fundamental-value engine, and already produce
real per-player raw stat-line projections (never a provider's own point
total) via `src/bdvm/projections.py::ProjectionRecord`. This is the single
most consequential finding for the sub-units that follow: **C5-PROJ-B's
canonical projection-stat schema should reconcile with BDVM's existing
`ProjectionRecord`/`supersede_merge_into_snapshot` pipeline rather than
building a second one.** Building a parallel schema for the seasonal
ensemble while BDVM already owns a working one would be exactly the kind
of duplicate-owner defect this whole C-Series exists to prevent — even
though BDVM's *consumer* (dynasty fundamental value) and the seasonal
ensemble's *consumer* (current-season competitive intelligence) are
different concepts that must stay separately named per the source-domain
boundary. The *projection* layer can be shared; the *valuation* layer built
from it must not be.

### Five sources are wired but mislabelled — rankings presented where a projection is wanted

`fantasyProsRosSf`, `fantasyProsRosIdp`, `fantasyProsRosOverall` (all in
`src/ros/sources/__init__.py`'s `ROS_SOURCES` registry) and the two
DraftSharks entries this census introduces
(`draftSharksOffenseProjections`, `draftSharksIdpProjections`, both backed
by `src/ros/sources/draftsharks_ros.py`) are live, enabled, and currently
consumed by the ROS aggregator — but none of them is a per-player projected
stat line. They are ECR rankings, a trade-value chart, or (for DraftSharks)
a dynasty rankings CSV reused as a ROS proxy pending a documented "PR 2
swap" to a real ROS scrape that has not happened. This census flags all
five as `RANKINGS_ONLY`, per the sub-unit's own instruction.

**One discrepancy recorded, not repaired here.** `ROS_SOURCES` marks
`draftSharksRosSf` (the entry both new DraftSharks census rows map to) as
`is_projection_source: True`, which this census's evidence does not
support — the module's own docstring describes the current feed as a
ranking-board proxy. `ROS_SOURCES` is a live, consumed registry with its
own weight/aggregation semantics; changing that flag is outside this
foundational unit's scope and risks moving the live ROS blend. Recorded so
C5-PROJ-B/C do not mistake `ROS_SOURCES` membership, or that flag
specifically, for proof of `PROJECTION_MODEL` evidence-class eligibility.

### Three sources are genuinely greenfield

`cbsSportsFantasyProjections`, `nflFantasyProjections` (both named as
initial-target offense families in plan §3) and `fantasyProsProjections`
(FantasyPros' actual, not-yet-touched projections page, as distinct from
its three rankings pages above) have zero existing code anywhere in the
repo. No URL is recorded for any of the three — inventing one would
pre-empt the "record the authorized path before automation" instruction
this unit exists to satisfy, and this session does not generate URLs it
cannot verify against a source the user or the codebase already provided.

### Two discovery lanes (DFS, betting market) are confirmed empty, not merely unexamined

Plan §3 requires actively looking for DFS and sportsbook/player-prop
sources. Both searches were performed (`scripts/`, `src/`, `config/`,
`Dynasty Scraper.py`, keyword and vendor-name greps) and found zero
existing infrastructure. Recording a confirmed-empty search result matters
here specifically: it distinguishes "nobody has looked" from "looked and
found nothing," which is the same missing-is-never-zero discipline this
codebase applies everywhere else.

### The IDP Show's access posture is the genuine open item — not a code gap

The existing `idpShowProjections` fetcher works today. What is missing is
a recorded authorization artifact proving the owner's subscription permits
automated acquisition of the *projection* data specifically — plan §3's
explicit caution, and the same gap `F-EXT-03` in
`docs/VERSION_1_COMPLETION_CONTRACT.md` §6 already names for the sibling
IDP Show *rankings* fetcher. This census does not resolve it (an `OD-01`
owner-decision class item), only names it precisely.

### One-writer boundary with Claude 8, recorded explicitly

`docs/EXECUTION_PLAN.md` §0 (2026-08-20 mass-build campaign) assigns
Claude 8 exclusive ownership of new source acquisition, naming Draft
Sharks cross-position qualification and IDP Show / Footballguys
acquisition specifically. Both DraftSharks census entries are stamped
`acquisitionOwnerLane: "Claude 8"` so a later C5-PROJ session does not
build acquisition code there and collide. The IDP Show *projection*
consumption path already existed before the 2026-08-20 lane split (built
under BDVM), so it is stamped `shared` with a note rather than reassigned.

## What C5-PROJ-B inherits

- Two real `PROJECTION_MODEL` sources ready to reconcile against, with a
  working schema (`ProjectionRecord`) already proven in production by BDVM.
- A precise list of which currently-wired ROS sources must NOT be treated
  as projection evidence (`sources_by_evidence_class("PROJECTION_MODEL")`
  structurally excludes every `RANKINGS_ONLY` entry).
- Three greenfield candidates and two discovery lanes, each with an
  explicit "no access path recorded" state rather than a silent absence.
- `automatable_sources()` — the subset whose access posture does not
  require a further owner decision before automation could even be
  considered (today: `clayProjections` only, plus every `RANKINGS_ONLY`
  entry, which are already live for their own registries and are excluded
  from projection-ensemble use by evidence class rather than access).

## Validation

`tests/ros/test_projection_source_census.py` — 17 tests: structural/
closed-vocabulary validation (with non-vacuousness checks — a bad
evidence class, a bad horizon, a missing module reference on a `LIVE`
entry, and a duplicate key are each proven to fail validation), plus a
`TestMeasuredFacts` class pinning the specific findings above so a future
edit cannot silently relabel a rankings feed as a projection or forget the
Claude-8 ownership boundary. `tests/ros/` full suite: 219 passed / 1
skipped (livedata-marked), no regressions.

## Deliberately NOT claimed

Any fetcher, parser, or new automation for any source in this census
(including the three greenfield offense candidates, which are Claude 11's
to build once an access path is recorded — but recording the census is
this unit's whole scope). Any change to `ROS_SOURCES`'s
`is_projection_source` flags. Any acquisition or auth code for DraftSharks
or Footballguys (Claude 8's scope). C5-PROJ-B (canonical schema/rescoring),
C5-PROJ-C/D (ensemble aggregation), C5-PROJ-E (archive), C5-PROJ-F
(consumer migration) — this unit only unblocks them.
