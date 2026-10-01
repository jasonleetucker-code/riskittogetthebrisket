"""Source trust census — one executable inventory of every dynasty source.

Batch 3 Unit A (``docs/EXECUTION_PLAN.md`` -> "Valuation Trust Program —
Batch 3").  Answers, for EVERY registered canonical source and every relevant
non-voting benchmark / second opinion: who publishes it, what it covers, how
it enters the pipeline, which family it votes in, how much authority it
carries right now and why, how current it is on each clock, what
point-in-time history exists for it, whether a clean out-of-sample evaluation
is currently possible, and what evidence about it exists.

Design rules (load-bearing):

* **Generated, not hand-maintained.**  Registration, families, weights,
  freshness, health, coverage, clocks, board coverage and archive depth are
  read from the canonical owners at census time: ``_RANKING_SOURCES`` /
  ``_VALUE_BASED_SOURCES`` / ``_NON_VOTING_SOURCE_CSV_KEYS`` /
  ``_RETIRED_SOURCE_CORRELATION_GROUPS`` / ``_SOURCE_CSV_PATHS``
  (``src/api/data_contract.py``, imported READ-ONLY), the built contract's own
  ``sourceWeighting`` block and per-row ``sourceRankMeta`` stamps,
  ``src/sources/freshness.py`` + dataset-state files, fetch stamps, the CSVs'
  git history, the export archive and the temporal ledger (``src/history``).
  Only what cannot be derived — provider identity, evidence basis, recorded
  ancestry/dependence and recorded defects — lives in ONE small registry,
  ``config/sources/source_lineage.json``, every entry carrying evidence
  pointers and a ``proven`` / ``measured`` / ``suspected`` classification.
* **No subjective score.**  Trust is an enumerated EVIDENCE STATE describing
  what has been measured about a source, never a number on a quality scale.
* **Missing is never zero.**  Every ``None`` in a source entry carries a
  machine-readable reason in that entry's ``unknown`` map, keyed by the
  field's dotted path; :func:`build_census` refuses (raises) on a ``None``
  without one, so the property is structural rather than a convention.
* **Effective authority is the pipeline's own.**  It is read from the
  ``appliedWeight`` the canonical pipeline stamped on each row, cross-checked
  against the contract's ``sourceWeighting`` summary; nothing here recomputes
  a weight.

Pure core: :func:`build_census` (inputs -> census dict) and
:func:`census_markdown`.  The ``load_*`` / ``collect_*`` helpers do the small
amount of IO the CLI (``scripts/source_census.py``) needs and are kept
separate so a future evaluation harness or the value explainer can supply
inputs from anywhere.
"""

from __future__ import annotations

import csv
import json
import subprocess
import zipfile
from collections import Counter, defaultdict
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from src.sources.ktc_market import KTC_MARKET_DERIVED_FROM, KTC_MARKET_KEY

CENSUS_SCHEMA = "source-census/v1"
LINEAGE_SCHEMA = "source-lineage/v1"

REPO_ROOT = Path(__file__).resolve().parents[2]
LINEAGE_PATH = REPO_ROOT / "config" / "sources" / "source_lineage.json"

# ── Closed vocabularies ──────────────────────────────────────────────────

# Lineage categories (owner requirement, Batch 3 Unit G, 2026-10-01).  The
# ONLY four durable answers to "how do these two sources relate"; defined
# here and in ``config/sources/source_lineage.json::categories`` (the two are
# held equal by ``validate_lineage``).  A measurement — however strong —
# never becomes ancestry: PROVEN_COMMON_ANCESTRY needs a supporting relation
# classified ``proven`` (vendor statement, payload structure or code).
# INDEPENDENT_NO_EVIDENCE is the ABSENCE of evidence, not proven independence.
LINEAGE_PROVEN_COMMON_ANCESTRY = "PROVEN_COMMON_ANCESTRY"
LINEAGE_MEASURED_DEPENDENCE = "MEASURED_DEPENDENCE"
LINEAGE_SUSPECTED_DEPENDENCE = "SUSPECTED_DEPENDENCE"
LINEAGE_INDEPENDENT_NO_EVIDENCE = "INDEPENDENT_NO_EVIDENCE"
LINEAGE_CATEGORIES: tuple[str, ...] = (
    LINEAGE_PROVEN_COMMON_ANCESTRY,
    LINEAGE_MEASURED_DEPENDENCE,
    LINEAGE_SUSPECTED_DEPENDENCE,
    LINEAGE_INDEPENDENT_NO_EVIDENCE,
)
#: Relation ``classification`` -> lineage category.
CATEGORY_OF_CLASSIFICATION: dict[str, str] = {
    "proven": LINEAGE_PROVEN_COMMON_ANCESTRY,
    "measured": LINEAGE_MEASURED_DEPENDENCE,
    "suspected": LINEAGE_SUSPECTED_DEPENDENCE,
}
#: Every reconciled pair states its consequence for each of these consumers.
PAIR_IMPLICATION_AXES: tuple[str, ...] = (
    "familyCap",
    "hillHoldout",
    "sourceQualityEvaluation",
    "hillTraining",
    "completedTradeEvaluation",
)
#: Fields a MEASURED_DEPENDENCE pair must pin (method, window, sample size).
MEASUREMENT_REQUIRED_FIELDS: tuple[str, ...] = ("method", "window", "n")
#: A relation's ``statistics.measurements`` history: exactly one ``current``
#: entry (the newest, dated the relation's ``asOf``); older ones are kept as
#: ``superseded`` rather than overwritten (by convention: the validator checks
#: the file's shape, not its history).
MEASUREMENT_CURRENT = "current"
MEASUREMENT_STATUSES: tuple[str, ...] = (MEASUREMENT_CURRENT, "superseded")


def lineage_category(relation: Mapping[str, Any]) -> str | None:
    """The lineage category a recorded relation's CLASSIFICATION names (None =
    unclassified).  A label; whether the relation counts as dependence evidence
    is :func:`relation_dependence_category`."""
    return CATEGORY_OF_CLASSIFICATION.get(str(relation.get("classification")))


#: Proven relation kinds that say two boards are ONE provider's one opinion --
#: calibration states of one crowd, one payload, one page, one provider's
#: boards.  Evidence about one member is evidence about the other, so the pair
#: validator follows exactly one of these hops per side (:func:`_identity_peers`).
#: Every member of such a relation must share one recorded ``provider``
#: (``validate_lineage`` refuses otherwise), so a kind as generic as
#: ``derived_from`` cannot chain two providers.
IDENTITY_RELATION_KINDS: frozenset[str] = frozenset(
    {
        "same_provider_same_payload",
        "calibration_state_of",
        "derived_from",
        "same_provider",
        "same_page_slice",
        "same_provider_distinct_board",
    }
)
#: Proven relation kinds that describe how a SPECIFIC board is built, not a
#: shared opinion: scale borrowing ("not shared opinion", per its own record),
#: use of another provider's data, a vendor aggregate of unnamed inputs, and a
#: same-provider board of a DIFFERENT game type (a redraft / ROS board is never
#: dynasty evidence -- CLAUDE.md source-domain boundaries).  They are never
#: followed as a hop, and contradict an independence verdict only on a pair
#: whose own sources they name.  Every proven relation's kind must sit in
#: exactly one of these two sets (``validate_lineage``), so a new kind is
#: classified deliberately rather than defaulting into either.
NON_IDENTITY_PROVEN_RELATION_KINDS: frozenset[str] = frozenset(
    {
        "scale_borrowed_from",
        "uses_provider_data",
        "derived_from_unnamed_inputs",
        "same_provider_other_game_type",
    }
)
#: Substrings naming a DEPENDENCE statistic in a measurement's ``values``: the
#: leave-pair-out / residual correlations (and partials) the sweeps record.
#: Raw correlations, value ratios and RMSEs are not dependence statistics --
#: every dynasty board correlates ~0.9 with every other on raw rank.
DEPENDENCE_STATISTIC_MARKERS: tuple[str, ...] = ("residual", "partial")


def is_identity_relation(relation: Mapping[str, Any]) -> bool:
    """A proven relation whose kind says its members are one provider's one opinion."""
    return (
        lineage_category(relation) == LINEAGE_PROVEN_COMMON_ANCESTRY
        and str(relation.get("relation")) in IDENTITY_RELATION_KINDS
    )


def measured_positive_dependence(relation: Mapping[str, Any]) -> bool:
    """Whether a MEASURED relation's latest recorded measurement shows positive
    dependence -- the D2 preregistration §5 rule ("measured with a positive
    dependence in its latest recorded measurement").

    Positive means any dependence statistic (``DEPENDENCE_STATISTIC_MARKERS``)
    in the ``current`` measurement is > 0.  Literal, deliberately: the
    leave-pair-out floor is itself about +0.07..+0.10, so a stricter cut would
    be a new threshold, and the +0.10 / +0.30 rule in
    ``OTC_LINEAGE_REMEASURE_2026-10-01.md`` was declared post hoc.  Fails
    closed: no current measurement, or one carrying no dependence statistic,
    counts as positive -- an unmeasured direction is not independence."""
    current = current_measurement(relation)
    if current is None:
        return True
    stats = [
        float(v)
        for k, v in (current.get("values") or {}).items()
        if any(mark in str(k).lower() for mark in DEPENDENCE_STATISTIC_MARKERS)
        and isinstance(v, (int, float))
        and not isinstance(v, bool)
    ]
    if not stats:
        return True
    return any(v > 0 for v in stats)


def relation_dependence_category(relation: Mapping[str, Any]) -> str | None:
    """The category a relation counts as when judging DEPENDENCE (None = none).

    The classification's category, except that a ``measured`` relation whose
    latest measurement shows no positive dependence (``dlf-ktc-independence``,
    residual -0.447; ``draftsharks-contrarian``, -0.505..-0.382) counts as
    nothing: it is measured evidence AGAINST dependence, which none of the four
    categories names (INDEPENDENT_NO_EVIDENCE is the absence of evidence).  Its
    classification and dated history are unchanged.  The one rule both the pair
    validator and the Hill manifest's worst-of read."""
    cat = lineage_category(relation)
    if cat == LINEAGE_MEASURED_DEPENDENCE and not measured_positive_dependence(relation):
        return None
    return cat


VOTING = "VOTING"
REGISTERED_NO_VOTES = "REGISTERED_NO_VOTES_ON_BOARD"
NON_VOTING = "NON_VOTING"
VOTING_STATUSES = frozenset({VOTING, REGISTERED_NO_VOTES, NON_VOTING})

NV_BENCHMARK = "benchmark"
NV_SECOND_OPINION = "second_opinion"
NV_DECLARED = "declared_non_voting"
NV_DOCUMENTED = "documented_non_voting"
NV_UNCLASSIFIED = "UNCLASSIFIED"
NON_VOTING_CLASSES = frozenset(
    {NV_BENCHMARK, NV_SECOND_OPINION, NV_DECLARED, NV_DOCUMENTED, NV_UNCLASSIFIED}
)

