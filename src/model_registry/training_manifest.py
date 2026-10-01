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
  carry must cite its evidence, and unverified fails closed.

Declared, because no registry can express them (``_DEFAULT_SPECS``):

* which native-value column a board publishes;
* which scope it trains or holds out — the methodology choice, kept exactly as
  it was before this unit except where the owner's Section D items force a
  change (players-only populations; no confirmed-ancestry holdout);
* measured dependence between boards (``_MEASURED_DEPENDENCES``), with the
  evidence it was measured from.

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
3. **No family on both sides of a split.** A holdout that shares a provider
   family with a trainer (confirmed common ancestry) is excluded, in either
   direction. Measured dependence is a different, weaker statement and is
   REPORTED on the holdout rather than confused with ancestry; excluding it
   too is an explicit policy (``HoldoutPolicy(measured_dependence="exclude")``).
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

REPO = Path(__file__).resolve().parents[2]

#: 1 = the pre-repair substrate (KTC pick rows in the OFFENSE fit, Fantasy
#: Navigator held out, no run pins). 2 = this manifest. A registry challenger
#: records the substrate it was fitted on; Hill Autopilot only tournaments the
#: current one (``training_run.is_tournament_eligible``).
SUBSTRATE_VERSION: int = 2
MANIFEST_SCHEMA_VERSION: int = 1

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


@dataclass(frozen=True)
class MeasuredDependence:
    """A measured (not ancestral) dependence of one board on a provider family."""

    source_key: str
    trainer_family: str
    metric: str
    value: float
    evidence: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "sourceKey": self.source_key,
            "trainerFamily": self.trainer_family,
            "metric": self.metric,
            "value": self.value,
            "evidence": self.evidence,
        }


@dataclass(frozen=True)
class HoldoutPolicy:
    #: ``retain_and_report``: a holdout with measured dependence on a training
    #: family still scores, tagged. ``exclude``: it is removed from the split.
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

#: Measured dependence, distinct from confirmed common ancestry (which the B10
#: family already expresses). Residual correlations from the 2026-08-04
#: decision-intelligence audit, as tabulated in the 2026-09-24 alignment audit.
_MEASURED_DEPENDENCES: tuple[MeasuredDependence, ...] = (
    MeasuredDependence(
        "pfkDynasty",
        "ktcCrowd",
        "residual_r",
        0.45,
        f"{_H_AUDIT} §2 H6/H7 and §4: PFK holdout RMSE flattered 1.64x by KTC in training",
    ),
    MeasuredDependence(
        "fantasyCalc",
        "dynastyDaddySf",
        "residual_r",
        0.677,
        f"{_H_AUDIT} §2 H6; docs/audits/decision-intelligence-audit-2026-08-04.registry.json",
    ),
    MeasuredDependence(
        "otcffbSf",
        "fantasyCalc",
        "residual_r",
        0.33,
        f"{_H_AUDIT} §2 H6 (OTC is the one plausibly independent offense holdout)",
    ),
)

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
    "ktcCrowdTradesSfTep": "KTC Market: benchmark only, never a vote, never Hill evidence",
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
    measured_dependence: tuple[MeasuredDependence, ...] = ()
    note: str = ""

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
            "measuredDependence": [d.to_dict() for d in self.measured_dependence],
        }


@dataclass(frozen=True)
class TrainingManifest:
    boards: tuple[ManifestBoard, ...]
    policy: TrainingPolicy

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
            "boards": [b.to_dict() for b in sorted(self.boards, key=lambda b: (b.scope, b.label))],
        }

    def manifest_hash(self) -> str:
        return hashlib.sha256(_canonical_json(self.to_dict()).encode("utf-8")).hexdigest()


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
    dependences: Iterable[MeasuredDependence] | None = None,
    policy: TrainingPolicy | None = None,
    registry: RegistryView | None = None,
) -> TrainingManifest:
    reg = registry or registry_view()
    pol = policy or TrainingPolicy()
    deps = tuple(_MEASURED_DEPENDENCES if dependences is None else dependences)
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
        for b in scoped:
            if b.role != ROLE_TRAIN:
                continue
            if b.family in train_families:
                raise ManifestError(
                    f"family {b.family!r} trains twice in {scope} ({train_families[b.family]} "
                    f"and {b.label}); same-source calibration states are one vote"
                )
            train_families[b.family] = b.label
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
            tags = tuple(
                d
                for d in deps
                if d.source_key == b.source_key and d.trainer_family in train_families
            )
            if tags and pol.holdout.measured_dependence == "exclude":
                out.append(
                    replace(
                        b,
                        role=ROLE_EXCLUDED,
                        measured_dependence=tags,
                        exclusion_reason="measured_dependence:"
                        + ",".join(sorted(d.trainer_family for d in tags)),
                    )
                )
                continue
            out.append(replace(b, measured_dependence=tags))
    return TrainingManifest(boards=tuple(out), policy=pol)


@lru_cache(maxsize=1)
def default_manifest() -> TrainingManifest:
    return build_manifest()


#: Public view of the declared measured dependences.
MEASURED_DEPENDENCES: tuple[MeasuredDependence, ...] = _MEASURED_DEPENDENCES


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
    """Players-only positive values from ``column``, descending (ties keep file order)."""
    pairs: list[tuple[str, float]] = []
    rows = picks = nonpos = bad = 0
    with path.open(newline="", encoding="utf-8-sig") as f:
        for row in csv.DictReader(f):
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
