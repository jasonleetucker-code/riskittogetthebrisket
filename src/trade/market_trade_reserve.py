"""Persistent, append-only holdout reserve for the Chase Upside Trade Market (G15).

WHY THIS EXISTS
───────────────
The trade-derived source (owner directive 2026-10-19, V2 §8) must be validated
on genuinely held-out evidence, with training and testing separated by time
AND by underlying league.  A holdout that is re-drawn per run, or chosen after
a model has looked at residuals, is not held out.  So the reserve is:

* **drawn once, before any residual-computing run** -- the salt lives in the
  committed config (``config/trade/chase_trade_market_reserve.json``), so it
  was fixed before the data it partitions was examined;
* **keyed by component**, not by trade -- a manager-lineage component (P2's
  side keys) so the same managers / league lineage never sit on both sides;
* **deterministic** -- ``sha256(componentId || 0x1f || salt)`` mapped to
  ``[0, 1)``; below ``reserveFraction`` the component is locked into a
  sub-reserve by the same uniform, else it is ``train``;
* **append-only** -- an assignment is written once (``INSERT OR IGNORE``) and
  never changed; a locked component can never move to ``train``
  (:func:`locked_to_train_violations` is the X13 check);
* **merge-safe** -- when a newly observed component absorbs members already
  assigned under other components (two lineages discovered to be one), it
  stays ``train`` if every part was ``train``, and INHERITS the lock if every
  part was locked to one sub-reserve (never re-drawn, so a lock is never
  lost).  Parts locked to DIFFERENT sub-reserves are locked to
  ``R-merged-conflict`` and reported.  A merge mixing ``train`` with a lock
  FAILS CLOSED (``ReserveIntegrityError``; dry run: ``trainLockConflicts``):
  inheriting the lock would put evidence a fitted model may already have seen
  inside a holdout, and keeping ``train`` would lose the lock -- the same
  refusal a merge that reuses an assigned id gets, so the outcome never
  depends on which id union-find keeps;
* **access-ledgered** -- reading a sub-reserve's members requires a recorded
  hypothesis (:func:`read_sub_reserve`), so every look is countable against a
  looks budget.

WHAT THIS DOES NOT DO
─────────────────────
It builds no component (that needs P2's private side keys), fits nothing and
touches no value.  :func:`draw_reserve` REFUSES to persist anything until the
config's ``status`` is ``APPROVED`` (owner decision Q2: the lock is permanent
once a model has been fitted against it); ``dry_run=True`` computes the counts
the draw would produce and writes nothing.  The store is box-local
(``data/market_trades/model/``, gitignored, 0600); component ids never leave
it.
"""

from __future__ import annotations

import hashlib
import json
import os
import sqlite3
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterable, Mapping

REPO_ROOT = Path(__file__).resolve().parents[2]
CONFIG_PATH = REPO_ROOT / "config" / "trade" / "chase_trade_market_reserve.json"

STATUS_APPROVED = "APPROVED"
TRAIN = "train"
MERGED_CONFLICT = "R-merged-conflict"

_PATH_ENV = "RISKIT_CTM_RESERVE_DB"
_FILE_NAME = "reserve.sqlite"

_SCHEMA = """
CREATE TABLE IF NOT EXISTS reserve_assignments (
  component_id    TEXT PRIMARY KEY,
  assignment      TEXT NOT NULL,
  basis           TEXT NOT NULL,
  config_version  TEXT NOT NULL,
  salt_sha256     TEXT NOT NULL,
  assigned_ms     INTEGER NOT NULL
);
CREATE TABLE IF NOT EXISTS reserve_members (
  member_key      TEXT PRIMARY KEY,
  component_id    TEXT NOT NULL,
  first_seen_ms   INTEGER NOT NULL
);
CREATE TABLE IF NOT EXISTS reserve_access (
  access_id       INTEGER PRIMARY KEY AUTOINCREMENT,
  sub_reserve     TEXT NOT NULL,
  hypothesis      TEXT NOT NULL,
  actor           TEXT NOT NULL,
  accessed_ms     INTEGER NOT NULL
);
"""

#: Tables this module writes.  Pinned by a structural test.
WRITE_TABLES = ("reserve_assignments", "reserve_members", "reserve_access")


@dataclass(frozen=True)
class ReserveConfig:
    version: str
    status: str
    salt: str
    reserve_fraction: float
    sub_reserves: tuple[tuple[str, float], ...]

    @property
    def salt_sha256(self) -> str:
        return hashlib.sha256(self.salt.encode("utf-8")).hexdigest()

    @property
    def approved(self) -> bool:
        return self.status == STATUS_APPROVED


