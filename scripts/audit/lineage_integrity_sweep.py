#!/usr/bin/env python3
"""Ingestion / lineage integrity sweep (Batch 3 Unit G) — measurement instrument.

Owner requirement (Section G): accuracy cannot exceed input integrity.  This
re-measures, from the repository's own captured evidence, the per-source
properties that the value pipeline silently trusts:

* the captured CSV's shape and native semantics (rank vs value, scale, ties,
  rank gaps, rank/value concordance, duplicate identities after canonical
  name resolution, offense / IDP / pick population);
* the dataset-state clocks (``data/scrape_state/<key>_dataset.json``) against
  git history of the CSV — a successful fetch of unchanged data must not
  become "new", so every recorded change event must correspond to a content
  change and no content change may be missed;
* the observed broad-publication cadence against the declared bounds in
  ``config/sources/freshness_v1.json``;
* rank-board change events split into ORDER-PRESERVING shifts (insertions /
  removals only — every surviving player keeps his relative order) versus
  genuine re-orderings, because a one-player insertion rewrites every rank
  below it and reads as a broad publication;
* pairwise dependence: raw Spearman plus a LEAVE-PAIR-OUT residual
  correlation (each pair is judged against a consensus that excludes both
  members, so two sources cannot manufacture agreement through their own
  contribution to the consensus), per asset universe;
* lagged VALUE IDENTITY: the share of shared players whose published value is
  exactly equal (and within 1%) to a comparator's value at any captured
  version in a look-back window.  Equality of hundreds of integer values on a
  0-9999 scale is a stronger statement than correlation; it is still recorded
  as *measured*, never *proven*, unless the vendor says so.

Evidence only.  Nothing here changes a vote, weight or value.  Network is
never used — live-page comparisons are recorded separately in the sweep
report with their capture date.

Usage::

    python scripts/audit/lineage_integrity_sweep.py \\
        --out docs/sources/integrity/INTEGRITY_SWEEP_2026-10-01.json

Exit codes: 0 sweep written; 2 input missing.
"""

from __future__ import annotations

import argparse
import csv
import io
import itertools
import json
import math
import statistics
import subprocess
import sys
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from src.identity.picks import is_pick_name  # noqa: E402
from src.utils.name_clean import resolve_canonical_name  # noqa: E402

CSV_DIR = REPO_ROOT / "CSVs" / "site_raw"
STATE_DIR = REPO_ROOT / "data" / "scrape_state"
FRESHNESS_CONFIG = REPO_ROOT / "config" / "sources" / "freshness_v1.json"

OFFENSE_POSITIONS = frozenset({"QB", "RB", "WR", "TE"})
IDP_POSITIONS = frozenset(
    {"DL", "DE", "DT", "ED", "EDGE", "LB", "ILB", "OLB", "DB", "CB", "S", "SS", "FS", "IDP"}
)
PICK_POSITIONS = frozenset({"PICK", "RDP"})

_NAME_COLUMNS = ("name", "player", "playername", "player_name")
_RANK_COLUMNS = ("rank", "effectiverank", "overallrank", "overall_rank")
_VALUE_COLUMNS = ("value", "boone_value", "3d value +", "trade_value", "normalizedvalue")
_POSITION_COLUMNS = ("position", "pos", "fantasy position")

MIN_PAIR_OVERLAP = 30
MIN_CONSENSUS_OTHERS = 3


# ── board loading ──────────────────────────────────────────────────────


@dataclass
class Board:
    """One captured source CSV reduced to identity → (rank, value, position)."""

    key: str
    header: list[str] = field(default_factory=list)
    rows: int = 0
    rank_col: str | None = None
    value_col: str | None = None
    entries: dict[str, dict[str, Any]] = field(default_factory=dict)
    duplicates: list[dict[str, Any]] = field(default_factory=list)
    unnamed_rows: int = 0


def _num(raw: Any) -> float | None:
    text = str(raw if raw is not None else "").strip().replace(",", "")
    if not text:
        return None
    try:
        value = float(text)
    except ValueError:
        return None
    return value if math.isfinite(value) else None


def canonical(name: str) -> str:
    """The identity key used for every cross-source join in this sweep."""
    return resolve_canonical_name(name or "") or ""


def parse_board(key: str, text: str) -> Board:
    board = Board(key=key)
    reader = csv.DictReader(io.StringIO(text.lstrip("﻿")))
    board.header = list(reader.fieldnames or [])
    lowered = {c.lower().strip(): c for c in board.header}
    name_col = next((lowered[c] for c in _NAME_COLUMNS if c in lowered), None)
    board.rank_col = next((lowered[c] for c in _RANK_COLUMNS if c in lowered), None)
    board.value_col = next((lowered[c] for c in _VALUE_COLUMNS if c in lowered), None)
    pos_col = next((lowered[c] for c in _POSITION_COLUMNS if c in lowered), None)
    for index, row in enumerate(reader):
        board.rows += 1
        raw_name = str(row.get(name_col) or "").strip() if name_col else ""
        ident = canonical(raw_name)
        if not ident:
            board.unnamed_rows += 1
            continue
        entry = {
            "raw": raw_name,
            "rank": _num(row.get(board.rank_col)) if board.rank_col else None,
            "value": _num(row.get(board.value_col)) if board.value_col else None,
            "position": str(row.get(pos_col) or "").strip().upper() if pos_col else "",
            "order": index + 1,
        }
        if ident in board.entries:
            prior = board.entries[ident]
            board.duplicates.append(
                {
                    "identity": ident,
                    "raw": [prior["raw"], raw_name],
                    "sameSignal": prior["rank"] == entry["rank"]
                    and prior["value"] == entry["value"],
                }
            )
            continue
        board.entries[ident] = entry
    return board


