"""Unified player-identity mapper across Sleeper, GSIS, ESPN, and
our internal IDs.

Why this exists
---------------
Every new data source in the 2026-04 upgrade (NFL usage via
nfl_data_py / nflverse, ESPN injury feed, ESPN depth charts, news
firehoses) keys on a different ID than Sleeper uses.  Without a
single resolver every integration re-invents the mapping, each
gets it subtly wrong, and we have N silent miss rates to debug.

The match ladder (in ``resolve_player``) is:

    0. Manual override by Sleeper ID.    confidence=1.00
    1. Exact external ID match.          confidence=1.00
    2. Exact normalized name + team.     confidence=0.98
    3. Exact normalized name + position. confidence=0.93
    4. Fuzzy normalized name only.       confidence=0.75..0.90

The override sits ABOVE the exact-ID match, not below it (W06-F004).
Below, it could only ever fire for ids Sleeper had never heard of — so
the one case overrides exist for, "the directory has this player wrong",
was the one case it could not serve.

Anything below the configured ``min_confidence`` is rejected and
counted in the unmapped-miss metric so we can observe drift.

Manual overrides
----------------
UDFAs, practice-squad callups, and same-name-different-player
cases live in ``config/identity/id_overrides.json`` — a flat
``{sleeper_id: {gsis_id, espn_id, full_name}}`` map that short-
circuits the match ladder.  Edit-and-redeploy ops; kept in config
so it's auditable in git.

No behavioural regressions
--------------------------
This module reads from existing player state and returns a new
``ResolvedPlayer`` struct.  It does NOT modify the existing
``src.identity.matcher`` or ``src.identity.models`` pipeline — the
scrape-normalize-merge flow still runs exactly as before.  The
mapper is a LOOKUP surface, not a write path.

C1-ID-01 status
---------------
This ladder is the LEGACY-V1 compat surface for its existing consumers
(``src/playerctx/normalize.py`` and the two ``server.py`` read sites).
The canonical resolution API is ``src.identity.resolution`` — its
``resolve_canonical_v2`` carries the repaired semantics (guarded fuzzy
per W06-F006, explicit AMBIGUOUS refusal, roster-presence homonym
separation) that this ladder's raw-difflib fuzzy rung lacks.  Do not add
NEW consumers here; use the resolution engine.  Migrating the existing
consumers is a staged step recorded in
``docs/identity/C1_ID_01_IDENTITY_CONSOLIDATION.md``.
"""

from __future__ import annotations

import json
import logging
import threading
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from src.utils import normalize_player_name

_LOGGER = logging.getLogger(__name__)

# ── Data model ────────────────────────────────────────────────────


@dataclass(frozen=True)
class ResolvedPlayer:
    """A player resolved across every known ID system.

    ``sleeper_id`` is the anchor — every other system is a side-
    channel.  Any of ``gsis_id`` / ``espn_id`` may be empty when
    the external system doesn't know this player.
    """

    sleeper_id: str
    gsis_id: str
    espn_id: str
    full_name: str
    position: str
    team: str
    confidence: float
    match_method: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


# ── Override layer ────────────────────────────────────────────────

_OVERRIDES_LOCK = threading.RLock()
_OVERRIDES_CACHE: dict[str, dict[str, Any]] = {}
_OVERRIDES_PATH_CACHE: Path | None = None


def _default_overrides_path() -> Path:
    repo = Path(__file__).resolve().parents[2]
    return repo / "config" / "identity" / "id_overrides.json"


def _load_overrides(path: Path | None = None) -> dict[str, dict[str, Any]]:
    """Load the ``config/identity/id_overrides.json`` map.  Missing
    file → empty override set (not an error — the file is optional)."""
    global _OVERRIDES_PATH_CACHE
    target = path or _default_overrides_path()
    with _OVERRIDES_LOCK:
        if _OVERRIDES_PATH_CACHE == target and _OVERRIDES_CACHE:
            return dict(_OVERRIDES_CACHE)
        _OVERRIDES_CACHE.clear()
        _OVERRIDES_PATH_CACHE = target
        if not target.exists():
            return {}
        try:
            raw = json.loads(target.read_text(encoding="utf-8"))
        except Exception as exc:  # noqa: BLE001 — log + ignore so a malformed file doesn't brick the mapper
            _LOGGER.warning("id_overrides.json parse failed: %s", exc)
            return {}
        if not isinstance(raw, dict):
            _LOGGER.warning("id_overrides.json root must be a dict; ignoring")
            return {}
        # Normalize keys to strings.  Underscore-prefixed keys are
        # documentation scaffolding (``_comment``, ``_example_entry_only``
        # — both shipped in the real file) and must never be treated as
        # live overrides: the override rung now outranks the directory,
        # so an example entry would be one edit away from resolving a
        # player (W06-F004).
        for k, v in raw.items():
            key = str(k)
            if key.startswith("_"):
                continue
            if isinstance(v, dict):
                _OVERRIDES_CACHE[key] = dict(v)
        return dict(_OVERRIDES_CACHE)


