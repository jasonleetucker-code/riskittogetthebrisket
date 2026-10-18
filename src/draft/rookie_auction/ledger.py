"""Completed-class rollover ledger — the spine rolls only on verified completion (Batch C).

The spine for class ``Y`` is the three most recent COMPLETED classes before
it (``snapshots.select_spine_years``).  "Completed" means a snapshot exists in
the league's ledger, ``config/draft_valuation/historical_curves/<league>/``,
and this module is the only writer of new ones.  So the spine rolls exactly
when the evidence does: 2027 → {2024, 2025, 2026}; 2028 → {2025, 2026, 2027}
only after 2027's snapshot is finalized; never on a calendar date, never from
an invented class.

:func:`finalize_completed_class` writes a class's curve once, and only when:

* the league is configured (``dynasty_main`` — owner scope 2026-10-18);
* ``src/identity/pick_lifecycle.draft_class_lifecycle`` — the one owner of
  "is this class done" — says ``retired`` for that league's OWN evidence
  (rookie draft complete AND the picked rookies consumed onto rosters).
  Evidence from another league is refused, so leagues with different
  completion dates are never conflated;
* the class's input snapshot is COMPLETE and was observed at or before the
  stated pre-draft cutoff, and the cutoff is at or before the completion
  observation — a post-draft board can never be filed as pre-draft history;
* the curve recomputes, from those inputs and the spine in force, to exactly
  $1,200.

Writes are atomic and create-only (``os.link`` of a fully written temporary
file): identical finalization evidence is an idempotent no-op returning the
same snapshot; different content for an existing class is refused
(:class:`ImmutableSnapshotConflict`) — a changed source after the cutoff
cannot rewrite history.  Nothing is ever deleted: a class that leaves the
three-year window stays readable for replay.

Called by Batch D (owner decision 12, 2026-10-18): ``promotion.py``'s
finalization step runs it from the scheduled refresh (live mode only; dry run
reports what it would file), and the snapshot lands in the repo-tracked
``historical_curves/`` that the workflow commits.  The pre-draft cutoff comes
from Sleeper's draft ``start_time`` (:func:`pre_draft_cutoff_from_sleeper`),
never a constant; unknown refuses.
"""

from __future__ import annotations

import json
import os
from fractions import Fraction
import tempfile
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

from src.draft.rookie_auction.class_snapshot import STATUS_COMPLETE, RookieClassSnapshot
from src.draft.rookie_auction.curve import (
    FORMULA_VERSION,
    WORKBOOK_PARAMS,
    compute_curve,
    curve_receipt,
    whole_dollar_constraints,
)
from src.draft.rookie_auction.verify import verify_whole_dollar_allocation
from src.draft.rookie_auction.league_scope import league_scope
from src.draft.rookie_auction.snapshots import (
    CONFIG_DIR,
    CURVE_DIR_NAME,
    CURVE_SCHEMA,
    KIND_GENERATED,
    KIND_SPREADSHEET,
    available_completed_classes,
    canonical_checksum,
    load_completed_class_curve,
    select_spine_years,
    spine_curves_for,
)
from src.identity.pick_lifecycle import (
    LeagueDraftEvidence,
    draft_class_lifecycle,
    is_retired,
)

__all__ = [
    "FinalizeOutcome",
    "ImmutableSnapshotConflict",
    "LedgerRefusal",
    "finalize_completed_class",
    "pre_draft_cutoff_from_sleeper",
    "replay_spine",
]

_ROOKIE_DRAFT_REASON = "rookie_draft_complete:"


class LedgerRefusal(RuntimeError):
    """The class cannot be finalized; ``reason`` is machine-readable."""

    def __init__(self, reason: str, detail: str = "") -> None:
        super().__init__(f"{reason}: {detail}" if detail else reason)
        self.reason = reason


class ImmutableSnapshotConflict(RuntimeError):
    """A different snapshot for this class already exists."""


