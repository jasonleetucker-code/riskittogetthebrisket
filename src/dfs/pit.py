"""Point-in-time (PIT) evidence for DFS: what was knowable BEFORE lock, kept apart from truth.

ADR-DFS-013.  Separate from ``src/history`` (dynasty value history) on purpose —
DFS data never enters dynasty valuation (ADR-DFS-006) — but it borrows that
module's as-of rules: a future observation is never selectable, and missing is
stated, never filled.

Entities (all owner-scoped, same SQLite file as ``store.py``):

* **slate index** — one row per snapshot: platform/sport/format, rule-set key,
  salary-file hash, the games and the LOCK time (earliest known start).  An
  unknown start time makes lock ``None`` — and a slate with no lock cannot
  certify anything as pre-lock.
* **observations** — APPEND-ONLY pre-lock inputs: (player, kind, source) →
  value, with ``observed_at`` (when the source published / the file was
  exported) and ``recorded_at`` (when we stored it).  Identical re-ingest is a
  no-op; a different value is a new row, never an overwrite.
* **as_of(T)** — for each (player, kind, source) the latest observation with
  ``observed_at <= T`` AND ``recorded_at <= T``: what we actually HAD at T,
  not what the source had.  Asking past lock for a pre-lock view is refused.
* **models** — versioned model definitions (params hashed, code SHA recorded)
  with a role (challenger / champion / shadow / retired), PREDEFINED promotion
  criteria, and an append-only event log of promotions and rollbacks.
* **decisions** — frozen records of what a model chose (and rejected) for a
  contest, from which inputs, labelled ``pre_lock`` only when made before lock.
* **evaluations** — metrics with sample sizes, scoped by sport / platform /
  format / slate size / source or model version.

Truth (post-lock ownership, points, standings, payouts) lives in the RESULTS
records (``store.put_result``) and is never written into observations.
"""

from __future__ import annotations

import hashlib
import json
import sqlite3
import subprocess
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from src.dfs import store

# "context": pre-lock game environment (spread, over/under, implied team total) — ownership features.
OBSERVATION_KINDS = ("projection", "ownership", "distribution", "status", "context")
MODEL_ROLES = ("challenger", "champion", "shadow", "retired")

_SCHEMA = """
CREATE TABLE IF NOT EXISTS dfs_pit_slates (
    snapshot_id TEXT PRIMARY KEY,
    owner TEXT NOT NULL,
    platform TEXT NOT NULL,
    sport TEXT NOT NULL,
    format TEXT NOT NULL,
    ruleset TEXT NOT NULL,
    salary_hash TEXT NOT NULL,
    lock_at TEXT,
    games TEXT NOT NULL,
    players INTEGER NOT NULL,
    created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS dfs_pit_observations (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    owner TEXT NOT NULL,
    snapshot_id TEXT NOT NULL,
    player_id TEXT NOT NULL,
    kind TEXT NOT NULL,
    source TEXT NOT NULL,
    observed_at TEXT NOT NULL,
    recorded_at TEXT NOT NULL,
    value TEXT NOT NULL,
    value_hash TEXT NOT NULL,
    provenance TEXT NOT NULL,
    UNIQUE (owner, snapshot_id, player_id, kind, source, observed_at, value_hash)
);
CREATE INDEX IF NOT EXISTS dfs_pit_obs_lookup
    ON dfs_pit_observations(owner, snapshot_id, kind, player_id, source, observed_at);
CREATE TABLE IF NOT EXISTS dfs_pit_models (
    model_id TEXT NOT NULL,
    version TEXT NOT NULL,
    kind TEXT NOT NULL,
    params TEXT NOT NULL,
    params_hash TEXT NOT NULL,
    code_sha TEXT,
    criteria TEXT NOT NULL,
    created_at TEXT NOT NULL,
    PRIMARY KEY (model_id, version)
);
CREATE TABLE IF NOT EXISTS dfs_pit_model_events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    model_id TEXT NOT NULL,
    version TEXT NOT NULL,
    role TEXT NOT NULL,
    reason TEXT NOT NULL,
    evidence TEXT,
    at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS dfs_pit_decisions (
    id TEXT PRIMARY KEY,
    owner TEXT NOT NULL,
    snapshot_id TEXT NOT NULL,
    contest_ref TEXT,
    as_of TEXT NOT NULL,
    created_at TEXT NOT NULL,
    timing TEXT NOT NULL,
    body TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS dfs_pit_decisions_owner ON dfs_pit_decisions(owner, created_at);
CREATE TABLE IF NOT EXISTS dfs_pit_evaluations (
    id TEXT PRIMARY KEY,
    owner TEXT NOT NULL,
    kind TEXT NOT NULL,
    subject TEXT NOT NULL,
    scope TEXT NOT NULL,
    n INTEGER NOT NULL,
    metrics TEXT NOT NULL,
    refs TEXT NOT NULL,
    created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS dfs_pit_eval_lookup ON dfs_pit_evaluations(owner, kind, subject);
"""


