"""Rookie-class input snapshots — which 72 values feed a class's curve (Batch B).

A curve for draft class ``Y`` needs 72 rookie-value inputs (the sheet's column
B).  This module turns either source of those inputs into one immutable,
hashed :class:`RookieClassSnapshot`:

``actual``
    built from the canonical board (``playersArray`` of the live contract):
    the players whose draft class is PROVEN to be ``Y``, valued by canonical
    ``rankDerivedValue``, one record per player, sorted descending with a
    stable identity tie-break, top ``pick_count``.
``frozen_fallback``
    the owner-approved provisional 2026 baseline
    (``config/draft_valuation/frozen_inputs/2026_spreadsheet_baseline.json``),
    in its original pick order (the golden-parity order).  It is a pricing
    TEMPLATE: it carries no player identities, so 2026 players can never be
    presented as participants in a 2027 auction.

Class identity is decided here and nowhere else in the workstream:

* an explicit ``eligibleDraftYear`` on the row wins (a source that states the
  class);
* else Sleeper ``yearsExp`` plus the NFL season the observation belongs to
  (``observed_nfl_season - yearsExp``) — the caller must say which season;
  this module never guesses it from the clock;
* else the row's class is UNPROVABLE (``unsupported_class_identity``).

The ``rookie`` boolean is deliberately not used: it means "zero NFL seasons"
on whatever day it was read, so in October it names the 2026 class, not the
2027 one (audit D5).  ``src/draft/rookie_pool.select_rookie_rows`` stays the
owner of "who is in THIS auction" for the auction tools; this module answers
the different question "which values price class Y".

Nothing here reads the clock, writes a file or changes a served value.
Missing is never zero: a row without a positive finite value is excluded and
counted, never priced at 0; too few eligible rows is ``NOT_READY``, never a
padded list.
"""

from __future__ import annotations

import hashlib
import json
import math
from dataclasses import dataclass
from decimal import Decimal
from typing import Any, Mapping

from src.draft.rookie_auction.curve import FORMULA_VERSION
from src.draft.rookie_auction.league_scope import LeagueNotConfiguredError, league_scope
from src.draft.rookie_auction.snapshots import FrozenRookieInputs, load_frozen_rookie_inputs

__all__ = [
    "IDENTITY_ELIGIBLE",
    "IDENTITY_OTHER_CLASS",
    "IDENTITY_UNSUPPORTED",
    "MODE_ACTUAL",
    "MODE_FROZEN_FALLBACK",
    "STATUS_COMPLETE",
    "STATUS_NOT_READY",
    "ClassEntry",
    "RookieClassSnapshot",
    "SnapshotRecordError",
    "build_class_candidate",
    "class_identity",
    "frozen_fallback_snapshot",
    "load_class_snapshot",
    "row_identity",
]

SCHEMA = "draft_valuation_rookie_class_snapshot_v1"
MODE_ACTUAL = "actual"
MODE_FROZEN_FALLBACK = "frozen_fallback"
STATUS_COMPLETE = "COMPLETE"
STATUS_NOT_READY = "NOT_READY"

IDENTITY_ELIGIBLE = "class_eligible_for_curve"
IDENTITY_OTHER_CLASS = "other_class"
IDENTITY_UNSUPPORTED = "unsupported_class_identity"


class SnapshotRecordError(ValueError):
    """A stored snapshot record does not reproduce its own ``snapshotSha256``."""


_IDP_POSITIONS = frozenset({"DL", "LB", "DB", "DE", "DT", "EDGE", "ILB", "OLB", "CB", "S"})


@dataclass(frozen=True)
class ClassEntry:
    rank: int
    canonical_player_id: str | None  # ``None`` only in a frozen pricing template
    name: str | None
    position: str | None
    asset_class: str | None
    eligible_draft_year: int | None
    class_basis: str  # explicit | sleeper_years_exp | frozen_template
    value: Decimal
    rosterable_on_sleeper: bool
    pick: str | None = None  # frozen template rows keep their pick label

    def to_dict(self) -> dict[str, Any]:
        return {
            "rank": self.rank,
            "canonicalPlayerId": self.canonical_player_id,
            "name": self.name,
            "position": self.position,
            "assetClass": self.asset_class,
            "eligibleDraftYear": self.eligible_draft_year,
            "classBasis": self.class_basis,
            "value": _dstr(self.value),
            "rosterableOnSleeper": self.rosterable_on_sleeper,
            "pick": self.pick,
        }


