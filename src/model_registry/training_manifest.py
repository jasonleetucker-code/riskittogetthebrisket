"""The Hill training manifest — ONE owner for "which evidence teaches the curve".

Why this module exists (owner Section D, Batch 3 Unit D, 2026-10-01)
──────────────────────────────────────────────────────────────────
Before it, the Hill trainer set lived in two hand-maintained dictionaries
(``scripts/fit_hill_curve_percentile.OFFENSE_SOURCES`` and
``holdout.OFFENSE_TRAINING_SOURCES``) tied to each other by a text-parsing test
and to nothing else (finding H8 of
``docs/valuation/HILL_SOURCE_ALIGNMENT_AUDIT_2026-09-24.md``). Three defects
lived in that gap:

* **E3** — the OFFENSE trainer read KTC's base board with every positive row,
  so 36 pick rows sat inside the top 400 it fits, while every other trainer,
  every holdout and every OFFENSE rank voter at serve time is players-only;
* **H5** — Fantasy Navigator, a KTC-derived board in the ``ktcCrowd`` family,
  scored the curve as an "independent" holdout while KTC trained it;
* **H8** — a source-role change (the KTC split, family caps) could leave Hill
  behind silently, because nothing tied the lists to the live registry.

What is DERIVED here, and what is DECLARED
──────────────────────────────────────────
Derived from source authority, never restated:

* the CSV path of every board — ``data_contract._SOURCE_CSV_PATHS``;
* its CSV signal type (value / rank) — the same registry;
* its live role — ``_VALUE_BASED_SOURCES`` (value voter), ``_RANKING_SOURCES``
  (rank voter), ``_NON_VOTING_SOURCE_CSV_KEYS`` (non-voting calibration
  capture) or ``ktc_market.KTC_MARKET_KEY`` (benchmark only);
* its provider family — ``data_contract.correlation_group_for`` (B10);
* its game type — the registry's ``game_type``; a key the registry does not
  carry must cite its evidence, and unverified fails closed;
* every holdout's lineage relationship with every training family —
  ``config/sources/source_lineage.json`` (``pairReconciliation`` categories and
  the cited relations' ``current`` measurements), validated by
  ``src.sources.source_census.validate_lineage``. The manifest used to keep a
  private copy of three residual correlations (``_MEASURED_DEPENDENCES``); it
  went stale the day OTC was re-measured (#1599) and production's
  ``independentCriterion`` kept counting OTC as independent. One concept, one
  owner: the lineage registry answers, this module only reads it.

Declared, because no registry can express them (``_DEFAULT_SPECS``):

* which native-value column a board publishes;
* which scope it trains or holds out — the methodology choice, kept exactly as
  it was before this unit except where the owner's Section D items force a
  change (players-only populations; no confirmed-ancestry holdout).

Rules enforced on every build (``build_manifest``), each test-pinned in
``tests/model_registry/test_training_manifest.py``:

1. **Players only.** Every training and holdout population drops pick rows
   (``src.identity.picks.is_pick_name`` — the canonical pick detector — plus a
   ``PICK`` position column where one exists). A Hill master prices PLAYER
   ranks; picks take the anchor path.
2. **Only native values teach spacing.** A rank-only board, or a snapshot
   field that holds the synthetic rank encoding of a rank-signal source, can
   never train or hold out. Native values published by a source that VOTES by
   rank (Dynasty Daddy, Dynasty Nerds, Yahoo/Boone, Fitzmaurice, DraftSharks)
   are real vendor spacing evidence and are allowed by default — the
   "document precisely" branch of owner item 3 — and one policy switch
   (``TrainingPolicy.allow_rank_voter_native_values=False``) restricts
   training to value-signal lineages.
3. **No family on both sides of a split, and no proven ancestry across it.** A
   holdout that shares a provider family with a trainer — or that the lineage
   registry reconciles as PROVEN_COMMON_ANCESTRY with a training family — is
   excluded. MEASURED / SUSPECTED dependence, and UNKNOWN lineage, are weaker
   statements: the board stays in the split, is tagged, and is NOT independent
   (it never enters ``independentCriterion``). Excluding those too is an
   explicit policy (``HoldoutPolicy(measured_dependence="exclude")``). See
   :func:`holdout_lineage` for the exact rule.
4. **One vote per family per scope.** Two trainers from one family in one
   scope (e.g. KTC base plus KTC TE++, same-source calibration states) are a
   ManifestError, not a silent double count.
5. **Benchmark-only never trains or holds out** (KTC Market).
6. **Every registered source is classified** — as a declared board or in
   ``NOT_HILL_BOARDS`` with a reason — so a new source cannot leave Hill
   behind unnoticed.

This module computes no curve and imports nothing from the fitter. It reads
the registry read-only.
"""

from __future__ import annotations

import csv
import hashlib
import json
from dataclasses import dataclass, field, replace
from functools import lru_cache
from pathlib import Path
from typing import Any, Callable, Iterable, Mapping

from src.identity.picks import is_pick_name
from src.sources import source_census as _sc
from src.sources.ktc_market import KTC_MARKET_KEY

REPO = Path(__file__).resolve().parents[2]

#: 1 = the pre-repair substrate (KTC pick rows in the OFFENSE fit, Fantasy
#: Navigator held out, no run pins). 2 = this manifest. A registry challenger
#: records the substrate it was fitted on; Hill Autopilot only tournaments the
#: current one (``training_run.is_tournament_eligible``).
SUBSTRATE_VERSION: int = 2
MANIFEST_SCHEMA_VERSION: int = 2

#: The fit truncates every CSV board to its top ``FIT_TOP_N`` rows before
#: computing canonical percentiles; the holdout scores the same window.
FIT_TOP_N: int = 400

SCOPES: tuple[str, ...] = ("OFFENSE", "GLOBAL", "IDP", "ROOKIE")

ROLE_TRAIN = "train"
ROLE_HOLDOUT = "holdout"
ROLE_EXCLUDED = "excluded"

POPULATION_PLAYERS_ONLY = "players_only"

SPACING_NATIVE_VALUE = "native_value"
SPACING_RANK_ONLY = "rank_only"
SPACING_SYNTHETIC = "synthetic_rank_encoding"

