"""As-of replay of a stored draft-class generation (Batch G).

"What did ``dynasty_main`` publish for draft class Y as of time T, and does it
recompute, byte for byte, from the inputs that existed at T?"::

    from src.draft.rookie_auction.replay import replay_generation
    out = replay_generation("dynasty_main", 2028, "2026-10-18T12:00:00+00:00")
    out.state, out.reproduced, out.reasons

The replay selects ONLY evidence that existed at ``as_of``:

* the stored record — the newest verified published allocation for that
  (league, year) whose ``effectiveAt`` is at or before ``as_of``
  (``published.allocation_history``); a record effective later is never
  selectable and is listed in ``excludedFutureRecords``;
* the spine — ``ledger.replay_spine(as_of=...)``: a generated completed-class
  snapshot counts only if its completion was observed at or before
  ``as_of``; the spreadsheet-sourced classes carry no completion time and are
  flagged by that function (``asOfUnknown``);
* the rookie inputs — the frozen provisional baseline, only if its
  ``effectiveSnapshotDate`` is on or before ``as_of``'s UTC date (the file
  states a date, not a time; the date is read as 00:00 UTC);
* promotion pointers — a pointer written at or before ``as_of`` would make a
  promoted generation current, which this replay does not reconstruct: the
  answer is then ``refused`` with that reason, never a guess.  None exists
  today.  Pointers written after ``as_of`` are ignored and listed.

It then checks every receipt the stored record carries against that as-of
evidence (spine years, each spine class checksum, the frozen inputs
checksum, the input snapshot hash, the input class year), recomputes the
curve with the canonical calculation (``curve.compute_curve`` via
``generation.class_curve_candidate`` over an as-of VIEW of the ledger, so the
spine is selected by the same code the live path uses), turns it into a
record with the canonical resolver (``published.resolve_published_allocation``
writing into a temporary store) and compares the bytes of that file with the
stored file.

* A record the live path computed (``provenance.source ==
  "rookie_auction_curve"``) is rebuilt with RECOMPUTED provenance — curve id,
  input and spine checksums and the curve receipt hash all come out of the
  replay, so byte equality proves them too (``provenanceMode:
  "recomputed"``).
* A workbook-derived seed (any other source) has a provenance text the live
  path does not produce; its provenance is carried verbatim AFTER every
  receipt in it is verified against the as-of evidence
  (``provenanceMode: "verified_receipts"``).

Read-only: nothing is written outside a temporary directory, which is
removed.  States: ``reproduced`` (byte-identical), ``differs`` (recomputed
and NOT identical — the diff is named), ``unavailable`` (nothing effective at
``as_of``), ``refused`` (the replay cannot be done honestly; the reason is
named).
"""

from __future__ import annotations

import shutil
import tempfile
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping, Sequence

from src.draft.rookie_auction import published as _published
from src.draft.rookie_auction import snapshots as _snap
from src.draft.rookie_auction.curve import FORMULA_VERSION, compute_curve
from src.draft.rookie_auction.league_scope import LeagueNotConfiguredError, league_scope

__all__ = [
    "PROVENANCE_RECOMPUTED",
    "PROVENANCE_VERIFIED_RECEIPTS",
    "STATE_DIFFERS",
    "STATE_REFUSED",
    "STATE_REPRODUCED",
    "STATE_UNAVAILABLE",
    "GenerationReplay",
    "replay_generation",
]

STATE_REPRODUCED = "reproduced"
STATE_DIFFERS = "differs"
STATE_UNAVAILABLE = "unavailable"
STATE_REFUSED = "refused"

PROVENANCE_RECOMPUTED = "recomputed"
PROVENANCE_VERIFIED_RECEIPTS = "verified_receipts"

_LIVE_PATH_SOURCE = "rookie_auction_curve"
_FROZEN_MODE = "frozen_fallback"


@dataclass(frozen=True)
class GenerationReplay:
    league_key: str
    draft_year: int
    as_of: str
    state: str
    reasons: tuple[str, ...]
    stored_path: str | None = None
    stored_checksum: str | None = None
    replayed_checksum: str | None = None
    spine_years: tuple[int, ...] | None = None
    provenance_mode: str | None = None
    excluded_future_records: tuple[str, ...] = ()
    ignored_future_pointers: tuple[int, ...] = ()
    first_difference: str | None = None
    ledger: tuple[Mapping[str, Any], ...] = field(default_factory=tuple)

    @property
    def reproduced(self) -> bool:
        return self.state == STATE_REPRODUCED

    def to_dict(self) -> dict[str, Any]:
        return {
            "leagueKey": self.league_key,
            "draftYear": self.draft_year,
            "asOf": self.as_of,
            "state": self.state,
            "reproduced": self.reproduced,
            "reasons": list(self.reasons),
            "storedPath": self.stored_path,
            "storedChecksum": self.stored_checksum,
            "replayedChecksum": self.replayed_checksum,
            "spineYears": None if self.spine_years is None else list(self.spine_years),
            "provenanceMode": self.provenance_mode,
            "excludedFutureRecords": list(self.excluded_future_records),
            "ignoredFuturePointers": list(self.ignored_future_pointers),
            "firstDifference": self.first_difference,
            "ledger": [dict(r) for r in self.ledger],
        }