def reload_overrides() -> None:
    """Clear the override cache so the next call re-reads the JSON.

    Called by tests (and by ``src/playerctx/normalize.py`` indirectly
    through ``_load_overrides``).  No HTTP endpoint reloads overrides —
    the previous claim of an ``/admin/refresh-id-overrides`` route was
    doc drift; edits to ``config/identity/id_overrides.json`` take
    effect on process restart.
    """
    with _OVERRIDES_LOCK:
        _OVERRIDES_CACHE.clear()
        global _OVERRIDES_PATH_CACHE
        _OVERRIDES_PATH_CACHE = None


# ── Mapping index ────────────────────────────────────────────────

# Module-level metrics so we can observe join coverage over time.
_METRICS_LOCK = threading.Lock()
_METRICS: dict[str, int] = {
    "resolve_attempts": 0,
    "resolved_exact_id": 0,
    "resolved_name_team_pos": 0,
    "resolved_name_pos": 0,
    "resolved_fuzzy": 0,
    "resolved_override": 0,
    "unresolved": 0,
}


def _bump(metric: str) -> None:
    with _METRICS_LOCK:
        _METRICS[metric] = _METRICS.get(metric, 0) + 1


def mapping_coverage_snapshot() -> dict[str, Any]:
    """Return {metrics, coverage_pct} for observability dashboards.

    ``coverage_pct`` = resolved / attempts.  Returns 1.0 when no
    attempts have been logged yet (so a silent app doesn't look
    like a broken mapper).
    """
    with _METRICS_LOCK:
        m = dict(_METRICS)
    attempts = m.get("resolve_attempts", 0)
    resolved = attempts - m.get("unresolved", 0)
    pct = (resolved / attempts) if attempts else 1.0
    return {"metrics": m, "coverage_pct": round(pct, 4)}


def reset_metrics() -> None:
    """Zero the metrics.  Tests and the refit cron call this."""
    with _METRICS_LOCK:
        for k in _METRICS:
            _METRICS[k] = 0


# ── Resolver ──────────────────────────────────────────────────────


def _fuzzy_score(a: str, b: str) -> float:
    """Lightweight fuzzy score in [0, 1].  Pure-Python, no SciPy.

    Uses the ratio of common tokens to total unique tokens (Jaccard-
    like on the word level), averaged with character-level Levenshtein-
    style edit-distance approximation (we use difflib).
    """
    import difflib

    a_low = a.lower()
    b_low = b.lower()
    if not a_low or not b_low:
        return 0.0
    if a_low == b_low:
        return 1.0
    # difflib is stdlib and good enough for "Michael Pittman Jr." vs.
    # "Mike Pittman" dynasty-grade name drift.
    ratio = difflib.SequenceMatcher(None, a_low, b_low).ratio()
    return float(ratio)


def _index_directory(players_dir: dict[str, dict[str, Any]] | None) -> dict:
    """Build three lookup dicts from the Sleeper player directory.

    Returns ``{by_sleeper_id, by_gsis, by_espn, by_norm_name}``.

    ``players_dir`` is the shape Sleeper returns from
    ``/v1/players/nfl``: ``{sleeper_id: {player_id, gsis_id, espn_id,
    full_name, position, team, ...}}``.
    """
    by_sleeper_id: dict[str, dict[str, Any]] = {}
    by_gsis: dict[str, dict[str, Any]] = {}
    by_espn: dict[str, dict[str, Any]] = {}
    by_norm_name: dict[str, list[dict[str, Any]]] = {}

    if not isinstance(players_dir, dict):
        return {
            "by_sleeper_id": by_sleeper_id,
            "by_gsis": by_gsis,
            "by_espn": by_espn,
            "by_norm_name": by_norm_name,
        }

    for sid, p in players_dir.items():
        if not isinstance(p, dict):
            continue
        sid_s = str(sid)
        by_sleeper_id[sid_s] = p
        gsis = str(p.get("gsis_id") or "").strip()
        if gsis:
            by_gsis[gsis] = p
        espn = str(p.get("espn_id") or "").strip()
        if espn:
            by_espn[espn] = p
        name = str(p.get("full_name") or p.get("search_full_name") or "").strip()
        norm = normalize_player_name(name) if name else ""
        if norm:
            by_norm_name.setdefault(norm, []).append(p)
    return {
        "by_sleeper_id": by_sleeper_id,
        "by_gsis": by_gsis,
        "by_espn": by_espn,
        "by_norm_name": by_norm_name,
    }