LOADER_CSV = "csv"
LOADER_CSV_CONCAT = "csv_concat"
LOADER_SNAPSHOT_IDP = "snapshot_idp_slice"
LOADER_SNAPSHOT_ROOKIE = "snapshot_rookie_slice"
SNAPSHOT_LOADERS = frozenset({LOADER_SNAPSHOT_IDP, LOADER_SNAPSHOT_ROOKIE})

LIVE_VALUE_VOTER = "value_voter"
LIVE_RANK_VOTER = "rank_voter"
LIVE_NON_VOTING = "non_voting_calibration"
LIVE_BENCHMARK = "benchmark_only"
LIVE_UNREGISTERED = "unregistered"

#: Header tokens that name a RANK column. Declaring one of these as a board's
#: value column would teach the curve an ordinal as if it were a price.
_RANK_COLUMN_TOKENS = frozenset({"avg", "rank", "overallrank", "effectiverank"})
#: Same alias set the contract's CSV reader accepts for a name column.
_NAME_COLUMNS = ("name", "Name", "player", "Player", "player_name", "PlayerName")
_POSITION_COLUMNS = ("position", "Position", "pos", "Pos", "Fantasy Position")


class ManifestError(RuntimeError):
    """A manifest declaration that would make the training substrate incoherent."""


class MissingColumnError(ManifestError):
    """A board's declared value column is absent from its file.

    Raised, never coerced: before this, every row of a renamed vendor column read
    as ``0.0`` and was counted ``nonpositive``, so the board silently emptied, its
    trainer was skipped, and a master fitted on fewer boards than declared still
    entered the tournament. Missing is never zero."""

    def __init__(self, path: Path, column: str, header: Iterable[str]) -> None:
        self.path = path
        self.column = column
        self.header = tuple(header)
        super().__init__(
            f"{path.name}: declared value column {column!r} is absent "
            f"(header: {list(self.header)})"
        )


# ── declarations ─────────────────────────────────────────────────────────────


@dataclass(frozen=True)
class BoardSpec:
    """One declared Hill board. Everything else about it is derived."""

    label: str
    source_key: str
    scope: str
    requested_role: str
    #: The board's native VALUE column (CSV loaders) or snapshot field. ``None``
    #: declares a rank-only board, which can never teach spacing.
    value_column: str | None
    loader: str = LOADER_CSV
    concat_keys: tuple[str, ...] = ()
    universe: str = "offense"
    #: Required only for a key the ranking registry does not carry.
    game_type_evidence: str = ""
    note: str = ""


# ── lineage: read from the one owner, never restated ────────────────────────

#: The lineage registry the manifest reads. Its normalized sha256 is RECORDED
#: provenance (``TrainingManifest.to_dict()["lineage"]``, and the run record's
#: ``lineage``) but is deliberately NOT inside ``manifest_hash``: only the
#: per-board labels DERIVED from it are (``_HASHED_DEPENDENCE_FIELDS``). An edit
#: that changes no Hill holdout's category -- an IDP or DLF pair, a prose fix, a
#: re-measurement that keeps the verdict -- must not stale every OFFENSE
#: challenger and restart the Autopilot persistence window (#1601 review); an
#: edit that changes a holdout's category does.
LINEAGE_REL = "config/sources/source_lineage.json"

#: The fields of one :class:`LineageDependence` that enter ``manifest_hash``:
#: exactly what the fit or the evaluation reads (the category decides exclusion
#: and ``independentCriterion`` membership). Reasons, pair / relation ids and
#: current measurements are provenance, recorded in ``to_dict`` but unhashed.
_HASHED_DEPENDENCE_FIELDS: tuple[str, ...] = ("trainerFamily", "category", "independent")

#: The four lineage categories are owned by ``src.sources.source_census``
#: (``LINEAGE_CATEGORIES``). ``UNKNOWN`` is not a fifth category: it is the
#: manifest's fail-closed answer when the registry cannot be read or validated,
#: names no reconciled pair for a (holdout, trainer family), or reconciles one
#: with a null category.
LINEAGE_PROVEN = _sc.LINEAGE_PROVEN_COMMON_ANCESTRY
LINEAGE_MEASURED = _sc.LINEAGE_MEASURED_DEPENDENCE
LINEAGE_SUSPECTED = _sc.LINEAGE_SUSPECTED_DEPENDENCE
LINEAGE_INDEPENDENT = _sc.LINEAGE_INDEPENDENT_NO_EVIDENCE
LINEAGE_UNKNOWN = "UNKNOWN"

#: Most dependent first. When several reconciled pairs link one holdout to one
#: training family (OTC vs ``ktc`` and vs ``ktcSfTep``), the most dependent
#: verdict wins: a known dependence is more informative than an unknown, and an
#: unknown can never be outvoted by an absence-of-evidence pair.
_CATEGORY_SEVERITY: dict[str, int] = {
    LINEAGE_PROVEN: 4,
    LINEAGE_MEASURED: 3,
    LINEAGE_SUSPECTED: 2,
    LINEAGE_UNKNOWN: 1,
    LINEAGE_INDEPENDENT: 0,
}

#: Internal marker distinguishing a deciding relation from a deciding pair.
_RELATION_TAG = "relation:"

_CATEGORY_REASON: dict[str, str] = {
    LINEAGE_PROVEN: "proven_common_ancestry",
    LINEAGE_MEASURED: "measured_dependence",
    # The D2 preregistration (docs/valuation/evidence/hill-d2-2026-10-01/
    # PREREGISTRATION.md §5) counts a SUSPECTED relation against a holdout's
    # independence; HILL_AUTOPILOT_V2 is silent, so the preregistered rule binds.
    LINEAGE_SUSPECTED: "suspected_dependence",
    LINEAGE_INDEPENDENT: "independent_no_evidence",
}


@dataclass(frozen=True)
class LineageView:
    """The lineage registry as the manifest consumed it: identity + validity."""

    path: str
    #: sha256 of the file's bytes with CRLF normalized to LF (``None`` when unreadable).
    sha256: str | None
    valid: bool
    errors: tuple[str, ...]
    pairs: tuple[Mapping[str, Any], ...] = ()
    relations: Mapping[str, Mapping[str, Any]] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "path": self.path,
            "sha256": self.sha256,
            "valid": self.valid,
            "errorCount": len(self.errors),
            "errors": list(self.errors[:10]),
        }