#: What has been measured about a source — strongest first.  Deliberately an
#: enumeration of evidence, not a quality scale: two sources in the same state
#: are not "equally good", they have been examined to the same depth.
EVIDENCE_OUT_OF_SAMPLE = "OUT_OF_SAMPLE_EVALUATED"
EVIDENCE_GATE = "ADMISSION_GATE_MEASURED"
EVIDENCE_CALIBRATION = "CALIBRATION_FIT_MEASURED"
EVIDENCE_DEPENDENCE = "DEPENDENCE_MEASURED"
EVIDENCE_UNEVALUATED = "UNEVALUATED"
EVIDENCE_STATES: tuple[str, ...] = (
    EVIDENCE_OUT_OF_SAMPLE,
    EVIDENCE_GATE,
    EVIDENCE_CALIBRATION,
    EVIDENCE_DEPENDENCE,
    EVIDENCE_UNEVALUATED,
)
EVIDENCE_STATE_MEANING = {
    EVIDENCE_OUT_OF_SAMPLE: "usefulness measured against later information, leakage-safe "
    "(produced by the Batch 3 B/C evaluator; no source holds it yet)",
    EVIDENCE_GATE: "a recorded admission-gate measurement exists; not a usefulness evaluation",
    EVIDENCE_CALIBRATION: "value-curve shape fit measured (Hill holdout); not usefulness",
    EVIDENCE_DEPENDENCE: "only dependence / agreement with other sources has been measured",
    EVIDENCE_UNEVALUATED: "nothing about this source's usefulness or dependence is recorded",
}
_EVALUATION_KIND_STATE = {
    "out_of_sample": EVIDENCE_OUT_OF_SAMPLE,
    "admission_gate": EVIDENCE_GATE,
    "calibration_fit": EVIDENCE_CALIBRATION,
}

CONDITION_CURRENT = "CURRENT"
CONDITION_UNMEASURED = "UNMEASURED"
_FRESHNESS_STATE_TO_CONDITION = {
    "ON_SCHEDULE": CONDITION_CURRENT,
    "OVERDUE": "OVERDUE",
    "STALE": "STALE",
    "SEVERELY_STALE": "SEVERELY_STALE",
    "QUARANTINED": "QUARANTINED",
    "UNMEASURED": CONDITION_UNMEASURED,
}
_CONDITION_SEVERITY = {
    CONDITION_CURRENT: 0,
    "OVERDUE": 1,
    "STALE": 2,
    "SEVERELY_STALE": 3,
    "QUARANTINED": 4,
    CONDITION_UNMEASURED: 5,
}

OOS_MET = "DATA_PREREQUISITES_MET"
OOS_BLOCKED = "BLOCKED"
OOS_GLOBAL_BLOCKERS = (
    "NO_PREREGISTERED_LEAKAGE_SAFE_TARGET: target definition and evaluation are Batch 3 "
    "Units B/C (and the completed-trade benchmark is Unit I); until one is preregistered "
    "no source can be CLEANLY evaluated out of sample, whatever its archive holds",
)

#: Top-of-board cut-offs for the coverage report.  Reporting resolution only:
#: nothing reads them to decide a value or a weight.
TOP_OF_BOARD_CUTOFFS: tuple[int, ...] = (50, 100, 200)
UNIVERSES: tuple[str, ...] = ("offense", "idp", "pick")

_VALUE_COLUMNS = ("value", "Value", "boone_value", "3D Value +", "normalizedValue")
_RANK_COLUMNS = ("rank", "Rank", "effectiveRank")


# ── Inputs ───────────────────────────────────────────────────────────────


@dataclass
class CensusInputs:
    """Everything :func:`build_census` reads.  Plain data; no IO happens there."""

    contract: Mapping[str, Any]
    registry: Sequence[Mapping[str, Any]]
    value_based: frozenset[str]
    non_voting_declared: frozenset[str]
    retired_groups: Mapping[str, str]
    csv_paths: Mapping[str, Any]
    lineage: Mapping[str, Any]
    #: Reasons for ingested-but-not-voting CSVs nobody declared in code
    #: (``scripts/source_inventory.KNOWN_NON_VOTING_REASONS`` — passed in, not
    #: copied, so there is one list).
    non_voting_reasons: Mapping[str, str] = field(default_factory=dict)
    on_disk_csv_stems: Sequence[str] = ()
    #: ``SourceWeighting.to_dict()`` for keys the contract's ``sourceWeighting``
    #: block does not cover (non-voting CSVs, second opinions).
    extra_weightings: Mapping[str, Mapping[str, Any] | None] = field(default_factory=dict)
    fetch_stamps: Mapping[str, str | None] = field(default_factory=dict)
    #: ``{key: {subset: number of recorded content-change events}}`` from the
    #: dataset-state files (``changeHistory`` is a rolling window of EVENTS,
    #: not an archive of values).
    dataset_change_events: Mapping[str, Mapping[str, int] | None] = field(default_factory=dict)
    csv_profiles: Mapping[str, Mapping[str, Any] | None] = field(default_factory=dict)
    #: ``{csv file name: [ISO commit times, newest first]}``; ``None`` = not collected.
    git_history: Mapping[str, Sequence[str]] | None = None
    git_history_reason: str | None = None
    #: ``{csv file name: [archive dates]}``; ``None`` = not collected.
    export_archive: Mapping[str, Sequence[str]] | None = None
    export_archive_reason: str | None = None
    #: ``src.history.asof.source_lane_coverage`` output; ``None`` = not queried.
    ledger: Mapping[str, Any] | None = None
    ledger_reason: str | None = None
    #: Source keys the ledger's ``source_value`` lane can EVER hold
    #: (``src/history/record`` + ``src/history/backfill`` restrictions).
    ledger_eligible_keys: frozenset[str] = frozenset()
    #: Second-opinion boards: ``[{sourceKey, displayName, positions, metadata,
    #: state, stateReason, fetchState, fetchReason}]``.
    second_opinions: Sequence[Mapping[str, Any]] = ()
    benchmark_key: str = KTC_MARKET_KEY
    benchmark_derived_from: Sequence[str] = KTC_MARKET_DERIVED_FROM
    pins: Mapping[str, Any] = field(default_factory=dict)
    label: str = "LOCAL"
    generated_at: str | None = None


# ── Helpers ──────────────────────────────────────────────────────────────


class _Entry:
    """A source entry plus the reason behind every ``None`` it holds."""

    def __init__(self, key: str) -> None:
        self.key = key
        self.data: dict[str, Any] = {"key": key}
        self.unknown: dict[str, str] = {}

    def set(self, path: str, value: Any, reason: str | None = None) -> None:
        node = self.data
        parts = path.split(".")
        for p in parts[:-1]:
            node = node.setdefault(p, {})
        node[parts[-1]] = value
        if value is None:
            if not reason:
                raise ValueError(f"{self.key}: {path} is None without a reason")
            self.unknown[path] = reason

    def finish(self) -> dict[str, Any]:
        out = dict(self.data)
        out["unknown"] = dict(sorted(self.unknown.items()))
        missing = [p for p in none_paths(out) if p not in self.unknown]
        if missing:
            raise ValueError(f"{self.key}: None without a reason at {missing}")
        return out


def none_paths(entry: Mapping[str, Any], prefix: str = "") -> list[str]:
    """Dotted paths of every ``None`` leaf in ``entry`` (the ``unknown`` map excluded)."""
    out: list[str] = []
    for k, v in entry.items():
        if not prefix and k == "unknown":
            continue
        path = f"{prefix}{k}"
        if v is None:
            out.append(path)
        elif isinstance(v, Mapping):
            out.extend(none_paths(v, f"{path}."))
        elif isinstance(v, list):
            for i, item in enumerate(v):
                if item is None:
                    out.append(f"{path}[{i}]")
                elif isinstance(item, Mapping):
                    out.extend(none_paths(item, f"{path}[{i}]."))
    return out


def _num(v: Any) -> float | None:
    if isinstance(v, bool) or v is None:
        return None
    if isinstance(v, (int, float)):
        return float(v)
    try:
        return float(str(v).strip())
    except (TypeError, ValueError):
        return None


def csv_path_of(key: str, csv_paths: Mapping[str, Any]) -> str:
    spec = csv_paths.get(key)
    if isinstance(spec, str):
        return spec
    if isinstance(spec, Mapping) and spec.get("path"):
        return str(spec["path"])
    return f"CSVs/site_raw/{key}.csv"


def _csv_signal_of(key: str, csv_paths: Mapping[str, Any], value_based: frozenset[str]) -> str:
    spec = csv_paths.get(key)
    if isinstance(spec, Mapping) and spec.get("signal"):
        return str(spec["signal"])
    return "value" if (key in value_based or isinstance(spec, str)) else "unknown"


def _family_of(src: Mapping[str, Any]) -> str:
    return str(src.get("correlation_group") or src.get("key") or "")


def _voted(meta: Mapping[str, Any]) -> bool:
    """Same predicate as ``data_contract._source_weighting_summary``."""
    w = meta.get("appliedWeight")
    return (
        meta.get("contributedToBlend") is not False
        and not meta.get("hampelDropped")
        and isinstance(w, (int, float))
        and not isinstance(w, bool)
        and w > 0
    )


def _date(iso: str | None) -> str | None:
    return iso[:10] if isinstance(iso, str) and len(iso) >= 10 else None


def _days_between(a: str | None, b: str | None) -> int | None:
    from datetime import date

    if not a or not b:
        return None
    try:
        return (date.fromisoformat(b[:10]) - date.fromisoformat(a[:10])).days
    except ValueError:
        return None


# ── Lineage registry ─────────────────────────────────────────────────────


def load_lineage(path: Path | None = None) -> dict[str, Any]:
    return json.loads(Path(path or LINEAGE_PATH).read_text(encoding="utf-8"))