def load_reserve_config(path: Path | None = None) -> ReserveConfig:
    """Read and validate the committed reserve config.  Raises ``ValueError``
    on anything that would make the draw ambiguous."""
    raw = json.loads(Path(path or CONFIG_PATH).read_text(encoding="utf-8"))
    salt = str(raw.get("salt") or "")
    if len(salt) < 32 or any(c not in "0123456789abcdef" for c in salt):
        raise ValueError("reserve salt must be >= 32 lowercase hex characters")
    frac = float(raw.get("reserveFraction"))
    if not 0.0 < frac < 1.0:
        raise ValueError("reserveFraction must be in (0, 1)")
    subs = raw.get("subReserves") or {}
    if not isinstance(subs, Mapping) or not subs:
        raise ValueError("subReserves must be a non-empty mapping")
    items = tuple((str(k), float(v)) for k, v in subs.items())
    if any(v <= 0 for _, v in items) or abs(sum(v for _, v in items) - 1.0) > 1e-9:
        raise ValueError("subReserves shares must be positive and sum to 1")
    if any(k in (TRAIN, MERGED_CONFLICT) for k, _ in items):
        raise ValueError("a sub-reserve may not be named train / R-merged-conflict")
    return ReserveConfig(
        version=str(raw.get("version") or ""),
        status=str(raw.get("status") or ""),
        salt=salt,
        reserve_fraction=frac,
        sub_reserves=items,
    )


def uniform_for(component_id: str, cfg: ReserveConfig) -> float:
    """The component's deterministic uniform in ``[0, 1)``."""
    digest = hashlib.sha256(f"{component_id}\x1f{cfg.salt}".encode("utf-8")).digest()
    return int.from_bytes(digest[:8], "big") / 2.0**64


def drawn_assignment(component_id: str, cfg: ReserveConfig) -> str:
    """``train`` or a sub-reserve name, from the hash alone (no history)."""
    u = uniform_for(component_id, cfg)
    if u >= cfg.reserve_fraction:
        return TRAIN
    pos = u / cfg.reserve_fraction
    acc = 0.0
    for name, share in cfg.sub_reserves:
        acc += share
        if pos < acc:
            return name
    return cfg.sub_reserves[-1][0]


def default_path() -> Path:
    override = os.getenv(_PATH_ENV, "").strip()
    if override:
        return Path(override)
    from src.trade import market_trade_archive as archive  # noqa: PLC0415

    return Path(archive.DEFAULT_DIR) / "model" / _FILE_NAME


def connect(path: Path | None = None) -> sqlite3.Connection:
    """Open (creating, 0600) the reserve store.  Writers only."""
    p = Path(path) if path is not None else default_path()
    p.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(p), timeout=30)
    conn.executescript(_SCHEMA)
    conn.commit()
    try:
        os.chmod(p, 0o600)
    except OSError:  # pragma: no cover
        pass
    return conn


@dataclass
class DrawResult:
    dry_run: bool
    config_version: str
    components_seen: int = 0
    already_assigned: int = 0
    new_assignments: int = 0
    inherited_from_merge: int = 0
    merge_conflicts: int = 0
    absorbed_conflicts: int = 0
    train_lock_conflicts: int = 0
    by_assignment: dict[str, int] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "dryRun": self.dry_run,
            "configVersion": self.config_version,
            "componentsSeen": self.components_seen,
            "alreadyAssigned": self.already_assigned,
            "newAssignments": self.new_assignments,
            "inheritedFromMerge": self.inherited_from_merge,
            "mergeConflicts": self.merge_conflicts,
            "absorbedConflicts": self.absorbed_conflicts,
            "trainLockConflicts": self.train_lock_conflicts,
            "byAssignment": dict(sorted(self.by_assignment.items())),
        }


class ReserveNotApproved(RuntimeError):
    """The owner has not approved the reserve (Q2); nothing may persist."""


class ReserveIntegrityError(RuntimeError):
    """A draw would move assigned members across the train/reserve line."""