class PitError(ValueError):
    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code
        self.message = message


def _connect() -> sqlite3.Connection:
    conn = sqlite3.connect(store._db_path(), timeout=10)
    conn.executescript(_SCHEMA)
    return conn


def _canon(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), default=str)


def _hash(value: Any) -> str:
    return hashlib.sha256(_canon(value).encode("utf-8")).hexdigest()


def _utc(ts: str | datetime) -> str:
    """Normalize to an ISO UTC string; a naive time is refused (it cannot be ordered honestly)."""
    dt = ts if isinstance(ts, datetime) else datetime.fromisoformat(str(ts).replace("Z", "+00:00"))
    if dt.tzinfo is None:
        raise PitError("NAIVE_TIME", "Timestamps must carry a timezone.")
    # One fixed shape (always microseconds, always +00:00) so string order IS time order.
    return dt.astimezone(timezone.utc).isoformat(timespec="microseconds")


def now() -> str:
    return _utc(datetime.now(timezone.utc))


# ── slates ────────────────────────────────────────────────────────────────


def lock_time(athletes: list[dict[str, Any]]) -> str | None:
    """Earliest start across the slate — or None when ANY start is unknown.

    A slate with one unknown start cannot prove when it locked, so nothing can be
    certified as made before lock.
    """
    starts = [a.get("start_time_utc") for a in athletes]
    if not starts or any(s is None for s in starts):
        return None
    return min(_utc(s) for s in starts)


def index_slate(owner: str, snapshot: dict[str, Any]) -> dict[str, Any]:
    body = snapshot["body"]
    athletes = body.get("athletes") or []
    rs = snapshot["ruleset"]
    platform, sport, fmt = rs.split("@", 1)[0].split(".")[:3]
    row = {
        "snapshotId": snapshot["id"],
        "platform": platform,
        "sport": sport,
        "format": fmt,
        "ruleset": rs,
        "salaryHash": snapshot["contentHash"],
        "lockAt": lock_time(athletes),
        "games": sorted({a["game"] for a in athletes if a.get("game")}),
        "players": len(athletes),
        "createdAt": snapshot["createdAt"],
    }
    with store._lock, _connect() as conn:
        conn.execute(
            "INSERT OR IGNORE INTO dfs_pit_slates VALUES (?,?,?,?,?,?,?,?,?,?,?)",
            (
                row["snapshotId"],
                owner,
                platform,
                sport,
                fmt,
                rs,
                row["salaryHash"],
                row["lockAt"],
                json.dumps(row["games"]),
                row["players"],
                row["createdAt"],
            ),
        )
    return row


def get_slate(owner: str, snapshot_id: str) -> dict[str, Any] | None:
    with store._lock, _connect() as conn:
        r = conn.execute(
            "SELECT platform, sport, format, ruleset, salary_hash, lock_at, games, players, created_at "
            "FROM dfs_pit_slates WHERE owner=? AND snapshot_id=?",
            (owner, snapshot_id),
        ).fetchone()
    if not r:
        return None
    return {
        "snapshotId": snapshot_id,
        "platform": r[0],
        "sport": r[1],
        "format": r[2],
        "ruleset": r[3],
        "salaryHash": r[4],
        "lockAt": r[5],
        "games": json.loads(r[6]),
        "players": r[7],
        "createdAt": r[8],
    }