def load_board(key: str, path: Path) -> Board | None:
    try:
        text = path.read_text(encoding="utf-8")
    except OSError:
        return None
    return parse_board(key, text)


def ordering(board: Board, idents: Iterable[str] | None = None) -> dict[str, float]:
    """``{identity: ordering key}``, lower is better: rank, else −value, else file order."""
    out: dict[str, float] = {}
    pool = (
        board.entries
        if idents is None
        else {i: board.entries[i] for i in idents if i in board.entries}
    )
    for ident, e in pool.items():
        if e["rank"] is not None:
            out[ident] = e["rank"]
        elif e["value"] is not None:
            out[ident] = -e["value"]
        else:
            out[ident] = float(e["order"])
    return out


# ── universes ──────────────────────────────────────────────────────────


def position_universe(position: str) -> str | None:
    p = (position or "").upper().strip()
    p = "".join(ch for ch in p if ch.isalpha())
    if p in OFFENSE_POSITIONS:
        return "offense"
    if p in IDP_POSITIONS:
        return "idp"
    if p in PICK_POSITIONS:
        return "pick"
    return None


def build_universe_index(boards: Mapping[str, Board]) -> dict[str, str]:
    """identity → universe, voted by every board that publishes a position.

    A name two universes both claim (e.g. a WR and an LB sharing a name) is
    left out rather than guessed — unresolved is not a best guess."""
    votes: dict[str, set[str]] = {}
    for board in boards.values():
        for ident, e in board.entries.items():
            if is_pick_name(e["raw"]):
                votes.setdefault(ident, set()).add("pick")
                continue
            u = position_universe(e["position"])
            if u:
                votes.setdefault(ident, set()).add(u)
    return {i: next(iter(u)) for i, u in votes.items() if len(u) == 1}


# ── semantics profile ──────────────────────────────────────────────────


def spearman(a: Mapping[str, float], b: Mapping[str, float]) -> tuple[float | None, int]:
    common = sorted(set(a) & set(b))
    n = len(common)
    if n < MIN_PAIR_OVERLAP:
        return None, n
    ra = _ranks([a[c] for c in common])
    rb = _ranks([b[c] for c in common])
    return _pearson(ra, rb), n


def _ranks(xs: Sequence[float]) -> list[float]:
    order = sorted(range(len(xs)), key=lambda i: xs[i])
    ranks = [0.0] * len(xs)
    i = 0
    while i < len(order):
        j = i
        while j + 1 < len(order) and xs[order[j + 1]] == xs[order[i]]:
            j += 1
        avg = (i + j) / 2.0 + 1.0
        for k in range(i, j + 1):
            ranks[order[k]] = avg
        i = j + 1
    return ranks


def _pearson(xs: Sequence[float], ys: Sequence[float]) -> float | None:
    if len(xs) < 3:
        return None
    mx, my = statistics.fmean(xs), statistics.fmean(ys)
    num = sum((x - mx) * (y - my) for x, y in zip(xs, ys))
    den = math.sqrt(sum((x - mx) ** 2 for x in xs) * sum((y - my) ** 2 for y in ys))
    return num / den if den else None


def semantics_profile(board: Board, universe: Mapping[str, str]) -> dict[str, Any]:
    ranks = [e["rank"] for e in board.entries.values() if e["rank"] is not None]
    values = [e["value"] for e in board.entries.values() if e["value"] is not None]
    out: dict[str, Any] = {
        "rows": board.rows,
        "identities": len(board.entries),
        "header": board.header,
        "rankColumn": board.rank_col,
        "valueColumn": board.value_col,
        "unnamedRows": board.unnamed_rows,
        "duplicateIdentities": len(board.duplicates),
        "duplicateExamples": board.duplicates[:5],
        "population": {},
    }
    pop: dict[str, int] = {"offense": 0, "idp": 0, "pick": 0, "unresolved": 0}
    for ident, e in board.entries.items():
        u = "pick" if is_pick_name(e["raw"]) else universe.get(ident)
        pop[u or "unresolved"] += 1
    out["population"] = pop
    if ranks:
        distinct = sorted(set(ranks))
        out["rank"] = {
            "min": min(ranks),
            "max": max(ranks),
            "distinct": len(distinct),
            "tiedRows": len(ranks) - len(distinct),
            "integerShare": round(sum(1 for r in ranks if float(r).is_integer()) / len(ranks), 3),
            "gapsInRun": int(max(ranks) - min(ranks) + 1 - len(distinct))
            if all(float(r).is_integer() for r in distinct)
            else None,
        }
    if values:
        distinct_v = set(values)
        out["value"] = {
            "min": min(values),
            "max": max(values),
            "distinct": len(distinct_v),
            "tiedRows": len(values) - len(distinct_v),
            "integerShare": round(sum(1 for v in values if float(v).is_integer()) / len(values), 3),
        }
    if ranks and values:
        both = {
            i: e
            for i, e in board.entries.items()
            if e["rank"] is not None and e["value"] is not None
        }
        rho, n = spearman(
            {i: e["rank"] for i, e in both.items()}, {i: -e["value"] for i, e in both.items()}
        )
        tied_value_distinct_rank = 0
        by_value: dict[float, set[float]] = {}
        for e in both.values():
            by_value.setdefault(e["value"], set()).add(e["rank"])
        for v, rs in by_value.items():
            if len(rs) > 1:
                tied_value_distinct_rank += len(rs)
        out["rankValueConcordance"] = {
            "spearman": None if rho is None else round(rho, 4),
            "n": n,
            "tiedValueRowsWithDistinctRanks": tied_value_distinct_rank,
        }
    return out