@dataclass(frozen=True)
class FinalizeOutcome:
    path: Path
    created: bool
    checksum: str
    spine_years: tuple[int, ...]


def _parse_ts(value: str | None, what: str) -> datetime:
    if not value:
        raise LedgerRefusal("timestamp_missing", what)
    try:
        ts = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError as exc:
        raise LedgerRefusal("timestamp_unreadable", f"{what}={value!r}") from exc
    if ts.tzinfo is None:
        raise LedgerRefusal("timestamp_without_timezone", f"{what}={value!r}")
    return ts


def _build_payload(
    *,
    league_key: str,
    draft_class: int,
    inputs: RookieClassSnapshot,
    evidence: LeagueDraftEvidence,
    lifecycle_reasons: tuple[str, ...],
    pre_draft_cutoff: str,
    config_dir: Path,
) -> dict[str, Any]:
    scope = league_scope(league_key)
    spine_years, curves = spine_curves_for(
        draft_class, league_key=league_key, config_dir=config_dir
    )
    result = compute_curve(inputs.curve_values(), curves, WORKBOOK_PARAMS)
    if result.whole_dollars is None:
        raise LedgerRefusal("whole_dollar_step_refused", str(result.whole_dollars_refusal))
    floors, caps = whole_dollar_constraints(WORKBOOK_PARAMS)
    verification = verify_whole_dollar_allocation(
        [Fraction(d) for d in result.reference_dollars],
        result.final_whole_dollars,
        scope.budget_dollars_per_class,
        floors=floors,
        caps=caps,
    )
    if not verification.ok:
        raise LedgerRefusal("verification_failed", ", ".join(verification.failures))
    spine_checksums = {
        str(y): load_completed_class_curve(y, league_key=league_key, config_dir=config_dir).checksum
        for y in spine_years
    }
    receipt = curve_receipt(
        result,
        spine_years=spine_years,
        input_provenance={"mode": inputs.mode, "snapshotSha256": inputs.snapshot_sha256},
    )
    labels = [r.label for r in result.rows]
    payload: dict[str, Any] = {
        "schema": CURVE_SCHEMA,
        "draftClass": int(draft_class),
        "kind": KIND_GENERATED,
        "label": f"{draft_class} rookie-draft dollar curve, finalized on verified completion",
        "leagueKey": league_key,
        "leagueConfig": {
            "teamCount": scope.team_count,
            "rounds": scope.rounds,
            "budgetDollars": scope.budget_dollars_per_class,
            "unitsPerDollar": WORKBOOK_PARAMS.units_per_dollar,
        },
        "provenance": {
            "inputsSnapshotSha256": inputs.snapshot_sha256,
            "inputsMode": inputs.mode,
            "actualInputClassYear": inputs.actual_input_class_year,
            "inputsAsOf": inputs.as_of,
            "preDraftCutoff": pre_draft_cutoff,
        },
        "inputs": inputs.to_dict(),
        "spineYears": list(spine_years),
        "spineChecksums": spine_checksums,
        "formulaVersion": FORMULA_VERSION,
        "draftCompletion": {
            "status": "retired",
            "reasons": list(lifecycle_reasons),
            "observedAt": evidence.observed_at,
            "sleeperLeagueId": evidence.sleeper_league_id,
            "evidence": evidence.to_dict(),
        },
        # Deterministic: the completion observation, never the wall clock, so
        # identical evidence always yields an identical snapshot.
        "createdAt": evidence.observed_at,
        "validation": {**receipt, "verifier": verification.receipt()},
        # Owner decision 2026-10-18 — two values per completed class:
        # ``referenceDollars`` (the spreadsheet curve at its original
        # precision) builds the three-year spine, as the F/G/H formula was
        # designed around; ``finalWholeDollars`` is what was published and
        # spendable.  Fractional dollars are never spendable budget.
        "referenceDollars": [
            {"pick": label, "dollars": format(d.normalize(), "f")}
            for label, d in zip(labels, result.dollars)
        ],
        # The published whole-dollar values (owner decision 2026-10-18).
        "finalWholeDollars": [
            {"pick": label, "dollars": d} for label, d in zip(labels, result.final_whole_dollars)
        ],
    }
    payload["checksum"] = {
        "algorithm": "sha256",
        "scope": "canonical JSON (sort_keys, separators (',',':'), UTF-8) of every top-level key except 'checksum'",
        "value": canonical_checksum(payload),
    }
    return payload