def load_lineage_view(path: Path | None = None) -> LineageView:
    """Read and validate the lineage registry. Never raises: an unreadable or
    invalid registry is returned ``valid=False`` and every holdout it would have
    vouched for reads UNKNOWN (fail closed), so a broken lineage file can never
    make a board look independent -- and can never crash a refit either."""
    target = Path(path) if path is not None else REPO / LINEAGE_REL
    try:
        rel = target.resolve().relative_to(REPO).as_posix()
    except ValueError:
        rel = target.as_posix()
    try:
        raw = target.read_bytes()
    except OSError as exc:
        return LineageView(rel, None, False, (f"unreadable: {type(exc).__name__}",))
    digest = hashlib.sha256(raw.replace(b"\r\n", b"\n")).hexdigest()
    try:
        data = json.loads(raw.decode("utf-8-sig"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        return LineageView(rel, digest, False, (f"unparsable: {exc}",))
    if not isinstance(data, Mapping):
        return LineageView(rel, digest, False, ("top level must be an object",))
    try:
        errors = tuple(_sc.validate_lineage(data))
    except Exception as exc:  # noqa: BLE001 - an unvalidatable registry fails closed
        errors = (f"validation_crashed: {type(exc).__name__}: {exc}",)
    if errors:
        # An invalid registry vouches for nothing: no pairs or relations are
        # carried, so no consumer can read a label out of it by accident.
        return LineageView(rel, digest, False, errors)
    raw_pairs = data.get("pairReconciliation") or []
    raw_relations = data.get("relations") or []
    if not isinstance(raw_pairs, list) or not isinstance(raw_relations, list):
        return LineageView(rel, digest, False, ("pairReconciliation/relations must be lists",))
    pairs = tuple(p for p in raw_pairs if isinstance(p, Mapping))
    relations = {str(r.get("id")): r for r in raw_relations if isinstance(r, Mapping)}
    return LineageView(rel, digest, True, (), pairs, relations)


@lru_cache(maxsize=1)
def default_lineage_view() -> LineageView:
    return load_lineage_view()


@dataclass(frozen=True)
class LineageDependence:
    """How one holdout board relates to one training family, per the lineage owner."""

    source_key: str
    trainer_family: str
    #: A ``source_census.LINEAGE_CATEGORIES`` value, or ``LINEAGE_UNKNOWN``.
    category: str
    reason: str
    #: ``pairReconciliation`` ids that decided the category.
    pairs: tuple[str, ...] = ()
    #: Training-family source keys those pairs (or relations) name.
    counterparts: tuple[str, ...] = ()
    #: Recorded proven / measured / suspected relation ids that decided the
    #: category directly (a relation joining the two sources is at least as
    #: dependent as any pair verdict; see :func:`holdout_lineage`).
    relations: tuple[str, ...] = ()
    #: ``{relation id: its current measurement}`` for the deciding pairs' relations.
    current_measurements: Mapping[str, Mapping[str, Any]] = field(default_factory=dict)

    @property
    def independent(self) -> bool:
        return self.category == LINEAGE_INDEPENDENT

    def to_dict(self) -> dict[str, Any]:
        return {
            "sourceKey": self.source_key,
            "trainerFamily": self.trainer_family,
            "category": self.category,
            "independent": self.independent,
            "reason": self.reason,
            "pairs": list(self.pairs),
            "counterparts": list(self.counterparts),
            "relations": list(self.relations),
            "currentMeasurements": {
                k: dict(v) for k, v in sorted(self.current_measurements.items())
            },
        }


def _current_measurement(relation: Mapping[str, Any]) -> dict[str, Any] | None:
    m = _sc.current_measurement(relation)
    if m is None:
        return None
    return {k: m.get(k) for k in ("asOf", "method", "window", "n", "values") if k in m}


def _pair_speaks_for(pair: Mapping[str, Any], a: str, b: str, lineage: LineageView) -> bool:
    """Whether a reconciled pair is a statement about sources ``a`` and ``b``.

    A two-source pair is unambiguous. A pair naming more sources is a statement
    about the sources its cited relations JOIN: ``pair-signals-market-families``
    lists Signals beside four market boards, and says nothing about FantasyCalc
    versus KTC Crowd; ``pair-otc-ktc`` cites a relation naming OTC and every KTC
    key, so it speaks for each of them."""
    srcs = [str(x) for x in (pair.get("sources") or [])]
    if len(srcs) == 2:
        return {a, b} == set(srcs)
    for rid in pair.get("relations") or []:
        rel_srcs = set(
            str(x) for x in ((lineage.relations.get(str(rid)) or {}).get("sources") or [])
        )
        if a in rel_srcs and b in rel_srcs:
            return True
    return False


def holdout_lineage(
    source_key: str | None,
    trainers_by_family: Mapping[str, Iterable[str]],
    *,
    lineage: LineageView,
    family_of: Callable[[str], str],
) -> tuple[LineageDependence, ...]:
    """One :class:`LineageDependence` per training family, derived from the owner.

    The rule (each clause test-pinned in ``tests/model_registry``):

    * the categories are the lineage owner's ``pairReconciliation`` verdicts;
      relations supply only the deciding pairs' ``current`` measurements, and
      decide which members a multi-source pair speaks for (``_pair_speaks_for``);
    * the unit is the B10 provider family, as everywhere else in this manifest:
      a reconciled pair naming the holdout and ANY member of a training family
      speaks for that family (``ktc`` / ``ktcSfTep`` / ``ktcCrowdSfTep`` are
      calibration states of one crowd). This is conservative: it can only mark
      MORE boards dependent;
    * ...except that INDEPENDENT_NO_EVIDENCE only counts when the pair names the
      family's actual TRAINER key -- absence of evidence about a sibling board is
      not absence of evidence about the trainer;
    * several pairs -> the most dependent category wins (``_CATEGORY_SEVERITY``);
    * PROVEN / MEASURED / SUSPECTED / UNKNOWN are all "not independent". This is
      the D2 preregistration's §5 rule (a proven, suspected, or positively
      measured relation counts). A measurement too weak to be dependence is
      reconciled SUSPECTED by the category's own definition, so a pair the owner
      reconciles MEASURED_DEPENDENCE IS the positive-dependence verdict;
    * a recorded relation is never outvoted by a pair: every proven / measured /
      suspected relation joining the holdout and a member of the family competes
      with the pair verdicts on the same ordering (PROVEN > MEASURED > SUSPECTED
      > INDEPENDENT). The validator already refuses an INDEPENDENT pair beside a
      proven / measured relation; this is the manifest's own defence, so a pair
      that omits the relation joining its sources cannot relabel a recorded
      dependence as independence (#1601 review). A MEASURED relation counts only
      when its latest measurement shows positive dependence
      (``source_census.relation_dependence_category`` -- the SAME rule the
      validator reads; ``dlf-ktc-independence``, residual -0.447, counts as
      nothing). A data-use relation joins through the owner's
      ``source_census.relation_reach`` (one identity hop from its members), so
      ``fn-uses-ktc-data`` reaches the ``ktcTrades`` family as well as
      ``ktcCrowd``;
    * fail closed: an invalid / unreadable registry, an unregistered holdout, a
      family with no reconciled pair or joining relation, or a pair with a null
      category -> UNKNOWN.
    """
    out: list[LineageDependence] = []
    peers = _sc.identity_peers(lineage.relations)
    for fam in sorted(trainers_by_family):
        trainer_keys = set(trainers_by_family[fam])
        if not lineage.valid:
            out.append(LineageDependence(source_key or "", fam, LINEAGE_UNKNOWN, "lineage_invalid"))
            continue
        if source_key is None:
            out.append(LineageDependence("", fam, LINEAGE_UNKNOWN, "holdout_unregistered"))
            continue
        found: list[tuple[str, str, tuple[str, ...], str]] = []
        for pair in lineage.pairs:
            srcs = [str(x) for x in (pair.get("sources") or [])]
            if source_key not in srcs:
                continue
            counter = tuple(
                sorted(
                    x
                    for x in srcs
                    if x != source_key
                    and family_of(x) == fam
                    and _pair_speaks_for(pair, source_key, x, lineage)
                )
            )
            if not counter:
                continue
            pid = str(pair.get("id"))
            cat = pair.get("category")
            if cat is None:
                why = str(pair.get("unknownReason") or "unstated")
                found.append((LINEAGE_UNKNOWN, pid, counter, f"null_category:{why}"))
            elif cat not in _CATEGORY_REASON:
                found.append((LINEAGE_UNKNOWN, pid, counter, f"unknown_category:{cat}"))
            elif cat == LINEAGE_INDEPENDENT and not (set(counter) & trainer_keys):
                continue
            else:
                found.append((str(cat), pid, counter, _CATEGORY_REASON[str(cat)]))
        for rid, rel in sorted(lineage.relations.items()):
            # The owner's one dependence rule: a measured relation whose latest
            # measurement shows no positive dependence counts as nothing.
            rel_cat = _sc.relation_dependence_category(rel)
            if rel_cat not in _CATEGORY_REASON:
                continue
            rel_srcs = {str(x) for x in (rel.get("sources") or [])}
            # Data use reaches one identity hop from its members (the owner's
            # relation_reach): FN using ktcCrowdSfTep data is evidence about FN
            # versus ktcTradesSfTep, i.e. the ktcTrades family too.  Other kinds
            # reach exactly their members.
            rel_reach = _sc.relation_reach(rel, peers)
            if source_key in rel_srcs:
                others = rel_reach
            elif source_key in rel_reach:
                others = rel_srcs
            else:
                continue
            counter = tuple(sorted(x for x in others if x != source_key and family_of(x) == fam))
            if counter:
                found.append(
                    (
                        rel_cat,
                        f"{_RELATION_TAG}{rid}",
                        counter,
                        f"relation_{_CATEGORY_REASON[rel_cat]}",
                    )
                )
        if not found:
            out.append(LineageDependence(source_key, fam, LINEAGE_UNKNOWN, "no_reconciled_pair"))
            continue
        top = max(_CATEGORY_SEVERITY[c] for c, _, _, _ in found)
        winners = [f for f in found if _CATEGORY_SEVERITY[f[0]] == top]
        pair_ids = tuple(sorted({w[1] for w in winners if not w[1].startswith(_RELATION_TAG)}))
        rel_ids = tuple(
            sorted({w[1][len(_RELATION_TAG) :] for w in winners if w[1].startswith(_RELATION_TAG)})
        )
        deciding_relations = set(rel_ids)
        for pair in lineage.pairs:
            if str(pair.get("id")) in pair_ids:
                deciding_relations.update(str(r) for r in (pair.get("relations") or []))
        measurements: dict[str, dict[str, Any]] = {}
        for rid in sorted(deciding_relations):
            rel = lineage.relations.get(rid)
            m = _current_measurement(rel) if rel is not None else None
            if m is not None:
                measurements[rid] = m
        out.append(
            LineageDependence(
                source_key=source_key,
                trainer_family=fam,
                category=winners[0][0],
                reason=";".join(sorted({w[3] for w in winners})),
                pairs=pair_ids,
                counterparts=tuple(sorted({k for w in winners for k in w[2]})),
                relations=rel_ids,
                current_measurements=measurements,
            )
        )
    return tuple(out)


@dataclass(frozen=True)
class HoldoutPolicy:
    #: ``retain_and_report``: a holdout that is not lineage-independent of every
    #: training family (MEASURED / SUSPECTED / UNKNOWN) still scores, tagged, and
    #: is left out of ``independentCriterion``. ``exclude``: it is removed from
    #: the split. PROVEN common ancestry is excluded under either policy. (The
    #: field keeps its historical name: it is a recorded policy key.)
    measured_dependence: str = "retain_and_report"

    def __post_init__(self) -> None:
        if self.measured_dependence not in ("retain_and_report", "exclude"):
            raise ManifestError(f"unknown measured-dependence policy {self.measured_dependence!r}")


@dataclass(frozen=True)
class TrainingPolicy:
    allow_rank_voter_native_values: bool = True
    holdout: HoldoutPolicy = field(default_factory=HoldoutPolicy)

    def to_dict(self) -> dict[str, Any]:
        return {
            "allowRankVoterNativeValues": self.allow_rank_voter_native_values,
            "holdoutMeasuredDependence": self.holdout.measured_dependence,
        }


_KTC_BASE_GAME_TYPE_EVIDENCE = (
    "legacy KTC dynasty Superflex Crowd capture written by the same Dynasty Scraper "
    "KTC scrape as ktcSfTep (data_contract._SOURCE_CSV_PATHS); declared a historical "
    "KTC Crowd calibration state by src/sources/ktc_market.KTC_HISTORICAL_MARKET_KEYS"
)

#: The declared boards. Membership is the methodology as it stood before this
#: unit, minus the owner-mandated repairs (Fantasy Navigator stays declared as a
#: holdout so its EXCLUSION is derived and visible, not silently dropped).
_DEFAULT_SPECS: tuple[BoardSpec, ...] = (
    # OFFENSE trainers.
    BoardSpec(
        "KTC",
        "ktc",
        "OFFENSE",
        ROLE_TRAIN,
        "value",
        game_type_evidence=_KTC_BASE_GAME_TYPE_EVIDENCE,
        note="KTC Crowd lineage, base calibration; H1 (train on live TE++ voters) deferred",
    ),
    BoardSpec("DynastyDaddy", "dynastyDaddySf", "OFFENSE", ROLE_TRAIN, "value"),
    BoardSpec("DynastyNerds", "dynastyNerdsSfTep", "OFFENSE", ROLE_TRAIN, "Value"),
    BoardSpec("YahooBoone", "yahooBoone", "OFFENSE", ROLE_TRAIN, "boone_value"),
    BoardSpec("Fitzmaurice", "fantasyProsFitzmaurice", "OFFENSE", ROLE_TRAIN, "value"),
    BoardSpec("DraftSharks", "draftSharks", "OFFENSE", ROLE_TRAIN, "3D Value +"),
    # OFFENSE holdouts.
    BoardSpec("FantasyCalc", "fantasyCalc", "OFFENSE", ROLE_HOLDOUT, "value"),
    BoardSpec("OTCFFB", "otcffbSf", "OFFENSE", ROLE_HOLDOUT, "value"),
    BoardSpec("PFKDynasty", "pfkDynasty", "OFFENSE", ROLE_HOLDOUT, "value"),
    BoardSpec("FantasyNavigator", "fantasyNavigatorSf", "OFFENSE", ROLE_HOLDOUT, "value"),
    # GLOBAL trainers (cross-universe value scales).
    BoardSpec(
        "IDPTradeCalc", "idpTradeCalc", "GLOBAL", ROLE_TRAIN, "value", universe="offense+idp"
    ),
    BoardSpec(
        "DraftSharks-Combined",
        "draftSharks",
        "GLOBAL",
        ROLE_TRAIN,
        "3D Value +",
        loader=LOADER_CSV_CONCAT,
        concat_keys=("draftSharks", "draftSharksIdp"),
        universe="offense+idp",
    ),
    # IDP trainers.
    BoardSpec(
        "IDPTradeCalc-IDP",
        "idpTradeCalc",
        "IDP",
        ROLE_TRAIN,
        "idpTradeCalc",
        loader=LOADER_SNAPSHOT_IDP,
        universe="idp",
    ),
    BoardSpec("DraftSharks-IDP", "draftSharksIdp", "IDP", ROLE_TRAIN, "3D Value +", universe="idp"),
    # ROOKIE trainers (refit tooling only; ROOKIE is not routed at serve time).
    BoardSpec(
        "KTC-Rookie",
        "ktc",
        "ROOKIE",
        ROLE_TRAIN,
        "ktc",
        loader=LOADER_SNAPSHOT_ROOKIE,
        universe="rookies",
        game_type_evidence=_KTC_BASE_GAME_TYPE_EVIDENCE,
    ),
    BoardSpec(
        "IDPTC-Rookie",
        "idpTradeCalc",
        "ROOKIE",
        ROLE_TRAIN,
        "idpTradeCalc",
        loader=LOADER_SNAPSHOT_ROOKIE,
        universe="rookies",
    ),
    BoardSpec(
        "Boone-Rookie",
        "yahooBoone",
        "ROOKIE",
        ROLE_TRAIN,
        "yahooBoone",
        loader=LOADER_SNAPSHOT_ROOKIE,
        universe="rookies",
        note="rank-signal source: its snapshot field is a synthetic rank encoding",
    ),
    BoardSpec(
        "Fitzmaurice-Rookie",
        "fantasyProsFitzmaurice",
        "ROOKIE",
        ROLE_TRAIN,
        "fantasyProsFitzmaurice",
        loader=LOADER_SNAPSHOT_ROOKIE,
        universe="rookies",
        note="rank-signal source: its snapshot field is a synthetic rank encoding",
    ),
    BoardSpec(
        "DraftSharks-Rookie",
        "draftSharks",
        "ROOKIE",
        ROLE_TRAIN,
        "draftSharks",
        loader=LOADER_SNAPSHOT_ROOKIE,
        universe="rookies",
    ),
)

_H_AUDIT = "docs/valuation/HILL_SOURCE_ALIGNMENT_AUDIT_2026-09-24.md"

#: Every registered source that is NOT a declared Hill board, with the reason.
NOT_HILL_BOARDS: dict[str, str] = {
    "ktcSfTep": "historical KTC Crowd TE++ capture; same ktcCrowd family as the KTC trainer",
    "ktcCrowdSfTep": (
        "live value voter, eligible native values, NOT selected: training on the live "
        f"KTC TE++ voters is owner decision H1 ({_H_AUDIT}), deferred"
    ),
    "ktcTradesSfTep": (
        "live value voter, eligible native values, NOT selected: KTC Trades as trainer "
        f"or holdout is owner decision H2 ({_H_AUDIT}), deferred"
    ),
    KTC_MARKET_KEY: "KTC Market: benchmark only, never a vote, never Hill evidence",
    "dlfSf": "rank-only expert board: contributes order, never spacing",
    "dlfRookieSf": "rank-only rookie board: contributes order, never spacing",
    "dlfIdp": "rank-only IDP board: contributes order, never spacing",
    "dlfRookieIdp": "rank-only IDP rookie board: contributes order, never spacing",
    "idpShowCombined": "rank-only (trade value is pick-equivalent text): order, never spacing",
    "fantasyProsSf": "rank-only consensus board: contributes order, never spacing",
    "fantasyProsIdp": "rank-only consensus board: contributes order, never spacing",
    "flockFantasySf": "rank-only expert board: contributes order, never spacing",
    "flockFantasySfRookies": "rank-only rookie board: contributes order, never spacing",
}


# ── the registry, read-only ─────────────────────────────────────────────────


@dataclass(frozen=True)
class RegistryView:
    """The source-authority facts the manifest derives from."""

    csv_paths: Mapping[str, str]
    csv_signals: Mapping[str, str]
    ranking_game_types: Mapping[str, str | None]
    value_based: frozenset[str]
    non_voting: frozenset[str]
    benchmark: frozenset[str]
    family_of: Callable[[str], str]

    def live_role(self, key: str) -> str:
        if key in self.benchmark:
            return LIVE_BENCHMARK
        if key in self.value_based:
            return LIVE_VALUE_VOTER
        if key in self.ranking_game_types:
            return LIVE_RANK_VOTER
        if key in self.non_voting:
            return LIVE_NON_VOTING
        return LIVE_UNREGISTERED


def registry_view() -> RegistryView:
    """Read the live source registry. Imported lazily: ``data_contract`` imports
    this package (for its provenance stamp) inside a function, never at module
    scope, so there is no cycle either way."""
    from src.api import data_contract as dc  # noqa: PLC0415
    from src.sources.ktc_market import KTC_MARKET_KEY  # noqa: PLC0415

    paths: dict[str, str] = {}
    signals: dict[str, str] = {}
    for key, cfg in dc._SOURCE_CSV_PATHS.items():
        if isinstance(cfg, str):
            paths[key], signals[key] = cfg, "value"
        elif isinstance(cfg, dict):
            paths[key] = str(cfg["path"])
            signals[key] = str(cfg.get("signal") or "value").lower()
    return RegistryView(
        csv_paths=paths,
        csv_signals=signals,
        ranking_game_types={
            str(s["key"]): s.get("game_type") for s in dc._RANKING_SOURCES if s.get("key")
        },
        value_based=frozenset(dc._VALUE_BASED_SOURCES),
        non_voting=frozenset(dc._NON_VOTING_SOURCE_CSV_KEYS),
        benchmark=frozenset({KTC_MARKET_KEY}),
        family_of=dc.correlation_group_for,
    )


# ── the derived manifest ────────────────────────────────────────────────────


@dataclass(frozen=True)
class ManifestBoard:
    label: str
    source_key: str
    scope: str
    role: str
    requested_role: str
    loader: str
    value_column: str | None
    path_keys: tuple[str, ...]
    paths: tuple[str, ...]
    csv_signal: str
    live_role: str
    spacing_evidence: str
    family: str
    game_type: str
    population: str
    universe: str
    exclusion_reason: str | None = None
    #: One entry per training family of the scope (holdouts only), from the
    #: lineage owner. Empty for trainers and for boards excluded before lineage.
    lineage_dependence: tuple[LineageDependence, ...] = ()
    note: str = ""

    @property
    def measured_dependence(self) -> tuple[LineageDependence, ...]:
        """The MEASURED_DEPENDENCE subset (the historical ``measuredDependence`` view)."""
        return tuple(d for d in self.lineage_dependence if d.category == LINEAGE_MEASURED)

    @property
    def dependent_families(self) -> tuple[str, ...]:
        """Training families this board is NOT lineage-independent of."""
        return tuple(sorted(d.trainer_family for d in self.lineage_dependence if not d.independent))

    @property
    def lineage_independent(self) -> bool:
        """Independent of EVERY training family. No entries is not independence."""
        return bool(self.lineage_dependence) and all(d.independent for d in self.lineage_dependence)

    def to_dict(self) -> dict[str, Any]:
        return {
            "label": self.label,
            "sourceKey": self.source_key,
            "scope": self.scope,
            "role": self.role,
            "requestedRole": self.requested_role,
            "loader": self.loader,
            "valueColumn": self.value_column,
            "paths": list(self.paths),
            "csvSignal": self.csv_signal,
            "liveRole": self.live_role,
            "spacingEvidence": self.spacing_evidence,
            "family": self.family,
            "gameType": self.game_type,
            "population": self.population,
            "universe": self.universe,
            "exclusionReason": self.exclusion_reason,
            "lineageIndependent": self.lineage_independent,
            "lineageDependence": [d.to_dict() for d in self.lineage_dependence],
        }


@dataclass(frozen=True)
class TrainingManifest:
    boards: tuple[ManifestBoard, ...]
    policy: TrainingPolicy
    #: The lineage registry the holdout labels were derived from. Recorded in
    #: ``to_dict`` as provenance; NOT inside ``manifest_hash`` (see ``LINEAGE_REL``).
    lineage: LineageView = field(default_factory=lambda: LineageView(LINEAGE_REL, None, False, ()))

    def _select(self, scope: str, role: str) -> tuple[ManifestBoard, ...]:
        return tuple(b for b in self.boards if b.scope == scope and b.role == role)

    def trainers(self, scope: str) -> tuple[ManifestBoard, ...]:
        return self._select(scope, ROLE_TRAIN)

    def holdouts(self, scope: str) -> tuple[ManifestBoard, ...]:
        return self._select(scope, ROLE_HOLDOUT)

    def excluded(self, scope: str) -> tuple[ManifestBoard, ...]:
        return self._select(scope, ROLE_EXCLUDED)

    def training_families(self, scope: str) -> set[str]:
        return {b.family for b in self.trainers(scope)}

    def holdout_families(self, scope: str) -> set[str]:
        return {b.family for b in self.holdouts(scope)}

    def csv_table(self, scope: str, role: str) -> dict[str, tuple[str, str]]:
        """``{label: (path, value_column)}`` for the plain-CSV boards of one role.

        The shape the fitter and holdout have always consumed, now derived."""
        return {
            b.label: (b.paths[0], str(b.value_column))
            for b in self._select(scope, role)
            if b.loader == LOADER_CSV
        }

    def board(self, scope: str, label: str) -> ManifestBoard:
        for b in self.boards:
            if b.scope == scope and b.label == label:
                return b
        raise KeyError((scope, label))

    def board_for_path(self, rel_path: str) -> ManifestBoard | None:
        for b in self.boards:
            if rel_path in b.paths:
                return b
        return None

    def input_paths(self) -> dict[str, ManifestBoard]:
        """Every file a trainer or holdout reads, keyed by repo-relative path."""
        out: dict[str, ManifestBoard] = {}
        for b in self.boards:
            if b.role == ROLE_EXCLUDED:
                continue
            for rel in b.paths:
                out.setdefault(rel, b)
        return dict(sorted(out.items()))

    def to_dict(self) -> dict[str, Any]:
        return {
            "schemaVersion": MANIFEST_SCHEMA_VERSION,
            "substrateVersion": SUBSTRATE_VERSION,
            "fitTopN": FIT_TOP_N,
            "policy": self.policy.to_dict(),
            "lineage": self.lineage.to_dict(),
            "boards": [b.to_dict() for b in sorted(self.boards, key=lambda b: (b.scope, b.label))],
        }

    def hash_payload(self) -> dict[str, Any]:
        """``to_dict`` minus lineage provenance: what ``manifest_hash`` covers.

        The lineage file's identity is dropped and each board's lineage entries
        keep only ``_HASHED_DEPENDENCE_FIELDS``, so the hash moves exactly when a
        derived holdout label the fit or evaluation reads moves."""
        blob = self.to_dict()
        blob.pop("lineage")
        for b in blob["boards"]:
            b["lineageDependence"] = [
                {k: d[k] for k in _HASHED_DEPENDENCE_FIELDS} for d in b["lineageDependence"]
            ]
        return blob

    def manifest_hash(self) -> str:
        return hashlib.sha256(_canonical_json(self.hash_payload()).encode("utf-8")).hexdigest()


def _canonical_json(obj: Any) -> str:
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=True)


def _is_rank_column(column: str) -> bool:
    return "".join(ch for ch in column.lower() if ch.isalnum()) in _RANK_COLUMN_TOKENS


def _derive(spec: BoardSpec, reg: RegistryView, policy: TrainingPolicy) -> ManifestBoard:
    if spec.scope not in SCOPES:
        raise ManifestError(f"{spec.label}: unknown scope {spec.scope!r}")
    if spec.requested_role not in (ROLE_TRAIN, ROLE_HOLDOUT):
        raise ManifestError(f"{spec.label}: requested role must be train or holdout")

    key = spec.source_key
    path_keys = spec.concat_keys if spec.loader == LOADER_CSV_CONCAT else (key,)
    if spec.loader in SNAPSHOT_LOADERS:
        path_keys = ()
    for pk in (key, *path_keys):
        if pk not in reg.csv_paths:
            raise ManifestError(f"{spec.label}: {pk!r} is not a registered source CSV")
    paths = tuple(reg.csv_paths[pk] for pk in path_keys)

    family = reg.family_of(key)
    for pk in path_keys:
        if reg.family_of(pk) != family:
            raise ManifestError(f"{spec.label}: concatenated boards span provider families")

    # Spacing evidence.
    if spec.loader in SNAPSHOT_LOADERS:
        spacing = SPACING_NATIVE_VALUE if reg.csv_signals.get(key) == "value" else SPACING_SYNTHETIC
    elif spec.value_column is None:
        spacing = SPACING_RANK_ONLY
    elif _is_rank_column(spec.value_column):
        raise ManifestError(
            f"{spec.label}: {spec.value_column!r} is a rank column; an ordinal cannot be "
            "declared as native value spacing"
        )
    else:
        spacing = SPACING_NATIVE_VALUE

    live_role = reg.live_role(key)
    if key in reg.ranking_game_types:
        game_type = str(reg.ranking_game_types[key] or "UNKNOWN")
    elif spec.game_type_evidence.strip():
        game_type = "DYNASTY"
    else:
        game_type = "UNKNOWN"

    reason: str | None = None
    if live_role == LIVE_BENCHMARK:
        reason = "benchmark_only: never Hill evidence"
    elif game_type != "DYNASTY":
        reason = f"game_type_unverified:{game_type}"
    elif spacing == SPACING_RANK_ONLY:
        reason = "rank_only: contributes order, never spacing"
    elif spacing == SPACING_SYNTHETIC:
        reason = "synthetic_rank_encoding: snapshot field of a rank-signal source"
    elif (
        spec.requested_role == ROLE_TRAIN
        and not policy.allow_rank_voter_native_values
        and live_role == LIVE_RANK_VOTER
    ):
        reason = "rank_voter_native_values_disallowed_by_policy"

    return ManifestBoard(
        label=spec.label,
        source_key=key,
        scope=spec.scope,
        role=ROLE_EXCLUDED if reason else spec.requested_role,
        requested_role=spec.requested_role,
        loader=spec.loader,
        value_column=spec.value_column,
        path_keys=path_keys,
        paths=paths,
        csv_signal=reg.csv_signals.get(key, ""),
        live_role=live_role,
        spacing_evidence=spacing,
        family=family,
        game_type=game_type,
        population=POPULATION_PLAYERS_ONLY,
        universe=spec.universe,
        exclusion_reason=reason,
        note=spec.note,
    )


def build_manifest(
    *,
    specs: Iterable[BoardSpec] | None = None,
    lineage: LineageView | None = None,
    policy: TrainingPolicy | None = None,
    registry: RegistryView | None = None,
) -> TrainingManifest:
    reg = registry or registry_view()
    pol = policy or TrainingPolicy()
    lin = lineage if lineage is not None else default_lineage_view()
    boards = [_derive(s, reg, pol) for s in (_DEFAULT_SPECS if specs is None else specs)]

    seen: set[tuple[str, str]] = set()
    for b in boards:
        if (b.scope, b.label) in seen:
            raise ManifestError(f"duplicate board label {b.label!r} in scope {b.scope}")
        seen.add((b.scope, b.label))

    out: list[ManifestBoard] = []
    for scope in SCOPES:
        scoped = [b for b in boards if b.scope == scope]
        train_families: dict[str, str] = {}
        trainer_keys: dict[str, set[str]] = {}
        for b in scoped:
            if b.role != ROLE_TRAIN:
                continue
            if b.family in train_families:
                raise ManifestError(
                    f"family {b.family!r} trains twice in {scope} ({train_families[b.family]} "
                    f"and {b.label}); same-source calibration states are one vote"
                )
            train_families[b.family] = b.label
            trainer_keys.setdefault(b.family, set()).update(trainer_lineage_keys(b))
        for b in scoped:
            if b.role != ROLE_HOLDOUT:
                out.append(b)
                continue
            if b.family in train_families:
                out.append(
                    replace(
                        b,
                        role=ROLE_EXCLUDED,
                        exclusion_reason=(
                            f"confirmed_common_ancestry:{b.family} "
                            f"(trains via {train_families[b.family]})"
                        ),
                    )
                )
                continue
            tags = holdout_lineage(b.source_key, trainer_keys, lineage=lin, family_of=reg.family_of)
            proven = [d for d in tags if d.category == LINEAGE_PROVEN]
            if proven:
                # Reconciled PROVEN_COMMON_ANCESTRY across families is the same
                # statement as a shared family: refused under either policy.
                out.append(
                    replace(
                        b,
                        role=ROLE_EXCLUDED,
                        lineage_dependence=tags,
                        exclusion_reason="confirmed_common_ancestry:lineage:"
                        + ",".join(sorted({p for d in proven for p in d.pairs})),
                    )
                )
                continue
            dependent = [d for d in tags if not d.independent]
            if dependent and pol.holdout.measured_dependence == "exclude":
                out.append(
                    replace(
                        b,
                        role=ROLE_EXCLUDED,
                        lineage_dependence=tags,
                        exclusion_reason="lineage_dependence:"
                        + ",".join(f"{d.trainer_family}={d.category}" for d in dependent),
                    )
                )
                continue
            out.append(replace(b, lineage_dependence=tags))
    return TrainingManifest(boards=tuple(out), policy=pol, lineage=lin)


def trainer_lineage_keys(board: ManifestBoard) -> frozenset[str]:
    """The source keys a trainer board stands for in lineage lookups.

    ``holdout.evaluate_offense_master`` derives the same set from file paths
    (``source_key_for_path``); ``tests/model_registry`` pins that the two agree
    for every CSV trainer."""
    return frozenset({board.source_key, *board.path_keys})


@lru_cache(maxsize=1)
def default_manifest() -> TrainingManifest:
    return build_manifest()


def _norm_rel(rel_path: str) -> str:
    return str(rel_path).replace("\\", "/").lstrip("./")


@lru_cache(maxsize=1)
def _path_index() -> dict[str, str]:
    """``{repo-relative CSV path: source key}`` from the registry."""
    return {_norm_rel(p): k for k, p in registry_view().csv_paths.items()}


def source_key_for_path(rel_path: str) -> str | None:
    return _path_index().get(_norm_rel(rel_path))


def family_for_path(rel_path: str) -> str:
    """The B10 provider family of the registered source at ``rel_path``.

    A path the registry does not know is its own singleton family: shared
    ancestry that cannot be proven is not assumed."""
    key = source_key_for_path(rel_path)
    if key is None:
        return f"unregistered:{_norm_rel(rel_path)}"
    return registry_view().family_of(key)


def unclassified_source_keys(registry: RegistryView | None = None) -> set[str]:
    """Registered sources that are neither a declared Hill board nor listed in
    ``NOT_HILL_BOARDS`` — must be empty."""
    reg = registry or registry_view()
    declared = {s.source_key for s in _DEFAULT_SPECS} | {
        k for s in _DEFAULT_SPECS for k in s.concat_keys
    }
    known = declared | set(NOT_HILL_BOARDS)
    return (set(reg.csv_paths) | set(reg.ranking_game_types)) - known


# ── the population rule: one loader for every trainer and holdout ───────────


@dataclass(frozen=True)
class BoardValues:
    names: tuple[str, ...]
    values: tuple[float, ...]
    rows_read: int
    picks_dropped: int
    nonpositive_dropped: int
    unparsable: int

    def to_pin(self) -> dict[str, int]:
        return {
            "rowsRead": self.rows_read,
            "picksDropped": self.picks_dropped,
            "nonPositiveDropped": self.nonpositive_dropped,
            "unparsable": self.unparsable,
            "playerRows": len(self.values),
        }


def _first(row: Mapping[str, Any], columns: tuple[str, ...]) -> str:
    for c in columns:
        v = row.get(c)
        if v not in (None, ""):
            return str(v)
    return ""


def is_training_pick_row(row: Mapping[str, Any]) -> bool:
    """A pick row may never enter a Hill training or holdout population."""
    if is_pick_name(_first(row, _NAME_COLUMNS)):
        return True
    return _first(row, _POSITION_COLUMNS).strip().upper() == "PICK"


def load_board_values(path: Path, column: str) -> BoardValues:
    """Players-only positive values from ``column``, descending (ties keep file order).

    Raises :class:`MissingColumnError` when ``column`` is not in the header. A
    present column with an empty cell is a row-level non-positive value; an
    absent column is not a board of zeros."""
    pairs: list[tuple[str, float]] = []
    rows = picks = nonpos = bad = 0
    with path.open(newline="", encoding="utf-8-sig") as f:
        reader = csv.DictReader(f)
        header = reader.fieldnames or []
        if column not in header:
            raise MissingColumnError(path, column, header)
        for row in reader:
            rows += 1
            if is_training_pick_row(row):
                picks += 1
                continue
            raw = row.get(column)
            try:
                v = float(raw) if raw not in (None, "") else 0.0
            except (TypeError, ValueError):
                bad += 1
                continue
            if v > 0:
                pairs.append((_first(row, _NAME_COLUMNS), v))
            else:
                nonpos += 1
    pairs.sort(key=lambda p: -p[1])
    return BoardValues(
        names=tuple(n for n, _ in pairs),
        values=tuple(v for _, v in pairs),
        rows_read=rows,
        picks_dropped=picks,
        nonpositive_dropped=nonpos,
        unparsable=bad,
    )
