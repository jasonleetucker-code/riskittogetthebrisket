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

    0. Manual override by sleeper_id.       confidence=1.00
    1. Exact external ID match.             confidence=1.00
    2. Exact normalized name + team + pos.  confidence=0.98
    3. Exact normalized name + team.        confidence=0.95
    4. Exact normalized name + position.    confidence=0.93
    5. Unique exact normalized name.        confidence=0.90
    6. Guarded fuzzy normalized name.       confidence=0.75..0.90

Anything below the configured ``min_confidence`` is rejected and
counted in the unmapped-miss metric so we can observe drift.  So is
anything AMBIGUOUS: when two directory rows answer to one name and
nothing the caller supplied separates them, the answer is ``None``.
It used to be whichever row the dict happened to hold first, reported
at confidence 1.00.

Manual overrides
----------------
UDFAs, practice-squad callups, and same-name-different-player
cases live in ``config/identity/id_overrides.json`` — a flat
``{sleeper_id: {gsis_id, espn_id, full_name}}`` map that short-
circuits the match ladder.  Edit-and-redeploy ops; kept in config
so it's auditable in git.  The rung is FIRST, not second: it used to
sit below the exact-sleeper_id rung, so it only fired for ids the
directory did not contain — while every case the file documents is an
id the directory does contain (W06-F004).  Keys beginning with ``_``
are documentation (``_comment``, ``_example_entry_only``) and are not
loaded as overrides.

No behavioural regressions
--------------------------
This module reads from existing player state and returns a new
``ResolvedPlayer`` struct.  It does NOT modify the existing
``src.identity.matcher`` or ``src.identity.models`` pipeline — the
scrape-normalize-merge flow still runs exactly as before.  The
mapper is a LOOKUP surface, not a write path.
"""

from __future__ import annotations

import json
import logging
import threading
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from src.utils import normalize_player_name
from src.utils.name_clean import resolve_canonical_name

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
        # Normalize keys to strings.  Keys starting with ``_`` are
        # documentation, not overrides — the shipped file's
        # ``_example_entry_only`` was being loaded as a live override
        # pinning gsis 00-0000000 to a player named "Example Player"
        # (W06-F004).
        for k, v in raw.items():
            key = str(k)
            if key.startswith("_"):
                continue
            if isinstance(v, dict):
                _OVERRIDES_CACHE[key] = dict(v)
        return dict(_OVERRIDES_CACHE)


def reload_overrides() -> None:
    """Clear the override cache so the next call re-reads the JSON.
    Used by tests and the ``/admin/refresh-id-overrides`` endpoint.
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
    "resolved_name_team": 0,
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


# ── Fuzzy-accept guard ────────────────────────────────────────────
#
# A raw difflib ratio does not know WHICH characters it is comparing,
# so "Tevin Coleman" vs "Kevin Coleman" scores 0.923 — higher than
# plenty of genuine matches, and no threshold separates the two.  Fed
# the 544 source-CSV names that failed the production canonical-name
# join, the unguarded ladder returned a match for ELEVEN of them at the
# default ``min_confidence``, every one a different human, each
# reported with ``match_method='fuzzy_name'`` at a confidence the
# docstring says that method cannot reach (audit W06-F006).
#
# The fix is structural rather than a higher threshold: a fuzzy accept
# requires the same surname AND a compatible first name, and both
# halves require the same initial letter — which is exactly what
# separates a typo ("Micheal"/"Michael") from a different name
# ("Eric"/"Cedric", "Tevin"/"Kevin", "Ian"/"Brian", "Ty"/"Tyren").
# Measured on the eleven-pair corpus: 11 of 11 refused, with the
# single-character-typo class the layer exists for preserved.
_FUZZY_FIRST_NAME_MIN = 0.85
_FUZZY_SURNAME_MIN = 0.80
# The ladder's own documented ceiling for a fuzzy match.  It used to
# report the raw ratio, so a guess could claim 0.98 — a higher
# confidence than the rung that verified name AND team AND position.
_FUZZY_MAX_CONFIDENCE = 0.90