@dataclass(frozen=True)
class RookieClassSnapshot:
    target_draft_year: int
    actual_input_class_year: int | None
    mode: str
    status: str
    league_key: str | None
    scoring_fingerprint: str | None
    idp_eligible: bool | None
    ranking_generation_hash: str | None
    as_of: str | None
    pick_count: int
    entries: tuple[ClassEntry, ...]
    exclusions: Mapping[str, int]
    missing_reasons: tuple[str, ...]
    provenance: Mapping[str, Any]
    model_version: str = FORMULA_VERSION

    def curve_values(self) -> tuple[Decimal, ...]:
        """Column B for the curve.  Refuses an incomplete snapshot."""
        if self.status != STATUS_COMPLETE or len(self.entries) != self.pick_count:
            raise ValueError(
                f"snapshot is {self.status} ({len(self.entries)}/{self.pick_count}); "
                "an incomplete class is never priced"
            )
        return tuple(e.value for e in self.entries)

    def body(self) -> dict[str, Any]:
        return {
            "schema": SCHEMA,
            "targetDraftYear": self.target_draft_year,
            "actualInputClassYear": self.actual_input_class_year,
            "mode": self.mode,
            "status": self.status,
            "leagueKey": self.league_key,
            "scoringFingerprint": self.scoring_fingerprint,
            "idpEligible": self.idp_eligible,
            "rankingGenerationHash": self.ranking_generation_hash,
            "asOf": self.as_of,
            "pickCount": self.pick_count,
            "coverage": {"required": self.pick_count, "eligible": len(self.entries)},
            "exclusions": dict(sorted(self.exclusions.items())),
            "missingReasons": list(self.missing_reasons),
            "provenance": dict(self.provenance),
            "modelVersion": self.model_version,
            "entries": [e.to_dict() for e in self.entries],
        }

    @property
    def snapshot_sha256(self) -> str:
        return _sha(self.body())

    def to_dict(self) -> dict[str, Any]:
        out = self.body()
        out["snapshotSha256"] = self.snapshot_sha256
        return out


def _sha(obj: object) -> str:
    text = json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _dstr(d: Decimal) -> str:
    return format(d.normalize(), "f")


def _int_or_none(v: Any) -> int | None:
    if isinstance(v, bool) or v is None:
        return None
    if isinstance(v, int):
        return v
    if isinstance(v, float) and v.is_integer():
        return int(v)
    return None


def class_identity(
    row: Mapping[str, Any], *, observed_nfl_season: int | None
) -> tuple[int | None, str]:
    """``(eligible draft year, basis)``; year ``None`` when it cannot be proven.

    ``basis`` is ``explicit``, ``sleeper_years_exp``, or
    ``unprovable:<why>``.
    """
    explicit = _int_or_none(row.get("eligibleDraftYear"))
    if explicit is not None:
        return explicit, "explicit"
    years_exp = _int_or_none(row.get("yearsExp"))
    if years_exp is None or years_exp < 0:
        return None, "unprovable:no_years_exp"
    if observed_nfl_season is None:
        return None, "unprovable:observation_season_unknown"
    return int(observed_nfl_season) - years_exp, "sleeper_years_exp"


def _value(row: Mapping[str, Any]) -> Decimal | None:
    v = row.get("rankDerivedValue")
    if isinstance(v, bool) or not isinstance(v, (int, float)):
        return None
    if not math.isfinite(float(v)) or float(v) <= 0:
        return None
    return Decimal(repr(v)) if isinstance(v, float) else Decimal(v)


def _is_idp(row: Mapping[str, Any]) -> bool:
    if str(row.get("assetClass") or "").lower() == "idp":
        return True
    return str(row.get("position") or "").upper() in _IDP_POSITIONS


def row_identity(row: Mapping[str, Any]) -> str | None:
    """The identity a class entry carries for ``row``: ``playerId``, else ``name:<lower>``.

    One definition, shared by :func:`build_class_candidate` and every gate
    that joins an entry back to its contract row (``promotion``).
    """
    player_id = str(row.get("playerId") or "").strip() or None
    if player_id is not None:
        return player_id
    name = str(row.get("canonicalName") or row.get("displayName") or "").strip() or None
    return f"name:{name.lower()}" if name else None