def validate_lineage(lineage: Mapping[str, Any], repo_root: Path = REPO_ROOT) -> list[str]:
    """Structural errors in the lineage registry (empty list = valid)."""
    errors: list[str] = []
    if lineage.get("schema") != LINEAGE_SCHEMA:
        errors.append(f"schema must be {LINEAGE_SCHEMA}")
    classes = set(lineage.get("classifications") or [])
    if classes != {"proven", "measured", "suspected"}:
        errors.append("classifications must be exactly proven/measured/suspected")
    providers = lineage.get("providers") or {}
    bases = set((lineage.get("evidenceBases") or {}).keys())

    def _check_evidence(where: str, ev: Any) -> None:
        if not isinstance(ev, list) or not ev:
            errors.append(f"{where}: evidence must be a non-empty list")
            return
        for p in ev:
            if not (repo_root / str(p)).exists():
                errors.append(f"{where}: evidence path does not exist: {p}")

    for key, s in (lineage.get("sources") or {}).items():
        if s.get("provider") not in providers:
            errors.append(f"sources.{key}: unknown provider {s.get('provider')!r}")
        if s.get("basis") not in bases:
            errors.append(f"sources.{key}: unknown basis {s.get('basis')!r}")
        _check_evidence(f"sources.{key}", s.get("evidence"))
        # A lineage entry may record only a NON-dynasty game type (proven by a
        # relation); DYNASTY is proven by the canonical source registry alone.
        if s.get("gameType") == "DYNASTY":
            errors.append(f"sources.{key}: gameType DYNASTY may only come from the source registry")
        if s.get("gameType") and not s.get("gameTypeEvidence"):
            errors.append(f"sources.{key}: gameType needs gameTypeEvidence")
    ids: set[str] = set()
    for section in ("relations", "evaluations", "defects"):
        for item in lineage.get(section) or []:
            rid = item.get("id")
            if not rid or rid in ids:
                errors.append(f"{section}: missing or duplicate id {rid!r}")
            ids.add(str(rid))
            if not item.get("sources"):
                errors.append(f"{section}.{rid}: sources must be non-empty")
            _check_evidence(f"{section}.{rid}", item.get("evidence"))
            if section == "relations" and item.get("classification") not in classes:
                errors.append(f"relations.{rid}: classification must be one of {sorted(classes)}")
            if section == "relations" and item.get("classification") == "measured":
                if "dependence" not in str(item.get("relation")) and "independence" not in str(
                    item.get("relation")
                ):
                    errors.append(
                        f"relations.{rid}: a measured relation is dependence, not ancestry"
                    )
            if section == "relations" and item.get("classification") == "proven":
                kind = str(item.get("relation"))
                if (kind in IDENTITY_RELATION_KINDS) == (
                    kind in NON_IDENTITY_PROVEN_RELATION_KINDS
                ):
                    errors.append(
                        f"relations.{rid}: proven relation kind {kind!r} must be in exactly one "
                        "of IDENTITY_RELATION_KINDS / NON_IDENTITY_PROVEN_RELATION_KINDS"
                    )
                elif kind in IDENTITY_RELATION_KINDS:
                    provs = {
                        str(((lineage.get("sources") or {}).get(str(x)) or {}).get("provider"))
                        for x in item.get("sources") or []
                    }
                    if len(provs) != 1:
                        errors.append(
                            f"relations.{rid}: identity kind {kind!r} spans providers "
                            f"{sorted(provs)}; an identity link is one provider's one opinion"
                        )
            if section == "evaluations" and item.get("kind") not in _EVALUATION_KIND_STATE:
                errors.append(f"evaluations.{rid}: unknown kind {item.get('kind')!r}")
            if section == "relations" and "statistics" in item:
                errors.extend(_validate_statistics(f"relations.{rid}", item))
    errors.extend(_validate_pairs(lineage, ids, _check_evidence))
    return errors


def _validate_statistics(where: str, relation: Mapping[str, Any]) -> list[str]:
    """A relation's statistics are a DATED HISTORY, never a bare number.

    The 2026-10-01 D2 review found summaries refreshed while flat
    ``statistics`` still carried superseded values (``residualRho`` 0.891 on
    a relation whose summary said "not reproduced").  So: every measurement
    pins its date, method and values; exactly one is ``current``, it is the
    newest, and it carries the relation's own ``asOf``.  Moving ``asOf``
    without also dating a ``current`` entry to match therefore fails.

    This checks the SHAPE of one file at one commit, nothing more.  It
    cannot see history: an in-place edit of an entry's values, or deletion
    of a ``superseded`` entry, passes.  Keeping superseded values is a
    convention this check makes visible, not one it enforces; an
    append-only check against the base commit is a recorded follow-up
    (``docs/sources/integrity/OTC_LINEAGE_REMEASURE_2026-10-01.md``)."""
    from datetime import date

    errors: list[str] = []
    stats = relation.get("statistics")
    if not isinstance(stats, Mapping) or set(stats) != {"measurements"}:
        return [f"{where}: statistics must be exactly {{'measurements': [...]}}"]
    entries = stats["measurements"]
    if not isinstance(entries, list) or not entries:
        return [f"{where}: statistics.measurements must be a non-empty list"]
    dated: list[tuple[str, str]] = []
    for i, m in enumerate(entries):
        at = f"{where}.statistics.measurements[{i}]"
        if not isinstance(m, Mapping):
            errors.append(f"{at}: must be an object")
            continue
        try:
            date.fromisoformat(str(m.get("asOf")))
        except ValueError:
            errors.append(f"{at}: asOf must be an ISO date, got {m.get('asOf')!r}")
            continue
        if m.get("status") not in MEASUREMENT_STATUSES:
            errors.append(f"{at}: status must be one of {list(MEASUREMENT_STATUSES)}")
        if not str(m.get("method") or "").strip():
            errors.append(f"{at}: method required")
        values = m.get("values")
        if not isinstance(values, Mapping) or not values:
            errors.append(f"{at}: values must be a non-empty object")
        elif any(isinstance(v, bool) or not isinstance(v, (int, float)) for v in values.values()):
            errors.append(f"{at}: every value must be a number")
        n = m.get("n")
        if n is not None and (isinstance(n, bool) or not isinstance(n, int) or n <= 0):
            errors.append(f"{at}: n must be an int > 0 or null (unrecorded), got {n!r}")
        dated.append((str(m.get("asOf")), str(m.get("status"))))
    current = [d for d, s in dated if s == MEASUREMENT_CURRENT]
    if len(current) != 1:
        errors.append(f"{where}: exactly one measurement must be current, found {len(current)}")
    else:
        if current[0] != str(relation.get("asOf")):
            errors.append(
                f"{where}: the current measurement ({current[0]}) must carry the relation "
                f"asOf ({relation.get('asOf')})"
            )
        if any(d > current[0] for d, _ in dated):
            errors.append(f"{where}: a superseded measurement is newer than the current one")
    return errors


def _identity_peers(relations: Mapping[Any, Mapping[str, Any]]) -> dict[str, set[str]]:
    """``{source: every source sharing an IDENTITY relation with it}`` -- one hop.

    Only :func:`is_identity_relation` links count (#1601 round-2 review): a
    proven scale-borrowing relation (``rookie-ladder-borrows-reference-scale``)
    is "not shared opinion" by its own record, and following it joined the DLF,
    Flock, KTC and IDPTC groups.  One hop, never the closure."""
    peers: dict[str, set[str]] = {}
    for rel in relations.values():
        if not is_identity_relation(rel):
            continue
        members = {str(x) for x in (rel.get("sources") or [])}
        for m in members:
            peers.setdefault(m, set()).update(members - {m})
    return peers


def _independence_contradictions(
    where: str,
    pair_sources: Sequence[Any],
    relations: Mapping[Any, Mapping[str, Any]],
    identity_peers: Mapping[str, set[str]],
    skip: set[str],
) -> list[str]:
    """Recorded relations that forbid an INDEPENDENT_NO_EVIDENCE pair.

    Absence of evidence cannot coexist with RECORDED evidence, cited or not:
    otherwise a pair that simply omits the relation joining its own sources
    relabels a measured dependence as independence (#1601 review).

    * A proven relation, or a measured one with positive dependence
      (:func:`relation_dependence_category`), contradicts the pair when it
      touches two DIFFERENT pair sources.
    * Opinion evidence travels ONE identity hop per side
      (:func:`_identity_peers`): ``ktc`` is a calibration state of
      ``ktcSfTep``, so a measured PFK~``ktcSfTep`` dependence is evidence about
      PFK~``ktc``.  Measured and identity relations are matched through that
      hop, and never further.
    * A non-identity proven relation (scale borrowing, data use) describes the
      construction of the boards it names, so it is matched on the pair's own
      sources only: DLF's rookie board borrowing KTC's scale says nothing about
      DLF's superflex ranking versus KTC.
    * SUSPECTED relations do not contradict "no evidence"; consumers that need
      the worse verdict (the Hill manifest) take it themselves."""
    direct = [{str(x)} for x in pair_sources]
    reach = [{str(x)} | set(identity_peers.get(str(x), ())) for x in pair_sources]
    out: list[str] = []
    for rid, rel in relations.items():
        if str(rid) in skip:
            continue  # already judged as a supporting relation of this pair
        cat = relation_dependence_category(rel)
        if cat not in (LINEAGE_PROVEN_COMMON_ANCESTRY, LINEAGE_MEASURED_DEPENDENCE):
            continue
        hops = (
            reach if (cat == LINEAGE_MEASURED_DEPENDENCE or is_identity_relation(rel)) else direct
        )
        members = {str(x) for x in (rel.get("sources") or [])}
        joined = any(
            a != b
            for i, ri in enumerate(hops)
            for j, rj in enumerate(hops)
            if i < j
            for a in members & ri
            for b in members & rj
        )
        if joined:
            out.append(
                f"{where}: INDEPENDENT_NO_EVIDENCE contradicts recorded relation {rid!r} "
                f"({rel.get('classification')}) joining the pair's sources"
            )
    return out