def _name_parts(norm: str) -> tuple[str, str]:
    """``(first, last)`` from an already-normalized name."""
    tokens = norm.split()
    if not tokens:
        return "", ""
    if len(tokens) == 1:
        return tokens[0], tokens[0]
    return tokens[0], tokens[-1]


def _initial_compatible(a: str, b: str, floor: float) -> bool:
    """Same word, allowing an initial or a typo — never a different one."""
    if not a or not b:
        return False
    if a == b:
        return True
    if len(a) == 1 or len(b) == 1:
        return a[0] == b[0]
    if a[0] != b[0]:
        return False
    return _fuzzy_score(a, b) >= floor


def _fuzzy_accept(query_norm: str, candidate_norm: str) -> bool:
    """Is this pair close enough to be ONE player rather than two?"""
    q_first, q_last = _name_parts(query_norm)
    c_first, c_last = _name_parts(candidate_norm)
    if not q_last or not c_last:
        return False
    if not _initial_compatible(q_last, c_last, _FUZZY_SURNAME_MIN):
        return False
    return _initial_compatible(q_first, c_first, _FUZZY_FIRST_NAME_MIN)


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
            # Also index under the curated nickname key.  The guarded
            # fuzzy rung deliberately refuses "Kenny"/"Kenneth" —
            # structurally it is indistinguishable from "Ty"/"Tyren",
            # which is two people — so the nickname class resolves the
            # way the rest of the pipeline resolves it: through the
            # human-maintained ``CANONICAL_NAME_ALIASES`` table, as an
            # EXACT match.  ``resolve_canonical_name`` is documented as
            # a drop-in for ``normalize_player_name`` for callers that
            # want alias-aware joins; this is one.
            alias = resolve_canonical_name(name)
            if alias and alias != norm:
                by_norm_name.setdefault(alias, []).append(p)
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
) -> ResolvedPlayer | None:
    """Resolve any subset of ID signals into a canonical player.

    ``players_dir`` is the master Sleeper player directory.  All
    non-Sleeper sources (nflverse, ESPN, etc.) resolve THROUGH
    this directory via the match ladder.  Callers pass the
    directory explicitly so tests don't need the full I/O.

    Returns ``None`` if no match above ``min_confidence`` is found, and
    ``None`` when the evidence is AMBIGUOUS — two directory rows
    answering to one name with nothing to tell them apart.  Metrics are
    bumped either way so coverage can be observed.

    Ladder order:
      1. Manual override by ``sleeper_id``.
      2. ``sleeper_id`` exact.
      3. ``gsis_id`` exact.
      4. ``espn_id`` exact.
      5. Normalized name + team + position.
      6. Normalized name + team.
      7. Normalized name + position.
      8. Unique normalized name.
      9. Guarded fuzzy name.
    """
    idx = _index_directory(players_dir)
    overrides = _load_overrides(overrides_path)
    return _resolve_from_index(
        idx,
        overrides,
        sleeper_id=sleeper_id,
        gsis_id=gsis_id,
        espn_id=espn_id,
        name=name,
        team=team,
        position=position,
        min_confidence=min_confidence,
    )