def build_class_candidate(
    contract: Mapping[str, Any] | None,
    *,
    target_draft_year: int,
    league_key: str | None,
    observed_nfl_season: int | None,
    scoring_fingerprint: str | None = None,
    ranking_generation_hash: str | None = None,
    as_of: str | None = None,
) -> RookieClassSnapshot:
    """An ``actual``-mode snapshot of class ``target_draft_year`` from a contract.

    Always returns a snapshot; ``status`` says whether it can price a curve.
    The league's pick count and IDP eligibility come from
    :mod:`league_scope`; a league that is not configured gets an empty
    ``NOT_READY`` snapshot (fail closed), never an adapted one.
    """
    target = int(target_draft_year)
    exclusions: dict[str, int] = {}
    missing: list[str] = []
    try:
        scope = league_scope(league_key)
    except LeagueNotConfiguredError:
        return RookieClassSnapshot(
            target_draft_year=target,
            actual_input_class_year=target,
            mode=MODE_ACTUAL,
            status=STATUS_NOT_READY,
            league_key=league_key,
            scoring_fingerprint=scoring_fingerprint,
            idp_eligible=None,
            ranking_generation_hash=ranking_generation_hash,
            as_of=as_of,
            pick_count=0,
            entries=(),
            exclusions={},
            missing_reasons=(f"league_not_configured:{league_key}",),
            provenance={"source": "canonical contract playersArray.rankDerivedValue"},
        )
    idp_eligible = scope.idp_eligible
    pick_count = scope.pick_count

    def exclude(reason: str) -> None:
        exclusions[reason] = exclusions.get(reason, 0) + 1

    rows = contract.get("playersArray") if isinstance(contract, Mapping) else None
    if not isinstance(rows, list):
        rows = []
        missing.append("no_players_array")

    by_id: dict[str, tuple[Decimal, ClassEntry]] = {}
    duplicates: set[str] = set()
    for row in rows:
        if not isinstance(row, Mapping):
            exclude("not_a_row")
            continue
        if str(row.get("assetClass") or "").lower() == "pick":
            exclude("pick_asset")
            continue
        year, basis = class_identity(row, observed_nfl_season=observed_nfl_season)
        if year is None:
            exclude(f"class_{basis}")
            continue
        if year != target:
            exclude("other_class")
            continue
        player_id = str(row.get("playerId") or "").strip() or None
        name = str(row.get("canonicalName") or row.get("displayName") or "").strip() or None
        if player_id is None and basis != "explicit":
            exclude("class_unprovable:no_identity")
            continue
        canonical_id = row_identity(row)
        if canonical_id is None:
            exclude("no_identity")
            continue
        if not idp_eligible and _is_idp(row):
            exclude("idp_not_eligible_in_league")
            continue
        value = _value(row)
        if value is None:
            exclude("no_positive_value")
            continue
        entry = ClassEntry(
            rank=0,
            canonical_player_id=canonical_id,
            name=name,
            position=(str(row.get("position") or "").upper() or None),
            asset_class=(str(row.get("assetClass") or "") or None),
            eligible_draft_year=year,
            class_basis=basis,
            value=value,
            rosterable_on_sleeper=player_id is not None,
        )
        if canonical_id in by_id:
            duplicates.add(canonical_id)
            continue
        by_id[canonical_id] = (value, entry)

    for dup in sorted(duplicates):
        missing.append(f"duplicate_identity:{dup}")
        by_id.pop(dup, None)  # never pick one of two records silently

    ordered = sorted(by_id.values(), key=lambda pair: (-pair[0], pair[1].canonical_player_id))
    chosen = [
        ClassEntry(**{**e.__dict__, "rank": i + 1})
        for i, (_, e) in enumerate(ordered[: int(pick_count)])
    ]
    if len(ordered) < pick_count:
        missing.append(f"insufficient_eligible:{len(ordered)}/{pick_count}")
    status = STATUS_COMPLETE if not missing and len(chosen) == pick_count else STATUS_NOT_READY
    return RookieClassSnapshot(
        target_draft_year=target,
        actual_input_class_year=target,
        mode=MODE_ACTUAL,
        status=status,
        league_key=league_key,
        scoring_fingerprint=scoring_fingerprint,
        idp_eligible=idp_eligible,
        ranking_generation_hash=ranking_generation_hash,
        as_of=as_of,
        pick_count=int(pick_count),
        entries=tuple(chosen),
        exclusions=exclusions,
        missing_reasons=tuple(missing),
        provenance={
            "source": "canonical contract playersArray.rankDerivedValue",
            "observedNflSeason": observed_nfl_season,
            "eligibleRowsBeforeCut": len(ordered),
        },
    )