def _ts(value: str) -> datetime:
    ts = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    if ts.tzinfo is None:
        raise ValueError(f"timestamp without timezone: {value!r}")
    return ts


def _first_difference(a: bytes, b: bytes) -> str | None:
    if a == b:
        return None
    la, lb = a.decode("utf-8").splitlines(), b.decode("utf-8").splitlines()
    for i, (x, y) in enumerate(zip(la, lb), start=1):
        if x != y:
            return f"line {i}: stored {x.strip()!r} vs replayed {y.strip()!r}"
    return f"length: stored {len(la)} lines vs replayed {len(lb)} lines"


def _as_of_view(config_dir: Path, league_key: str, usable: Sequence[int], into: Path) -> Path:
    """A copy of the ledger holding only the completed classes usable at ``as_of``."""
    src = config_dir / _snap.CURVE_DIR_NAME / league_key
    dst = into / _snap.CURVE_DIR_NAME / league_key
    dst.mkdir(parents=True)
    for year in usable:
        shutil.copy2(src / f"{int(year)}.json", dst / f"{int(year)}.json")
    return into


def replay_generation(
    league_key: str,
    draft_year: int,
    as_of: str,
    *,
    config_dir: Path | None = None,
    store_dirs: Sequence[Path] | None = None,
    promotion_root: Path | None = None,
) -> GenerationReplay:
    """Replay ``(league_key, draft_year)`` as of ``as_of``.  See the module docstring."""
    from src.draft.rookie_auction.class_snapshot import frozen_fallback_snapshot  # noqa: PLC0415
    from src.draft.rookie_auction.generation import (  # noqa: PLC0415
        ClassCurveInputs,
        class_curve_candidate,
    )
    from src.draft.rookie_auction.ledger import LedgerRefusal, replay_spine  # noqa: PLC0415

    year = int(draft_year)
    key = str(league_key or "")
    cfg = Path(config_dir) if config_dir is not None else _snap.CONFIG_DIR
    base = {"league_key": key, "draft_year": year, "as_of": str(as_of)}

    def out(state: str, *reasons: str, **kw: Any) -> GenerationReplay:
        return GenerationReplay(**base, state=state, reasons=tuple(reasons), **kw)

    try:
        league_scope(key)
    except LeagueNotConfiguredError:
        return out(STATE_REFUSED, f"league_not_configured:{key}")
    try:
        cutoff = _ts(as_of)
    except (TypeError, ValueError) as exc:
        return out(STATE_REFUSED, f"as_of_unreadable:{exc}")

    # 1. the record in force at ``as_of`` (records effective later are not selectable).
    history = _published.allocation_history(key, year, store_dirs=store_dirs)
    eligible: list[tuple[Path, dict]] = []
    future: list[str] = []
    for path, record, _error in history:
        if record is None or record.get("formulaVersion") != FORMULA_VERSION:
            continue
        if _ts(record["effectiveAt"]) <= cutoff:
            eligible.append((path, record))
        else:
            future.append(path.name)

    # 2. promotion pointers: one at or before ``as_of`` is not reconstructed here.
    proot = promotion_root if promotion_root is not None else _published.PROMOTION_ROOT
    gen = _published.generation_state(key, year, root=proot)
    if gen.error is not None:
        return out(STATE_REFUSED, f"promotion_pointer_history_unreadable:{gen.error}")
    past_ptr = [p for p in gen.pointers if _ts(p["at"]) <= cutoff]
    future_ptr = tuple(int(p["sequence"]) for p in gen.pointers if _ts(p["at"]) > cutoff)
    if past_ptr:
        return out(
            STATE_REFUSED,
            "promoted_generation_replay_not_supported",
            ignored_future_pointers=future_ptr,
            excluded_future_records=tuple(future),
        )
    if not eligible:
        return out(
            STATE_UNAVAILABLE,
            "no_record_effective_as_of",
            excluded_future_records=tuple(future),
            ignored_future_pointers=future_ptr,
        )
    stored_path, record = eligible[-1]
    common = {
        "stored_path": str(stored_path),
        "stored_checksum": record["checksum"]["value"],
        "excluded_future_records": tuple(future),
        "ignored_future_pointers": future_ptr,
    }
    prov = record.get("provenance") or {}

    # 3. the spine as of ``as_of`` — and the receipts the record carries for it.
    try:
        spine_view = replay_spine(year, league_key=key, as_of=str(as_of), config_dir=cfg)
    except (LedgerRefusal, _snap.SnapshotIntegrityError, OSError) as exc:
        return out(STATE_REFUSED, f"ledger_unreadable:{exc}", **common)
    ledger_rows = tuple(spine_view["ledger"])
    spine = spine_view["spineYears"]
    if spine is None:
        return out(
            STATE_REFUSED,
            f"spine_unavailable_as_of:{spine_view['spineUnavailable']}",
            ledger=ledger_rows,
            **common,
        )
    spine = tuple(int(y) for y in spine)
    common.update(spine_years=spine, ledger=ledger_rows)
    if prov.get("inputsMode") != _FROZEN_MODE:
        return out(
            STATE_REFUSED, f"inputs_not_on_file:inputsMode={prov.get('inputsMode')!r}", **common
        )
    for required in ("spineYears", "spineChecksums", "frozenInputsChecksum"):
        if not prov.get(required):
            return out(STATE_REFUSED, f"record_lacks_replay_receipt:{required}", **common)
    if tuple(int(y) for y in prov["spineYears"]) != spine:
        return out(
            STATE_DIFFERS,
            f"spine_differs:record={list(prov['spineYears'])}:as_of={list(spine)}",
            **common,
        )
    for y in spine:
        curve = _snap.load_completed_class_curve(y, league_key=key, config_dir=cfg)
        if prov["spineChecksums"].get(str(y)) != curve.checksum:
            return out(STATE_DIFFERS, f"spine_class_checksum_differs:{y}", **common)

    # 4. the inputs as of ``as_of``.
    frozen = _snap.load_frozen_rookie_inputs(config_dir=cfg)
    if frozen.checksum != prov["frozenInputsChecksum"]:
        return out(STATE_DIFFERS, "frozen_inputs_checksum_differs", **common)
    eff = frozen.effective_snapshot_date
    if not eff:
        return out(STATE_REFUSED, "inputs_effective_date_unknown", **common)
    inputs_at = datetime.fromisoformat(str(eff)).replace(tzinfo=timezone.utc)
    if inputs_at > cutoff or inputs_at > _ts(record["effectiveAt"]):
        return out(STATE_REFUSED, f"inputs_not_effective_as_of:{eff}", **common)
    snapshot = frozen_fallback_snapshot(year, league_key=key, frozen=frozen)
    for field_name, expected in (
        ("inputsSnapshotSha256", snapshot.snapshot_sha256),
        ("actualInputClassYear", snapshot.actual_input_class_year),
        ("workbookSha256", frozen.provenance.get("sourceWorkbookSha256")),
    ):
        if field_name in prov and prov[field_name] != expected:
            return out(STATE_DIFFERS, f"receipt_differs:{field_name}", **common)

    # 5. recompute, rebuild through the canonical resolver, compare bytes.
    work = Path(tempfile.mkdtemp(prefix="draft-valuation-replay-"))
    try:
        view = _as_of_view(cfg, key, spine, work / "config")
        live_path = prov.get("source") == _LIVE_PATH_SOURCE

        def inputs_fn(_league: str, _year: int) -> ClassCurveInputs:
            return ClassCurveInputs(
                values=tuple(snapshot.curve_values()),
                input_mode=str(snapshot.mode),
                inputs_id=frozen.snapshot_id,
                actual_input_class_year=snapshot.actual_input_class_year,
                provenance=dict(snapshot.provenance),
            )

        if live_path:
            candidate = class_curve_candidate(
                key, year, now=record["effectiveAt"], config_dir=view, inputs_fn=inputs_fn
            )
            mode = PROVENANCE_RECOMPUTED
        else:
            curves = [
                _snap.load_completed_class_curve(y, league_key=key, config_dir=view).dollars
                for y in spine
            ]
            result = compute_curve(list(snapshot.curve_values()), curves)
            candidate = _published.AllocationCandidate.from_curve(
                result, draft_year=year, effective_at=record["effectiveAt"], provenance=dict(prov)
            )
            mode = PROVENANCE_VERIFIED_RECEIPTS
        if not isinstance(candidate, _published.AllocationCandidate):
            reason = getattr(candidate, "reason", "no_candidate")
            return out(STATE_REFUSED, f"recompute_failed:{reason}", provenance_mode=mode, **common)
        write = work / "store"
        alloc = _published.resolve_published_allocation(
            key, year, candidate=candidate, store_dirs=[], write_dir=write, persist=True
        )
        written = sorted((write / key / str(year)).glob("*.json")) if write.is_dir() else []
        if alloc.allocation_state != _published.STATE_CURRENT or len(written) != 1:
            return out(
                STATE_REFUSED,
                f"recompute_not_publishable:{alloc.allocation_state}:{alloc.unavailable_reason}",
                provenance_mode=mode,
                **common,
            )
        stored_bytes = Path(stored_path).read_bytes()
        replayed_bytes = written[0].read_bytes()
        diff = _first_difference(stored_bytes, replayed_bytes)
        same_name = written[0].name == Path(stored_path).name
        if diff is None and same_name:
            return out(
                STATE_REPRODUCED,
                "byte_identical",
                replayed_checksum=alloc.record_checksum,
                provenance_mode=mode,
                **common,
            )
        return out(
            STATE_DIFFERS,
            "bytes_differ" if diff else f"file_name_differs:{written[0].name}",
            replayed_checksum=alloc.record_checksum,
            provenance_mode=mode,
            first_difference=diff,
            **common,
        )
    finally:
        shutil.rmtree(work, ignore_errors=True)