def resolve_player(
    players_dir: dict[str, dict[str, Any]] | None,
    *,
    sleeper_id: str | None = None,
    gsis_id: str | None = None,
    espn_id: str | None = None,
    name: str | None = None,
    team: str | None = None,
    position: str | None = None,
    min_confidence: float = 0.85,
    overrides_path: Path | None = None,
    _index: dict | None = None,
) -> ResolvedPlayer | None:
    """Resolve any subset of ID signals into a canonical player.

    ``players_dir`` is the master Sleeper player directory.  All
    non-Sleeper sources (nflverse, ESPN, etc.) resolve THROUGH
    this directory via the match ladder.  Callers pass the
    directory explicitly so tests don't need the full I/O.

    Returns ``None`` if no match above ``min_confidence`` is found;
    metrics are bumped either way so coverage can be observed.

    ``_index`` is an internal seam for :func:`resolve_many` to pass a
    directory index it already built (W06-F007). Callers should leave it
    unset; it is a pure function of ``players_dir``, so supplying it
    changes nothing but the cost.

    Ladder order:
      1. Manual override by ``sleeper_id`` (merged over the directory).
      2. ``sleeper_id`` exact.
      3. ``gsis_id`` exact.
      4. ``espn_id`` exact.
      5. Normalized name + team + position.
      6. Normalized name + position.
      7. Fuzzy name only.
    """
    _bump("resolve_attempts")
    idx = _index if _index is not None else _index_directory(players_dir)
    overrides = _load_overrides(overrides_path)

    # 1. Manual override by Sleeper ID — ABOVE the directory (W06-F004).
    #
    # This rung used to sit below the exact-ID match, which made it
    # unreachable for exactly the case it exists to serve: an operator
    # pins a player BECAUSE the directory has them wrong, and the
    # directory then won. It only ever fired for ids Sleeper had never
    # heard of, and the test covering it used such an id, so nothing
    # caught the inversion.
    #
    # The override MERGES over the directory record rather than replacing
    # it. Replacing was survivable while the rung was unreachable, but
    # promoted above the directory a partial entry (say ``{"team": "MIA"}``)
    # would blank the name, position and every other id — turning a
    # resolved player into an anonymous row. An override says "this field
    # is wrong", not "forget everything you know".
    if sleeper_id:
        sid = str(sleeper_id).strip()
        if sid and sid in overrides:
            ov = overrides[sid]
            base = idx["by_sleeper_id"].get(sid) or {}
            _bump("resolved_override")

            def _field(name: str, *base_keys: str) -> str:
                if ov.get(name) not in (None, ""):
                    return str(ov[name])
                for bk in base_keys or (name,):
                    if base.get(bk) not in (None, ""):
                        return str(base[bk])
                return ""

            return ResolvedPlayer(
                sleeper_id=sid,
                gsis_id=_field("gsis_id"),
                espn_id=_field("espn_id"),
                full_name=_field("full_name", "full_name", "search_full_name"),
                position=_field("position"),
                team=_field("team"),
                confidence=1.00,
                match_method="manual_override",
            )

    # 2. Exact Sleeper ID.
    if sleeper_id:
        sid = str(sleeper_id).strip()
        if sid and sid in idx["by_sleeper_id"]:
            p = idx["by_sleeper_id"][sid]
            _bump("resolved_exact_id")
            return _to_resolved(p, confidence=1.00, method="sleeper_id")

    # 3. Exact GSIS ID.
    if gsis_id:
        gid = str(gsis_id).strip()
        if gid and gid in idx["by_gsis"]:
            p = idx["by_gsis"][gid]
            _bump("resolved_exact_id")
            return _to_resolved(p, confidence=1.00, method="gsis_id")

    # 4. Exact ESPN ID.
    if espn_id:
        eid = str(espn_id).strip()
        if eid and eid in idx["by_espn"]:
            p = idx["by_espn"][eid]
            _bump("resolved_exact_id")
            return _to_resolved(p, confidence=1.00, method="espn_id")

    # 5/6/7. Name-based ladder.
    if name:
        norm = normalize_player_name(name)
        candidates = idx["by_norm_name"].get(norm) or []
        team_u = (team or "").strip().upper()
        pos_u = (position or "").strip().upper()

        # name+team+pos
        for p in candidates:
            if (
                team_u
                and pos_u
                and str(p.get("team") or "").strip().upper() == team_u
                and str(p.get("position") or "").strip().upper() == pos_u
            ):
                _bump("resolved_name_team_pos")
                return _to_resolved(p, confidence=0.98, method="name_team_pos")
        # name+pos
        for p in candidates:
            if pos_u and str(p.get("position") or "").strip().upper() == pos_u:
                _bump("resolved_name_pos")
                return _to_resolved(p, confidence=0.93, method="name_pos")
        # unique exact-normalized-name hit still wins if no tie
        if len(candidates) == 1:
            _bump("resolved_name_pos")
            return _to_resolved(candidates[0], confidence=0.90, method="name_unique")

        # Fuzzy fallback across the full directory when exact-normalized
        # didn't land (e.g. "Marv Jones Jr." vs. "Marvin Jones").
        best_p = None
        best_score = 0.0
        for norm_key, plist in idx["by_norm_name"].items():
            score = _fuzzy_score(norm, norm_key)
            if score <= best_score:
                continue
            # Tie-break by position match when we have one.
            for p in plist:
                if pos_u and str(p.get("position") or "").strip().upper() != pos_u:
                    continue
                best_p = p
                best_score = score
                break
            else:
                if not pos_u:
                    best_p = plist[0]
                    best_score = score
        if best_p and best_score >= min_confidence:
            _bump("resolved_fuzzy")
            return _to_resolved(best_p, confidence=best_score, method="fuzzy_name")

    _bump("unresolved")
    _LOGGER.debug(
        "unified_mapper: miss sleeper=%s gsis=%s espn=%s name=%s team=%s pos=%s",
        sleeper_id,
        gsis_id,
        espn_id,
        name,
        team,
        position,
    )
    return None