def _validate_pairs(lineage: Mapping[str, Any], ids: set[str], check_evidence: Any) -> list[str]:
    """Structural rules for the four-category pair reconciliation."""
    errors: list[str] = []
    declared = lineage.get("categories")
    # A MISSING key is an error too: the config is the second half of the
    # vocabulary, not an optional echo of this module.
    if not isinstance(declared, Mapping) or set(declared) != set(LINEAGE_CATEGORIES):
        errors.append(f"categories must be exactly {list(LINEAGE_CATEGORIES)}")
    relations = {r.get("id"): r for r in lineage.get("relations") or []}
    known_sources = set((lineage.get("sources") or {}).keys())
    identity_peers = _identity_peers(relations)
    for pair in lineage.get("pairReconciliation") or []:
        pid = pair.get("id")
        where = f"pairReconciliation.{pid}"
        if not pid or pid in ids:
            errors.append(f"pairReconciliation: missing or duplicate id {pid!r}")
        ids.add(str(pid))
        srcs = pair.get("sources") or []
        if len(srcs) < 2:
            errors.append(f"{where}: a pair names at least two sources")
        for s in srcs:
            if s not in known_sources:
                errors.append(f"{where}: unknown source {s!r}")
        check_evidence(where, pair.get("evidence"))
        if not pair.get("asOf"):
            errors.append(f"{where}: asOf required")
        cat = pair.get("category")
        if cat is None:
            # UNKNOWN is not a fifth category: it is the absence of a
            # category, and must say why.
            if not pair.get("unknownReason"):
                errors.append(f"{where}: a null category needs unknownReason")
        elif cat not in LINEAGE_CATEGORIES:
            errors.append(f"{where}: category must be one of {list(LINEAGE_CATEGORIES)}")
        supporting = []
        supporting_ids: set[str] = set()
        pair_sources = set(srcs)
        for rid in pair.get("relations") or []:
            if rid not in relations:
                errors.append(f"{where}: unknown relation {rid!r}")
                continue
            # A relation supports THIS pair only if it is about this pair:
            # at least two of its sources must be the pair's own.  Without
            # this a PROVEN (A, B) could cite a relation on (A, C) or (C, D).
            shared = pair_sources & set(relations[rid].get("sources") or [])
            if len(shared) < 2:
                errors.append(
                    f"{where}: relation {rid!r} involves {sorted(shared)} of the pair's "
                    "sources; a supporting relation must involve at least two"
                )
                continue
            supporting.append(relation_dependence_category(relations[rid]))
            supporting_ids.add(str(rid))
        if (
            cat == LINEAGE_PROVEN_COMMON_ANCESTRY
            and LINEAGE_PROVEN_COMMON_ANCESTRY not in supporting
        ):
            errors.append(f"{where}: PROVEN_COMMON_ANCESTRY needs a supporting proven relation")
        if cat == LINEAGE_MEASURED_DEPENDENCE:
            if LINEAGE_MEASURED_DEPENDENCE not in supporting:
                errors.append(f"{where}: MEASURED_DEPENDENCE needs a supporting measured relation")
            meas = pair.get("measurement") or {}
            missing = [f for f in MEASUREMENT_REQUIRED_FIELDS if meas.get(f) in (None, "")]
            if missing:
                errors.append(f"{where}: measurement must pin {missing}")
        meas_any = pair.get("measurement")
        if isinstance(meas_any, Mapping) and meas_any.get("n") is not None:
            n = meas_any["n"]
            # n is a sample size on ANY pair that pins one: a positive int
            # (bool is an int subclass and is refused; 0 measured nothing).
            if isinstance(n, bool) or not isinstance(n, int) or n <= 0:
                errors.append(f"{where}: measurement.n must be an int > 0, got {n!r}")
        if cat == LINEAGE_INDEPENDENT_NO_EVIDENCE and any(
            c in (LINEAGE_PROVEN_COMMON_ANCESTRY, LINEAGE_MEASURED_DEPENDENCE) for c in supporting
        ):
            errors.append(f"{where}: INDEPENDENT_NO_EVIDENCE contradicts a supporting relation")
        if cat == LINEAGE_INDEPENDENT_NO_EVIDENCE:
            errors.extend(
                _independence_contradictions(where, srcs, relations, identity_peers, supporting_ids)
            )
        impl = pair.get("implications") or {}
        missing_axes = [a for a in PAIR_IMPLICATION_AXES if not impl.get(a)]
        if missing_axes:
            errors.append(f"{where}: implications missing {missing_axes}")
    return errors


# ── IO collectors (used by the CLI; never by build_census) ───────────────


def profile_csv(path: Path) -> dict[str, Any] | None:
    """Row count, native value column range and ordinal-tie check for one CSV."""
    if not path.exists():
        return None
    try:
        with path.open(encoding="utf-8", newline="") as fh:
            reader = csv.DictReader(fh)
            columns = list(reader.fieldnames or [])
            rows = list(reader)
    except (OSError, UnicodeDecodeError, csv.Error):
        return None
    vcol = next((c for c in _VALUE_COLUMNS if c in columns), None)
    rcol = next((c for c in _RANK_COLUMNS if c in columns), None)
    values = [_num(r.get(vcol)) for r in rows] if vcol else []
    numeric = [v for v in values if v is not None]
    tied_distinct = None
    if vcol and rcol and numeric:
        groups: dict[float, set[str]] = defaultdict(set)
        sizes: Counter[float] = Counter()
        for r, v in zip(rows, values):
            if v is None:
                continue
            groups[v].add(str(r.get(rcol)))
            sizes[v] += 1
        tied_distinct = sum(
            sizes[v] for v, ranks in groups.items() if sizes[v] > 1 and len(ranks) > 1
        )
    return {
        "rows": len(rows),
        "columns": columns,
        "valueColumn": vcol,
        "rankColumn": rcol,
        "numericValueRows": len(numeric),
        "valueMax": max(numeric) if numeric else None,
        "valueMin": min(numeric) if numeric else None,
        "tiedValueRowsWithDistinctRanks": tied_distinct,
    }


def collect_git_history(
    repo_root: Path = REPO_ROOT, rel_dir: str = "CSVs/site_raw"
) -> dict[str, list[str]] | None:
    """``{csv file name: [commit ISO times, newest first]}`` from ONE ``git log``."""
    try:
        out = subprocess.run(
            ["git", "-C", str(repo_root), "log", "--format=@%cI", "--name-only", "--", rel_dir],
            capture_output=True,
            text=True,
            timeout=120,
        )
    except (OSError, subprocess.TimeoutExpired):
        return None
    if out.returncode != 0:
        return None
    history: dict[str, list[str]] = defaultdict(list)
    current: str | None = None
    for line in out.stdout.splitlines():
        line = line.strip()
        if line.startswith("@"):
            current = line[1:]
        elif line and current:
            history[Path(line).name].append(current)
    return dict(history)


def collect_export_archive(archive_dir: Path) -> dict[str, list[str]] | None:
    """``{site_raw csv name: [archive dates, ascending]}`` from zip name lists."""
    if not archive_dir.is_dir():
        return None
    index: dict[str, list[str]] = defaultdict(list)
    for z in sorted(archive_dir.glob("dynasty_export_*.zip")):
        stamp = z.stem.split("_")[2] if len(z.stem.split("_")) > 2 else ""
        day = f"{stamp[:4]}-{stamp[4:6]}-{stamp[6:8]}" if len(stamp) >= 8 else None
        if day is None:
            continue
        try:
            with zipfile.ZipFile(z) as zf:
                names = zf.namelist()
        except (OSError, zipfile.BadZipFile):
            continue
        for n in names:
            if n.startswith("site_raw/") and n.endswith(".csv"):
                index[Path(n).name].append(day)
    return dict(index)


def read_fetch_stamp(state_dir: Path, key: str) -> str | None:
    """ISO-8601 UTC of ``<key>_last_success`` (stamps are epoch seconds or ISO)."""
    from datetime import datetime, timezone

    p = state_dir / f"{key}_last_success"
    try:
        text = p.read_text(encoding="utf-8").strip()
    except OSError:
        return None
    if text.isdigit():
        return datetime.fromtimestamp(int(text), tz=timezone.utc).isoformat().replace("+00:00", "Z")
    return text or None


# ── Builders ─────────────────────────────────────────────────────────────


def _row_universe(row: Mapping[str, Any]) -> str | None:
    cls = row.get("assetClass")
    return cls if cls in UNIVERSES else None


def _board_index(contract: Mapping[str, Any]) -> dict[str, Any]:
    """One pass over the board: per-source observed/voted counts and stamps."""
    rows = [r for r in (contract.get("playersArray") or []) if isinstance(r, Mapping)]
    by_universe: dict[str, list[Mapping[str, Any]]] = defaultdict(list)
    for r in rows:
        u = _row_universe(r)
        if u:
            by_universe[u].append(r)
    top_sets: dict[str, dict[int, set[int]]] = {}
    for u, urows in by_universe.items():
        priced = sorted(
            (r for r in urows if _num(r.get("rankDerivedValue")) is not None),
            key=lambda r: -float(r["rankDerivedValue"]),
        )
        top_sets[u] = {n: {id(r) for r in priced[:n]} for n in TOP_OF_BOARD_CUTOFFS}

    per: dict[str, dict[str, Any]] = defaultdict(
        lambda: {
            "observed": Counter(),
            "voted": Counter(),
            "applied": defaultdict(float),
            "familyAdj": [],
            "familyCapped": 0,
            "hampel": 0,
            "freshExcluded": 0,
            "paths": Counter(),
            "methods": Counter(),
            "top": defaultdict(Counter),
            "votedTop": defaultdict(Counter),
            "shareSum": 0.0,
        }
    )
    for r in rows:
        u = _row_universe(r)
        meta = r.get("sourceRankMeta") or {}
        if not isinstance(meta, Mapping):
            continue
        voters = {
            k: float(m["appliedWeight"])
            for k, m in meta.items()
            if isinstance(m, Mapping) and _voted(m)
        }
        total = sum(voters.values())
        excluded = set(r.get("freshnessExcludedSources") or [])
        for k, m in meta.items():
            if not isinstance(m, Mapping):
                continue
            p = per[k]
            cols = [u] if u else []
            if r.get("rookie") and u != "pick":
                cols.append("rookie")
            for c in cols:
                p["observed"][c] += 1
            if m.get("valueContributionPath"):
                p["paths"][str(m["valueContributionPath"])] += 1
            if m.get("method"):
                p["methods"][str(m["method"])] += 1
            if m.get("hampelDropped"):
                p["hampel"] += 1
            if k in excluded:
                p["freshExcluded"] += 1
            if u:
                for n in TOP_OF_BOARD_CUTOFFS:
                    if id(r) in top_sets.get(u, {}).get(n, set()):
                        p["top"][u][n] += 1
            if k in voters:
                for c in cols:
                    p["voted"][c] += 1
                if u:
                    p["applied"][u] += voters[k]
                    for n in TOP_OF_BOARD_CUTOFFS:
                        if id(r) in top_sets.get(u, {}).get(n, set()):
                            p["votedTop"][u][n] += 1
                fa = _num(m.get("familyAdjustment"))
                if fa is not None:
                    p["familyAdj"].append(fa)
                    if fa < 1.0:
                        p["familyCapped"] += 1
                if total > 0:
                    p["shareSum"] += voters[k] / total
    universe_sizes = {u: len(by_universe.get(u, [])) for u in UNIVERSES}
    return {"per": per, "universeSizes": universe_sizes, "rows": len(rows)}


def _relations_for(key: str, lineage: Mapping[str, Any]) -> list[Mapping[str, Any]]:
    return [r for r in (lineage.get("relations") or []) if key in (r.get("sources") or [])]


def current_measurement(rel: Mapping[str, Any]) -> dict[str, Any] | None:
    """The relation's current dated measurement (None when it records none)."""
    entries = (rel.get("statistics") or {}).get("measurements") or []
    for m in entries:
        if isinstance(m, Mapping) and m.get("status") == MEASUREMENT_CURRENT:
            return dict(m)
    return None