# ── observations ──────────────────────────────────────────────────────────


def record(
    owner: str,
    snapshot_id: str,
    observations: list[dict[str, Any]],
    *,
    recorded_at: str | None = None,
) -> dict[str, int]:
    """Append observations: each {playerId, kind, source, observedAt, value, provenance?}.

    ``recorded_at`` defaults to now.  An observation cannot be recorded as known
    before it was published (``recorded_at < observed_at`` is refused).
    """
    rec_at = _utc(recorded_at) if recorded_at else now()
    rows = []
    for o in observations:
        if o["kind"] not in OBSERVATION_KINDS:
            raise PitError("UNKNOWN_KIND", f"Unknown observation kind {o['kind']!r}.")
        obs_at = _utc(o["observedAt"])
        if obs_at > rec_at:
            raise PitError(
                "RECORDED_BEFORE_OBSERVED", "An observation cannot be held before it existed."
            )
        rows.append(
            (
                owner,
                snapshot_id,
                str(o["playerId"]),
                o["kind"],
                str(o["source"])[:120],
                obs_at,
                rec_at,
                _canon(o["value"]),
                _hash(o["value"]),
                _canon(o.get("provenance") or {}),
            )
        )
    with store._lock, _connect() as conn:
        before = conn.total_changes
        conn.executemany(
            "INSERT OR IGNORE INTO dfs_pit_observations "
            "(owner, snapshot_id, player_id, kind, source, observed_at, recorded_at, value, value_hash, provenance) "
            "VALUES (?,?,?,?,?,?,?,?,?,?)",
            rows,
        )
        added = conn.total_changes - before
    return {"received": len(rows), "added": added, "duplicates": len(rows) - added}


def as_of(
    owner: str,
    snapshot_id: str,
    at: str | datetime,
    *,
    kinds: tuple[str, ...] = OBSERVATION_KINDS,
    pre_lock: bool = True,
) -> dict[str, Any]:
    """What we HELD at ``at``: latest observation per (player, kind, source).

    ``pre_lock`` (default) refuses a time after the slate locked, and refuses a
    slate whose lock is unknown — a pre-lock view must be provably pre-lock.
    """
    t = _utc(at)
    slate = get_slate(owner, snapshot_id)
    if slate is None:
        raise PitError("SLATE_NOT_INDEXED", "This slate has no point-in-time index.")
    if pre_lock:
        if slate["lockAt"] is None:
            raise PitError(
                "LOCK_UNKNOWN",
                "The slate's lock time is unknown; nothing can be certified pre-lock.",
            )
        if t > slate["lockAt"]:
            raise PitError("AFTER_LOCK", "A pre-lock view cannot be taken after the slate locked.")
    marks = ",".join("?" for _ in kinds)
    with store._lock, _connect() as conn:
        rows = conn.execute(
            f"SELECT player_id, kind, source, observed_at, recorded_at, value FROM dfs_pit_observations "
            f"WHERE owner=? AND snapshot_id=? AND kind IN ({marks}) AND observed_at<=? AND recorded_at<=? "
            f"ORDER BY observed_at, recorded_at, id",
            (owner, snapshot_id, *kinds, t, t),
        ).fetchall()
    latest: dict[tuple[str, str, str], dict[str, Any]] = {}
    for pid, kind, source, obs_at, rec_at, value in rows:
        latest[(pid, kind, source)] = {
            "value": json.loads(value),
            "observedAt": obs_at,
            "recordedAt": rec_at,
        }
    out: dict[str, dict[str, dict[str, Any]]] = {}
    for (pid, kind, source), v in latest.items():
        out.setdefault(pid, {}).setdefault(kind, {})[source] = v
    return {
        "snapshotId": snapshot_id,
        "asOf": t,
        "lockAt": slate["lockAt"],
        "preLock": pre_lock,
        "players": out,
        "digest": _hash(out),
    }