def _to_resolved(
    p: dict[str, Any],
    *,
    confidence: float,
    method: str,
) -> ResolvedPlayer:
    return ResolvedPlayer(
        sleeper_id=str(p.get("player_id") or p.get("sleeper_id") or ""),
        gsis_id=str(p.get("gsis_id") or ""),
        espn_id=str(p.get("espn_id") or ""),
        full_name=str(p.get("full_name") or p.get("search_full_name") or ""),
        position=str(p.get("position") or ""),
        team=str(p.get("team") or ""),
        confidence=float(confidence),
        match_method=method,
    )


# ── Bulk resolver for batch jobs ──────────────────────────────────


def resolve_many(
    players_dir: dict[str, dict[str, Any]] | None,
    inputs: list[dict[str, Any]],
    *,
    min_confidence: float = 0.85,
) -> tuple[list[ResolvedPlayer], list[dict[str, Any]]]:
    """Resolve a list of input dicts in one pass.

    Returns ``(resolved, unresolved)`` — inputs that didn't meet
    ``min_confidence`` are echoed back verbatim in ``unresolved``
    so callers can log / fuzzy-match / surface them.

    Used by nightly jobs (injury feed, nflverse weekly ingest) so
    the mapper's internal index is built once, not per-row.

    W06-F007: that last sentence was false for as long as it existed.
    ``resolve_player`` re-indexed the entire Sleeper directory on every
    call, so a batch of N rows walked the ~11k-entry directory N times —
    the cost this function was written to avoid. The index is a pure
    function of ``players_dir``, so it is built here and passed down;
    ``test_resolve_many_returns_what_it_did_before_the_hoist`` pins that
    the results are identical to the per-row path, because a
    performance repair that quietly changes identity resolution would be
    a far worse bug than the one it fixes.
    """
    resolved: list[ResolvedPlayer] = []
    unresolved: list[dict[str, Any]] = []
    idx = _index_directory(players_dir)
    for row in inputs:
        if not isinstance(row, dict):
            continue
        got = resolve_player(
            players_dir,
            sleeper_id=row.get("sleeper_id"),
            gsis_id=row.get("gsis_id"),
            espn_id=row.get("espn_id"),
            name=row.get("name") or row.get("full_name"),
            team=row.get("team"),
            position=row.get("position"),
            min_confidence=min_confidence,
            _index=idx,
        )
        if got:
            resolved.append(got)
        else:
            unresolved.append(row)
    return resolved, unresolved