def frozen_fallback_snapshot(
    target_draft_year: int,
    *,
    league_key: str,
    frozen: FrozenRookieInputs | None = None,
) -> RookieClassSnapshot:
    """The provisional 2026 baseline as class ``target_draft_year``'s inputs.

    Only for a configured league (``dynasty_main``); raises
    :class:`LeagueNotConfiguredError` otherwise.

    Original pick order is preserved (it is the golden-parity order).  The
    entries carry pick labels and values only — no player identities.
    """
    scope = league_scope(league_key)
    frozen = frozen or load_frozen_rookie_inputs()
    season_label = frozen.source_season_label
    entries = tuple(
        ClassEntry(
            rank=i + 1,
            canonical_player_id=None,
            name=None,
            position=None,
            asset_class=None,
            eligible_draft_year=None,
            class_basis="frozen_template",
            value=v,
            rosterable_on_sleeper=False,
            pick=pick,
        )
        for i, (pick, v) in enumerate(zip(frozen.picks, frozen.values))
    )
    return RookieClassSnapshot(
        target_draft_year=int(target_draft_year),
        actual_input_class_year=season_label if isinstance(season_label, int) else None,
        mode=MODE_FROZEN_FALLBACK,
        status=STATUS_COMPLETE,
        league_key=league_key,
        scoring_fingerprint=None,
        idp_eligible=scope.idp_eligible,
        ranking_generation_hash=None,
        as_of=frozen.effective_snapshot_date,
        pick_count=len(entries),
        entries=entries,
        exclusions={},
        missing_reasons=(),
        provenance={
            "frozenSnapshotId": frozen.snapshot_id,
            "frozenChecksum": frozen.checksum,
            "kind": frozen.kind,
            "isPreDraftObservation": False,
            "playerIdentities": "unavailable — pricing template only",
        },
    )


def _decimal(text: Any, what: str) -> Decimal:
    if not isinstance(text, str):
        raise SnapshotRecordError(f"{what} must be a decimal string, got {text!r}")
    try:
        return Decimal(text)
    except ArithmeticError as exc:
        raise SnapshotRecordError(f"{what} unreadable: {text!r}") from exc


def load_class_snapshot(payload: Mapping[str, Any]) -> RookieClassSnapshot:
    """Inverse of :meth:`RookieClassSnapshot.to_dict`, verified.

    The rebuilt snapshot must reproduce the stored ``snapshotSha256`` exactly,
    so an edited record (a value, an entry, a provenance field) is refused
    rather than read.
    """
    if not isinstance(payload, Mapping) or payload.get("schema") != SCHEMA:
        raise SnapshotRecordError("not a rookie class snapshot")
    try:
        entries = tuple(
            ClassEntry(
                rank=int(e["rank"]),
                canonical_player_id=e.get("canonicalPlayerId"),
                name=e.get("name"),
                position=e.get("position"),
                asset_class=e.get("assetClass"),
                eligible_draft_year=e.get("eligibleDraftYear"),
                class_basis=str(e["classBasis"]),
                value=_decimal(e.get("value"), f"entry {e.get('rank')} value"),
                rosterable_on_sleeper=bool(e["rosterableOnSleeper"]),
                pick=e.get("pick"),
            )
            for e in payload["entries"]
        )
        snap = RookieClassSnapshot(
            target_draft_year=int(payload["targetDraftYear"]),
            actual_input_class_year=payload.get("actualInputClassYear"),
            mode=str(payload["mode"]),
            status=str(payload["status"]),
            league_key=payload.get("leagueKey"),
            scoring_fingerprint=payload.get("scoringFingerprint"),
            idp_eligible=payload.get("idpEligible"),
            ranking_generation_hash=payload.get("rankingGenerationHash"),
            as_of=payload.get("asOf"),
            pick_count=int(payload["pickCount"]),
            entries=entries,
            exclusions=dict(payload.get("exclusions") or {}),
            missing_reasons=tuple(payload.get("missingReasons") or ()),
            provenance=dict(payload.get("provenance") or {}),
            model_version=str(payload["modelVersion"]),
        )
    except (KeyError, TypeError, ValueError) as exc:
        if isinstance(exc, SnapshotRecordError):
            raise
        raise SnapshotRecordError(f"snapshot record malformed: {exc}") from exc
    if snap.snapshot_sha256 != payload.get("snapshotSha256"):
        raise SnapshotRecordError("snapshotSha256 mismatch — record was edited")
    return snap