# ── models ────────────────────────────────────────────────────────────────


def _code_sha() -> str | None:
    try:
        out = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=Path(__file__).resolve().parents[2],
            capture_output=True,
            text=True,
            timeout=5,
        )
        return out.stdout.strip() or None if out.returncode == 0 else None
    except (OSError, subprocess.SubprocessError):
        return None


def register_model(
    model_id: str, version: str, kind: str, params: dict[str, Any], criteria: dict[str, Any]
) -> dict[str, Any]:
    """Register a model version as a CHALLENGER.  Params are immutable per version:
    re-registering the same version with different params is refused."""
    ph = _hash(params)
    created = now()
    with store._lock, _connect() as conn:
        existing = conn.execute(
            "SELECT params_hash FROM dfs_pit_models WHERE model_id=? AND version=?",
            (model_id, version),
        ).fetchone()
        if existing and existing[0] != ph:
            raise PitError(
                "VERSION_REUSED", "A model version's parameters cannot change; bump the version."
            )
        if not existing:
            conn.execute(
                "INSERT INTO dfs_pit_models VALUES (?,?,?,?,?,?,?,?)",
                (
                    model_id,
                    version,
                    kind,
                    _canon(params),
                    ph,
                    _code_sha(),
                    _canon(criteria),
                    created,
                ),
            )
            conn.execute(
                "INSERT INTO dfs_pit_model_events (model_id, version, role, reason, evidence, at) VALUES (?,?,?,?,?,?)",
                (model_id, version, "challenger", "registered", None, created),
            )
    return model_role(model_id, version)


def model_role(model_id: str, version: str) -> dict[str, Any]:
    with store._lock, _connect() as conn:
        m = conn.execute(
            "SELECT kind, params, params_hash, code_sha, criteria, created_at FROM dfs_pit_models "
            "WHERE model_id=? AND version=?",
            (model_id, version),
        ).fetchone()
        ev = conn.execute(
            "SELECT role, reason, at FROM dfs_pit_model_events WHERE model_id=? AND version=? ORDER BY id DESC LIMIT 1",
            (model_id, version),
        ).fetchone()
    if not m:
        raise PitError("UNKNOWN_MODEL", "No such model version.")
    return {
        "modelId": model_id,
        "version": version,
        "kind": m[0],
        "params": json.loads(m[1]),
        "paramsHash": m[2],
        "codeSha": m[3],
        "criteria": json.loads(m[4]),
        "createdAt": m[5],
        "role": ev[0],
        "roleReason": ev[1],
        "roleAt": ev[2],
    }


def champion(model_id: str) -> dict[str, Any] | None:
    with store._lock, _connect() as conn:
        versions = [
            v
            for (v,) in conn.execute(
                "SELECT version FROM dfs_pit_models WHERE model_id=?", (model_id,)
            ).fetchall()
        ]
    for v in versions:
        r = model_role(model_id, v)
        if r["role"] == "champion":
            return r
    return None