# ── dependence ─────────────────────────────────────────────────────────


def to_percentiles(order_keys: Mapping[str, float]) -> dict[str, float]:
    ranked = sorted(order_keys, key=lambda n: (order_keys[n], n))
    total = len(ranked)
    return {name: (i + 1) / total for i, name in enumerate(ranked)} if total else {}


def leave_pair_out_residuals(
    percentiles: Mapping[str, Mapping[str, float]],
    a: str,
    b: str,
    consensus_pool: Iterable[str],
    min_others: int = MIN_CONSENSUS_OTHERS,
) -> tuple[float | None, int]:
    """Residual correlation of ``a`` and ``b`` against a consensus built from
    ``consensus_pool`` MINUS both members.  A name needs ``min_others`` other
    observations to have a consensus at all."""
    others = [k for k in consensus_pool if k not in (a, b) and k in percentiles]
    pa, pb = percentiles.get(a) or {}, percentiles.get(b) or {}
    xs, ys = [], []
    for name in sorted(set(pa) & set(pb)):
        obs = [percentiles[k][name] for k in others if name in percentiles[k]]
        if len(obs) < min_others:
            continue
        c = statistics.fmean(obs)
        xs.append(pa[name] - c)
        ys.append(pb[name] - c)
    if len(xs) < MIN_PAIR_OVERLAP:
        return None, len(xs)
    return _pearson(xs, ys), len(xs)


def dependence_matrix(
    boards: Mapping[str, Board],
    universe: Mapping[str, str],
    universe_name: str,
    consensus_pool: Sequence[str],
    pairs: Iterable[tuple[str, str]],
) -> list[dict[str, Any]]:
    percentiles: dict[str, dict[str, float]] = {}
    for key, board in boards.items():
        idents = [
            i
            for i, e in board.entries.items()
            if universe.get(i) == universe_name and not is_pick_name(e["raw"])
        ]
        if len(idents) >= MIN_PAIR_OVERLAP:
            percentiles[key] = to_percentiles(ordering(board, idents))
    out = []
    for a, b in pairs:
        if a not in percentiles or b not in percentiles:
            continue
        rho, n_raw = spearman(percentiles[a], percentiles[b])
        res, n_res = leave_pair_out_residuals(percentiles, a, b, consensus_pool)
        out.append(
            {
                "a": a,
                "b": b,
                "universe": universe_name,
                "spearman": None if rho is None else round(rho, 4),
                "n": n_raw,
                "leavePairOutResidual": None if res is None else round(res, 4),
                "nResidual": n_res,
            }
        )
    return out


def value_identity(a: Mapping[str, float], b: Mapping[str, float]) -> dict[str, Any] | None:
    common = sorted(set(a) & set(b))
    if not common:
        return None
    exact = sum(1 for n in common if abs(a[n] - b[n]) < 0.5)
    ratios = [a[n] / b[n] for n in common if b[n]]
    within = sum(1 for r in ratios if abs(r - 1.0) <= 0.01)
    return {
        "n": len(common),
        "exactEqual": exact,
        "exactShare": round(exact / len(common), 3),
        "within1pct": within,
        "within1pctShare": round(within / len(common), 3),
        "medianRatio": round(statistics.median(ratios), 4) if ratios else None,
    }


# ── git history ────────────────────────────────────────────────────────


def _git(*args: str) -> str:
    return subprocess.run(
        ["git", *args], cwd=REPO_ROOT, capture_output=True, text=True, encoding="utf-8", check=False
    ).stdout


def git_versions(
    path: Path, since: datetime | None = None, until: datetime | None = None
) -> list[tuple[str, datetime]]:
    rel = path.relative_to(REPO_ROOT).as_posix()
    args = ["log", "--format=%h %cI"]
    if since:
        args.append(f"--since={since.isoformat()}")
    if until:
        args.append(f"--until={until.isoformat()}")
    out = []
    for line in _git(*args, "--", rel).splitlines():
        parts = line.split()
        if len(parts) == 2:
            out.append((parts[0], datetime.fromisoformat(parts[1]).astimezone(timezone.utc)))
    return out


def board_at(key: str, path: Path, sha: str) -> Board:
    return parse_board(key, _git("show", f"{sha}:{path.relative_to(REPO_ROOT).as_posix()}"))