def draw_reserve(
    components: Mapping[str, Iterable[str]],
    *,
    conn: sqlite3.Connection | None = None,
    cfg: ReserveConfig | None = None,
    dry_run: bool = False,
    clock_ms: Any = None,
) -> DrawResult:
    """Assign every component in ``components`` (``{component_id: member
    keys}``) not yet assigned, append-only.  Components are processed in
    sorted id order, so the outcome is deterministic for a given history.

    Refuses (``ReserveNotApproved``) to persist unless the config is
    ``APPROVED``; ``dry_run=True`` evaluates against the existing store (or
    an empty one when ``conn`` is ``None``) and writes nothing."""
    cfg = cfg or load_reserve_config()
    if not dry_run and not cfg.approved:
        raise ReserveNotApproved(
            f"reserve config status is {cfg.status!r}; owner decision Q2 must set APPROVED first"
        )
    if not dry_run and conn is None:
        raise ValueError("a persisting draw needs a store connection")
    tick = clock_ms or (lambda: int(time.time() * 1000))
    result = DrawResult(dry_run=dry_run, config_version=cfg.version)
    assigned: dict[str, str] = {}
    members: dict[str, str] = {}
    if conn is not None:
        assigned = {
            str(r[0]): str(r[1])
            for r in conn.execute("SELECT component_id, assignment FROM reserve_assignments")
        }
        members = {
            str(r[0]): str(r[1])
            for r in conn.execute("SELECT member_key, component_id FROM reserve_members")
        }
    for cid in sorted(components):
        result.components_seen += 1
        keys = sorted({str(k) for k in components[cid] if k})
        parts = sorted({members[k] for k in keys if k in members and members[k] != cid})
        if cid in assigned:
            result.already_assigned += 1
            label = assigned[cid]
            # A merge that KEEPS an existing id (union-find's smallest-member
            # root) absorbing a part assigned differently would silently move
            # that part's members across the train/reserve line -- and the
            # component-keyed X13 check cannot see it.  Fail closed.
            if any(assigned.get(p, label) != label for p in parts):
                result.absorbed_conflicts += 1
                if not dry_run:
                    if conn is not None:
                        conn.rollback()
                    raise ReserveIntegrityError(
                        "an assigned component absorbed a differently assigned part"
                    )
        else:
            part_labels = sorted({assigned[p] for p in parts if p in assigned})
            locked = [lbl for lbl in part_labels if lbl != TRAIN]
            if locked and TRAIN in part_labels:
                # Train + lock: neither inheriting the lock (contaminates the
                # holdout with possibly-fitted evidence) nor train (loses the
                # lock) is sound.  Fail closed, as the id-reusing branch does.
                result.train_lock_conflicts += 1
                if not dry_run:
                    if conn is not None:
                        conn.rollback()
                    raise ReserveIntegrityError("a merged component mixes train and locked parts")
                label, basis = MERGED_CONFLICT, "merge_train_lock_conflict"
            elif locked:
                label = locked[0] if len(set(locked)) == 1 else MERGED_CONFLICT
                basis = "merge_inherited_lock"
                result.inherited_from_merge += 1
                if label == MERGED_CONFLICT:
                    result.merge_conflicts += 1
            elif part_labels:
                label, basis = TRAIN, "merge_inherited_train"
                result.inherited_from_merge += 1
            else:
                label, basis = drawn_assignment(cid, cfg), "hash_draw"
            result.new_assignments += 1
            assigned[cid] = label
            if not dry_run and conn is not None:
                conn.execute(
                    "INSERT OR IGNORE INTO reserve_assignments "
                    "(component_id, assignment, basis, config_version, salt_sha256, assigned_ms) "
                    "VALUES (?, ?, ?, ?, ?, ?)",
                    (cid, label, basis, cfg.version, cfg.salt_sha256, int(tick())),
                )
        for k in keys:
            if k not in members:
                members[k] = cid
                if not dry_run and conn is not None:
                    conn.execute(
                        "INSERT OR IGNORE INTO reserve_members "
                        "(member_key, component_id, first_seen_ms) VALUES (?, ?, ?)",
                        (k, cid, int(tick())),
                    )
        result.by_assignment[label] = result.by_assignment.get(label, 0) + 1
    if not dry_run and conn is not None:
        conn.commit()
    return result


def read_sub_reserve(
    conn: sqlite3.Connection,
    sub_reserve: str,
    *,
    hypothesis: str,
    actor: str,
    clock_ms: Any = None,
) -> list[str]:
    """The component ids locked into ``sub_reserve`` -- logged in the access
    ledger FIRST, so a look that crashes half-way still counts."""
    if not str(hypothesis or "").strip() or not str(actor or "").strip():
        raise ValueError("a reserve read must name its hypothesis and actor")
    tick = clock_ms or (lambda: int(time.time() * 1000))
    conn.execute(
        "INSERT INTO reserve_access (sub_reserve, hypothesis, actor, accessed_ms) "
        "VALUES (?, ?, ?, ?)",
        (sub_reserve, hypothesis.strip(), actor.strip(), int(tick())),
    )
    conn.commit()
    return [
        str(r[0])
        for r in conn.execute(
            "SELECT component_id FROM reserve_assignments WHERE assignment = ? "
            "ORDER BY component_id",
            (sub_reserve,),
        )
    ]


def access_counts(conn: sqlite3.Connection) -> dict[str, int]:
    """``{sub_reserve: looks}`` -- the looks-budget numerator."""
    return {
        str(r[0]): int(r[1])
        for r in conn.execute(
            "SELECT sub_reserve, COUNT(*) FROM reserve_access GROUP BY sub_reserve"
        )
    }


def locked_to_train_violations(
    before: Mapping[str, str],
    after: Mapping[str, str],
) -> list[str]:
    """X13: components locked in ``before`` that are ``train`` (or missing) in
    ``after``.  Must be empty for every build; the append-only store makes it
    so, and this check proves it against two snapshots of the assignment."""
    return sorted(
        cid for cid, label in before.items() if label != TRAIN and after.get(cid) != label
    )


def assignment_snapshot(conn: sqlite3.Connection) -> dict[str, str]:
    return {
        str(r[0]): str(r[1])
        for r in conn.execute("SELECT component_id, assignment FROM reserve_assignments")
    }