def finalize_completed_class(
    *,
    league_key: str,
    draft_class: int,
    inputs: RookieClassSnapshot,
    evidence: LeagueDraftEvidence,
    pre_draft_cutoff: str,
    config_dir: Path = CONFIG_DIR,
) -> FinalizeOutcome:
    """File class ``draft_class``'s curve into the ledger.  See the module docstring."""
    league_scope(league_key)
    draft_class = int(draft_class)
    if evidence is None or evidence.league_key != league_key:
        raise LedgerRefusal(
            "evidence_league_mismatch",
            f"evidence is for {getattr(evidence, 'league_key', None)!r}, not {league_key!r}",
        )
    lifecycle = draft_class_lifecycle(draft_class, evidence)
    if not is_retired(lifecycle):
        raise LedgerRefusal(
            "class_not_verified_complete", f"{lifecycle.status}: {list(lifecycle.reasons)}"
        )
    if inputs.league_key != league_key or inputs.target_draft_year != draft_class:
        raise LedgerRefusal("inputs_for_another_class_or_league")
    if inputs.status != STATUS_COMPLETE:
        raise LedgerRefusal("inputs_incomplete", ", ".join(inputs.missing_reasons))
    inputs_at = _parse_ts(inputs.as_of, "inputs.as_of")
    cutoff = _parse_ts(pre_draft_cutoff, "pre_draft_cutoff")
    completed_at = _parse_ts(evidence.observed_at, "evidence.observed_at")
    if inputs_at > cutoff:
        raise LedgerRefusal("inputs_after_pre_draft_cutoff", f"{inputs.as_of} > {pre_draft_cutoff}")
    if cutoff > completed_at:
        raise LedgerRefusal(
            "cutoff_after_completion_observation", f"{pre_draft_cutoff} > {evidence.observed_at}"
        )

    payload = _build_payload(
        league_key=league_key,
        draft_class=draft_class,
        inputs=inputs,
        evidence=evidence,
        lifecycle_reasons=lifecycle.reasons,
        pre_draft_cutoff=pre_draft_cutoff,
        config_dir=config_dir,
    )
    target_dir = config_dir / CURVE_DIR_NAME / league_key
    target_dir.mkdir(parents=True, exist_ok=True)
    final = target_dir / f"{draft_class}.json"
    text = json.dumps(payload, indent=1, ensure_ascii=False) + "\n"
    checksum = payload["checksum"]["value"]

    fd, tmp_name = tempfile.mkstemp(prefix=f".{draft_class}.", suffix=".tmp", dir=target_dir)
    tmp = Path(tmp_name)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            fh.write(text)
            fh.flush()
            os.fsync(fh.fileno())
        try:
            os.link(tmp, final)  # atomic create-only: fails if the class exists
            created = True
        except FileExistsError:
            created = False
    finally:
        tmp.unlink(missing_ok=True)

    if not created:
        existing = json.loads(final.read_text(encoding="utf-8"))
        if (existing.get("checksum") or {}).get("value") != checksum:
            raise ImmutableSnapshotConflict(
                f"class {draft_class} for {league_key} is already finalized with different content"
            )
    # Read back through the validating loader: what was filed must load.
    load_completed_class_curve(draft_class, league_key=league_key, config_dir=config_dir)
    return FinalizeOutcome(
        path=final,
        created=created,
        checksum=checksum,
        spine_years=tuple(payload["spineYears"]),
    )