def promote(model_id: str, version: str, evaluation: dict[str, Any]) -> dict[str, Any]:
    """Promote a challenger to champion ONLY if the evaluation meets its predefined criteria.

    Criteria are fixed at registration: ``minSamples`` and ``metric`` +
    ``mustBeatBaselineBy`` (lower-is-better metrics compare challenger < baseline).
    The evaluation window must START after the model was registered, so a model
    cannot be promoted on data it was fitted to.  The previous champion is retired,
    and every step is an event — rollback is ``rollback()``, never an overwrite.
    """
    m = model_role(model_id, version)
    crit = m["criteria"]
    if m["role"] != "challenger" and m["role"] != "shadow":
        raise PitError(
            "NOT_A_CHALLENGER", f"Only a challenger can be promoted (this is {m['role']})."
        )
    window_start = evaluation.get("windowStart")
    if not window_start or _utc(window_start) < m["createdAt"]:
        raise PitError(
            "EVALUATION_CONTAMINATED",
            "The evaluation window must start after the model was registered (no fitting-period evidence).",
        )
    n = int(evaluation.get("n") or 0)
    if n < int(crit.get("minSamples", 0)):
        raise PitError("INSUFFICIENT_EVIDENCE", f"{n} samples < required {crit.get('minSamples')}.")
    metric = crit.get("metric")
    ch, base = (
        evaluation.get("challenger", {}).get(metric),
        evaluation.get("baseline", {}).get(metric),
    )
    if ch is None or base is None:
        raise PitError(
            "INSUFFICIENT_EVIDENCE", f"Evaluation lacks {metric} for challenger and baseline."
        )
    margin = float(crit.get("mustBeatBaselineBy", 0.0))
    better = ch <= base - margin if crit.get("lowerIsBetter", True) else ch >= base + margin
    if not better:
        raise PitError(
            "DID_NOT_BEAT_BASELINE",
            f"{metric}: challenger {ch} vs baseline {base} (margin {margin}).",
        )
    current = champion(model_id)
    at = now()
    with store._lock, _connect() as conn:
        if current:
            conn.execute(
                "INSERT INTO dfs_pit_model_events (model_id, version, role, reason, evidence, at) VALUES (?,?,?,?,?,?)",
                (model_id, current["version"], "retired", f"superseded by {version}", None, at),
            )
        conn.execute(
            "INSERT INTO dfs_pit_model_events (model_id, version, role, reason, evidence, at) VALUES (?,?,?,?,?,?)",
            (model_id, version, "champion", "met predefined criteria", _canon(evaluation), at),
        )
    return model_role(model_id, version)


def rollback(model_id: str, to_version: str, reason: str) -> dict[str, Any]:
    """Make an earlier version champion again (retiring the current one), as new events."""
    model_role(model_id, to_version)
    current = champion(model_id)
    at = now()
    with store._lock, _connect() as conn:
        if current and current["version"] != to_version:
            conn.execute(
                "INSERT INTO dfs_pit_model_events (model_id, version, role, reason, evidence, at) VALUES (?,?,?,?,?,?)",
                (model_id, current["version"], "retired", f"rolled back: {reason}"[:200], None, at),
            )
        conn.execute(
            "INSERT INTO dfs_pit_model_events (model_id, version, role, reason, evidence, at) VALUES (?,?,?,?,?,?)",
            (model_id, to_version, "champion", f"rollback: {reason}"[:200], None, at),
        )
    return model_role(model_id, to_version)


# ── decisions + evaluations ───────────────────────────────────────────────