def _relation_view(rel: Mapping[str, Any], key: str) -> dict[str, Any]:
    """Compact per-source pointer; the full relation is in ``lineageRelations``."""
    out = {
        "id": rel["id"],
        "relation": rel.get("relation"),
        "with": [s for s in rel.get("sources") or [] if s != key],
    }
    current = current_measurement(rel)
    if current is not None:
        # A census entry may hold no unexplained None: an unrecorded sample
        # size is stated as such rather than published as a null.
        if current.get("n") is None:
            current.pop("n", None)
            current["nRecorded"] = False
        out["statistics"] = current
    return {k: v for k, v in out.items() if v is not None}


def _weighting_entry(key: str, inp: CensusInputs) -> tuple[Mapping[str, Any] | None, str | None]:
    sw = ((inp.contract.get("sourceWeighting") or {}).get("sources") or {}).get(key)
    if isinstance(sw, Mapping):
        return sw, None
    extra = inp.extra_weightings.get(key)
    if isinstance(extra, Mapping):
        return extra, None
    if key in inp.extra_weightings:
        return (
            None,
            "no dataset-state file for this key, so freshness/health/coverage are unmeasured",
        )
    return (
        None,
        "not covered by the contract's sourceWeighting block and no dataset state was assessed",
    )


def build_census(inp: CensusInputs) -> dict[str, Any]:
    """The census, as a JSON-ready dict (schema ``source-census/v1``)."""
    lineage = inp.lineage
    lin_sources = lineage.get("sources") or {}
    providers = lineage.get("providers") or {}
    registry = {str(s["key"]): s for s in inp.registry if s.get("key")}
    families: dict[str, list[str]] = defaultdict(list)
    for k, s in registry.items():
        families[_family_of(s)].append(k)
    board = _board_index(inp.contract)
    per = board["per"]
    sw_block = inp.contract.get("sourceWeighting") or {}
    ktc_market = inp.contract.get("ktcMarket") or {}

    so_keys = [str(b["sourceKey"]) for b in inp.second_opinions]
    mapped_files = {Path(csv_path_of(k, inp.csv_paths)).name for k in inp.csv_paths}
    unmapped_disk = {s for s in inp.on_disk_csv_stems if f"{s}.csv" not in mapped_files}
    keys = list(registry)
    for extra in (
        sorted(set(inp.csv_paths) - set(registry)),
        sorted(inp.non_voting_declared - set(registry)),
        sorted(set(inp.retired_groups) - set(registry)),
        sorted(unmapped_disk - set(registry)),
        sorted(set(inp.non_voting_reasons) - set(registry)),
        [inp.benchmark_key],
        so_keys,
    ):
        for k in extra:
            if k not in keys:
                keys.append(k)

    entries = []
    for key in keys:
        src = registry.get(key)
        so = next((b for b in inp.second_opinions if b["sourceKey"] == key), None)
        e = _Entry(key)
        lin = lin_sources.get(key)

        # identity
        if src is not None:
            e.set("displayName", src.get("display_name"), "registry entry carries no display_name")
        elif so is not None:
            e.set("displayName", so.get("displayName"), "second-opinion spec carries no name")
        elif key == inp.benchmark_key:
            e.set("displayName", "KeepTradeCut Market (published Crowd+Trades)")
            e.set("benchmarkDerivedFrom", list(inp.benchmark_derived_from))
        else:
            e.set("displayName", None, "not registered; no canonical display name exists")
        if lin is not None:
            pid = str(lin.get("provider"))
            e.set("provider", {"id": pid, "name": providers.get(pid, pid)})
            e.set("evidenceBasis", lin.get("basis"), "lineage registry basis missing")
            if lin.get("notes"):
                e.set("providerNotes", lin["notes"])
        else:
            e.set("provider", None, "no entry in config/sources/source_lineage.json — LINEAGE GAP")
            e.set("evidenceBasis", None, "no entry in config/sources/source_lineage.json")
        if src is not None:
            e.set("gameType", src.get("game_type"), "registry entry declares no game_type")
            e.set(
                "gameTypeEvidence",
                src.get("game_type_evidence"),
                "registry entry declares no evidence",
            )
        elif so is not None:
            meta = so.get("metadata") or {}
            e.set("gameType", meta.get("gameType"), "second-opinion metadata declares no game type")
            e.set("gameTypeEvidence", meta.get("gameTypeEvidence"), "no recorded evidence")
        elif lin is not None and lin.get("gameType"):
            # Proven by a lineage relation (e.g. Draft Sharks' rest-of-season
            # boards are REDRAFT_ROS) -- never inferred from a name.
            e.set("gameType", lin["gameType"])
            e.set("gameTypeEvidence", lin.get("gameTypeEvidence"), "no recorded evidence")
        else:
            e.set(
                "gameType", None, "not registered: game type is proven only for registered voters"
            )
            e.set("gameTypeEvidence", None, "not registered")

        # voting status
        voted_rows = sum(per[key]["voted"][u] for u in UNIVERSES) if key in per else 0
        if src is not None:
            e.set("votingStatus", VOTING if voted_rows > 0 else REGISTERED_NO_VOTES)
            e.set("nonVotingClass", None, "registered model input")
            e.set("nonVotingReason", None, "registered model input")
        else:
            e.set("votingStatus", NON_VOTING)
            if key == inp.benchmark_key:
                cls, why = (
                    NV_BENCHMARK,
                    (
                        "KTC Market — KTC's published Crowd+Trades blend; benchmark only, never a "
                        "vote (src/sources/ktc_market.py; registering it is refused at import)"
                    ),
                )
            elif so is not None:
                meta = so.get("metadata") or {}
                cls, why = (
                    NV_SECOND_OPINION,
                    (
                        f"second opinion only (votes={meta.get('votes')}, consumer="
                        f"{meta.get('intendedConsumer')}); positional ordinal ranks with no value "
                        "scale and no cross-position ordering (src/sources/signals.py)"
                    ),
                )
            elif key in inp.non_voting_declared or key in inp.retired_groups:
                cls = NV_DECLARED
                why = inp.non_voting_reasons.get(key) or "declared in _NON_VOTING_SOURCE_CSV_KEYS"
                if key in inp.retired_groups:
                    why = f"{why}; retired into family {inp.retired_groups[key]}"
            elif key in inp.non_voting_reasons:
                cls, why = NV_DOCUMENTED, inp.non_voting_reasons[key]
            else:
                cls, why = (
                    NV_UNCLASSIFIED,
                    "ingested with no registry entry and no stated reason — REVIEW",
                )
            e.set("nonVotingClass", cls)
            e.set("nonVotingReason", why)

        # family
        if src is not None:
            fam = _family_of(src)
            e.set("family.correlationGroup", fam)
            e.set("family.members", sorted(families[fam]))
        elif key in inp.retired_groups:
            e.set("family.correlationGroup", inp.retired_groups[key])
            e.set("family.members", sorted(families.get(inp.retired_groups[key], [])))
        else:
            e.set("family.correlationGroup", None, "non-voting: belongs to no voting family")
            e.set("family.members", [])

        # population / applicability
        p = per.get(key)
        sw, sw_reason = _weighting_entry(key, inp)
        subsets = (sw or {}).get("subsets") or {}
        if src is not None:
            scopes = [str(src.get("scope"))] + [str(s) for s in (src.get("extra_scopes") or [])]
            e.set("population.scopes", scopes)
            e.set("population.offense", "overall_offense" in scopes)
            e.set("population.idp", "overall_idp" in scopes)
            if src.get("needs_rookie_translation"):
                rook: Any = "rookie_only"
            elif src.get("excludes_rookies"):
                rook = False
            else:
                rook = bool(p and p["observed"]["rookie"] > 0)
            e.set("population.rookies", rook)
        elif so is not None:
            pos = list(so.get("positions") or [])
            e.set("population.scopes", pos)
            e.set("population.offense", bool(set(pos) & {"QB", "RB", "WR", "TE"}))
            e.set("population.idp", bool(set(pos) & {"CB", "S", "DT", "DE", "LB", "DL", "DB"}))
            e.set("population.rookies", None, "public board does not flag rookies")
        elif key == inp.benchmark_key:
            e.set("population.scopes", ["overall_offense"])
            e.set("population.offense", True)
            e.set("population.idp", False)
            e.set("population.rookies", True)
        else:
            e.set("population.scopes", None, "not registered: no canonical scope declaration")
            e.set("population.offense", None, "not registered: population undeclared")
            e.set("population.idp", None, "not registered: population undeclared")
            e.set("population.rookies", None, "not registered: population undeclared")
        if "picks" in subsets:
            e.set("population.picks", True)
        elif p and p["observed"]["pick"] > 0:
            e.set("population.picks", True)
        elif sw is not None and sw.get("measured"):
            e.set("population.picks", False)
        else:
            e.set(
                "population.picks", None, "no dataset state and no board rows to show pick coverage"
            )

        # signal / normalization
        prof = inp.csv_profiles.get(key)
        if key == inp.benchmark_key:
            published, vote = "native_value", None
        elif so is not None:
            published, vote = "positional_rank", None
        else:
            sig = (
                _csv_signal_of(key, inp.csv_paths, inp.value_based)
                if key in inp.csv_paths
                else None
            )
            if prof and prof.get("numericValueRows"):
                published = "native_value"
            elif sig == "rank" or (prof and prof.get("rankColumn")):
                published = "rank"
            else:
                published = None
            if src is None:
                vote = None
            elif key in inp.value_based:
                vote = "value_direct"
            else:
                vote = "rank_hill"
        e.set(
            "signal.published",
            published,
            "no CSV profile / declaration shows what the vendor publishes",
        )
        e.set("signal.vote", vote, "does not vote")
        role = {
            NV_BENCHMARK: "benchmark",
            NV_SECOND_OPINION: "second_opinion",
        }.get(
            e.data.get("nonVotingClass") or "",
            "model_input" if src is not None else "non_voting_input",
        )
        e.set("signal.role", role)
        if key == inp.benchmark_key and _num(ktc_market.get("boardMax")) is not None:
            e.set(
                "signal.nativeScale",
                {
                    "max": _num(ktc_market.get("boardMax")),
                    "declaredMax": 9999.0,
                    "source": "contract.ktcMarket",
                },
            )
        elif prof and prof.get("numericValueRows"):
            e.set(
                "signal.nativeScale",
                {
                    "column": prof.get("valueColumn"),
                    "max": prof.get("valueMax"),
                    "min": prof.get("valueMin"),
                    "numericRows": prof.get("numericValueRows"),
                    "source": "captured CSV (vendor semantics per fetcher)",
                },
            )
        else:
            e.set("signal.nativeScale", None, "no numeric native value is captured for this source")
        if src is not None:
            if src.get("needs_rookie_translation"):
                translation = "rookie_ladder"
            elif src.get("needs_shared_market_translation"):
                translation = "shared_market_idp"
            elif src.get("is_cross_market"):
                translation = "combined_cross_market"
            else:
                translation = "direct"
            e.set(
                "normalization.path",
                "raw / site_max x 9999 (value-direct)"
                if key in inp.value_based
                else "rank -> percentile -> scope Hill master",
            )
            e.set("normalization.translation", translation)
            e.set("normalization.tePremiumNative", bool(src.get("is_tep_premium")))
            e.set("normalization.pathsObserved", dict(p["paths"]) if p else {})
            e.set("normalization.methodsObserved", dict(p["methods"]) if p else {})
        else:
            e.set("normalization.path", None, "does not enter the canonical blend")
            e.set("normalization.translation", None, "does not enter the canonical blend")

        # weighting / authority
        if src is not None:
            base = _num(src.get("weight"))
            e.set("weighting.baseWeight", base, "registry weight missing")
        else:
            e.set("weighting.baseWeight", None, "not a model input")
        if sw is not None and sw.get("measured"):
            players = subsets.get("players") or {}
            picks_sub = subsets.get("picks") or {}
            f_p = _num(players.get("freshness"))
            e.set("weighting.freshnessFactor", f_p, "no players subset clock")
            if picks_sub:
                e.set(
                    "weighting.picksFreshnessFactor",
                    _num(picks_sub.get("freshness")),
                    "picks subset unclocked",
                )
            h = _num(sw.get("healthFactor"))
            c = _num(sw.get("coverageFactor"))
            e.set("weighting.healthFactor", h, "health factor not published")
            e.set("weighting.coverageFactor", c, "coverage factor not published")
            # DIAGNOSTIC ONLY: the product of the published source-level factors
            # (players subset).  The pipeline NEVER applies this number -- it
            # weighs per row with per-universe clocks, the picks subset and then
            # the family cap.  The applied quantity is ``authority.meanAppliedWeight``.
            if src is not None and None not in (base, f_p, h, c):
                e.set("weighting.playersSubsetFactorProduct", round(base * f_p * h * c, 4))  # type: ignore[operator]
            else:
                e.set(
                    "weighting.playersSubsetFactorProduct",
                    None,
                    "not a model input" if src is None else "a factor is unmeasured",
                )
        else:
            why = sw_reason or "dataset state unmeasured"
            for f in (
                "freshnessFactor",
                "healthFactor",
                "coverageFactor",
                "playersSubsetFactorProduct",
            ):
                e.set(f"weighting.{f}", None, why)
        if src is not None:
            vrows = voted_rows
            fam_adj = p["familyAdj"] if p else []
            e.set(
                "weighting.familyCap",
                {
                    "rowsVoted": vrows,
                    "rowsStamped": len(fam_adj),
                    "rowsCapped": p["familyCapped"] if p else 0,
                    "meanFamilyAdjustment": round(sum(fam_adj) / len(fam_adj), 4)
                    if fam_adj
                    else None,
                },
            )
            if not fam_adj:
                e.unknown["weighting.familyCap.meanFamilyAdjustment"] = (
                    "no voted rows carry a familyAdjustment stamp"
                )
            by_u = {}
            for u in UNIVERSES:
                n = p["voted"][u] if p else 0
                by_u[u] = {
                    "votingRows": n,
                    "meanAppliedWeight": round(p["applied"][u] / n, 4) if (p and n) else None,
                }
                if not n:
                    e.unknown[f"weighting.effectiveAuthority.byUniverse.{u}.meanAppliedWeight"] = (
                        "votes on no rows of this universe"
                    )
            total_applied = sum(p["applied"].values()) if p else 0.0
            mean_applied = round(total_applied / vrows, 4) if vrows else None
            pipe = (
                ((sw_block.get("sources") or {}).get(key) or {})
                if isinstance(sw_block, Mapping)
                else {}
            )
            pipe_mean = _num(pipe.get("meanAppliedWeight"))
            pipe_rows = pipe.get("votingRows")
            e.set(
                "weighting.effectiveAuthority",
                {
                    "votingRows": vrows,
                    "meanAppliedWeight": mean_applied,
                    "meanVoteShare": round(p["shareSum"] / vrows, 4) if (p and vrows) else None,
                    "pipelineMeanAppliedWeight": pipe_mean,
                    "matchesPipelineSummary": bool(pipe)
                    and pipe_rows == vrows
                    and pipe_mean is not None
                    and mean_applied is not None
                    and abs(pipe_mean - mean_applied) <= 1.5e-4,  # both rounded to 4 dp
                    "byUniverse": by_u,
                    "basis": "mean of the appliedWeight the canonical pipeline stamped on each voted row",
                },
            )
            if not vrows:
                e.unknown["weighting.effectiveAuthority.meanAppliedWeight"] = (
                    "votes on no board row"
                )
                e.unknown["weighting.effectiveAuthority.meanVoteShare"] = "votes on no board row"
            if pipe_mean is None:
                e.unknown["weighting.effectiveAuthority.pipelineMeanAppliedWeight"] = (
                    "contract sourceWeighting block carries no mean for this key"
                )
        else:
            e.set("weighting.familyCap", None, "not a model input")
            e.set("weighting.effectiveAuthority", None, "not a model input: carries no authority")

        # freshness + clocks
        players = subsets.get("players") or {}
        if sw is not None and sw.get("measured") and players:
            e.set(
                "freshness.publicationStyle", players.get("publicationStyle"), "style unclassified"
            )
            e.set(
                "freshness.expectedCadenceHours",
                _num(players.get("expectedCadenceHours")),
                "no cadence",
            )
            e.set("freshness.cadenceSource", players.get("cadenceSource"), "no cadence source")
            e.set("freshness.ageHours", _num(players.get("ageHours")), "no data clock")
            e.set("freshness.state", players.get("state"), "no state")
            e.set(
                "freshness.subsets",
                {
                    k: {
                        "state": v.get("state"),
                        "freshness": v.get("freshness"),
                        "publicationStyle": v.get("publicationStyle"),
                        "expectedCadenceHours": v.get("expectedCadenceHours"),
                        "ageHours": v.get("ageHours"),
                        "sourceDataAsOf": v.get("sourceDataAsOf"),
                    }
                    for k, v in subsets.items()
                },
            )
            for k, v in subsets.items():
                for fld in (
                    "state",
                    "freshness",
                    "publicationStyle",
                    "expectedCadenceHours",
                    "ageHours",
                    "sourceDataAsOf",
                ):
                    if v.get(fld) is None:
                        e.unknown[f"freshness.subsets.{k}.{fld}"] = "not published for this subset"
            e.set("clocks.sourceDataAsOf", players.get("sourceDataAsOf"), "no data clock")
            e.set("clocks.freshnessClock", players.get("freshnessClock"), "no data clock")
            e.set(
                "clocks.lastMeaningfulChange",
                players.get("lastAnyMeaningfulChangeAt"),
                "no change observed",
            )
            e.set(
                "clocks.lastBroadDatasetChange",
                players.get("lastBroadDatasetChangeAt"),
                "no broad change observed",
            )
        else:
            why = sw_reason or "dataset state unmeasured"
            for f in (
                "publicationStyle",
                "expectedCadenceHours",
                "cadenceSource",
                "ageHours",
                "state",
            ):
                e.set(f"freshness.{f}", None, why)
            for f in (
                "sourceDataAsOf",
                "freshnessClock",
                "lastMeaningfulChange",
                "lastBroadDatasetChange",
            ):
                e.set(f"clocks.{f}", None, why)
        if so is not None:
            fetch = (
                (so.get("fetchState") or {}).get("lastSuccessAt") if so.get("fetchState") else None
            )
            e.set(
                "clocks.lastSuccessfulFetch",
                fetch,
                so.get("fetchReason") or "no fetch state on this host",
            )
        else:
            e.set(
                "clocks.lastSuccessfulFetch",
                inp.fetch_stamps.get(key),
                "no per-key fetch stamp (data/scrape_state/<key>_last_success)",
            )
        if key == "idpShowCombined" or (players.get("freshnessClock") == "upstreamPublishedAt"):
            e.set(
                "clocks.upstreamPublishedAt", players.get("sourceDataAsOf"), "no upstream timestamp"
            )

        # condition (operational, derived)
        flags: list[str] = []
        cond = CONDITION_UNMEASURED
        if sw is not None and sw.get("measured") and subsets:
            cond = max(
                (
                    _FRESHNESS_STATE_TO_CONDITION.get(str(v.get("state")), CONDITION_UNMEASURED)
                    for v in subsets.values()
                ),
                key=lambda s: _CONDITION_SEVERITY[s],
            )
            for k, v in subsets.items():
                if v.get("state") not in (None, "ON_SCHEDULE"):
                    flags.append(f"{k}:{v.get('state')}")
            if sw.get("health") not in (None, "HEALTHY"):
                flags.append(f"HEALTH_{sw.get('health')}")
            cf = _num(sw.get("coverageFactor"))
            if cf is not None and cf < 1.0:
                flags.append(f"COVERAGE_FACTOR_{cf}")
        if src is not None and voted_rows == 0:
            flags.append("NO_VOTES_ON_BOARD")
        e.set("condition", {"state": cond, "flags": flags})

        # coverage
        if sw is not None and sw.get("measured"):
            e.set("coverage.datasetRows", sw.get("rowCount"), "row count not published")
            e.set("coverage.rollingMedianRows", sw.get("rollingMedianRows"), "no row-count history")
            e.set(
                "coverage.coverageRatio", _num(sw.get("coverage")), "coverage ratio not computable"
            )
        else:
            why = sw_reason or "dataset state unmeasured"
            e.set("coverage.datasetRows", prof.get("rows") if prof else None, why)
            e.set("coverage.rollingMedianRows", None, why)
            e.set("coverage.coverageRatio", None, why)
        if p is not None:
            e.set(
                "coverage.board",
                {
                    u: {"observed": p["observed"][u], "voted": p["voted"][u]}
                    for u in (*UNIVERSES, "rookie")
                },
            )
            e.set("coverage.hampelDropped", p["hampel"])
            e.set("coverage.freshnessExcludedRows", p["freshExcluded"])
            tob: dict[str, Any] = {}
            for u in UNIVERSES:
                if p["observed"][u] == 0:
                    continue
                tob[u] = {
                    f"top{n}": {
                        "observed": p["top"][u][n],
                        "voted": p["votedTop"][u][n],
                        "of": min(n, board["universeSizes"][u]),
                    }
                    for n in TOP_OF_BOARD_CUTOFFS
                }
            e.set("coverage.topOfBoard", tob)
        elif key == inp.benchmark_key:
            priced = ktc_market.get("pricedRows")
            e.set(
                "coverage.board",
                {"pricedRows": priced} if isinstance(priced, int) else None,
                "contract ktcMarket block carries no pricedRows",
            )
            e.set("coverage.topOfBoard", None, "benchmark rows carry no per-source vote stamps")
        else:
            e.set("coverage.board", None, "not loaded onto the canonical board")
            e.set("coverage.topOfBoard", None, "not loaded onto the canonical board")

        # history / archive
        csv_name = Path(csv_path_of(key, inp.csv_paths)).name
        hist: dict[str, Any] = {}
        if inp.git_history is None:
            e.set(
                "history.gitCsvVersions",
                None,
                inp.git_history_reason or "git history not collected",
            )
        else:
            commits = list(inp.git_history.get(csv_name) or [])
            if commits and so is None:
                e.set(
                    "history.gitCsvVersions",
                    {
                        "file": csv_name,
                        "versions": len(commits),
                        "first": _date(commits[-1]),
                        "last": _date(commits[0]),
                    },
                )
                hist["git"] = (len(commits), _date(commits[-1]), _date(commits[0]))
            else:
                e.set(
                    "history.gitCsvVersions",
                    None,
                    "box-local store (data/sources/signals), not committed"
                    if so is not None
                    else f"{csv_name} has no committed history",
                )
        if inp.export_archive is None:
            e.set(
                "history.exportArchive",
                None,
                inp.export_archive_reason or "export archive not indexed",
            )
        else:
            snaps = list(inp.export_archive.get(csv_name) or [])
            if snaps:
                e.set(
                    "history.exportArchive",
                    {
                        "file": csv_name,
                        "snapshots": len(snaps),
                        "first": snaps[0],
                        "last": snaps[-1],
                    },
                )
                hist["export"] = (len(snaps), snaps[0], snaps[-1])
            else:
                e.set(
                    "history.exportArchive",
                    None,
                    f"export archives do not carry site_raw/{csv_name}",
                )
        eligible = key in inp.ledger_eligible_keys
        if not eligible:
            e.set(
                "history.temporalLedger",
                {"laneEligible": False, "distinctDates": None, "firstDate": None},
            )
            e.unknown["history.temporalLedger.distinctDates"] = (
                "the source_value lane records only value-direct retail keys; this source can never appear there"
            )
            e.unknown["history.temporalLedger.firstDate"] = e.unknown[
                "history.temporalLedger.distinctDates"
            ]
        elif inp.ledger is None or not inp.ledger.get("exists"):
            reason = inp.ledger_reason or (inp.ledger or {}).get("reason") or "ledger not queried"
            e.set(
                "history.temporalLedger",
                {"laneEligible": True, "distinctDates": None, "firstDate": None},
            )
            e.unknown["history.temporalLedger.distinctDates"] = reason
            e.unknown["history.temporalLedger.firstDate"] = reason
        else:
            got = (inp.ledger.get("sources") or {}).get(key)
            if got:
                e.set(
                    "history.temporalLedger",
                    {
                        "laneEligible": True,
                        "distinctDates": got["distinctDates"],
                        "firstDate": got["firstDate"],
                    },
                )
                hist["ledger"] = (int(got["distinctDates"]), got["firstDate"], got["lastDate"])
            else:
                e.set(
                    "history.temporalLedger",
                    {"laneEligible": True, "distinctDates": None, "firstDate": None},
                )
                e.unknown["history.temporalLedger.distinctDates"] = (
                    "ledger present but holds no rows for this key"
                )
                e.unknown["history.temporalLedger.firstDate"] = (
                    "ledger present but holds no rows for this key"
                )
        events = inp.dataset_change_events.get(key)
        e.set(
            "history.datasetChangeEvents",
            dict(events) if events else None,
            "no dataset-state change history for this key",
        )
        if hist:
            firsts = [v[1] for v in hist.values() if v[1]]
            lasts = [v[2] for v in hist.values() if v[2]]
            first = min(firsts) if firsts else None
            last = max(lasts) if lasts else None
            e.set("history.archiveStart", first, "archived versions carry no dates")
            e.set(
                "history.archiveSpanDays",
                _days_between(first, last) if first and last else None,
                "dates unparseable",
            )
            e.set("history.pointInTimeValueVersions", max(v[0] for v in hist.values()))
        else:
            e.set(
                "history.archiveStart",
                None,
                "no point-in-time archive of this source's values was found",
            )
            e.set("history.archiveSpanDays", None, "no point-in-time archive")
            e.set("history.pointInTimeValueVersions", None, "no point-in-time archive")

        # lineage
        rels = _relations_for(key, lineage)
        e.set(
            "lineage.provenAncestry",
            [_relation_view(r, key) for r in rels if r.get("classification") == "proven"],
        )
        e.set(
            "lineage.measuredDependence",
            [_relation_view(r, key) for r in rels if r.get("classification") == "measured"],
        )
        e.set(
            "lineage.suspectedAncestry",
            [_relation_view(r, key) for r in rels if r.get("classification") == "suspected"],
        )

        # out-of-sample evaluation prerequisites
        blockers: list[str] = []
        caveats: list[str] = []
        # Unverified game type fails closed: a redraft/ROS board, or one whose
        # game type was never proven, must never enter a DYNASTY evaluation.
        if e.data.get("gameType") != "DYNASTY":
            blockers.append("GAME_TYPE_NOT_VERIFIED_DYNASTY")
        versions = e.data["history"].get("pointInTimeValueVersions")
        if versions is None:
            blockers.append("NO_POINT_IN_TIME_VALUE_ARCHIVE")
        elif versions < 2:
            blockers.append("SINGLE_ARCHIVED_VERSION")
        fam_members = e.data["family"].get("members") or []
        if src is not None and len(fam_members) > 1:
            caveats.append(
                "FAMILY_SHARED: evaluate leave-family-out with "
                + ",".join(m for m in fam_members if m != key)
            )
        own_family = set(fam_members) | {key}
        dep = sorted(
            {
                o
                for r in rels
                if r.get("classification") in ("proven", "measured")
                and "independence" not in str(r.get("relation"))
                for o in r.get("sources") or []
                if o not in own_family
            }
        )
        if dep:
            caveats.append("LINEAGE_OR_DEPENDENCE_OUTSIDE_FAMILY: " + ",".join(dep))
        sus = sorted(
            {
                o
                for r in rels
                if r.get("classification") == "suspected"
                for o in r.get("sources") or []
                if o != key
            }
        )
        if sus:
            caveats.append("SUSPECTED_ANCESTRY: " + ",".join(sus))
        if so is not None:
            caveats.append(
                "POSITIONAL_RANK_ONLY: no value scale or cross-position ordering to score"
            )
        if src is None and so is None and key != inp.benchmark_key:
            caveats.append("NOT_A_MODEL_INPUT: evaluable only as a candidate")
        span = e.data["history"].get("archiveSpanDays")
        if span is not None:
            caveats.append(f"ARCHIVE_SPAN_DAYS: {span}")
        e.set(
            "outOfSampleEvaluation",
            {
                "state": OOS_BLOCKED if blockers else OOS_MET,
                "blockers": blockers,
                "caveats": caveats,
            },
        )

        # evidence + defects
        records = [
            {"id": ev["id"], "kind": ev.get("kind"), "evidence": list(ev.get("evidence") or [])}
            for ev in lineage.get("evaluations") or []
            if key in (ev.get("sources") or [])
        ]
        held = {
            _EVALUATION_KIND_STATE[str(r["kind"])]
            for r in records
            if r["kind"] in _EVALUATION_KIND_STATE
        }
        if e.data["lineage"]["measuredDependence"]:
            held.add(EVIDENCE_DEPENDENCE)
        state = next((s for s in EVIDENCE_STATES if s in held), EVIDENCE_UNEVALUATED)
        # ``evidenceState`` is the DEEPEST examination, not a quality rank;
        # ``evidenceHeld`` keeps every kind of evidence so none is collapsed.
        e.set("evidenceState", state)
        e.set("evidenceHeld", [s for s in EVIDENCE_STATES if s in held])
        e.set("evidenceRecords", records)
        defects = [
            {
                "id": d["id"],
                "status": d.get("status"),
                "summary": d.get("summary"),
                "recordedAt": d.get("recordedAt"),
                "evidence": list(d.get("evidence") or []),
            }
            for d in lineage.get("defects") or []
            if key in (d.get("sources") or [])
        ]
        e.set("knownDefects", defects)
        findings = list(flags)
        if sw is not None:
            for err in sw.get("healthErrors") or []:
                findings.append(f"health error: {err}")
        if prof and prof.get("tiedValueRowsWithDistinctRanks"):
            findings.append(
                f"{prof['tiedValueRowsWithDistinctRanks']} rows share a native value but carry distinct ranks"
            )
        e.set("currentFindings", findings)
        if prof is not None:
            e.set(
                "csvProfile",
                {
                    "file": csv_name,
                    "rows": prof.get("rows"),
                    "valueColumn": prof.get("valueColumn"),
                    "rankColumn": prof.get("rankColumn"),
                    "tiedValueRowsWithDistinctRanks": prof.get("tiedValueRowsWithDistinctRanks"),
                },
            )
            for fld, why in (
                ("valueColumn", "CSV carries no recognised native-value column"),
                ("rankColumn", "CSV carries no recognised rank column"),
                ("tiedValueRowsWithDistinctRanks", "needs both a numeric value and a rank column"),
            ):
                if prof.get(fld) is None:
                    e.unknown[f"csvProfile.{fld}"] = why
        else:
            e.set("csvProfile", None, f"no CSV on disk at {csv_path_of(key, inp.csv_paths)}")
        entries.append(e.finish())

    return {
        "schema": CENSUS_SCHEMA,
        "label": inp.label,
        "generatedAt": inp.generated_at,
        "boardAsOf": sw_block.get("asOf") if isinstance(sw_block, Mapping) else None,
        "pins": dict(inp.pins),
        "vocabularies": {
            "votingStatus": sorted(VOTING_STATUSES),
            "nonVotingClass": sorted(NON_VOTING_CLASSES),
            "evidenceState": {s: EVIDENCE_STATE_MEANING[s] for s in EVIDENCE_STATES},
            "outOfSampleEvaluation": [OOS_MET, OOS_BLOCKED],
            "lineageClassification": ["proven", "measured", "suspected"],
        },
        "outOfSampleEvaluation": {
            "globalBlockers": list(OOS_GLOBAL_BLOCKERS),
            "rule": "per source: DATA_PREREQUISITES_MET needs a point-in-time archive of the "
            "source's OWN published values with >= 2 versions (git CSV history, export-archive "
            "snapshots or the temporal ledger); dependence/family overlap are caveats that force "
            "leave-family-out / leave-lineage-out designs, not blockers",
        },
        "weightingFormula": sw_block.get("formula") if isinstance(sw_block, Mapping) else None,
        "boardRows": board["rows"],
        "boardUniverseSizes": board["universeSizes"],
        "lineageRelations": [
            {**dict(r), "category": lineage_category(r)} for r in lineage.get("relations") or []
        ],
        "lineageCategories": list(LINEAGE_CATEGORIES),
        "lineagePairs": [dict(p) for p in lineage.get("pairReconciliation") or []],
        "sources": entries,
        "summary": summarize(entries),
    }