def replay_spine(
    target_class: int,
    *,
    league_key: str,
    as_of: str | None = None,
    config_dir: Path = CONFIG_DIR,
) -> dict[str, Any]:
    """Which spine class ``target_class`` would have used as of ``as_of``.

    Generated snapshots count only if their completion was observed at or
    before ``as_of``; spreadsheet-sourced curves have no recorded completion
    time, so they are included and flagged ``asOfUnknown``.  ``as_of=None``
    means "the ledger as it stands".
    """
    league_scope(league_key)
    cutoff = _parse_ts(as_of, "as_of") if as_of else None
    usable: list[int] = []
    classes: list[dict[str, Any]] = []
    for year in available_completed_classes(league_key=league_key, config_dir=config_dir):
        curve = load_completed_class_curve(year, league_key=league_key, config_dir=config_dir)
        row = {
            "draftClass": year,
            "kind": curve.kind,
            "completionObservedAt": curve.completion_observed_at,
            "checksum": curve.checksum,
            "asOfUnknown": curve.kind == KIND_SPREADSHEET,
        }
        include = True
        if cutoff is not None and curve.kind == KIND_GENERATED:
            include = _parse_ts(curve.completion_observed_at, "completionObservedAt") <= cutoff
        row["usableAsOf"] = include
        classes.append(row)
        if include:
            usable.append(year)
    try:
        spine = list(select_spine_years(target_class, usable, league_key=league_key))
        error = None
    except LookupError as exc:
        spine, error = None, str(exc)
    return {
        "leagueKey": league_key,
        "targetClass": int(target_class),
        "asOf": as_of,
        "spineYears": spine,
        "spineUnavailable": error,
        "ledger": classes,
    }


def pre_draft_cutoff_from_sleeper(
    evidence: LeagueDraftEvidence | None,
    draft_class: int,
    *,
    fetch: Callable[[str], Any] | None = None,
) -> str:
    """The pre-draft cutoff for ``draft_class``: Sleeper's draft ``start_time``.

    The rookie draft(s) are the ones ``pick_lifecycle`` itself named when it
    verified completion (its ``rookie_draft_complete:<ids>`` reason), so this
    never picks a different draft than the completion verdict did.  Each
    draft's ``/draft/{id}`` object is read through the draft-evidence fetch
    path and its ``start_time`` (epoch milliseconds) taken; with several, the
    EARLIEST (a board observed after any of them started is not pre-draft).
    A missing, non-positive or unreadable ``start_time`` refuses
    (``pre_draft_cutoff_unknown``) — never a constant, never the clock.
    """
    from src.api import draft_class_evidence as dce  # noqa: PLC0415

    lifecycle = draft_class_lifecycle(int(draft_class), evidence)
    if not is_retired(lifecycle):
        raise LedgerRefusal(
            "class_not_verified_complete", f"{lifecycle.status}: {list(lifecycle.reasons)}"
        )
    ids: list[str] = []
    for reason in lifecycle.reasons:
        if reason.startswith(_ROOKIE_DRAFT_REASON):
            ids.extend(i for i in reason[len(_ROOKIE_DRAFT_REASON) :].split(",") if i)
    if not ids:
        raise LedgerRefusal("pre_draft_cutoff_unknown", "no completed rookie draft identified")
    get = fetch or dce._default_fetch
    starts: list[int] = []
    for draft_id in ids:
        try:
            draft = get(f"{dce.SLEEPER_API}/draft/{draft_id}")
        except Exception as exc:  # noqa: BLE001 — any fetch failure is "unknown"
            raise LedgerRefusal("pre_draft_cutoff_unknown", f"draft {draft_id}: {exc}") from exc
        raw = draft.get("start_time") if isinstance(draft, dict) else None
        if isinstance(raw, bool) or not isinstance(raw, (int, float)) or raw <= 0:
            raise LedgerRefusal(
                "pre_draft_cutoff_unknown", f"draft {draft_id} has no usable start_time ({raw!r})"
            )
        starts.append(int(raw))
    return datetime.fromtimestamp(min(starts) / 1000, tz=timezone.utc).isoformat()