def freeze_decision(
    owner: str,
    snapshot_id: str,
    *,
    as_of_view: dict[str, Any],
    contest_ref: str | None,
    models: list[dict[str, str]],
    objective: dict[str, Any],
    constraints: dict[str, Any],
    selected: list[dict[str, Any]],
    rejected: list[dict[str, Any]],
    uncertainty: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Record what was chosen, from which inputs, IMMUTABLY.

    ``timing`` is ``pre_lock`` only when the decision is made before the slate's
    known lock; otherwise ``post_lock`` or ``lock_unknown`` — such a decision can
    never count as forward evidence.
    """
    created = now()
    slate = get_slate(owner, snapshot_id)
    lock = slate["lockAt"] if slate else None
    timing = "lock_unknown" if lock is None else ("pre_lock" if created <= lock else "post_lock")
    did = "decision_" + uuid.uuid4().hex[:20]
    body = {
        "decisionId": did,
        "snapshotId": snapshot_id,
        "contestRef": contest_ref,
        "asOf": as_of_view["asOf"],
        "inputsDigest": as_of_view["digest"],
        "createdAt": created,
        "lockAt": lock,
        "timing": timing,
        "models": models,
        "objective": objective,
        "constraints": constraints,
        "selected": selected,
        "rejected": rejected[:500],
        "rejectedTotal": len(rejected),
        "uncertainty": uncertainty,
    }
    with store._lock, _connect() as conn:
        conn.execute(
            "INSERT INTO dfs_pit_decisions VALUES (?,?,?,?,?,?,?,?)",
            (
                did,
                owner,
                snapshot_id,
                contest_ref,
                as_of_view["asOf"],
                created,
                timing,
                _canon(body),
            ),
        )
    return body


def get_decision(owner: str, decision_id: str) -> dict[str, Any] | None:
    with store._lock, _connect() as conn:
        r = conn.execute(
            "SELECT body FROM dfs_pit_decisions WHERE owner=? AND id=?", (owner, decision_id)
        ).fetchone()
    return json.loads(r[0]) if r else None


def record_evaluation(
    owner: str,
    kind: str,
    subject: str,
    scope: dict[str, Any],
    n: int,
    metrics: dict[str, Any],
    refs: dict[str, Any],
) -> dict[str, Any]:
    eid = "eval_" + uuid.uuid4().hex[:20]
    created = now()
    with store._lock, _connect() as conn:
        conn.execute(
            "INSERT INTO dfs_pit_evaluations VALUES (?,?,?,?,?,?,?,?,?)",
            (
                eid,
                owner,
                kind,
                subject,
                _canon(scope),
                int(n),
                _canon(metrics),
                _canon(refs),
                created,
            ),
        )
    return {
        "evaluationId": eid,
        "kind": kind,
        "subject": subject,
        "scope": scope,
        "n": n,
        "metrics": metrics,
        "refs": refs,
        "createdAt": created,
    }


def list_evaluations(owner: str, kind: str | None = None) -> list[dict[str, Any]]:
    q = "SELECT id, kind, subject, scope, n, metrics, refs, created_at FROM dfs_pit_evaluations WHERE owner=?"
    args: list[Any] = [owner]
    if kind:
        q += " AND kind=?"
        args.append(kind)
    with store._lock, _connect() as conn:
        rows = conn.execute(q + " ORDER BY created_at", args).fetchall()
    return [
        {
            "evaluationId": r[0],
            "kind": r[1],
            "subject": r[2],
            "scope": json.loads(r[3]),
            "n": r[4],
            "metrics": json.loads(r[5]),
            "refs": json.loads(r[6]),
            "createdAt": r[7],
        }
        for r in rows
    ]


def capture_snapshot(owner: str, snapshot: dict[str, Any]) -> dict[str, Any]:
    """Index a saved slate snapshot and record its owner-imported inputs as observations.

    ``observedAt`` is the IMPORT time: when the source actually published is not
    known, and the import time is the earliest moment we can prove we held it —
    never earlier.  An input imported after lock is therefore after lock, and a
    pre-lock view excludes it.
    """
    slate = index_slate(owner, snapshot)
    at = _utc(snapshot["createdAt"])
    prov = {"via": "owner_import", "snapshotContentHash": snapshot["contentHash"]}
    obs = []
    for a in snapshot["body"].get("athletes") or []:
        pid = a["player_id"]
        if a.get("projection") is not None:
            src = a.get("projection_source") or "owner_import"
            obs.append(
                {
                    "playerId": pid,
                    "kind": "projection",
                    "source": src,
                    "observedAt": at,
                    "value": a["projection"],
                    "provenance": prov,
                }
            )
        if a.get("ownership") is not None:
            obs.append(
                {
                    "playerId": pid,
                    "kind": "ownership",
                    "source": a.get("ownership_source") or "owner_import",
                    "observedAt": at,
                    "value": a["ownership"],
                    "provenance": prov,
                }
            )
        if a.get("distribution"):
            obs.append(
                {
                    "playerId": pid,
                    "kind": "distribution",
                    "source": "owner_import",
                    "observedAt": at,
                    "value": a["distribution"],
                    "provenance": prov,
                }
            )
        if a.get("status"):
            obs.append(
                {
                    "playerId": pid,
                    "kind": "status",
                    "source": "platform_file",
                    "observedAt": at,
                    "value": a["status"],
                    "provenance": prov,
                }
            )
    counts = (
        record(owner, snapshot["id"], obs, recorded_at=at)
        if obs
        else {"received": 0, "added": 0, "duplicates": 0}
    )
    return {"slate": slate, "observations": counts}