def lagged_value_identity(
    subject: Mapping[str, float],
    comparator_key: str,
    comparator_path: Path,
    window_end: datetime,
    window_days: int,
    max_versions: int = 60,
) -> dict[str, Any] | None:
    versions = git_versions(comparator_path, window_end - timedelta(days=window_days), window_end)
    if not versions:
        return None
    stride = max(1, len(versions) // max_versions)
    best: dict[str, Any] | None = None
    for sha, at in versions[::stride]:
        comp = board_at(comparator_key, comparator_path, sha)
        vals = {i: e["value"] for i, e in comp.entries.items() if e["value"] is not None}
        vi = value_identity(subject, vals)
        if vi and (best is None or vi["exactEqual"] > best["identity"]["exactEqual"]):
            best = {"comparatorVersion": sha, "comparatorAt": at.isoformat(), "identity": vi}
    if best:
        best["versionsScanned"] = len(versions[::stride])
        best["versionsInWindow"] = len(versions)
    return best


def classify_rank_change(prev: Board, cur: Board) -> dict[str, Any] | None:
    """Split one rank-board change into insert/remove-only vs re-ordering.

    ``orderPreserving`` is True when every identity present in both versions
    keeps exactly its relative order — the only differences are players
    entering or leaving, which shift ranks below them without anyone being
    re-evaluated."""
    po, co = ordering(prev), ordering(cur)
    if po == co:
        return None
    common = set(po) & set(co)
    prev_seq = [i for i in sorted(po, key=lambda n: (po[n], n)) if i in common]
    cur_seq = [i for i in sorted(co, key=lambda n: (co[n], n)) if i in common]
    rank_moved = sum(1 for i in common if po[i] != co[i])
    return {
        "added": len(set(co) - set(po)),
        "removed": len(set(po) - set(co)),
        "common": len(common),
        "rankKeyChanged": rank_moved,
        "orderPreserving": prev_seq == cur_seq,
    }


def rank_change_census(key: str, path: Path, since: datetime) -> dict[str, Any]:
    versions = list(reversed(git_versions(path, since)))
    events = []
    prev: Board | None = None
    for sha, at in versions:
        cur = board_at(key, path, sha)
        if prev is not None:
            c = classify_rank_change(prev, cur)
            if c is not None:
                c["at"] = at.isoformat()
                events.append(c)
        prev = cur
    shift = [e for e in events if e["orderPreserving"]]
    broadish_shift = [e for e in shift if e["rankKeyChanged"] >= 5]
    return {
        "versions": len(versions),
        "changeEvents": len(events),
        "orderPreservingEvents": len(shift),
        "orderPreservingWithRankShift>=5": len(broadish_shift),
        "examples": broadish_shift[:3],
    }


# ── dataset state / cadence ────────────────────────────────────────────


def _parse(ts: Any) -> datetime | None:
    if not isinstance(ts, str) or not ts:
        return None
    try:
        dt = datetime.fromisoformat(ts.replace("Z", "+00:00"))
    except ValueError:
        return None
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


def _quantile(xs: Sequence[float], q: float) -> float | None:
    if not xs:
        return None
    s = sorted(xs)
    pos = q * (len(s) - 1)
    lo, hi = math.floor(pos), math.ceil(pos)
    return s[lo] + (s[hi] - s[lo]) * (pos - lo)


def cadence_check(
    subset_state: Mapping[str, Any] | None,
    declared: Mapping[str, Any],
    as_of: datetime,
    trailing_days: int = 120,
) -> dict[str, Any]:
    hist = list((subset_state or {}).get("changeHistory") or [])
    broad = sorted(t for t in (_parse(h.get("at")) for h in hist if h.get("broad")) if t)
    broad = [t for t in broad if t >= as_of - timedelta(days=trailing_days)]
    intervals = [(b - a).total_seconds() / 3600.0 for a, b in zip(broad, broad[1:])]
    p50, p75 = _quantile(intervals, 0.5), _quantile(intervals, 0.75)
    lo, hi = declared.get("minHours"), declared.get("maxHours")
    binding = None
    if p75 is not None and lo is not None and hi is not None:
        binding = "minHours" if p75 < lo else ("maxHours" if p75 > hi else None)
    return {
        "broadEventsTrailing": len(broad),
        "closedIntervals": len(intervals),
        "observedP50Hours": None if p50 is None else round(p50, 1),
        "observedP75Hours": None if p75 is None else round(p75, 1),
        "declared": dict(declared),
        "declaredBoundBinding": binding,
    }


def match_versions_to_events(
    version_times: Sequence[datetime],
    event_times: Sequence[datetime],
    tolerance: timedelta = timedelta(hours=3),
) -> tuple[int, list[datetime]]:
    """Greedy one-to-one match of CSV versions to recorded change events.

    An event is stamped at OBSERVATION time and the commit lands after it, so
    a version committed at ``c`` matches an event at ``e`` when
    ``c - tolerance <= e <= c + 5 min``.  Returns ``(matches, unmatched
    events)`` so a second pass can only claim events the first left over."""
    events = sorted(event_times)
    used = [False] * len(events)
    matched = 0
    for c in sorted(version_times):
        for i, e in enumerate(events):
            if used[i]:
                continue
            if c - tolerance <= e <= c + timedelta(minutes=5):
                used[i] = True
                matched += 1
                break
    return matched, [e for e, u in zip(events, used) if not u]


def clock_honesty(
    key: str,
    path: Path,
    state: Mapping[str, Any] | None,
    as_of: datetime,
    window_days: int = 30,
    signal: str = "value",
) -> dict[str, Any]:
    """Do the data clocks move exactly when meaningful content changes?

    Over a trailing window every git version of the CSV is classified as
    MEANINGFUL or BYTE-ONLY using the dataset-state owner's OWN definition of
    meaningful content (``src.sources.dataset_integrity.parse_board`` — one
    owner, never a second fingerprint), and meaningful versions are matched
    by time to the recorded change events.  Byte-only versions may only
    claim events no meaningful version explained.

    * ``byteOnlyCoincidingWithEvent`` > 0 would mean an unchanged re-fetch
      became "new" — the defect this guards (expected 0);
    * ``meaningfulWithoutEvent`` is a genuine change never recorded (the
      state process sampled less often than the CSV changed);
    * ``eventsWithoutVersion`` is a clock that moved with no content change
      in git (expected 0).

    The window keeps the comparison inside ``changeHistory``'s bounded
    retention (``MAX_CHANGE_HISTORY``)."""
    subsets = (state or {}).get("subsets") or {}
    if not subsets:
        return {"state": "NO_DATASET_STATE"}
    since = as_of - timedelta(days=window_days)
    first = min(
        (t for t in (_parse(s.get("firstObservedAt")) for s in subsets.values()) if t), default=None
    )
    if first is not None and first > since:
        since = first + timedelta(seconds=1)
    rel = path.relative_to(REPO_ROOT).as_posix()
    versions = list(reversed(git_versions(path, since, as_of)))
    prev_sha = _git("log", "-1", "--format=%h", f"--until={since.isoformat()}", "--", rel).strip()
    prev = _meaningful_content(_git("show", f"{prev_sha}:{rel}"), signal) if prev_sha else None
    meaningful_times: list[datetime] = []
    byte_only_times: list[datetime] = []
    for sha, at in versions:
        cur = _meaningful_content(_git("show", f"{sha}:{rel}"), signal)
        same = prev is not None and prev == cur
        (byte_only_times if same else meaningful_times).append(at)
        prev = cur
    # One CSV version can move several subsets (players + picks); collapse
    # per-subset events stamped at the same instant into one observation.
    event_times = sorted(
        {
            t.replace(microsecond=0)
            for s in subsets.values()
            for h in (s.get("changeHistory") or [])
            if (t := _parse(h.get("at"))) is not None and since <= t <= as_of
        }
    )
    matched, leftover = match_versions_to_events(meaningful_times, event_times)
    byte_matched, _ = match_versions_to_events(byte_only_times, leftover)
    return {
        "windowStart": since.isoformat(),
        "gitContentVersions": len(versions),
        "meaningfulVersions": len(meaningful_times),
        "byteOnlyVersions": len(byte_only_times),
        "recordedChangeInstants": len(event_times),
        "meaningfulMatched": matched,
        "meaningfulWithoutEvent": len(meaningful_times) - matched,
        "eventsWithoutVersion": len(event_times) - matched,
        "byteOnlyCoincidingWithEvent": byte_matched,
    }


def _meaningful_content(text: str, signal: str) -> dict[str, dict[str, str]]:
    """The dataset-state owner's meaningful content of one CSV version."""
    from src.sources.dataset_integrity import parse_board as owner_parse

    return owner_parse(text, signal=signal).rows


_POSITIONS_CACHE: dict[str, str] = {}


def _position_map() -> dict[str, str]:
    """identity -> position letters, from every captured board that publishes one."""
    if not _POSITIONS_CACHE:
        for path in sorted(CSV_DIR.glob("*.csv")):
            b = load_board(path.stem, path)
            if b is None:
                continue
            for i, e in b.entries.items():
                p = "".join(ch for ch in (e["position"] or "") if ch.isalpha())
                if p and i not in _POSITIONS_CACHE:
                    _POSITIONS_CACHE[i] = p
    return _POSITIONS_CACHE


def batch_value_identity_history(
    subject_key: str,
    comparator_key: str,
    universe: Mapping[str, str],
    universe_name: str,
    exclude_positions: frozenset[str] = frozenset({"TE"}),
    min_rows_changed: int = 50,
    lookback_days: int = 6,
) -> list[dict[str, Any]]:
    """For every historical BATCH in which ``subject_key``'s rows of one
    universe changed broadly, find the comparator capture (within the
    preceding ``lookback_days``) that maximises exact value equality.

    TE rows are excluded by default because a subject may apply its own TE
    premium on top of a copied base value.  Identity of hundreds of integer
    values at a consistent short lag is reported as MEASURED value identity —
    never as proven ancestry, which needs the vendor's own statement."""
    spath, cpath = csv_path(subject_key), csv_path(comparator_key)
    positions = _position_map()
    members = {
        i
        for i, u in universe.items()
        if u == universe_name and positions.get(i, "") not in exclude_positions
    }
    out: list[dict[str, Any]] = []
    prev: dict[str, float] | None = None
    for sha, at in reversed(git_versions(spath)):
        b = board_at(subject_key, spath, sha)
        vals = {
            i: e["value"] for i, e in b.entries.items() if i in members and e["value"] is not None
        }
        if (
            prev is not None
            and sum(1 for i, v in vals.items() if prev.get(i) != v) < min_rows_changed
        ):
            prev = vals
            continue
        prev = vals
        best: dict[str, Any] | None = None
        for csha, cat in git_versions(cpath, at - timedelta(days=lookback_days), at):
            comp = board_at(comparator_key, cpath, csha)
            cvals = {i: e["value"] for i, e in comp.entries.items() if e["value"] is not None}
            vi = value_identity(vals, cvals)
            if (
                vi
                and vi["n"] >= 50
                and (best is None or vi["exactEqual"] > best["identity"]["exactEqual"])
            ):
                best = {
                    "comparatorAt": cat.isoformat(),
                    "lagHours": round((at - cat).total_seconds() / 3600, 1),
                    "identity": vi,
                }
        out.append({"subjectBatchAt": at.isoformat(), "best": best})
    return out


def discordant_share(a: Mapping[str, float], b: Mapping[str, float]) -> tuple[int, float | None]:
    """Share of shared-identity pairs the two orderings put in opposite order
    (pairs tied in either ordering are neither concordant nor discordant)."""
    common = sorted(set(a) & set(b))
    n = len(common)
    if n < MIN_PAIR_OVERLAP:
        return n, None
    av = [a[c] for c in common]
    bv = [b[c] for c in common]
    disc = 0
    for i in range(n):
        ai, bi = av[i], bv[i]
        for j in range(i + 1, n):
            if (ai - av[j]) * (bi - bv[j]) < 0:
                disc += 1
    return n, round(disc / (n * (n - 1) / 2), 4)


def order_lead_lag(
    subject_key: str,
    comparator_key: str,
    universe: Mapping[str, str],
    universe_name: str,
    since: datetime,
) -> dict[str, Any]:
    """Does the subject's ordering snap toward the comparator right after the
    comparator publishes?  For each subject version: discordance against the
    comparator version current at that time.  A subject that repeatedly falls
    to near-identity within days of each comparator publication, then
    drifts, is FOLLOWING the comparator — direction measured, ancestry still
    not proven."""
    members = {i for i, u in universe.items() if u == universe_name}
    cpath, spath = csv_path(comparator_key), csv_path(subject_key)
    comp_versions = []
    for sha, at in reversed(git_versions(cpath)):
        cb = board_at(comparator_key, cpath, sha)
        comp_versions.append((at, ordering(cb, [i for i in cb.entries if i in members])))
    rows = []
    for sha, at in reversed(git_versions(spath, since)):
        sb = board_at(subject_key, spath, sha)
        so = ordering(sb, [i for i in sb.entries if i in members])
        current = [(cat, co) for cat, co in comp_versions if cat <= at]
        if not current:
            continue
        cat, co = current[-1]
        n, share = discordant_share(so, co)
        rows.append(
            {
                "subjectAt": at.isoformat(),
                "comparatorAt": cat.isoformat(),
                "n": n,
                "discordantShare": share,
            }
        )
    publications = [cat.isoformat() for cat, _ in comp_versions if cat >= since]
    first_after = []
    for c in publications:
        after = [r for r in rows if r["comparatorAt"] == c]
        if after:
            before = [r for r in rows if r["subjectAt"] < after[0]["subjectAt"]]
            first_after.append(
                {
                    "comparatorAt": c,
                    "subjectBeforeShare": before[-1]["discordantShare"] if before else None,
                    "firstSubjectAt": after[0]["subjectAt"],
                    "firstShare": after[0]["discordantShare"],
                    "minShareUntilNextPublication": min(
                        (r["discordantShare"] for r in after if r["discordantShare"] is not None),
                        default=None,
                    ),
                }
            )
    shares = [r["discordantShare"] for r in rows if r["discordantShare"] is not None]
    return {
        "subjectVersions": len(rows),
        "comparatorPublications": publications,
        "afterEachPublication": first_after,
        "discordantShareMin": min(shares) if shares else None,
        "discordantShareMax": max(shares) if shares else None,
        "latest": rows[-1] if rows else None,
    }


def identity_join_census(payload_path: Path, voting: Sequence[str]) -> dict[str, Any]:
    """Per-source identity join, measured through the LIVE contract build.

    Builds the canonical contract from a pinned raw payload (read-only, the
    same path ``scripts/source_census.py`` uses) and, per voting source,
    compares the CSV's identities with the board rows the canonical identity
    owner (``src.identity.resolution`` via ``_enrich_from_source_csvs``)
    attached them to.

    * ``csvIdentities`` — distinct contract match keys in the CSV;
    * ``csvDuplicateKeys`` — keys the CSV lists more than once;
    * ``attachedIdentities`` — CSV keys that reached at least one board row;
    * ``notAttached`` — CSV keys that reached none (identity misses AND
      vendor rows outside the board's universe — the two are not separated
      here, so this is an upper bound on identity failures);
    * ``withheldCrossGroupCollisions`` — names deliberately withheld because
      two different players share them (issue #1011): never a wrong vote;
    * ``rowsWithAmbiguousEntry`` — board rows whose match had several CSV
      candidates."""
    from src.api import data_contract as dc

    raw = json.loads(Path(payload_path).read_text(encoding="utf-8"))
    contract = dc.build_api_data_contract(raw)
    summary = getattr(dc, "_LAST_CONTRACT_JOIN_SUMMARY", {}) or {}
    withheld = summary.get("withheldForCrossGroupNameCollision") or {}
    rows = contract.get("playersArray") or []
    key_fn = dc._canonical_match_key
    out: dict[str, Any] = {
        "payload": Path(payload_path).relative_to(REPO_ROOT).as_posix()
        if Path(payload_path).is_relative_to(REPO_ROOT)
        else str(payload_path),
        "joinPolicy": summary.get("policy"),
        "sources": {},
    }
    for key in voting:
        path = csv_path(key)
        try:
            text = path.read_text(encoding="utf-8")
        except OSError:
            continue
        reader = csv.DictReader(io.StringIO(text.lstrip("﻿")))
        lowered = {c.lower().strip(): c for c in (reader.fieldnames or [])}
        name_col = next((lowered[c] for c in _NAME_COLUMNS if c in lowered), None)
        counts: dict[str, int] = {}
        for r in reader:
            k = key_fn(str(r.get(name_col) or "").strip()) if name_col else ""
            if k:
                counts[k] = counts.get(k, 0) + 1
        attached: set[str] = set()
        ambiguous_rows = 0
        present_rows = 0
        for row in rows:
            v = (row.get("canonicalSiteValues") or {}).get(key)
            if v is None:
                continue
            present_rows += 1
            detail = ((row.get("sourceAudit") or {}).get("matchedDetails") or {}).get(key) or {}
            nm = (
                detail.get("matchedName")
                or row.get("canonicalName")
                or row.get("displayName")
                or ""
            )
            attached.add(key_fn(str(nm)))
            if detail.get("ambiguous"):
                ambiguous_rows += 1
        csv_keys = set(counts)
        not_attached = sorted(csv_keys - attached)
        out["sources"][key] = {
            "csvIdentities": len(csv_keys),
            "csvDuplicateKeys": sorted(k for k, n in counts.items() if n > 1),
            "boardRowsCarryingSource": present_rows,
            "attachedIdentities": len(csv_keys & attached),
            "notAttached": len(not_attached),
            "notAttachedExamples": [k for k in not_attached if not is_pick_name(k)][:8],
            "withheldCrossGroupCollisions": sorted(set(withheld.get(key) or [])),
            "rowsWithAmbiguousEntry": ambiguous_rows,
        }
    return out


# ── assembly ───────────────────────────────────────────────────────────


def load_state(key: str) -> dict[str, Any] | None:
    try:
        return json.loads((STATE_DIR / f"{key}_dataset.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def state_summary(state: Mapping[str, Any] | None) -> dict[str, Any] | None:
    if not state:
        return None
    out = {
        "health": (state.get("health") or {}).get("state"),
        "warnings": (state.get("health") or {}).get("warnings"),
        "upstream": state.get("upstream"),
        "subsets": {},
    }
    for name, s in (state.get("subsets") or {}).items():
        out["subsets"][name] = {
            "rowCount": s.get("rowCount"),
            "firstObservedAt": s.get("firstObservedAt"),
            "lastAnyMeaningfulChangeAt": s.get("lastAnyMeaningfulChangeAt"),
            "lastBroadDatasetChangeAt": s.get("lastBroadDatasetChangeAt"),
            "changeEvents": len(s.get("changeHistory") or []),
        }
    return out


#: Pairs whose dependence the Unit G open questions name explicitly, plus the
#: cross-publisher pairs already recorded in config/sources/source_lineage.json.
NAMED_PAIRS: tuple[tuple[str, str], ...] = (
    ("ktcCrowdSfTep", "ktcTradesSfTep"),
    ("fantasyNavigatorSf", "ktcCrowdSfTep"),
    ("fantasyNavigatorSf", "ktcTradesSfTep"),
    ("fantasyNavigatorSf", "ktcCrowdTradesSfTep"),
    ("pfkDynasty", "ktcCrowdSfTep"),
    ("pfkDynasty", "ktcTradesSfTep"),
    ("fantasyCalc", "dynastyDaddySf"),
    ("otcffbSf", "fantasyCalc"),
    ("otcffbSf", "ktcCrowdSfTep"),
    ("otcffbSf", "ktcTradesSfTep"),
    ("idpTradeCalc", "ktcCrowdSfTep"),
    ("idpTradeCalc", "ktcTradesSfTep"),
    ("idpTradeCalc", "idpShowCombined"),
    ("idpTradeCalc", "idpShow"),
    ("idpShowCombined", "idpShow"),
    ("fantasyProsFitzmaurice", "fantasyProsSf"),
    ("fantasyProsFitzmaurice", "dynastyNerdsSfTep"),
    ("flockFantasySf", "flockFantasySfRookies"),
    ("dlfSf", "dlfRookieSf"),
    ("dlfIdp", "dlfRookieIdp"),
    ("dlfSf", "dlfValuesSfTep"),
    ("draftSharks", "draftSharksIdp"),
    ("dlfSf", "ktcCrowdSfTep"),
    ("fantasyProsIdp", "idpShowCombined"),
    ("fantasyProsIdp", "idpTradeCalc"),
    ("dlfIdp", "idpTradeCalc"),
    ("draftSharksIdp", "idpTradeCalc"),
)

#: Lagged value-identity tests: (subject, comparator, comparator CSV, window days).
IDENTITY_TESTS: tuple[tuple[str, str, str, int], ...] = (
    ("fantasyNavigatorSf", "ktc", "ktc.csv", 10),
    ("fantasyNavigatorSf", "ktcCrowdSfTep", "ktcCrowdSfTep.csv", 10),
    ("pfkDynasty", "ktc", "ktc.csv", 10),
    ("pfkDynasty", "ktcCrowdSfTep", "ktcCrowdSfTep.csv", 10),
    ("fantasyCalc", "dynastyDaddySf", "dynastyDaddySf.csv", 4),
    ("dynastyDaddySf", "fantasyCalc", "fantasyCalc.csv", 4),
    ("otcffbSf", "ktc", "ktc.csv", 10),
    ("ktcTradesSfTep", "ktcCrowdSfTep", "ktcCrowdSfTep.csv", 3),
)

#: Board file per source key, filled from the contract's ``_SOURCE_CSV_PATHS``
#: (the single declaration of which CSV a source reads) by :func:`_registry`.
CSV_FILE_FOR: dict[str, Path] = {}


def csv_path(key: str) -> Path:
    return CSV_FILE_FOR.get(key) or (CSV_DIR / f"{key}.csv")


def run(
    voting: Sequence[str],
    non_voting: Sequence[str],
    as_of: datetime,
    rank_signal: Mapping[str, bool],
    history_days: int = 120,
    payload: Path | None = None,
) -> dict[str, Any]:
    keys = list(voting) + [k for k in non_voting if k not in voting]
    boards = {k: b for k in keys if (b := load_board(k, csv_path(k))) is not None}
    universe = build_universe_index(boards)
    config = json.loads(FRESHNESS_CONFIG.read_text(encoding="utf-8"))
    declared_default = config.get("defaultCadence") or {}
    since = as_of - timedelta(days=history_days)

    sources: dict[str, Any] = {}
    for key in keys:
        board = boards.get(key)
        state = load_state(key)
        entry: dict[str, Any] = {
            "voting": key in voting,
            "csv": csv_path(key).relative_to(REPO_ROOT).as_posix(),
        }
        if board is None:
            entry["semantics"] = None
            sources[key] = entry
            continue
        entry["semantics"] = semantics_profile(board, universe)
        entry["datasetState"] = state_summary(state)
        if state:
            declared = (config.get("sources") or {}).get(key) or declared_default
            entry["cadence"] = {
                sub: cadence_check(s, declared, as_of)
                for sub, s in (state.get("subsets") or {}).items()
            }
            entry["clockHonesty"] = clock_honesty(
                key, csv_path(key), state, as_of, signal="rank" if rank_signal.get(key) else "value"
            )
        if rank_signal.get(key):
            entry["rankChangeCensus"] = rank_change_census(key, csv_path(key), since)
        sources[key] = entry

    offense_pool = [k for k in voting if k in boards]
    pairs = list(NAMED_PAIRS)
    dependence = dependence_matrix(boards, universe, "offense", offense_pool, pairs)
    dependence += dependence_matrix(boards, universe, "idp", offense_pool, pairs)
    # full voting matrix, offense, for context (top correlated pairs reported)
    full = dependence_matrix(
        boards, universe, "offense", offense_pool, itertools.combinations(sorted(offense_pool), 2)
    )
    full_idp = dependence_matrix(
        boards, universe, "idp", offense_pool, itertools.combinations(sorted(offense_pool), 2)
    )

    identity = []
    for subject, comp_key, comp_file, days in IDENTITY_TESTS:
        b = boards.get(subject)
        if b is None:
            continue
        subj_vals = {
            i: e["value"]
            for i, e in b.entries.items()
            if e["value"] is not None
            and universe.get(i) == "offense"
            and not is_pick_name(e["raw"])
        }
        res = lagged_value_identity(subj_vals, comp_key, CSV_DIR / comp_file, as_of, days)
        identity.append(
            {"subject": subject, "comparator": comp_key, "windowDays": days, "best": res}
        )

    # IDP Trade Calculator lineage, measured from its own history (Unit G
    # open question).  Offense: every broad offense batch vs KTC base SF.
    # IDP: does its ordering follow each IDP Show publication?
    idp_ids = {i for i, u in universe.items() if u == "idp"}
    idptc = boards.get("idpTradeCalc")
    idptc_order = ordering(idptc, [i for i in idptc.entries if i in idp_ids]) if idptc else {}
    current_idp_order_identity = {}
    for other in ("idpShow", "idpShowCombined", "dlfIdp", "fantasyProsIdp", "draftSharksIdp"):
        ob = boards.get(other)
        if ob is None or not idptc_order:
            continue
        n, share = discordant_share(
            idptc_order, ordering(ob, [i for i in ob.entries if i in idp_ids])
        )
        current_idp_order_identity[other] = {"n": n, "discordantShare": share}
    since = as_of - timedelta(days=history_days)
    lineage_history = {
        "idpTradeCalcOffenseBatchesVsKtcBaseSf": batch_value_identity_history(
            "idpTradeCalc", "ktc", universe, "offense"
        ),
        "idpTradeCalcIdpOrderVsOtherIdpBoards": current_idp_order_identity,
        "idpTradeCalcIdpLeadLagVsIdpShow": order_lead_lag(
            "idpTradeCalc", "idpShow", universe, "idp", since
        ),
    }

    return {
        "schema": "lineage-integrity-sweep/v1",
        "asOf": as_of.isoformat(),
        "codeSha": _git("rev-parse", "HEAD").strip(),
        "historyDays": history_days,
        "universeIndexSize": len(universe),
        "sources": sources,
        "namedPairDependence": dependence,
        "votingMatrixTop": {
            "offense": sorted(
                (p for p in full if p["leavePairOutResidual"] is not None),
                key=lambda p: -p["leavePairOutResidual"],
            )[:12],
            "idp": sorted(
                (p for p in full_idp if p["leavePairOutResidual"] is not None),
                key=lambda p: -p["leavePairOutResidual"],
            )[:8],
        },
        "laggedValueIdentity": identity,
        "lineageHistory": lineage_history,
        "identityJoin": identity_join_census(payload, voting) if payload else None,
    }


def _registry() -> tuple[list[str], dict[str, bool]]:
    from src.api import data_contract as dc

    voting = [s["key"] for s in dc._RANKING_SOURCES]
    rank_signal = {}
    for key, cfg in dc._SOURCE_CSV_PATHS.items():
        rank_signal[key] = isinstance(cfg, dict) and cfg.get("signal") == "rank"
        rel = cfg.get("path") if isinstance(cfg, dict) else cfg
        if isinstance(rel, str):
            CSV_FILE_FOR[key] = REPO_ROOT / rel
    return voting, rank_signal


def _latest_payload() -> Path | None:
    paths = sorted((REPO_ROOT / "exports" / "latest").glob("dynasty_data_*.json"))
    return paths[-1] if paths else None


NON_VOTING_COMPARATORS = ("ktc", "ktcSfTep", "ktcCrowdTradesSfTep", "idpShow", "dlfValuesSfTep")


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("--out", type=Path, required=False)
    parser.add_argument("--as-of", default=None, help="ISO timestamp (default: now, UTC)")
    parser.add_argument("--history-days", type=int, default=120)
    parser.add_argument(
        "--payload",
        type=Path,
        default=None,
        help="raw payload for the identity-join census (default: newest exports/latest/dynasty_data_*.json)",
    )
    args = parser.parse_args(argv)
    if not CSV_DIR.is_dir():
        print(f"[integrity-sweep] missing {CSV_DIR}", file=sys.stderr)
        return 2
    as_of = _parse(args.as_of) if args.as_of else datetime.now(timezone.utc).replace(microsecond=0)
    voting, rank_signal = _registry()
    payload = args.payload or _latest_payload()
    result = run(voting, NON_VOTING_COMPARATORS, as_of, rank_signal, args.history_days, payload)
    text = json.dumps(result, indent=1, sort_keys=False, default=str) + "\n"
    if args.out:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(text, encoding="utf-8")
        print(f"[integrity-sweep] wrote {args.out}")
    else:
        sys.stdout.write(text)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
