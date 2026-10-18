"""Immutable draft-valuation snapshots: frozen rookie inputs + completed-class curves.

Two kinds of tracked, checksummed snapshot live under
``config/draft_valuation/`` (tracked and outside ``data/`` so CI and
production read the same bytes):

``frozen_inputs/<id>.json``
    A frozen set of 72 rookie-value inputs (the curve's column B).  The first
    is ``2026_spreadsheet_baseline`` — the owner-approved PROVISIONAL rookie
    values copied from ``Draft Data!B2:B73`` (owner decision 2026-10-18).  It
    is labelled as what it is: a provisional baseline, never a pre-draft
    observation, and daily value changes never rewrite it.

``historical_curves/<leagueKey>/<year>.json``
    The final 72 pick dollars of a COMPLETED rookie draft class (a spine
    input, columns F/G/H).  The 2024/2025/2026 curves are spreadsheet-sourced
    and say so: the inputs, spine years and formula version that produced
    them are not in the workbook, so those fields are ``null`` with a reason
    rather than invented.  A historical curve is valuation history, not an
    active asset — loading one never reactivates a retired pick class.

Every file carries a sha256 over its canonical JSON (every top-level key
except ``checksum``); the loader refuses a mismatch, a malformed pick list or
a curve that breaks the pool invariants.  There is no fallback: a refused or
missing snapshot is an error, never a zero or a substitute year.

The spine for a target class is the :data:`SPINE_CLASS_COUNT` most recent
completed classes strictly before it (2027 -> 2024, 2025, 2026).  Rolling the
spine forward requires a new completed-class snapshot, which Batch C writes
only on verified draft completion.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any, Iterable, Sequence

from src.draft.rookie_auction.curve import WORKBOOK_PARAMS, CurveParams, iter_labels
from src.draft.rookie_auction.league_scope import league_scope

__all__ = [
    "CONFIG_DIR",
    "CURVE_SCHEMA",
    "DEFAULT_LEAGUE_KEY",
    "KIND_GENERATED",
    "KIND_SPREADSHEET",
    "SPINE_CLASS_COUNT",
    "CompletedClassCurve",
    "FrozenRookieInputs",
    "SnapshotIntegrityError",
    "SpineUnavailableError",
    "available_completed_classes",
    "canonical_checksum",
    "load_completed_class_curve",
    "load_frozen_rookie_inputs",
    "select_spine_years",
    "spine_curves_for",
]

CONFIG_DIR = Path(__file__).resolve().parents[3] / "config" / "draft_valuation"
FROZEN_DIR_NAME = "frozen_inputs"
CURVE_DIR_NAME = "historical_curves"
SPINE_CLASS_COUNT = 3
#: The Draft Data workbook is the registry default league's.
DEFAULT_LEAGUE_KEY = "dynasty_main"
KIND_SPREADSHEET = "spreadsheet_sourced_historical_curve"
KIND_GENERATED = "generated_class_curve"
CURVE_KINDS = frozenset({KIND_SPREADSHEET, KIND_GENERATED})

FROZEN_SCHEMA = "draft_valuation_frozen_rookie_inputs_v1"
CURVE_SCHEMA = "draft_valuation_completed_class_curve_v1"


class SnapshotIntegrityError(RuntimeError):
    """A snapshot file failed its checksum or structural validation."""


class SpineUnavailableError(LookupError):
    """Fewer completed classes exist than the spine needs."""


def canonical_checksum(payload: dict[str, Any]) -> str:
    body = {k: v for k, v in payload.items() if k != "checksum"}
    text = json.dumps(body, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


@dataclass(frozen=True)
class FrozenRookieInputs:
    snapshot_id: str
    picks: tuple[str, ...]
    values: tuple[Decimal, ...]
    kind: str
    is_pre_draft_observation: bool
    provenance: dict[str, Any]
    checksum: str
    effective_snapshot_date: str | None = None
    source_season_label: int | None = None


@dataclass(frozen=True)
class CompletedClassCurve:
    draft_class: int
    league_key: str
    picks: tuple[str, ...]
    dollars: tuple[Decimal, ...]
    kind: str
    provenance: dict[str, Any]
    #: ``referenceDollars`` (above, as ``dollars``) builds the spine;
    #: ``finalWholeDollars`` is what was published and spendable — ``None``
    #: for a spreadsheet-imported class whose published allocation is unknown.
    final_whole_dollars: tuple[int, ...] | None
    completion_observed_at: str | None
    checksum: str


def _read(path: Path) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        raise
    except (OSError, ValueError) as exc:
        raise SnapshotIntegrityError(f"{path.name}: unreadable ({exc})") from exc
    if not isinstance(payload, dict):
        raise SnapshotIntegrityError(f"{path.name}: not a JSON object")
    stated = (
        (payload.get("checksum") or {}).get("value")
        if isinstance(payload.get("checksum"), dict)
        else None
    )
    if not isinstance(stated, str) or stated != canonical_checksum(payload):
        raise SnapshotIntegrityError(f"{path.name}: checksum mismatch — snapshot was edited")
    return payload


def _decimal_list(
    rows: Any, key: str, path: Path, params: CurveParams
) -> tuple[tuple[str, ...], tuple[Decimal, ...]]:
    expected = tuple(iter_labels(params))
    if not isinstance(rows, list) or len(rows) != len(expected):
        raise SnapshotIntegrityError(f"{path.name}: expected {len(expected)} picks")
    picks: list[str] = []
    values: list[Decimal] = []
    for want, row in zip(expected, rows):
        if not isinstance(row, dict) or row.get("pick") != want:
            raise SnapshotIntegrityError(f"{path.name}: pick order broken at {want}")
        raw = row.get(key)
        if not isinstance(raw, str):
            raise SnapshotIntegrityError(f"{path.name}: {want} {key} must be a decimal string")
        try:
            value = Decimal(raw)
        except InvalidOperation as exc:
            raise SnapshotIntegrityError(f"{path.name}: {want} {key} is not a number") from exc
        if not value.is_finite() or value < 0:
            raise SnapshotIntegrityError(f"{path.name}: {want} {key} out of range")
        picks.append(want)
        values.append(value)
    return tuple(picks), tuple(values)


def load_frozen_rookie_inputs(
    snapshot_id: str = "2026_spreadsheet_baseline",
    *,
    config_dir: Path = CONFIG_DIR,
    params: CurveParams = WORKBOOK_PARAMS,
) -> FrozenRookieInputs:
    path = config_dir / FROZEN_DIR_NAME / f"{snapshot_id}.json"
    payload = _read(path)
    if payload.get("schema") != FROZEN_SCHEMA or payload.get("snapshotId") != snapshot_id:
        raise SnapshotIntegrityError(f"{path.name}: wrong schema or snapshot id")
    if payload.get("isPreDraftObservation") is not False:
        raise SnapshotIntegrityError(
            f"{path.name}: a frozen baseline is never a pre-draft observation"
        )
    picks, values = _decimal_list(payload.get("values"), "value", path, params)
    return FrozenRookieInputs(
        snapshot_id=snapshot_id,
        picks=picks,
        values=values,
        kind=str(payload.get("kind")),
        is_pre_draft_observation=False,
        provenance=dict(payload.get("provenance") or {}),
        checksum=payload["checksum"]["value"],
        effective_snapshot_date=payload.get("effectiveSnapshotDate") or None,
        source_season_label=payload.get("sourceSeasonLabel")
        if isinstance(payload.get("sourceSeasonLabel"), int)
        else None,
    )


def _whole_dollars(payload, kind, path: Path, params: CurveParams) -> tuple[int, ...] | None:
    raw = payload.get("finalWholeDollars")
    if raw is None:
        if kind == KIND_GENERATED:
            raise SnapshotIntegrityError(
                f"{path.name}: a generated curve must carry finalWholeDollars"
            )
        if not payload.get("finalWholeDollarsUnavailableReason"):
            raise SnapshotIntegrityError(f"{path.name}: finalWholeDollars missing without a reason")
        return None
    labels = list(iter_labels(params))
    if not isinstance(raw, list) or [r.get("pick") for r in raw if isinstance(r, dict)] != labels:
        raise SnapshotIntegrityError(f"{path.name}: finalWholeDollars pick list broken")
    whole = [r.get("dollars") for r in raw]
    if any(isinstance(d, bool) or not isinstance(d, int) or d < 0 for d in whole):
        raise SnapshotIntegrityError(f"{path.name}: finalWholeDollars must be whole dollars")
    if sum(whole) != params.budget_dollars:
        raise SnapshotIntegrityError(f"{path.name}: finalWholeDollars do not sum to the pool")
    if any(whole[i] > whole[i - 1] for i in range(1, len(whole))):
        raise SnapshotIntegrityError(f"{path.name}: finalWholeDollars rise")
    return tuple(whole)


def _curve_dir(config_dir: Path, league_key: str) -> Path:
    league_scope(league_key)  # fail closed: only configured leagues have a ledger
    key = str(league_key or "").strip()
    if not key or "/" in key or key.startswith("."):
        raise SnapshotIntegrityError(f"invalid league key {league_key!r}")
    return config_dir / CURVE_DIR_NAME / key


def load_completed_class_curve(
    draft_class: int,
    *,
    league_key: str = DEFAULT_LEAGUE_KEY,
    config_dir: Path = CONFIG_DIR,
    params: CurveParams = WORKBOOK_PARAMS,
) -> CompletedClassCurve:
    path = _curve_dir(config_dir, league_key) / f"{int(draft_class)}.json"
    payload = _read(path)
    if payload.get("schema") != CURVE_SCHEMA or payload.get("draftClass") != int(draft_class):
        raise SnapshotIntegrityError(f"{path.name}: wrong schema or draft class")
    if payload.get("leagueKey") != league_key:
        raise SnapshotIntegrityError(f"{path.name}: belongs to {payload.get('leagueKey')!r}")
    kind = payload.get("kind")
    if kind not in CURVE_KINDS:
        raise SnapshotIntegrityError(f"{path.name}: unknown curve kind {kind!r}")
    if kind == KIND_GENERATED:
        completion = payload.get("draftCompletion")
        if not isinstance(completion, dict) or completion.get("status") != "retired":
            raise SnapshotIntegrityError(
                f"{path.name}: a generated class curve needs verified draft completion"
            )
    picks, dollars = _decimal_list(payload.get("referenceDollars"), "dollars", path, params)
    whole = _whole_dollars(payload, kind, path, params)
    units = [d * params.units_per_dollar for d in dollars]
    if any(u != u.to_integral_value() for u in units):
        raise SnapshotIntegrityError(f"{path.name}: dollars are not whole units")
    if sum(dollars, Decimal(0)) != Decimal(params.budget_dollars):
        raise SnapshotIntegrityError(f"{path.name}: dollars do not sum to the class pool")
    if any(dollars[i] > dollars[i - 1] for i in range(1, len(dollars))):
        raise SnapshotIntegrityError(f"{path.name}: curve rises")
    return CompletedClassCurve(
        draft_class=int(draft_class),
        league_key=league_key,
        picks=picks,
        dollars=dollars,
        kind=str(kind),
        provenance=dict(payload.get("provenance") or {}),
        final_whole_dollars=whole,
        completion_observed_at=(payload.get("draftCompletion") or {}).get("observedAt")
        if isinstance(payload.get("draftCompletion"), dict)
        else None,
        checksum=payload["checksum"]["value"],
    )


def available_completed_classes(
    *, league_key: str = DEFAULT_LEAGUE_KEY, config_dir: Path = CONFIG_DIR
) -> tuple[int, ...]:
    d = _curve_dir(config_dir, league_key)
    if not d.is_dir():
        return ()
    return tuple(sorted(int(p.stem) for p in d.glob("*.json") if p.stem.isdigit()))


def select_spine_years(
    target_class: int,
    available: Iterable[int] | None = None,
    *,
    count: int = SPINE_CLASS_COUNT,
    league_key: str = DEFAULT_LEAGUE_KEY,
    config_dir: Path = CONFIG_DIR,
) -> tuple[int, ...]:
    """The ``count`` most recent completed classes strictly before ``target_class``.

    A class is "completed" for this purpose only if its snapshot exists in
    this league's ledger — the ledger writes one only on verified completion
    (``ledger.finalize_completed_class``) — so the spine rolls exactly when
    the evidence does, never on a calendar date.
    """
    league_scope(league_key)
    pool = (
        available_completed_classes(league_key=league_key, config_dir=config_dir)
        if available is None
        else available
    )
    prior = sorted({int(y) for y in pool if int(y) < int(target_class)})
    if len(prior) < count:
        raise SpineUnavailableError(
            f"class {target_class} needs {count} completed classes before it; have {prior}"
        )
    return tuple(prior[-count:])


def spine_curves_for(
    target_class: int,
    *,
    league_key: str = DEFAULT_LEAGUE_KEY,
    config_dir: Path = CONFIG_DIR,
    params: CurveParams = WORKBOOK_PARAMS,
) -> tuple[tuple[int, ...], Sequence[tuple[Decimal, ...]]]:
    years = select_spine_years(
        target_class, league_key=league_key, config_dir=config_dir, count=params.spine_curve_count
    )
    curves = [
        load_completed_class_curve(
            y, league_key=league_key, config_dir=config_dir, params=params
        ).dollars
        for y in years
    ]
    return years, curves