def summarize(entries: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    by_status = Counter(e["votingStatus"] for e in entries)
    by_class = Counter(e.get("nonVotingClass") for e in entries if e.get("nonVotingClass"))
    fams: dict[str, list[str]] = defaultdict(list)
    for e in entries:
        if e["votingStatus"] != NON_VOTING and e["family"].get("correlationGroup"):
            fams[e["family"]["correlationGroup"]].append(e["key"])
    degraded = [
        {"key": e["key"], "condition": e["condition"]["state"], "flags": e["condition"]["flags"]}
        for e in entries
        if e["condition"]["state"] not in (CONDITION_CURRENT,) or e["condition"]["flags"]
    ]
    rels: dict[str, set[str]] = {"proven": set(), "measured": set(), "suspected": set()}
    for e in entries:
        for cls, fld in (
            ("proven", "provenAncestry"),
            ("measured", "measuredDependence"),
            ("suspected", "suspectedAncestry"),
        ):
            for r in e["lineage"][fld]:
                rels[cls].add(r["id"])
    return {
        "sources": len(entries),
        "votingStatus": dict(by_status),
        "nonVotingClass": dict(by_class),
        "votingFamilies": {k: sorted(v) for k, v in sorted(fams.items())},
        "votingFamilyCount": len(fams),
        "evidenceState": dict(Counter(e["evidenceState"] for e in entries)),
        "degradedOrNotCurrent": degraded,
        "outOfSampleDataPrerequisitesMet": sorted(
            e["key"] for e in entries if e["outOfSampleEvaluation"]["state"] == OOS_MET
        ),
        "outOfSampleBlocked": {
            e["key"]: e["outOfSampleEvaluation"]["blockers"]
            for e in entries
            if e["outOfSampleEvaluation"]["state"] == OOS_BLOCKED
        },
        "cleanOutOfSampleEvaluationPossibleNow": [],
        "lineageRelations": {k: sorted(v) for k, v in rels.items()},
        "unclassified": sorted(
            e["key"] for e in entries if e.get("nonVotingClass") == NV_UNCLASSIFIED
        ),
        "lineageGaps": sorted(e["key"] for e in entries if e.get("provider") is None),
        "authorityMismatches": sorted(
            e["key"]
            for e in entries
            if e.get("weighting", {}).get("effectiveAuthority")
            and not e["weighting"]["effectiveAuthority"]["matchesPipelineSummary"]
        ),
    }


# ── Markdown ─────────────────────────────────────────────────────────────


def _fmt(v: Any, nd: int = 2) -> str:
    if v is None:
        return "—"
    if isinstance(v, float):
        return f"{v:.{nd}f}"
    return str(v)


def census_markdown(census: Mapping[str, Any]) -> str:
    pins = census.get("pins") or {}
    s = census["summary"]
    lines = [
        f"# Source trust census — {census.get('label')} build",
        "",
        "Generated by `scripts/source_census.py` (`src/sources/source_census.py`, schema "
        f"`{census['schema']}`). Evidence only: nothing here changes a vote, weight or value. "
        "Trust is an enumerated evidence state, never a score. `—` = unknown; the JSON carries the "
        "reason for every unknown.",
        "",
        "| pin | value |",
        "|---|---|",
        f"| label | {census.get('label')} |",
        f"| code SHA | `{pins.get('codeRevision')}` (dirty: {pins.get('workingTreeDirty')}) |",
        f"| payload | `{(pins.get('payload') or {}).get('path')}` sha256 `{str((pins.get('payload') or {}).get('sha256'))[:16]}…` |",
        f"| board asOf | {census.get('boardAsOf')} |",
        f"| full-pins digest | `{str(pins.get('pinsDigest'))[:16]}…` |",
        f"| generatedAt | {census.get('generatedAt')} |",
        "",
        "## Summary",
        "",
        f"- **{s['sources']} sources**: {s['votingStatus']}; non-voting classes {s['nonVotingClass']}.",
        f"- **{s['votingFamilyCount']} voting families**: "
        + "; ".join(f"`{k}` = {', '.join(v)}" for k, v in s["votingFamilies"].items()),
        f"- Evidence states: {s['evidenceState']}.",
        f"- Clean out-of-sample evaluation possible now: **none** — "
        f"{census['outOfSampleEvaluation']['globalBlockers'][0].split(':')[0]}. "
        f"Data prerequisites met ({len(s['outOfSampleDataPrerequisitesMet'])}): "
        f"{', '.join(s['outOfSampleDataPrerequisitesMet'])}.",
        f"- Blocked on data: {', '.join(f'{k} ({v[0]})' for k, v in s['outOfSampleBlocked'].items())}.",
        f"- Not current / flagged: {', '.join(f'{d['key']} ({d['condition']}{(' ' + ','.join(d['flags'])) if d['flags'] else ''})' for d in s['degradedOrNotCurrent'])}.",
        f"- Unclassified: {s['unclassified'] or 'none'}; lineage gaps: {s['lineageGaps'] or 'none'}; "
        f"authority mismatches vs pipeline summary: {s['authorityMismatches'] or 'none'}.",
        "",
        "## Sources",
        "",
        "| source | provider | family | status | signal → vote | base | fresh × health × cov | fam adj (mean) | authority: mean applied / share / rows | style · cadence h | data as-of | condition | git versions (since) | OOS data | evidence |",
        "|" + "---|" * 15,
    ]
    for e in census["sources"]:
        w = e.get("weighting") or {}
        auth = w.get("effectiveAuthority") or {}
        fc = w.get("familyCap") or {}
        git = (e.get("history") or {}).get("gitCsvVersions") or {}
        status = (
            e["votingStatus"]
            if e["votingStatus"] != NON_VOTING
            else f"NV:{e.get('nonVotingClass')}"
        )
        lines.append(
            "| `{k}` | {prov} | {fam} | {st} | {pub} → {vote} | {base} | {f} × {h} × {c} | {fa} | {ma} / {sh} / {rows} | {style} · {cad} | {asof} | {cond} | {gv} | {oos} | {ev} |".format(
                k=e["key"],
                prov=(e.get("provider") or {}).get("name", "—"),
                fam=_fmt((e.get("family") or {}).get("correlationGroup")),
                st=status,
                pub=_fmt((e.get("signal") or {}).get("published")),
                vote=_fmt((e.get("signal") or {}).get("vote")),
                base=_fmt(w.get("baseWeight"), 1),
                f=_fmt(w.get("freshnessFactor"), 3),
                h=_fmt(w.get("healthFactor"), 1),
                c=_fmt(w.get("coverageFactor"), 3),
                fa=_fmt(fc.get("meanFamilyAdjustment"), 3),
                ma=_fmt(auth.get("meanAppliedWeight"), 3),
                sh=_fmt(auth.get("meanVoteShare"), 3),
                rows=_fmt(auth.get("votingRows")),
                style=_fmt((e.get("freshness") or {}).get("publicationStyle")),
                cad=_fmt((e.get("freshness") or {}).get("expectedCadenceHours"), 0),
                asof=_fmt(_date((e.get("clocks") or {}).get("sourceDataAsOf"))),
                cond=e["condition"]["state"],
                gv=f"{git['versions']} ({git['first']})" if git else "—",
                oos="met" if e["outOfSampleEvaluation"]["state"] == OOS_MET else "blocked",
                ev=e["evidenceState"],
            )
        )
    lines += [
        "",
        "## Effective authority by asset universe",
        "",
        "Mean `appliedWeight` the pipeline stamped on the rows each source voted on, per universe "
        "(rows in parentheses). Differs from the source-level factor when a row is aged on its own "
        "universe's clock (a board that published only IDP changes ages its offense and pick rows).",
        "",
        "| source | offense | idp | pick |",
        "|---|---|---|---|",
    ]
    for e in census["sources"]:
        auth = ((e.get("weighting") or {}).get("effectiveAuthority") or {}).get("byUniverse")
        if not auth:
            continue
        cells = [
            f"{_fmt(auth[u]['meanAppliedWeight'], 3)} ({auth[u]['votingRows']})"
            if auth[u]["votingRows"]
            else "—"
            for u in UNIVERSES
        ]
        lines.append(f"| `{e['key']}` | " + " | ".join(cells) + " |")
    lines += [
        "",
        "## Lineage (from `config/sources/source_lineage.json`)",
        "",
        "`measured` is dependence, never common ancestry; `suspected` is kept apart from `proven`.",
        "",
        "| relation | class | category | sources | as of | summary |",
        "|---|---|---|---|---|---|",
    ]
    order = {"proven": 0, "measured": 1, "suspected": 2}
    for r in sorted(
        census.get("lineageRelations") or [], key=lambda r: order.get(r.get("classification"), 9)
    ):
        lines.append(
            f"| `{r['id']}` | {r.get('classification')} | {r.get('category') or '—'} | {', '.join(r.get('sources') or [])} "
            f"| {r.get('asOf', '—')} | {r.get('summary', '')} |"
        )
    pairs = census.get("lineagePairs") or []
    if pairs:
        lines += [
            "",
            "## Lineage pairs (four categories)",
            "",
            "Categories: "
            + ", ".join(f"`{c}`" for c in census.get("lineageCategories") or [])
            + ". A measurement never becomes ancestry; `INDEPENDENT_NO_EVIDENCE` is absence "
            "of evidence; a blank category is UNKNOWN with its reason.",
            "",
            "| pair | category | sources | as of | measurement | family cap | Hill holdout |",
            "|---|---|---|---|---|---|---|",
        ]
        for p in pairs:
            m = p.get("measurement") or {}
            meas = f"{m.get('statistic', '')} (n={m.get('n')}, {m.get('window')})" if m else "—"
            impl = p.get("implications") or {}
            lines.append(
                f"| `{p['id']}` | {p.get('category') or 'UNKNOWN: ' + str(p.get('unknownReason'))} "
                f"| {', '.join(p.get('sources') or [])} | {p.get('asOf', '—')} | {meas} "
                f"| {impl.get('familyCap', '—')} | {impl.get('hillHoldout', '—')} |"
            )
    defects = {}
    for e in census["sources"]:
        for d in e.get("knownDefects") or []:
            defects.setdefault(d["id"], (d, []))[1].append(e["key"])
    if defects:
        lines += [
            "",
            "## Recorded source defects",
            "",
            "| defect | status | sources | summary |",
            "|---|---|---|---|",
        ]
        for did, (d, ks) in defects.items():
            lines.append(f"| `{did}` | {d.get('status')} | {', '.join(ks)} | {d.get('summary')} |")
    lines.append("")
    return "\n".join(lines)