def _resolve_from_index(
    idx: dict[str, Any],
    overrides: dict[str, dict[str, Any]],
    *,
    sleeper_id: str | None = None,
    gsis_id: str | None = None,
    espn_id: str | None = None,
    name: str | None = None,
    team: str | None = None,
    position: str | None = None,
    min_confidence: float = 0.85,
) -> ResolvedPlayer | None:
    """The ladder itself, run against an ALREADY-BUILT index.

    Split out so ``resolve_many`` can index the directory once rather
    than once per input row — 199 redundant rebuilds and 99.5% of wall
    time on a 200-row batch against an 11k directory (W06-F007).
    """
    _bump("resolve_attempts")

    # 1. Manual override by Sleeper ID.  FIRST, above the exact-id rung:
    # an override that loses to the directory it exists to override is
    # not an override (W06-F004).
    if sleeper_id:
        sid = str(sleeper_id).strip()
        if sid and sid in overrides:
            ov = overrides[sid]
            _bump("resolved_override")
            return ResolvedPlayer(
                sleeper_id=sid,
                gsis_id=str(ov.get("gsis_id") or ""),
                espn_id=str(ov.get("espn_id") or ""),
                full_name=str(ov.get("full_name") or ""),
                position=str(ov.get("position") or ""),
                team=str(ov.get("team") or ""),
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

    # 5/6/7/8/9. Name-based ladder.
    if name:
        norm = normalize_player_name(name)
        candidates = idx["by_norm_name"].get(norm) or []
        if not candidates:
            # Curated nickname table, exact — never a guess.  See
            # ``_index_directory`` for why the fuzzy rung cannot own
            # this class.
            alias = resolve_canonical_name(name)
            if alias and alias != norm:
                candidates = idx["by_norm_name"].get(alias) or []
        team_u = (team or "").strip().upper()
        pos_u = (position or "").strip().upper()

        def _pos_of(p: dict[str, Any]) -> str:
            return str(p.get("position") or "").strip().upper()

        def _team_of(p: dict[str, Any]) -> str:
            return str(p.get("team") or "").strip().upper()

        # Each rung: the rows that satisfy it.  Exactly one → answer.
        # More than one → the rung cannot separate them and no weaker
        # rung can either, so refuse rather than pick by dict order.
        rungs: list[tuple[str, float, str, list[dict[str, Any]]]] = []
        if team_u and pos_u:
            rungs.append(
                (
                    "name_team_pos",
                    0.98,
                    "resolved_name_team_pos",
                    [p for p in candidates if _team_of(p) == team_u and _pos_of(p) == pos_u],
                )
            )
        if team_u:
            # This rung did not exist.  With two "Josh Allen" rows and
            # no position supplied, the caller's team was ignored
            # entirely and the answer came from dict insertion order at
            # confidence 1.00 (W06-F006).
            rungs.append(
                (
                    "name_team",
                    0.95,
                    "resolved_name_team",
                    [p for p in candidates if _team_of(p) == team_u],
                )
            )
        if pos_u:
            rungs.append(
                (
                    "name_pos",
                    0.93,
                    "resolved_name_pos",
                    [p for p in candidates if _pos_of(p) == pos_u],
                )
            )
        rungs.append(("name_unique", 0.90, "resolved_name_pos", list(candidates)))

        for method, confidence, metric, matches in rungs:
            if len(matches) == 1:
                _bump(metric)
                return _to_resolved(matches[0], confidence=confidence, method=method)
            if len(matches) > 1:
                _bump("unresolved")
                _LOGGER.debug(
                    "unified_mapper: ambiguous name=%r team=%r pos=%r (%d candidates)",
                    name,
                    team,
                    position,
                    len(matches),
                )
                return None

        # Guarded fuzzy fallback for spelling drift the exact key missed
        # (e.g. "Micheal Thomas" for "Michael Thomas").  ``_fuzzy_accept``
        # is what keeps this from merging two different people — the raw
        # ratio alone does not.
        best_p = None
        best_score = 0.0
        for norm_key, plist in idx["by_norm_name"].items():
            if not _fuzzy_accept(norm, norm_key):
                continue
            score = _fuzzy_score(norm, norm_key)
            if score <= best_score:
                continue
            for p in plist:
                if pos_u and _pos_of(p) != pos_u:
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
            return _to_resolved(
                best_p,
                confidence=min(best_score, _FUZZY_MAX_CONFIDENCE),
                method="fuzzy_name",
            )

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
    """
    idx = _index_directory(players_dir)
    overrides = _load_overrides()
    resolved: list[ResolvedPlayer] = []
    unresolved: list[dict[str, Any]] = []
    for row in inputs:
        if not isinstance(row, dict):
            continue
        got = _resolve_from_index(
            idx,
            overrides,
            sleeper_id=row.get("sleeper_id"),
            gsis_id=row.get("gsis_id"),
            espn_id=row.get("espn_id"),
            name=row.get("name") or row.get("full_name"),
            team=row.get("team"),
            position=row.get("position"),
            min_confidence=min_confidence,
        )
        if got:
            resolved.append(got)
        else:
            unresolved.append(row)
    return resolved, unresolved
