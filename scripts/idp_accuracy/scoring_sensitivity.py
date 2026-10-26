"""Lane E: scoring-sensitivity experiment for the IDP block of the ``dynasty_main`` card.

Research only (``docs/owner/IDP_VALUATION_ACCURACY_DIRECTIVE_2026-10-25.md`` sections 10 and 13).
Nothing in ``src/`` imports this module, nothing here is served, and production scoring is untouched.

What it does.  It rescores 2026 weeks 1-6 (and 2025 / 2024 for the year-over-year rows) under a grid of
IDP scoring cards - each directive key varied alone, joint cards, the league's own historical cards and
two constructed cards - and measures, per card, how production, elite-versus-average separation,
starter-versus-replacement gaps, predictability, weekly variance and best-ball lineup contribution
differ by position group and archetype.

Why rescoring is exact.  Sleeper's scorer is a dot product of the stat counts on a stat line and the
card rates (``src.league_intel.scorer.score_stat_line``).  A sack play therefore pays ``idp_sack``,
``idp_tkl_loss`` and ``idp_qb_hit`` together because the STAT LINE carries all three counts: stacking
is a property of the data, reproduced here by construction and never modelled.  Each player-week is
stored once as ``fixed`` (every key this study does not vary, scored by the production scorer under the
actual card) plus the counts of the 16 IDP keys it does vary; any card's points are
``fixed + counts @ rates``.  ``verify_parity`` pins that identity against ``compute_weekly_points`` for
the actual card and for perturbed cards, and against Sleeper's own awarded points.

Provenance of copied code.  The exact vectorized best-ball lineup solver, the slot-signature helper,
the nflverse fine-position join and the archetype rule are COPIED from Lane D
(PR #1941, ``scripts/idp_accuracy/d_engine.py`` / ``d_data.py``, branch
``claude/idp-d-bestball-archetypes-v2``) so this lane has no dependency on a branch that has not
landed.  They are marked ``VENDORED`` below, pinned to ``src.ros.lineup`` by the tests, and compared
function-for-function against Lane D's modules whenever those are importable.  When #1941 merges,
replace the vendored block with imports; the parity test then becomes an import-equivalence check.

CLI::

    python scripts/idp_accuracy/scoring_sensitivity.py run [--offline] [--workers N]
    python scripts/idp_accuracy/scoring_sensitivity.py tables
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import io
import itertools
import json
import math
import os
import re
import subprocess
import sys
import time
import urllib.request
import warnings
from collections import Counter, defaultdict
from concurrent.futures import ProcessPoolExecutor
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence

import numpy as np
from scipy.stats import rankdata

from src.league_comparison.sleeper_scoring import scoring_fingerprint
from src.nfl_data.realized_points import (
    compute_weekly_points,
    host_stat_line,
    is_host_player_entry,
)
from src.ros.lineup import (
    RosterPlayer,
    lineup_position,
    normalize_slot,
    precompute_slot_eligibility,
)
from src.scoring.sleeper_ingest import KEY_ALIASES

REPO = Path(__file__).resolve().parents[2]
CONFIG_PATH = REPO / "config/idp_accuracy/scoring_sensitivity_cards.json"
EVIDENCE_PATH = REPO / "docs/valuation/idp_accuracy/evidence/scoring_sensitivity.json"
DOC_PATH = REPO / "docs/valuation/idp_accuracy/E_SCORING_SENSITIVITY.md"
CACHE_DIR = REPO / "data/idp_accuracy/cache"
NFLVERSE_DIR = CACHE_DIR / "nflverse"

SLEEPER = "https://api.sleeper.app/v1"
NFLVERSE_BASE = "https://github.com/nflverse/nflverse-data/releases/download"
NFLVERSE_FILES = {
    "roster_2026": "rosters/roster_2026.csv",
    "roster_2025": "rosters/roster_2025.csv",
    "games": "schedules/games.csv",
}

STUDY_SEASON = 2026
STUDY_WEEKS = (1, 2, 3, 4, 5, 6)
SEASONS_PRIOR = (2025, 2024)
ALL_WEEKS = {2026: STUDY_WEEKS, 2025: tuple(range(1, 19)), 2024: tuple(range(1, 19))}

GROUPS = ("QB", "RB", "WR", "TE", "K", "DL", "LB", "DB")
OFFENSE_GROUPS = ("QB", "RB", "WR", "TE")
IDP_GROUPS = ("DL", "LB", "DB")
ARCHETYPES = ("EDGE", "DT", "ILB", "OLB", "CB", "S")
PLAYED, DNP, BYE, UNKNOWN = 0, 1, 2, 3

#: Canonical STAT-LINE spellings of the sixteen IDP keys this study can vary.  The league card spells two
#: of them differently (``idp_qb_hit`` -> ``idp_hit``, ``idp_pass_def`` -> ``idp_pd``); the production scorer
#: resolves that alias, and so does ``rate_vector`` (same rule, pinned by ``verify_parity``).
TENSOR_KEYS: tuple[str, ...] = (
    "idp_tkl_solo",
    "idp_tkl_ast",
    "idp_tkl",
    "idp_tkl_loss",
    "idp_sack",
    "idp_sack_yd",
    "idp_hit",
    "idp_pd",
    "idp_int",
    "idp_int_ret_yd",
    "idp_ff",
    "idp_fum_rec",
    "idp_fum_ret_yd",
    "idp_def_td",
    "idp_safe",
    "idp_blk_kick",
)
TENSOR_SET = frozenset(TENSOR_KEYS)
KIDX = {k: i for i, k in enumerate(TENSOR_KEYS)}
#: Event counts whose per-game stability is reported (config-free).
EVENT_KEYS = (
    "idp_tkl_solo",
    "idp_tkl_ast",
    "idp_tkl_loss",
    "idp_sack",
    "idp_hit",
    "idp_pd",
    "idp_int",
    "idp_ff",
    "idp_fum_rec",
)
EVENT_COLS = [KIDX[k] for k in EVENT_KEYS]

_ALIASES = {a: c for a, c in KEY_ALIASES.items() if a != c}

TIER_BOUNDS = {"p12": (0, 12), "p13_24": (12, 24), "p25_36": (24, 36), "p37_48": (36, 48)}
STARTERS = 36
IDP_SLOT_NAMES = frozenset({"DL", "LB", "DB"})
OFFENSE_SLOT_NAMES = frozenset({"QB", "RB", "WR", "TE", "FLEX", "SUPER_FLEX", "K"})

#: nflverse -> Sleeper team abbreviation differences (VENDORED from Lane D).
TEAM_ALIAS = {"LA": "LAR", "JAC": "JAX", "WSH": "WAS", "OAK": "LV", "SD": "LAC", "STL": "LAR"}
UNAVAILABLE_INJURY = frozenset({"out", "ir", "pup", "sus", "na", "dnr", "nfi"})
UNAVAILABLE_STATUS = frozenset(
    {"injured reserve", "inactive", "suspended", "pup", "nfi", "reserve/injured", "retired"}
)


# ── small helpers ─────────────────────────────────────────────────────────────


def sha256_bytes(blob: bytes) -> str:
    return hashlib.sha256(blob).hexdigest()


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def canonical_sha256(obj: Any) -> str:
    return sha256_bytes(json.dumps(obj, sort_keys=True, separators=(",", ":")).encode())


def _num(v: Any) -> float:
    if isinstance(v, bool) or v is None:
        return 0.0
    try:
        x = float(v)
    except (TypeError, ValueError):
        return 0.0
    return x if math.isfinite(x) else 0.0


def _quiet(fn, *args, **kwargs):
    """A numpy nan-reducer with its all-NaN-slice RuntimeWarning silenced (the NaN IS the answer)."""
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", RuntimeWarning)
        return fn(*args, **kwargs)


def load_config(path: Path = CONFIG_PATH) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def config_sha256(path: Path = CONFIG_PATH) -> str:
    """sha256 of the config with line endings normalized, so a Windows checkout hashes like a Linux one."""
    crlf, lf = bytes([13, 10]), bytes([10])
    return sha256_bytes(path.read_bytes().replace(crlf, lf))


# ── cards ─────────────────────────────────────────────────────────────────────


def _mult_id(m: float) -> str:
    return f"x{m:g}"


def build_cards(actual: Mapping[str, float], cfg: Mapping[str, Any]) -> dict[str, dict[str, float]]:
    """Every configuration as a FULL Sleeper card (offense and fixed keys at their actual rates).

    ``actual`` is the league's own 2026 ``scoring_settings``.  One-at-a-time and joint cards multiply
    the named IDP rate(s); reference cards replace the whole IDP block (any IDP key a reference card does
    not list is 0, so a reference pays only what it names).  Offense, special teams and every non-IDP
    key are never touched.
    """
    study = cfg["studyKeys"]
    cards: dict[str, dict[str, float]] = {"actual": {k: float(v) for k, v in actual.items()}}

    def base() -> dict[str, float]:
        return dict(cards["actual"])

    for key in cfg["oneAtATime"]["keys"]:
        ck = study[key]
        for m in cfg["oneAtATime"]["multipliers"]:
            c = base()
            c[ck] = cards["actual"].get(ck, 0.0) * float(m)
            cards[f"oat:{key}:{_mult_id(float(m))}"] = c
    for j in cfg["joint"]:
        c = base()
        for key, m in j["multipliers"].items():
            ck = study.get(key, key)
            c[ck] = cards["actual"].get(ck, 0.0) * float(m)
        for ck in j.get("zeroCardKeys", []):
            c[ck] = 0.0
        cards[f"joint:{j['id']}"] = c
    for r in cfg["reference"]:
        c = base()
        for ck in cfg["idpCardKeys"]:
            c[ck] = 0.0
        for ck, v in r["idpBlock"].items():
            c[ck] = float(v)
        cards[f"ref:{r['id']}"] = c
    return cards


def card_label(cid: str) -> str:
    """A short human label for a configuration id."""
    if cid == "actual":
        return "actual 2026 card"
    kind, _, rest = cid.partition(":")
    if kind == "oat":
        key, _, mult = rest.partition(":")
        return f"{key} {mult.replace('x', 'x')}"
    return rest.replace("_", " ")


def rate_vector(card: Mapping[str, Any]) -> np.ndarray:
    """Rates over ``TENSOR_KEYS`` with the production scorer's alias rule.

    ``compute_weekly_points`` copies an alias key's rate onto the canonical key only when the canonical
    key is absent from the card; this does the same, so ``fixed + counts @ rate_vector(card)`` equals the
    production scorer's total for any card.
    """
    scoring = {str(k): _num(v) for k, v in card.items()}
    for alias, canonical in _ALIASES.items():
        if alias in scoring and canonical not in scoring:
            scoring[canonical] = scoring[alias]
    return np.array([scoring.get(k, 0.0) for k in TENSOR_KEYS], dtype=float)


def card_without_tensor(card: Mapping[str, Any]) -> dict[str, float]:
    """The card with every varied key (and its alias spellings) set to 0: scores the ``fixed`` part."""
    return {
        str(k): (0.0 if _ALIASES.get(str(k), str(k)) in TENSOR_SET else _num(v))
        for k, v in card.items()
    }


def idp_block(card: Mapping[str, Any], keys: Iterable[str]) -> dict[str, float]:
    return {k: float(card.get(k, 0.0)) for k in keys}


# ── VENDORED from Lane D (PR #1941): lineup solver, signatures, fine positions, archetypes ──────────


def signature_for(
    player_id: str, position: str, fantasy_positions: Sequence[str], slots: Sequence[str]
) -> frozenset[str]:
    """VENDORED (Lane D ``d_engine.signature_for``).  The slot-family names a player may fill."""
    rp = RosterPlayer(
        player_id=player_id,
        canonical_name=player_id,
        position=position,
        ros_value=0.0,
        fantasy_positions=tuple(fantasy_positions),
    )
    elig = precompute_slot_eligibility([rp], list(slots))
    return frozenset(normalize_slot(slots[i]) for i in elig.get(player_id, ()))


def subproblem_of(sig: frozenset[str]) -> str | None:
    """VENDORED (Lane D).  "off" / "idp", or None for a signature spanning both or neither."""
    if not sig:
        return None
    if sig <= OFFENSE_SLOT_NAMES:
        return "off"
    if sig <= IDP_SLOT_NAMES:
        return "idp"
    return None


def split_slots(slots: Sequence[str]) -> tuple[list[str], list[str]]:
    """VENDORED (Lane D)."""
    off = [s for s in slots if normalize_slot(s) in OFFENSE_SLOT_NAMES]
    idp = [s for s in slots if normalize_slot(s) in IDP_SLOT_NAMES]
    return off, idp


class LineupSolver:
    """VENDORED (Lane D ``d_engine.LineupSolver``).  Exact best-ball lineup totals for many weeks at once.

    Slot eligibility is a transversal matroid, so "take players in descending score, keep one if the kept
    set is still assignable" is exactly optimal; assignability is Hall's condition over unions of
    eligibility signatures.  Like the owner (``OBJECTIVE_REALIZED_POINTS``) it fills every fillable slot.
    Pinned to ``src.ros.lineup.solve_optimal_assignment`` by ``tests/idp_accuracy/test_scoring_sensitivity.py``.
    """

    def __init__(self, slots: Sequence[str], signatures: Iterable[frozenset[str]]):
        self.slot_caps = Counter(normalize_slot(s) for s in slots)
        self.n_slots = int(sum(self.slot_caps.values()))
        sigs = sorted({frozenset(s) for s in signatures if s}, key=lambda s: (len(s), sorted(s)))
        self.types: list[frozenset[str]] = sigs
        self.type_id = {s: i for i, s in enumerate(sigs)}
        unions: set[frozenset[str]] = set()
        for r in range(1, len(sigs) + 1):
            for combo in itertools.combinations(sigs, r):
                unions.add(frozenset().union(*combo))
        self.hall_sets = sorted(unions, key=lambda s: (len(s), sorted(s)))
        T = len(sigs)
        self.M = np.zeros((T, len(self.hall_sets)), dtype=np.int16)
        for j, S in enumerate(self.hall_sets):
            for t, sig in enumerate(sigs):
                if sig <= S:
                    self.M[t, j] = 1
        self.caps = np.array(
            [sum(self.slot_caps.get(g, 0) for g in S) for S in self.hall_sets], dtype=np.int16
        )

    def solve(self, X: np.ndarray, type_ids: np.ndarray) -> np.ndarray:
        """``X`` is (weeks, players) scores; ``type_ids`` (players,).  Returns (weeks,) totals."""
        D, N = X.shape
        if N == 0:
            return np.zeros(D)
        type_ids = np.asarray(type_ids, dtype=np.int64)
        order = np.argsort(-X, axis=1, kind="stable")
        rows = np.arange(D)
        cnt = np.zeros((D, len(self.types)), dtype=np.int16)
        total = np.zeros(D)
        filled = np.zeros(D, dtype=np.int16)
        for j in range(N):
            idx = order[:, j]
            t = type_ids[idx]
            cnt[rows, t] += 1
            ok = ((cnt @ self.M) <= self.caps).all(axis=1)
            bad = ~ok
            if bad.any():
                cnt[rows[bad], t[bad]] -= 1
            val = X[rows, idx]
            total += np.where(ok, val, 0.0)
            filled += ok
            if j + 1 >= self.n_slots and (filled >= self.n_slots).all():
                break
        return total


_SUFFIXES = {"jr", "sr", "ii", "iii", "iv", "v"}
_FINE = {
    "DE": "DE",
    "DT": "DT",
    "NT": "DT",
    "OLB": "OLB",
    "ILB": "ILB",
    "MLB": "ILB",
    "CB": "CB",
    "FS": "S",
    "SS": "S",
    "S": "S",
}
_SLEEPER_DEPTH = {
    "LDE": "DE",
    "RDE": "DE",
    "LDT": "DT",
    "RDT": "DT",
    "NT": "DT",
    "LOLB": "OLB",
    "ROLB": "OLB",
    "SLB": "OLB",
    "WLB": "OLB",
    "LILB": "ILB",
    "RILB": "ILB",
    "MLB": "ILB",
    "LCB": "CB",
    "RCB": "CB",
    "NB": "CB",
    "SS": "S",
    "FS": "S",
}


def _team(t: str | None) -> str | None:
    if not t:
        return None
    t = t.strip().upper()
    return TEAM_ALIAS.get(t, t)


def _clean_id(v: Any) -> str | None:
    s = str(v).strip() if v is not None else ""
    return s or None


def name_key(name: Any) -> str:
    """VENDORED (Lane D).  Lower-case alphanumeric tokens, generational suffixes removed (join key only)."""
    toks = "".join(ch if ch.isalnum() else " " for ch in str(name or "").lower()).split()
    return " ".join(t for t in toks if t not in _SUFFIXES)


@dataclass(frozen=True)
class FineIndex:
    by_sleeper: dict[str, tuple[str, str]]
    by_gsis: dict[str, tuple[str, str]]
    by_name_team: dict[tuple[str, str], list[tuple[str, str]]]


def build_fine_index(roster_2026: list[dict], roster_2025: list[dict]) -> FineIndex:
    """VENDORED (Lane D ``d_data.build_fine_index``).  2025 first so the newest assignment wins."""
    by_s: dict[str, tuple[str, str]] = {}
    by_g: dict[str, tuple[str, str]] = {}
    by_nt: dict[tuple[str, str], list[tuple[str, str]]] = defaultdict(list)
    for fname, rows in (("roster_2025", roster_2025), ("roster_2026", roster_2026)):
        for r in rows:
            raw = (r.get("depth_chart_position") or r.get("position") or "").strip().upper()
            if not raw:
                continue
            sid = _clean_id(r.get("sleeper_id"))
            gid = _clean_id(r.get("gsis_id"))
            if sid:
                by_s[sid] = (raw, fname)
            if gid:
                by_g[gid] = (raw, fname)
            team = _team(r.get("team"))
            if team and fname == "roster_2026":
                by_nt[(name_key(r.get("full_name")), team)].append((raw, fname))
    return FineIndex(by_s, by_g, dict(by_nt))


def resolve_fine(pid: str, meta: Mapping[str, Any], idx: FineIndex) -> tuple[str, str]:
    """VENDORED (Lane D ``d_data.resolve_fine``).  (fine position, provenance) or ("UNKNOWN", reason)."""
    hit = idx.by_sleeper.get(pid)
    how = "sleeper_id"
    if hit is None:
        gid = _clean_id(meta.get("gsis_id"))
        hit = idx.by_gsis.get(gid) if gid else None
        how = "gsis_id"
    if hit is None:
        team = _team(meta.get("team"))
        cands = idx.by_name_team.get((name_key(meta.get("full_name")), team)) if team else None
        if cands and len(cands) == 1:
            hit, how = cands[0], "name_team"
        elif cands:
            return "UNKNOWN", "ambiguous_name_team"
    if hit is not None:
        raw, fname = hit
        fine = _FINE.get(raw)
        if fine is not None:
            return fine, f"{how}:{fname}"
        generic = f"nflverse_generic_position:{raw}"
    else:
        generic = "no_nflverse_roster_match"
    sd = _SLEEPER_DEPTH.get(str(meta.get("depth_chart_position") or "").strip().upper())
    if sd is not None:
        return sd, "sleeper_depth_chart"
    return "UNKNOWN", generic


def archetype_for(fine: str, position_group: str, fantasy_positions: Sequence[str]) -> str:
    """VENDORED (Lane D ``d_data.archetype_for``).  Provenance fields only, never performance."""
    if position_group in ("QB", "RB", "WR", "TE", "K"):
        return position_group
    if fine == "DE":
        return "EDGE"
    if fine == "OLB":
        return "EDGE" if "DL" in fantasy_positions else "OLB"
    if fine in ("DT", "ILB", "CB", "S"):
        return fine
    return f"UNK_{position_group}"


def schedule_weeks(games: list[dict[str, str]], season: int) -> dict[str, set[int]]:
    """VENDORED (Lane D).  team -> set of REG weeks in which that team plays."""
    played: dict[str, set[int]] = defaultdict(set)
    for g in games:
        if g.get("season") != str(season) or g.get("game_type") != "REG":
            continue
        wk = int(g["week"])
        for side in ("away_team", "home_team"):
            t = _team(g.get(side))
            if t:
                played[t].add(wk)
    return dict(played)


def is_forward_unavailable(meta: Mapping[str, Any]) -> bool:
    """VENDORED (Lane D).  Out / IR / PUP / suspended / inactive by the host's own status."""
    inj = str(meta.get("injury_status") or "").strip().lower()
    st = str(meta.get("status") or "").strip().lower()
    return inj in UNAVAILABLE_INJURY or st in UNAVAILABLE_STATUS


# ── data access ───────────────────────────────────────────────────────────────


class Fetcher:
    """Cached, throttled GET of public endpoints.  Same cache key scheme as Lanes A and D
    (``sha256(url)[:24]``), so a body another lane fetched is a body this lane reads.  Public,
    unauthenticated GETs only, throttled under 5 requests / second."""

    MIN_INTERVAL_S = 0.25

    def __init__(self, *, offline: bool = False) -> None:
        CACHE_DIR.mkdir(parents=True, exist_ok=True)
        NFLVERSE_DIR.mkdir(parents=True, exist_ok=True)
        self.offline = offline
        self._last = 0.0
        self.receipts: dict[str, dict[str, Any]] = {}

    def _http(self, url: str) -> bytes:
        if self.offline:
            raise RuntimeError(f"offline and not cached: {url}")
        wait = self.MIN_INTERVAL_S - (time.time() - self._last)
        if wait > 0:
            time.sleep(wait)
        req = urllib.request.Request(
            url, headers={"User-Agent": "brisket-idp-accuracy-research/1.0"}
        )
        with urllib.request.urlopen(req, timeout=120) as resp:  # noqa: S310 - public https GET
            blob = resp.read()
        self._last = time.time()
        return blob

    def _receipt(self, key: str, path: Path, blob: bytes) -> None:
        self.receipts[key] = {
            "sha256": sha256_bytes(blob),
            "bytes": len(blob),
            "fetchedAtUtc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(path.stat().st_mtime)),
        }

    def sleeper(self, path: str) -> Any:
        url = f"{SLEEPER}/{path}"
        cache = CACHE_DIR / f"{hashlib.sha256(url.encode()).hexdigest()[:24]}.json"
        if not cache.exists():
            cache.write_bytes(self._http(url))
        blob = cache.read_bytes()
        self._receipt(f"sleeper:{path}", cache, blob)
        return json.loads(blob)

    def nflverse(self, key: str) -> list[dict[str, str]]:
        rel = NFLVERSE_FILES[key]
        cache = NFLVERSE_DIR / rel.replace("/", "__")
        if not cache.exists():
            cache.write_bytes(self._http(f"{NFLVERSE_BASE}/{rel}"))
        blob = cache.read_bytes()
        self._receipt(f"nflverse:{rel}", cache, blob)
        return list(csv.DictReader(io.StringIO(blob.decode("utf-8"))))


# ── season arrays ─────────────────────────────────────────────────────────────


@dataclass
class SeasonData:
    """One season of host stat lines as arrays, decomposed for exact rescoring.

    ``fixed[p, w]`` = points from every key this study does NOT vary (production scorer, actual card,
    varied keys zeroed); ``counts[p, w, k]`` = the stat counts of the 16 varied keys.  Both are 0 in a
    week the player did not play.  ``status`` is PLAYED / DNP / BYE / UNKNOWN: a bye is excluded, a DNP
    is a real best-ball zero, an unknown is neither - and none of the three is ever a played week.
    """

    season: int
    weeks: tuple[int, ...]
    pids: list[str]
    status: np.ndarray
    fixed: np.ndarray
    counts: np.ndarray
    index: dict[str, int] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not self.index:
            self.index = {p: i for i, p in enumerate(self.pids)}

    def n_played(self) -> np.ndarray:
        return (self.status == PLAYED).sum(axis=1)

    def points(self, rates: np.ndarray) -> np.ndarray:
        """(players, weeks) points under ``rates``; 0 where the player did not play."""
        return self.fixed + self.counts @ rates


def build_season(
    stats_by_week: Mapping[int, Mapping[str, Mapping[str, Any]]],
    directory: Mapping[str, Mapping[str, Any]],
    card: Mapping[str, Any],
    play: Mapping[str, set[int]],
    season: int,
    weeks: Sequence[int],
) -> SeasonData:
    """Score every host player's stat lines once and classify every (player, week).

    Players enter when they have a stat line in any of ``weeks``.  A week with no line is classified from
    the nflverse schedule (bye / DNP / unknown), never scored as a zero.
    """
    rates = rate_vector(card)
    card0 = card_without_tensor(card)
    K = len(TENSOR_KEYS)
    W = len(weeks)
    wpos = {w: i for i, w in enumerate(weeks)}
    recs: dict[str, dict[int, tuple[int, float, np.ndarray]]] = {}
    for w in weeks:
        for pid, line in (stats_by_week.get(w) or {}).items():
            if not is_host_player_entry(pid):
                continue
            meta = directory.get(pid)
            if meta is None:
                continue
            pos = lineup_position(str(meta.get("position") or ""))
            if pos not in GROUPS:
                continue
            row = {**line, "player_id": pid, "season": season, "week": w}
            res = compute_weekly_points(row, card0, position=pos, source="sleeper")
            if res is None:
                continue
            hl = host_stat_line(line)
            cnt = np.array([hl.get(k, 0.0) for k in TENSOR_KEYS], dtype=float)
            fixed = float(res.fantasy_points)
            pts = fixed + float(cnt @ rates)
            appeared = (
                _num(line.get("gp")) > 0
                or _num(line.get("def_snp")) > 0
                or _num(line.get("off_snp")) > 0
                or abs(pts) > 1e-9
            )
            team = _team(meta.get("team"))
            team_plays = team is not None and w in play.get(team, set())
            team_bye = team is not None and team in play and w not in play[team]
            if appeared:
                status = PLAYED
            elif team_bye:
                status = BYE
            elif (
                team_plays or _num(line.get("gms_active")) > 0 or line.get("tm_def_snp") is not None
            ):
                status = DNP
            else:
                status = UNKNOWN
            recs.setdefault(pid, {})[w] = (status, fixed, cnt)
    pids = sorted(recs)
    status = np.full((len(pids), W), UNKNOWN, dtype=np.int8)
    fixed_a = np.zeros((len(pids), W))
    counts_a = np.zeros((len(pids), W, K))
    for i, pid in enumerate(pids):
        meta = directory.get(pid) or {}
        team = _team(meta.get("team"))
        for w in weeks:
            j = wpos[w]
            if w in recs[pid]:
                st, fx, cnt = recs[pid][w]
                status[i, j] = st
                if st == PLAYED:
                    fixed_a[i, j] = fx
                    counts_a[i, j, :] = cnt
            elif team is None or team not in play:
                status[i, j] = UNKNOWN
            elif w not in play[team]:
                status[i, j] = BYE
            else:
                status[i, j] = DNP
    return SeasonData(season, tuple(weeks), pids, status, fixed_a, counts_a)


@dataclass(frozen=True)
class Player:
    pid: str
    name: str
    group: str
    position: str
    fantasy_positions: tuple[str, ...]
    sig: frozenset[str]
    sub: str | None
    arch: str
    fine: str
    team: str | None
    healthy: bool


def make_player(
    pid: str, meta: Mapping[str, Any], slots: Sequence[str], fine_idx: FineIndex | None
) -> Player | None:
    pos = str(meta.get("position") or "")
    group = lineup_position(pos)
    if group not in GROUPS:
        return None
    fps = tuple(str(x) for x in (meta.get("fantasy_positions") or []))
    sig = signature_for(pid, pos, fps, slots)
    fine = "UNKNOWN"
    if group in IDP_GROUPS and fine_idx is not None:
        fine, _prov = resolve_fine(pid, meta, fine_idx)
    arch = archetype_for(fine, group, tuple(lineup_position(x) for x in fps))
    return Player(
        pid=pid,
        name=str(
            meta.get("full_name") or f"{meta.get('first_name', '')} {meta.get('last_name', '')}"
        ).strip(),
        group=group,
        position=pos,
        fantasy_positions=fps,
        sig=sig,
        sub=subproblem_of(sig),
        arch=arch,
        fine=fine,
        team=_team(meta.get("team")),
        healthy=not is_forward_unavailable(meta),
    )


@dataclass
class Inputs:
    league: dict[str, Any]
    card: dict[str, float]
    fingerprint: str | None
    slots: list[str]
    directory: dict[str, dict]
    rosters: list[list[str]]
    s26: SeasonData
    s25: SeasonData
    s24: SeasonData
    fine_idx: FineIndex
    prior_cards: dict[str, dict[str, float]]
    prior_league_ids: dict[str, str]
    receipts: dict[str, dict[str, Any]]


def load_inputs(*, offline: bool = False) -> Inputs:
    f = Fetcher(offline=offline)
    cfg = load_config()
    lid = cfg["league"]["sleeperLeagueId"]
    league = f.sleeper(f"league/{lid}")
    rosters = f.sleeper(f"league/{lid}/rosters")
    directory = f.sleeper("players/nfl")
    card = {str(k): float(v) for k, v in (league.get("scoring_settings") or {}).items()}
    fp = scoring_fingerprint(league.get("scoring_settings"))
    slots = [s for s in league["roster_positions"] if s not in ("BN", "IR", "TAXI")]
    games = f.nflverse("games")
    r26 = f.nflverse("roster_2026")
    r25 = f.nflverse("roster_2025")
    prior_cards: dict[str, dict[str, float]] = {}
    prior_ids: dict[str, str] = {}
    prev = league.get("previous_league_id")
    for season in SEASONS_PRIOR:
        if not prev or str(prev) == "0":
            break
        pl = f.sleeper(f"league/{prev}")
        prior_ids[str(season)] = str(prev)
        prior_cards[str(season)] = {str(k): float(v) for k, v in pl["scoring_settings"].items()}
        prev = pl.get("previous_league_id")
    seasons: dict[int, SeasonData] = {}
    for season, weeks in ALL_WEEKS.items():
        stats = {w: f.sleeper(f"stats/nfl/regular/{season}/{w}") for w in weeks}
        play = schedule_weeks(games, season)
        seasons[season] = build_season(stats, directory, card, play, season, weeks)
    return Inputs(
        league=league,
        card=card,
        fingerprint=fp,
        slots=slots,
        directory=directory,
        rosters=[
            [str(p) for p in (r.get("players") or [])]
            for r in sorted(rosters, key=lambda r: r["roster_id"])
        ],
        s26=seasons[2026],
        s25=seasons[2025],
        s24=seasons[2024],
        fine_idx=build_fine_index(r26, r25),
        prior_cards=prior_cards,
        prior_league_ids=prior_ids,
        receipts=f.receipts,
    )


# ── pure metric helpers ───────────────────────────────────────────────────────


def tier_means(sorted_desc: np.ndarray) -> dict[str, np.ndarray]:
    """Tier means of a descending-sorted (players, configs) array.

    A tier is defined only when the pool reaches its last rank, otherwise NaN: a pool of 30 has no
    "ranks 25-36" tier, and a partial tier is a different quantity.
    """
    n, c = sorted_desc.shape
    out = {}
    for name, (a, b) in TIER_BOUNDS.items():
        out[name] = sorted_desc[a:b].mean(axis=0) if n >= b else np.full(c, np.nan)
    out["starters"] = sorted_desc[:STARTERS].mean(axis=0) if n >= STARTERS else np.full(c, np.nan)
    return out


def derived_tier_metrics(t: Mapping[str, np.ndarray]) -> dict[str, np.ndarray]:
    with np.errstate(divide="ignore", invalid="ignore"):
        sep = t["p12"] - t["p25_36"]
        sep_ratio = np.where(t["p25_36"] > 0, t["p12"] / t["p25_36"], np.nan)
        gap_rank = t["starters"] - t["p37_48"]
        rel_gap_rank = np.where(t["starters"] > 0, gap_rank / t["starters"], np.nan)
    return {"sep": sep, "sep_ratio": sep_ratio, "gap_rank": gap_rank, "rel_gap_rank": rel_gap_rank}


def fa_level(fa_mean: np.ndarray) -> np.ndarray:
    """Median conditional ppg of the top five production-qualified free agents (needs >= 3)."""
    c = fa_mean.shape[1] if fa_mean.ndim == 2 else 0
    if fa_mean.shape[0] < 3:
        return np.full(c, np.nan)
    top = -np.sort(-fa_mean, axis=0)[:5]
    return np.median(top, axis=0)


def icc1(pts: np.ndarray, valid: np.ndarray, n: np.ndarray, mean: np.ndarray) -> np.ndarray:
    """One-way random-effects ICC(1) for unbalanced groups: the between-player share of weekly variance.

    ``pts`` (a, W, C), ``valid`` (a, W) bool, ``n`` (a,) observations per player, ``mean`` (a, C).
    """
    a = pts.shape[0]
    if a < 3:
        return np.full(pts.shape[2], np.nan)
    N = float(n.sum())
    grand = (mean * n[:, None]).sum(axis=0) / N
    ssb = (n[:, None] * (mean - grand) ** 2).sum(axis=0)
    dev = (pts - mean[:, None, :]) * valid[:, :, None]
    ssw = (dev**2).sum(axis=(0, 1))
    msb = ssb / (a - 1)
    msw = ssw / max(N - a, 1.0)
    n0 = (N - float((n**2).sum()) / N) / (a - 1)
    with np.errstate(divide="ignore", invalid="ignore"):
        return (msb - msw) / (msb + (n0 - 1.0) * msw)


def spearman_cols(a: np.ndarray, b: np.ndarray) -> np.ndarray:
    """Spearman correlation of matching columns of two (n, C) arrays."""
    if a.shape[0] < 3:
        return np.full(a.shape[1], np.nan)
    ra = rankdata(a, axis=0)
    rb = rankdata(b, axis=0)
    ra = ra - ra.mean(axis=0)
    rb = rb - rb.mean(axis=0)
    den = np.sqrt((ra**2).sum(axis=0) * (rb**2).sum(axis=0))
    with np.errstate(divide="ignore", invalid="ignore"):
        return np.where(den > 0, (ra * rb).sum(axis=0) / den, np.nan)


def spearman_brown(r: np.ndarray) -> np.ndarray:
    with np.errstate(divide="ignore", invalid="ignore"):
        return np.where(1.0 + r > 1e-9, 2.0 * r / (1.0 + r), np.nan)


def balanced_partitions(
    weeks: Sequence[int] = STUDY_WEEKS,
) -> list[tuple[tuple[int, ...], tuple[int, ...]]]:
    """All distinct 3|3 splits of the six weeks (C(6,3)/2 = 10); half A always contains the first week."""
    ws = tuple(weeks)
    out = []
    for a in itertools.combinations(ws, len(ws) // 2):
        if ws[0] in a:
            out.append((a, tuple(w for w in ws if w not in a)))
    return out


def basic_ci(theta: np.ndarray | float, reps: np.ndarray, alpha: float = 0.05):
    """Basic (reverse-percentile) interval ``2 theta - q_hi, 2 theta - q_lo`` over axis 0 of ``reps``."""
    reps = np.asarray(reps, dtype=float)
    with np.errstate(all="ignore"):
        lo = _quiet(np.nanpercentile, reps, 100.0 * alpha / 2.0, axis=0)
        hi = _quiet(np.nanpercentile, reps, 100.0 * (1.0 - alpha / 2.0), axis=0)
    return 2.0 * np.asarray(theta, float) - hi, 2.0 * np.asarray(theta, float) - lo


def ols_slope(y: np.ndarray, cv: np.ndarray, ppg: np.ndarray, group: np.ndarray) -> float:
    """Coefficient of ``cv`` in OLS ``y ~ 1 + cv + ppg + group dummies`` (first group is the baseline)."""
    ok = np.isfinite(y) & np.isfinite(cv) & np.isfinite(ppg)
    if ok.sum() < 8:
        return float("nan")
    cols = [np.ones(ok.sum()), cv[ok], ppg[ok]]
    g = group[ok]
    for lab in sorted(set(g.tolist()))[1:]:
        cols.append((g == lab).astype(float))
    X = np.column_stack(cols)
    beta, *_ = np.linalg.lstsq(X, y[ok], rcond=None)
    return float(beta[1])


# ── the study object ──────────────────────────────────────────────────────────


@dataclass
class Universe:
    """Every 2026 player-row with at least two played weeks, as padded played-first arrays."""

    rows: np.ndarray  # row index into s26
    pids: list[str]
    Fp: np.ndarray  # (U, 6) fixed points of played weeks, padded
    Cp: np.ndarray  # (U, 6, K)
    wk: np.ndarray  # (U, 6) week position (0-5) of each played entry, -1 padded
    n: np.ndarray  # (U,) played weeks
    M: np.ndarray  # (U, 6) bool valid
    mF: np.ndarray  # (U,) mean fixed over played weeks
    mC: np.ndarray  # (U, K)
    group: np.ndarray  # (U,) str
    arch: np.ndarray  # (U,) str
    rostered: np.ndarray  # (U,) bool
    fa: np.ndarray  # (U,) bool: production-qualified free agent
    name: list[str]


class Study:
    """All arrays and indexes the experiment needs, built once from ``Inputs``."""

    def __init__(self, inputs: Inputs, cfg: Mapping[str, Any]):
        self.inputs = inputs
        self.cfg = cfg
        self.cards = build_cards(inputs.card, cfg)
        self.cfg_ids = list(self.cards)
        self.cidx = {c: i for i, c in enumerate(self.cfg_ids)}
        self.R = np.column_stack([rate_vector(c) for c in self.cards.values()])
        self.players: dict[str, Player] = {}
        rostered = {p for team in inputs.rosters for p in team}
        self.rostered = rostered
        for pid in set(inputs.s26.pids) | rostered:
            meta = inputs.directory.get(pid)
            if meta is None:
                continue
            pl = make_player(pid, meta, inputs.slots, inputs.fine_idx)
            if pl is not None:
                self.players[pid] = pl
        self.universe = self._build_universe()

    # -- universe ------------------------------------------------------------------------------

    def _build_universe(self) -> Universe:
        s = self.inputs.s26
        npl = s.n_played()
        rows = [i for i, p in enumerate(s.pids) if npl[i] >= 2 and p in self.players]
        U, K = len(rows), len(TENSOR_KEYS)
        Fp = np.zeros((U, 6))
        Cp = np.zeros((U, 6, K))
        wk = np.full((U, 6), -1, dtype=np.int64)
        n = np.zeros(U, dtype=np.int64)
        for u, r in enumerate(rows):
            js = np.where(s.status[r] == PLAYED)[0]
            m = len(js)
            n[u] = m
            Fp[u, :m] = s.fixed[r, js]
            Cp[u, :m, :] = s.counts[r, js, :]
            wk[u, :m] = js
        M = np.arange(6)[None, :] < n[:, None]
        mF = Fp.sum(axis=1) / n
        mC = Cp.sum(axis=1) / n[:, None]
        pids = [s.pids[r] for r in rows]
        group = np.array([self.players[p].group for p in pids])
        arch = np.array([self.players[p].arch for p in pids])
        ros = np.array([p in self.rostered for p in pids])
        late = np.array([(s.status[r, 3:6] == PLAYED).any() for r in rows])
        healthy = np.array([self.players[p].healthy for p in pids])
        fa = (~ros) & healthy & late
        return Universe(
            rows=np.array(rows),
            pids=pids,
            Fp=Fp,
            Cp=Cp,
            wk=wk,
            n=n,
            M=M,
            mF=mF,
            mC=mC,
            group=group,
            arch=arch,
            rostered=ros,
            fa=fa,
            name=[self.players[p].name for p in pids],
        )

    # -- pools ---------------------------------------------------------------------------------

    def pools(self, min_games: int) -> dict[str, np.ndarray]:
        u = self.universe
        out: dict[str, np.ndarray] = {}
        for g in IDP_GROUPS + OFFENSE_GROUPS:
            out[g] = np.where((u.group == g) & (u.n >= min_games))[0]
        for a in ARCHETYPES:
            out[a] = np.where((u.arch == a) & (u.n >= min_games))[0]
        return out

    def fa_rows(self) -> dict[str, np.ndarray]:
        u = self.universe
        return {g: np.where((u.group == g) & u.fa)[0] for g in IDP_GROUPS + OFFENSE_GROUPS}


# ── scheme W: week resampling within player ──────────────────────────────────────────────────


def draw_weeks(u: Universe, rng: np.random.Generator) -> tuple[np.ndarray, np.ndarray]:
    """One scheme-W replicate: each player's played weeks resampled with replacement.

    Deviations about the player's own observed mean are inflated by sqrt(n / (n - 1)) so a six-game
    sample is not under-dispersed (the plug-in variance of n draws is (n - 1) / n of the sample's).
    Because scoring is linear in the stat counts, inflating the counts inflates every configuration's
    points by the same factor, so all configurations are re-scored from the SAME resample (paired).
    """
    P = u.n.shape[0]
    j = np.minimum((rng.random((P, 6)) * u.n[:, None]).astype(np.int64), (u.n - 1)[:, None])
    Fb = np.take_along_axis(u.Fp, j, axis=1)
    Cb = np.take_along_axis(u.Cp, j[:, :, None], axis=1)
    kk = np.where(u.n > 1, np.sqrt(u.n / np.maximum(u.n - 1, 1)), 1.0)
    Fb = u.mF[:, None] + kk[:, None] * (Fb - u.mF[:, None])
    Cb = u.mC[:, None, :] + kk[:, None, None] * (Cb - u.mC[:, None, :])
    return Fb, Cb


def w_metrics(
    Fw: np.ndarray,
    Cw: np.ndarray,
    u: Universe,
    R: np.ndarray,
    pools: Mapping[str, np.ndarray],
    fas: Mapping[str, np.ndarray],
) -> dict[str, np.ndarray]:
    """Every scheme-W metric, vectorized over configurations.  Keys are ``"<pool>.<metric>"``."""
    C = R.shape[1]
    pts = Fw[:, :, None] + np.einsum("pjk,kc->pjc", Cw, R)
    Mf = u.M[:, :, None].astype(float)
    n = u.n
    mean = (pts * Mf).sum(axis=1) / n[:, None]
    dev = (pts - mean[:, None, :]) * Mf
    sd = np.sqrt((dev**2).sum(axis=1) / np.maximum(n - 1, 1)[:, None])
    with np.errstate(divide="ignore", invalid="ignore"):
        cv = np.where(mean > 0, sd / mean, np.nan)
    out: dict[str, np.ndarray] = {}
    for name, idx in pools.items():
        out[f"{name}.n"] = np.full(C, float(idx.size))
        if idx.size == 0:
            continue
        m = mean[idx]
        order = np.argsort(-m, axis=0, kind="stable")
        ms = np.take_along_axis(m, order, axis=0)
        t = tier_means(ms)
        for k, v in t.items():
            out[f"{name}.{k}"] = v
        for k, v in derived_tier_metrics(t).items():
            out[f"{name}.{k}"] = v
        top = min(STARTERS, idx.size)
        sds = np.take_along_axis(sd[idx], order, axis=0)[:top]
        cvs = np.take_along_axis(cv[idx], order, axis=0)[:top]
        full = idx.size >= STARTERS
        with np.errstate(all="ignore"):
            out[f"{name}.sd_med"] = (
                _quiet(np.nanmedian, sds, axis=0) if full else np.full(C, np.nan)
            )
            out[f"{name}.cv_med"] = (
                _quiet(np.nanmedian, cvs, axis=0) if full else np.full(C, np.nan)
            )
        out[f"{name}.icc"] = icc1(pts[idx], u.M[idx], n[idx], mean[idx])
        if name in fas:
            fa_idx = fas[name]
            repl = fa_level(mean[fa_idx]) if fa_idx.size else np.full(C, np.nan)
            out[f"{name}.repl_fa"] = repl
            with np.errstate(divide="ignore", invalid="ignore"):
                gap = t["starters"] - repl
                out[f"{name}.gap_fa"] = gap
                out[f"{name}.rel_gap_fa"] = np.where(t["starters"] > 0, gap / t["starters"], np.nan)
            out[f"{name}.n_fa"] = np.full(C, float(fa_idx.size))
        if name in IDP_GROUPS and full:
            arch_top = u.arch[idx][order[:STARTERS]]
            labels = ("DT", "EDGE", "ILB", "OLB", "CB", "S")
            for lab in labels:
                out[f"{name}.top36_{lab}"] = (arch_top == lab).sum(axis=0).astype(float)
    if all(g in pools and f"{g}.starters" in out for g in IDP_GROUPS):
        tot = sum(out[f"{g}.starters"] for g in IDP_GROUPS)
        for g in IDP_GROUPS:
            with np.errstate(divide="ignore", invalid="ignore"):
                out[f"{g}.share"] = out[f"{g}.starters"] / tot
    return out


# ── scheme P: player resampling for reliability ──────────────────────────────────────────────


@dataclass
class PairSet:
    """Paired per-player measures for one pool: ``A[s]`` / ``B[s]`` (n, C) for partition ``s``."""

    A: list[np.ndarray]
    B: list[np.ndarray]
    elig: list[np.ndarray]  # (n,) bool per partition
    n: int


def half_means(u: Universe, weeks_a: Sequence[int]) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Per universe row: n played weeks in the half, mean fixed, mean counts (K).

    ``weeks_a`` are WEEK NUMBERS (1-6); ``u.wk`` stores week POSITIONS (0-5), so they are converted.
    """
    inA = np.isin(u.wk, [STUDY_WEEKS.index(w) for w in weeks_a]) & u.M
    nA = inA.sum(axis=1)
    with np.errstate(divide="ignore", invalid="ignore"):
        fA = np.where(nA > 0, (u.Fp * inA).sum(axis=1) / np.maximum(nA, 1), 0.0)
        cA = np.where(
            nA[:, None] > 0, (u.Cp * inA[:, :, None]).sum(axis=1) / np.maximum(nA, 1)[:, None], 0.0
        )
    return nA, fA, cA


def build_split_pairs(
    u: Universe,
    idx: np.ndarray,
    R: np.ndarray,
    partitions: Sequence[tuple[tuple[int, ...], tuple[int, ...]]],
    *,
    events: bool = False,
) -> PairSet:
    A, B, E = [], [], []
    for wa, wb in partitions:
        nA, fA, cA = half_means(u, wa)
        nB, fB, cB = half_means(u, wb)
        if events:
            a = cA[idx][:, EVENT_COLS]
            b = cB[idx][:, EVENT_COLS]
        else:
            a = fA[idx][:, None] + cA[idx] @ R
            b = fB[idx][:, None] + cB[idx] @ R
        A.append(a)
        B.append(b)
        E.append((nA[idx] >= 2) & (nB[idx] >= 2))
    return PairSet(A, B, E, idx.size)


def pair_stats(ps: PairSet, draw: np.ndarray, *, oos: bool = True) -> dict[str, np.ndarray]:
    """Split-half reliability (Spearman-Brown, mean over partitions) and out-of-sample separation.

    ``draw`` indexes the pool (with replacement for a bootstrap replicate).  Out-of-sample separation:
    rank on one half, then take the held-out half's mean of the elite tier minus the average-starter tier
    (and the starters minus the first-bench tier), averaged over partitions and both directions.
    """
    r_all: list[np.ndarray] = []
    held: dict[str, list[np.ndarray]] = defaultdict(list)
    for A, B, el in zip(ps.A, ps.B, ps.elig):
        sel = draw[el[draw]]
        if sel.size < 8:
            continue
        a, b = A[sel], B[sel]
        r_all.append(spearman_brown(spearman_cols(a, b)))
        if oos:
            for x, y in ((a, b), (b, a)):
                order = np.argsort(-x, axis=0, kind="stable")
                t = tier_means(np.take_along_axis(y, order, axis=0))
                held["oos_p12"].append(t["p12"])
                held["oos_p25_36"].append(t["p25_36"])
                held["oos_sep"].append(t["p12"] - t["p25_36"])
                held["oos_gap"].append(t["starters"] - t["p37_48"])
    c = ps.A[0].shape[1]
    nan = np.full(c, np.nan)

    def avg(rows: list[np.ndarray]) -> np.ndarray:
        arr = np.array(rows)
        if arr.size == 0 or np.isnan(arr).all(axis=0).all():
            return nan
        with np.errstate(all="ignore"):
            return _quiet(np.nanmean, arr, axis=0)

    out = {"split_half": avg(r_all)}
    if oos:
        for k in ("oos_p12", "oos_p25_36", "oos_sep", "oos_gap"):
            out[k] = avg(held[k])
    return out


def build_yoy_pairs(
    s_a: SeasonData,
    s_b: SeasonData,
    pids: Sequence[str],
    R: np.ndarray,
    min_a: int,
    min_b: int,
    *,
    events: bool = False,
) -> PairSet:
    """Season-over-season pairs: conditional ppg of each season under every configuration."""

    def means(s: SeasonData, rows: np.ndarray):
        played = s.status[rows] == PLAYED
        n = played.sum(axis=1)
        f = (s.fixed[rows] * played).sum(axis=1) / np.maximum(n, 1)
        c = (s.counts[rows] * played[:, :, None]).sum(axis=1) / np.maximum(n, 1)[:, None]
        return n, f, c

    keep = [p for p in pids if p in s_a.index and p in s_b.index]
    ra = np.array([s_a.index[p] for p in keep], dtype=int)
    rb = np.array([s_b.index[p] for p in keep], dtype=int)
    na, fa_, ca = (
        means(s_a, ra) if keep else (np.zeros(0), np.zeros(0), np.zeros((0, len(TENSOR_KEYS))))
    )
    nb, fb, cb = (
        means(s_b, rb) if keep else (np.zeros(0), np.zeros(0), np.zeros((0, len(TENSOR_KEYS))))
    )
    ok = (na >= min_a) & (nb >= min_b)
    if events:
        a = ca[:, EVENT_COLS]
        b = cb[:, EVENT_COLS]
    else:
        a = fa_[:, None] + ca @ R
        b = fb[:, None] + cb @ R
    return PairSet([a[ok]], [b[ok]], [np.ones(int(ok.sum()), dtype=bool)], int(ok.sum()))


def yoy_stat(ps: PairSet, draw: np.ndarray, *, forward: bool = True) -> dict[str, np.ndarray]:
    """Season-over-season Spearman correlation and the FORWARD tier means.

    Forward: rank the pool on the earlier season's rescored ppg, then take the later season's mean of
    the earlier season's elite tier (and average-starter tier).  Unlike the within-2026 split, the
    training window is a full season, and the outcome is a different season.
    """
    c = ps.A[0].shape[1]
    nan = np.full(c, np.nan)
    if ps.n < 8:
        out = {"yoy": nan}
        if forward:
            out |= {"fwd_p12": nan, "fwd_p25_36": nan, "fwd_sep": nan, "fwd_gap": nan}
        return out
    a, b = ps.A[0][draw], ps.B[0][draw]
    out = {"yoy": spearman_cols(a, b)}
    if forward:
        order = np.argsort(-a, axis=0, kind="stable")
        t = tier_means(np.take_along_axis(b, order, axis=0))
        out["fwd_p12"] = t["p12"]
        out["fwd_p25_36"] = t["p25_36"]
        out["fwd_sep"] = t["p12"] - t["p25_36"]
        out["fwd_gap"] = t["starters"] - t["p37_48"]
    return out


# ── best ball ────────────────────────────────────────────────────────────────────────────────


@dataclass
class BBWorld:
    """Realized 2026 weeks 1-6 on the 12 current rosters, as arrays the exact solver can use.

    Entities are every rostered player plus every production-qualified free agent.  A rostered player
    with no stat line at all scores 0.0 every week (Sleeper's own awarded lineups do the same; Lane A /
    Lane B measured 72 of 72 team-week totals reproduced under that rule).  Only aggregates ever leave
    this object: no team, manager or per-roster number is published.
    """

    pids: list[str]
    names: list[str]
    group: list[str]
    arch: list[str]
    sig: list[frozenset[str]]
    sub: list[str | None]
    Fr: np.ndarray  # (E, 6) fixed points of played weeks
    Cr: np.ndarray  # (E, 6, K)
    Pm: np.ndarray  # (E, 6) bool played
    Am: np.ndarray  # (E, 6) bool counted (played or DNP)
    owner: list[int | None]
    fa: np.ndarray  # (E,) bool qualified free agent
    type_of: np.ndarray
    solvers: dict[str, LineupSolver]
    roster_idx: list[dict[str, list[int]]]
    pool_ents: dict[str, np.ndarray] = field(default_factory=dict)
    pool_ents_min: int = 4

    def weekly(self, rates: np.ndarray) -> np.ndarray:
        """(6, E) points under ``rates``; 0 in weeks the player did not play."""
        return (self.Fr + self.Cr @ rates).T


def build_bb_world(study: Study, min_games: int = 4) -> BBWorld:
    inp = study.inputs
    s = inp.s26
    team_of: dict[str, int] = {}
    for k, team in enumerate(inp.rosters):
        for p in team:
            team_of[p] = k
    u = study.universe
    fa_pids = {u.pids[i] for i in np.where(u.fa)[0]}
    pids = sorted(p for p in study.players if p in team_of or p in fa_pids)
    E = len(pids)
    K = len(TENSOR_KEYS)
    Fr = np.zeros((E, 6))
    Cr = np.zeros((E, 6, K))
    Pm = np.zeros((E, 6), dtype=bool)
    Am = np.zeros((E, 6), dtype=bool)
    for e, p in enumerate(pids):
        r = s.index.get(p)
        if r is None:
            continue
        Pm[e] = s.status[r] == PLAYED
        Am[e] = (s.status[r] == PLAYED) | (s.status[r] == DNP)
        Fr[e] = s.fixed[r]
        Cr[e] = s.counts[r]
    pl = [study.players[p] for p in pids]
    sub = [x.sub for x in pl]
    sigs: dict[str, set[frozenset[str]]] = {"off": set(), "idp": set()}
    for x in pl:
        if x.sub:
            sigs[x.sub].add(x.sig)
    off_slots, idp_slots = split_slots(inp.slots)
    solvers = {
        "off": LineupSolver(off_slots, sigs["off"]),
        "idp": LineupSolver(idp_slots, sigs["idp"]),
    }
    type_of = np.zeros(E, dtype=np.int64)
    for e, x in enumerate(pl):
        if x.sub:
            type_of[e] = solvers[x.sub].type_id[x.sig]
    roster_idx = [{"off": [], "idp": []} for _ in inp.rosters]
    pos = {p: e for e, p in enumerate(pids)}
    for p, k in team_of.items():
        e = pos.get(p)
        if e is not None and sub[e]:
            roster_idx[k][sub[e]].append(e)
    owner = [team_of.get(p) for p in pids]
    fa = np.array([p in fa_pids for p in pids])
    world = BBWorld(
        pids=pids,
        names=[x.name for x in pl],
        group=[x.group for x in pl],
        arch=[x.arch for x in pl],
        sig=[x.sig for x in pl],
        sub=sub,
        Fr=Fr,
        Cr=Cr,
        Pm=Pm,
        Am=Am,
        owner=owner,
        fa=fa,
        type_of=type_of,
        solvers=solvers,
        roster_idx=roster_idx,
        pool_ents_min=min_games,
    )
    nplay = Pm.sum(axis=1)
    pe: dict[str, np.ndarray] = {}
    grp = np.array(world.group)
    arc = np.array(world.arch)
    for g in IDP_GROUPS + OFFENSE_GROUPS:
        pe[g] = np.where((grp == g) & (nplay >= min_games))[0]
    for a in ARCHETYPES:
        pe[a] = np.where((arc == a) & (nplay >= min_games))[0]
    world.pool_ents = pe
    return world


def _pick_replacement(vals: list[tuple[str, np.ndarray]], mode: str = "median"):
    """VENDORED (Lane D).  The median-scoring candidate roster, ties by id."""
    ranked = sorted(vals, key=lambda t: (-float(t[1].mean()), t[0]))
    return ranked[len(ranked) // 2] if mode == "median" else ranked[0]


def bb_marginals(
    world: BBWorld,
    X: np.ndarray,
    A: np.ndarray,
    *,
    subs: Sequence[str] = ("idp", "off"),
    cand_ranks: Sequence[int] = (1, 2, 3, 4, 5),
) -> dict[str, np.ndarray]:
    """Best-ball marginal and its deterministic counterpart for every ROSTERED player, own roster.

    ``X`` (D, E) weekly points (0 where not played), ``A`` (D, E) counted weeks.  Marginal =
    mean over weeks of ``F(roster) - F(roster - player + replacement)``; the replacement is the
    median-scoring roster among the rank 1-5 production-qualified free agents (ranked by points per
    counted week) for each slot family the player can fill.  The deterministic counterpart puts every
    player at his expected points per counted week every week.  Entities never rostered get NaN.
    """
    D, E = X.shape
    counted = np.maximum(A.sum(axis=0), 1)
    mu = X.sum(axis=0) / counted
    Xext = np.vstack([X, mu[None, :]])
    marg_bb = np.full(E, np.nan)
    marg_det = np.full(E, np.nan)
    fa_idx = sorted(np.where(world.fa)[0].tolist(), key=lambda i: (-mu[i], world.pids[i]))
    fa_by_family: dict[str, list[int]] = defaultdict(list)
    for i in fa_idx:
        for g in world.sig[i]:
            fa_by_family[g].append(i)
    for sub in subs:
        solver = world.solvers[sub]
        for team in world.roster_idx:
            roster = team[sub]
            if not roster:
                continue
            f_with = solver.solve(Xext[:, roster], world.type_of[roster])
            for p in roster:
                base = [c for c in roster if c != p]
                cands: list[int] = []
                for g in sorted(world.sig[p]):
                    pool = [i for i in fa_by_family.get(g, []) if i != p]
                    for r in cand_ranks:
                        if 0 < r <= len(pool) and pool[r - 1] not in cands:
                            cands.append(pool[r - 1])
                if cands:
                    vals = []
                    for c in cands:
                        cols = base + [c]
                        vals.append(
                            (world.pids[c], solver.solve(Xext[:, cols], world.type_of[cols]))
                        )
                    wo_bb = _pick_replacement([(k, v[:D]) for k, v in vals])[1]
                    wo_det = _pick_replacement([(k, v[D:]) for k, v in vals])[1]
                else:
                    wo = (
                        solver.solve(Xext[:, base], world.type_of[base])
                        if base
                        else np.zeros(D + 1)
                    )
                    wo_bb, wo_det = wo[:D], wo[D:]
                marg_bb[p] = float((f_with[:D] - wo_bb).mean())
                marg_det[p] = float(f_with[D] - wo_det[0])
    return {"bb": marg_bb, "det": marg_det, "mu": mu}


def bb_pool_metrics(
    world: BBWorld,
    X: np.ndarray,
    Pm: np.ndarray,
    marg: Mapping[str, np.ndarray],
    pools: Mapping[str, np.ndarray],
) -> dict[str, float]:
    """Tier means of the best-ball marginal, ranking the pool by conditional ppg of ``X``."""
    nplay = np.maximum(Pm.sum(axis=0), 1)
    ppg = (X * Pm).sum(axis=0) / nplay
    out: dict[str, float] = {}
    mb, md = marg["bb"], marg["det"]
    for name, idx in pools.items():
        if idx.size == 0:
            continue
        order = idx[np.argsort(-ppg[idx], kind="stable")]
        for tier, (a, b) in {**TIER_BOUNDS, "starters": (0, STARTERS)}.items():
            if order.size < b:
                out[f"{name}.bb_{tier}"] = float("nan")
                out[f"{name}.det_{tier}"] = float("nan")
                out[f"{name}.n_ros_{tier}"] = 0.0
                continue
            mem = order[a:b]
            v = mb[mem]
            d = md[mem]
            out[f"{name}.bb_{tier}"] = (
                float(_quiet(np.nanmean, v)) if np.isfinite(v).any() else float("nan")
            )
            out[f"{name}.det_{tier}"] = (
                float(_quiet(np.nanmean, d)) if np.isfinite(d).any() else float("nan")
            )
            out[f"{name}.n_ros_{tier}"] = float(np.isfinite(v).sum())
    return out


def bb_player_table(
    world: BBWorld, X: np.ndarray, Pm: np.ndarray, marg: Mapping[str, np.ndarray]
) -> dict[str, np.ndarray]:
    """Per rostered IDP pool player: ppg, weekly CV, group code, premium and marginals (for scheme P)."""
    nplay = Pm.sum(axis=0)
    ok = [
        e
        for e in range(len(world.pids))
        if world.group[e] in IDP_GROUPS
        and nplay[e] >= world.pool_ents_min
        and np.isfinite(marg["bb"][e])
    ]
    ok_a = np.array(ok, dtype=int)
    if ok_a.size == 0:
        return {k: np.zeros(0) for k in ("ppg", "cv", "premium", "bb", "det")} | {
            "group": np.zeros(0, dtype=str)
        }
    vals = np.where(Pm, X, np.nan)
    ppg = _quiet(np.nanmean, vals[:, ok_a], axis=0)
    with np.errstate(all="ignore"):
        sd = _quiet(np.nanstd, vals[:, ok_a], axis=0, ddof=1)
        cv = np.where(ppg > 0, sd / ppg, np.nan)
    bb = marg["bb"][ok_a]
    det = marg["det"][ok_a]
    return {
        "ppg": ppg,
        "cv": cv,
        "premium": bb - det,
        "bb": bb,
        "det": det,
        "group": np.array([world.group[e] for e in ok_a]),
        "ent": ok_a,
    }


# ── parity: the rescoring identity against production and against Sleeper ────────────────────


def verify_parity(
    study: Study,
    stats26: Mapping[int, Mapping[str, Mapping[str, Any]]],
    matchups: Mapping[int, list[dict]],
    *,
    sample_cards: int = 8,
    seed: int = 20261026,
) -> dict[str, Any]:
    """Pin ``fixed + counts @ rates`` to the production scorer, and the actual card to Sleeper.

    1. Every 2026 played player-week, actual card: linear total vs ``compute_weekly_points``.
    2. A sample of the perturbed cards on a sample of player-weeks: linear vs ``compute_weekly_points``
       called with the perturbed card.
    3. Sleeper's own awarded ``players_points`` (league matchups) vs the linear total, every rostered
       player-week with a stat line; and the stacking check on sack plays carrying a TFL or QB hit.
    """
    inp = study.inputs
    s = inp.s26
    rates_actual = study.R[:, study.cidx["actual"]]
    lin_actual = s.fixed + s.counts @ rates_actual
    worst1, n1 = 0.0, 0
    for w_i, w in enumerate(s.weeks):
        for pid, line in (stats26.get(w) or {}).items():
            r = s.index.get(pid)
            if r is None or s.status[r, w_i] != PLAYED:
                continue
            meta = inp.directory[pid]
            pos = lineup_position(str(meta.get("position") or ""))
            res = compute_weekly_points(
                {**line, "player_id": pid, "season": 2026, "week": w},
                inp.card,
                position=pos,
                source="sleeper",
            )
            if res is None:
                continue
            worst1 = max(worst1, abs(res.fantasy_points - lin_actual[r, w_i]))
            n1 += 1
    rng = np.random.default_rng(seed)
    cand = [c for c in study.cfg_ids if c != "actual"]
    pick = [
        cand[i] for i in rng.choice(len(cand), size=min(sample_cards, len(cand)), replace=False)
    ]
    played_rows = [
        (r, j) for r in range(len(s.pids)) for j in range(len(s.weeks)) if s.status[r, j] == PLAYED
    ]
    take = rng.choice(len(played_rows), size=min(3000, len(played_rows)), replace=False)
    worst2, n2 = 0.0, 0
    for cid in pick:
        card = study.cards[cid]
        lin = s.fixed + s.counts @ study.R[:, study.cidx[cid]]
        for t in take:
            r, j = played_rows[t]
            pid = s.pids[r]
            w = s.weeks[j]
            line = stats26[w][pid]
            pos = lineup_position(str(inp.directory[pid].get("position") or ""))
            res = compute_weekly_points(
                {**line, "player_id": pid, "season": 2026, "week": w},
                card,
                position=pos,
                source="sleeper",
            )
            if res is None:
                continue
            worst2 = max(worst2, abs(res.fantasy_points - lin[r, j]))
            n2 += 1
    # 3. Sleeper's awarded points
    n3, worst3, within = 0, 0.0, 0
    stack_n, stack_ok, unstack_ok = 0, 0, 0
    kt, ks, kh = KIDX["idp_tkl_loss"], KIDX["idp_sack"], KIDX["idp_hit"]
    for w_i, w in enumerate(s.weeks):
        for m in matchups.get(w) or []:
            for pid, awarded in (m.get("players_points") or {}).items():
                r = s.index.get(pid)
                if r is None or s.status[r, w_i] != PLAYED:
                    continue
                d = abs(lin_actual[r, w_i] - float(awarded))
                n3 += 1
                worst3 = max(worst3, d)
                within += d <= 0.01
                c = s.counts[r, w_i]
                if c[ks] > 0 and (c[kt] > 0 or c[kh] > 0):
                    stack_n += 1
                    stack_ok += d <= 0.01
                    un = (
                        lin_actual[r, w_i]
                        - rates_actual[kt] * min(c[ks], c[kt])
                        - rates_actual[kh] * min(c[ks], c[kh])
                    )
                    unstack_ok += abs(un - float(awarded)) <= 0.01
    return {
        "actualCardVsProductionScorer": {"playerWeeks": n1, "maxAbsDiff": worst1},
        "perturbedCardsVsProductionScorer": {
            "cards": pick,
            "playerWeeksPerCard": int(len(take)),
            "comparisons": n2,
            "maxAbsDiff": worst2,
        },
        "vsSleeperAwarded": {
            "playerWeeks": n3,
            "within0.01": int(within),
            "maxAbsDiff": worst3,
        },
        "stacking": {
            "sackPlayerWeeksWithTflOrHit": stack_n,
            "awardedMatchesStacked": int(stack_ok),
            "awardedMatchesUnstacked": int(unstack_ok),
        },
    }


# ── descriptive blocks (observed data, actual card) ───────────────────────────────────────────


def component_profile(
    study: Study, pool: np.ndarray, tiers: Mapping[str, tuple[int, int]]
) -> dict[str, Any]:
    """Mean points-per-game by scoring component for tiers of a pool, under the actual card."""
    u = study.universe
    r = study.R[:, study.cidx["actual"]]
    ppg = u.mF + u.mC @ r
    order = pool[np.argsort(-ppg[pool], kind="stable")]
    out: dict[str, Any] = {}
    comps = {
        "tackles": ["idp_tkl_solo", "idp_tkl_ast"],
        "tfl": ["idp_tkl_loss"],
        "sack_and_yards": ["idp_sack", "idp_sack_yd"],
        "qb_hit": ["idp_hit"],
        "pass_defended": ["idp_pd"],
        "interception": ["idp_int", "idp_int_ret_yd"],
        "forced_fumble": ["idp_ff"],
        "fumble_recovery": ["idp_fum_rec", "idp_fum_ret_yd"],
        "defensive_td": ["idp_def_td"],
    }
    # TFL beyond the sacks (the sack play's own TFL is the stacked part)
    kt, ks = KIDX["idp_tkl_loss"], KIDX["idp_sack"]
    excess = np.maximum(u.Cp[:, :, kt] - u.Cp[:, :, ks], 0.0)
    excess_mean = (excess * u.M).sum(axis=1) / u.n
    for tname, (a, b) in tiers.items():
        mem = order[a:b] if order.size >= b else order[a:]
        if mem.size == 0:
            continue
        row: dict[str, Any] = {"n": int(mem.size), "ppg": float(ppg[mem].mean())}
        comp_total = 0.0
        for cname, keys in comps.items():
            pts = sum(float((u.mC[mem, KIDX[k]] * r[KIDX[k]]).mean()) for k in keys)
            row[f"{cname}_pts"] = pts
            comp_total += pts
        row["other_pts"] = float(ppg[mem].mean()) - comp_total
        for ev in ("idp_tkl_loss", "idp_sack", "idp_hit", "idp_pd", "idp_int"):
            row[f"{ev}_per_game"] = float(u.mC[mem, KIDX[ev]].mean())
        row["tfl_beyond_sacks_per_game"] = float(excess_mean[mem].mean())
        out[tname] = row
    return out


# ── evidence plumbing ────────────────────────────────────────────────────────────────────────


def _clean(x: Any) -> Any:
    if isinstance(x, (np.floating, float)):
        v = float(x)
        return None if not math.isfinite(v) else float(f"{v:.6g}")
    if isinstance(x, (np.integer,)):
        return int(x)
    if isinstance(x, np.ndarray):
        return [_clean(v) for v in x.tolist()]
    if isinstance(x, dict):
        return {str(k): _clean(v) for k, v in x.items()}
    if isinstance(x, (list, tuple)):
        return [_clean(v) for v in x]
    return x


# ── estimates with replicates ────────────────────────────────────────────────────────────────


class Est:
    """A point estimate and its bootstrap replicates, closed under + - * /.

    Contrasts are built from these, so a contrast's replicates are the replicate-wise difference of its
    parts: paired by construction when both parts came from the same resamples.
    """

    __slots__ = ("obs", "reps")

    def __init__(self, obs: float, reps: np.ndarray | None = None):
        self.obs = float(obs)
        self.reps = None if reps is None else np.asarray(reps, dtype=float)

    def _bin(self, other: Any, op) -> "Est":
        o = other.obs if isinstance(other, Est) else float(other)
        r = None
        if self.reps is not None:
            if isinstance(other, Est):
                if other.reps is None or other.reps.shape != self.reps.shape:
                    raise ValueError("contrast mixes estimates from different resampling schemes")
                r = op(self.reps, other.reps)
            else:
                r = op(self.reps, float(other))
        with np.errstate(divide="ignore", invalid="ignore"):
            return Est(op(self.obs, o), r)

    def __add__(self, other):
        return self._bin(other, lambda a, b: a + b)

    def __sub__(self, other):
        return self._bin(other, lambda a, b: a - b)

    def __mul__(self, other):
        return self._bin(other, lambda a, b: a * b)

    def __truediv__(self, other):
        return self._bin(other, lambda a, b: a / b)

    def ci(self, alpha: float = 0.05) -> tuple[float, float]:
        if self.reps is None:
            return float("nan"), float("nan")
        lo, hi = basic_ci(self.obs, self.reps, alpha)
        return float(lo), float(hi)


@dataclass
class Results:
    """Observed metrics and replicates, ``key -> (C,)`` and ``key -> (B, C)``, over the configurations."""

    obs: dict[str, np.ndarray]
    reps: dict[str, np.ndarray]
    cidx: dict[str, int]

    def est(self, key: str, cid: str) -> Est:
        i = self.cidx[cid]
        return Est(self.obs[key][i], self.reps[key][:, i] if key in self.reps else None)

    def point(self, key: str, cid: str) -> float:
        return float(self.obs[key][self.cidx[cid]])


# ── runs ─────────────────────────────────────────────────────────────────────────────────────


def run_w(
    study: Study, reps: int, seed: int, min_games: int = 4, *, bootstrap: bool = True
) -> Results:
    u = study.universe
    pools = study.pools(min_games)
    fas = study.fa_rows()
    obs = w_metrics(u.Fp, u.Cp, u, study.R, pools, fas)
    store: dict[str, np.ndarray] = {}
    if bootstrap:
        store = {k: np.empty((reps, study.R.shape[1])) for k in obs}
        for b in range(reps):
            rng = np.random.default_rng([seed, 1, b])
            Fb, Cb = draw_weeks(u, rng)
            mb = w_metrics(Fb, Cb, u, study.R, pools, fas)
            for k in obs:
                store[k][b] = mb.get(k, np.nan)
    return Results(obs, store, study.cidx)


SPLIT_POOLS = IDP_GROUPS + OFFENSE_GROUPS + ("EDGE", "DT", "ILB", "CB", "S")


def group_of(directory: Mapping[str, Mapping[str, Any]], pid: str) -> str:
    return lineup_position(str((directory.get(pid) or {}).get("position") or ""))


def build_p_pairs(study: Study) -> dict[str, tuple[str, PairSet]]:
    inp = study.inputs
    u = study.universe
    R = study.R
    pools = study.pools(4)
    parts = balanced_partitions()
    pairs: dict[str, tuple[str, PairSet]] = {}
    for name in SPLIT_POOLS:
        pairs[f"split:{name}"] = ("split", build_split_pairs(u, pools[name], R, parts))
    for g in IDP_GROUPS:
        pairs[f"esplit:{g}"] = ("esplit", build_split_pairs(u, pools[g], R, parts, events=True))
    by_group = {
        g: [p for p in inp.s25.pids if group_of(inp.directory, p) == g]
        for g in IDP_GROUPS + OFFENSE_GROUPS
    }
    for g in IDP_GROUPS + OFFENSE_GROUPS:
        pairs[f"yoy2425:{g}"] = ("yoy", build_yoy_pairs(inp.s24, inp.s25, by_group[g], R, 8, 8))
        pairs[f"yoy2526:{g}"] = ("yoy", build_yoy_pairs(inp.s25, inp.s26, by_group[g], R, 8, 4))
    for g in IDP_GROUPS:
        pairs[f"eyoy2425:{g}"] = (
            "eyoy",
            build_yoy_pairs(inp.s24, inp.s25, by_group[g], R, 8, 8, events=True),
        )
    # Archetype pools for the season-over-season pairs.  Archetype comes from provenance fields for
    # the 2025 roster, never from a 2026 roster, so a player who is not on a 2026 roster is not dropped
    # (that would condition the pool on the future).
    by_arch: dict[str, list[str]] = defaultdict(list)
    for pid in inp.s25.pids:
        if group_of(inp.directory, pid) not in IDP_GROUPS:
            continue
        pl = make_player(pid, inp.directory[pid], inp.slots, inp.fine_idx)
        if pl is not None and pl.arch in ARCHETYPES:
            by_arch[pl.arch].append(pid)
    for a in ("EDGE", "DT", "ILB", "CB", "S"):
        pairs[f"yoy2425:{a}"] = ("yoy", build_yoy_pairs(inp.s24, inp.s25, by_arch[a], R, 8, 8))
        pairs[f"yoy2526:{a}"] = ("yoy", build_yoy_pairs(inp.s25, inp.s26, by_arch[a], R, 8, 4))
    return pairs


def eval_pair(kind: str, ps: PairSet, draw: np.ndarray) -> dict[str, np.ndarray]:
    if kind in ("split", "esplit"):
        return pair_stats(ps, draw, oos=(kind == "split"))
    return yoy_stat(ps, draw, forward=(kind == "yoy"))


_G: dict[str, Any] = {}


def _init_worker(payload: dict[str, Any]) -> None:
    _G.clear()
    _G.update(payload)


def _p_chunk(args: tuple[str, int, int]) -> tuple[str, int, dict[str, np.ndarray]]:
    key, start, stop = args
    kind, ps = _G["pairs"][key]
    seed = _G["seed"]
    pid = _G["pair_ids"][key]
    out: dict[str, list[np.ndarray]] = defaultdict(list)
    for b in range(start, stop):
        rng = np.random.default_rng([seed, 2, b, pid])
        draw = rng.integers(0, ps.n, ps.n) if ps.n else np.zeros(0, dtype=int)
        for m, v in eval_pair(kind, ps, draw).items():
            out[m].append(v)
    return key, start, {m: np.vstack(v) for m, v in out.items()}


def run_p(study: Study, reps: int, seed: int, workers: int) -> tuple[Results, dict[str, int]]:
    pairs = build_p_pairs(study)
    pair_ids = {k: i for i, k in enumerate(pairs)}
    obs: dict[str, np.ndarray] = {}
    for key, (kind, ps) in pairs.items():
        for m, v in eval_pair(kind, ps, np.arange(ps.n)).items():
            obs[f"{key}|{m}"] = v
    store = {k: np.empty((reps, v.shape[0])) for k, v in obs.items()}
    chunk = 25
    tasks = [(key, s, min(s + chunk, reps)) for key in pairs for s in range(0, reps, chunk)]
    payload = {"pairs": pairs, "seed": seed, "pair_ids": pair_ids}
    if workers > 1:
        with ProcessPoolExecutor(
            max_workers=workers, initializer=_init_worker, initargs=(payload,)
        ) as ex:
            results = list(ex.map(_p_chunk, tasks, chunksize=1))
    else:
        _init_worker(payload)
        results = [_p_chunk(t) for t in tasks]
    for key, start, got in results:
        for m, arr in got.items():
            store[f"{key}|{m}"][start : start + arr.shape[0]] = arr
    return Results(obs, store, study.cidx), {k: ps.n for k, (_, ps) in pairs.items()}


# -- best ball runs --------------------------------------------------------------------------------


def merged_marginals(world: BBWorld, X: np.ndarray, A: np.ndarray, off: dict | None = None):
    """IDP marginals for this ``X`` merged with the (configuration-independent) offense marginals."""
    idp = bb_marginals(world, X, A, subs=("idp",))
    off = off if off is not None else bb_marginals(world, X, A, subs=("off",))
    return {
        "bb": np.where(np.isnan(idp["bb"]), off["bb"], idp["bb"]),
        "det": np.where(np.isnan(idp["det"]), off["det"], idp["det"]),
        "mu": idp["mu"],
    }, off


def _bb_rep(b: int) -> dict[str, dict[str, float]]:
    """One scheme-B replicate: resample the six weeks as blocks, re-run the whole procedure."""
    world: BBWorld = _G["world"]
    rng = np.random.default_rng([_G["seed"], 3, b])
    wk = rng.integers(0, 6, 6)
    out: dict[str, dict[str, float]] = {}
    off = None
    for cid, rates in _G["key_rates"].items():
        X = world.weekly(rates)[wk]
        A = world.Am.T[wk]
        Pm = world.Pm.T[wk]
        marg, off = merged_marginals(world, X, A, off)
        out[cid] = bb_pool_metrics(world, X, Pm, marg, world.pool_ents)
    return out


def run_bb(study: Study, seed: int, reps: int, workers: int, key_configs: Sequence[str]):
    """Best-ball marginals for every configuration, and scheme-B replicates for the key ones."""
    world = build_bb_world(study)
    A = world.Am.T
    Pm = world.Pm.T
    metrics: dict[str, dict[str, float]] = {}
    tables: dict[str, dict[str, np.ndarray]] = {}
    off = None
    for cid in study.cfg_ids:
        X = world.weekly(study.R[:, study.cidx[cid]])
        marg, off = merged_marginals(world, X, A, off)
        metrics[cid] = bb_pool_metrics(world, X, Pm, marg, world.pool_ents)
        tables[cid] = bb_player_table(world, X, Pm, marg)
    key_rates = {cid: study.R[:, study.cidx[cid]] for cid in key_configs}
    rep_store: dict[str, dict[str, np.ndarray]] = {}
    if reps > 0:
        payload = {"world": world, "seed": seed, "key_rates": key_rates}
        if workers > 1:
            with ProcessPoolExecutor(
                max_workers=workers, initializer=_init_worker, initargs=(payload,)
            ) as ex:
                got = list(ex.map(_bb_rep, range(reps), chunksize=4))
        else:
            _init_worker(payload)
            got = [_bb_rep(b) for b in range(reps)]
        for cid in key_configs:
            keys = metrics[cid].keys()
            rep_store[cid] = {k: np.array([g[cid].get(k, np.nan) for g in got]) for k in keys}
    return world, metrics, tables, rep_store


def oos_premium_tables(
    study: Study, world: BBWorld, cid: str, base: Mapping[str, np.ndarray]
) -> list[dict[str, np.ndarray]]:
    """Ex-ante tables: CV and ppg from one half of the weeks, best-ball premium from the other.

    Ten balanced partitions, both directions: twenty tables over the SAME players (the rostered IDP
    pool of the full window, ``base["ent"]``), so one player-resampling draw is valid across all.
    """
    rates = study.R[:, study.cidx[cid]]
    full = world.weekly(rates)
    ent = base["ent"]
    out = []
    for wa, wb in balanced_partitions():
        for ha, hb in ((wa, wb), (wb, wa)):
            ia = [w - 1 for w in ha]
            ib = [w - 1 for w in hb]
            Xa, Pa = full[ia], world.Pm.T[ia]
            Xb, Ab = full[ib], world.Am.T[ib]
            idp_b = bb_marginals(world, Xb, Ab, subs=("idp",))
            vals = np.where(Pa, Xa, np.nan)
            na = Pa.sum(axis=0)
            with np.errstate(all="ignore"):
                ppg_a = _quiet(np.nanmean, vals, axis=0)
                sd_a = _quiet(np.nanstd, vals, axis=0, ddof=1)
                cv_a = np.where((ppg_a > 0) & (na >= 2), sd_a / ppg_a, np.nan)
            out.append(
                {
                    "premium_b": (idp_b["bb"] - idp_b["det"])[ent],
                    "cv_a": cv_a[ent],
                    "ppg_a": ppg_a[ent],
                }
            )
    return out


def q4_estimates(
    tables: Mapping[str, Mapping[str, np.ndarray]],
    oos: Mapping[str, list[dict[str, np.ndarray]]],
    cids: Sequence[str],
    reps: int,
    seed: int,
) -> dict[str, dict[str, Est]]:
    """Q4.1-Q4.3 per configuration by player resampling (the same draw for every configuration)."""
    ref = tables["actual"]
    n = ref["ppg"].shape[0]
    for cid in cids:
        if not np.array_equal(tables[cid]["ent"], ref["ent"]):
            raise AssertionError("the rostered IDP pool differs between configurations")
    group = ref["group"]

    def stats(cid: str, draw: np.ndarray) -> dict[str, float]:
        t = tables[cid]
        det_d, bb_d = t["det"][draw], t["bb"][draw]
        start = det_d > 1e-9  # players who start in the deterministic lineup (no bench ties at 0)
        d = {
            "q41": ols_slope(t["premium"][draw], t["cv"][draw], t["ppg"][draw], group[draw]),
            "q43": float(spearman_cols(det_d[:, None], bb_d[:, None])[0]),
            "q43_start": (
                float(spearman_cols(det_d[start][:, None], bb_d[start][:, None])[0])
                if start.sum() >= 8
                else float("nan")
            ),
        }
        if cid in oos:
            sl = [
                ols_slope(o["premium_b"][draw], o["cv_a"][draw], o["ppg_a"][draw], group[draw])
                for o in oos[cid]
            ]
            d["q42"] = float(_quiet(np.nanmean, sl))
        return d

    obs = {cid: stats(cid, np.arange(n)) for cid in cids}
    store: dict[str, dict[str, list[float]]] = {cid: defaultdict(list) for cid in cids}
    for b in range(reps):
        draw = np.random.default_rng([seed, 4, b]).integers(0, n, n)
        for cid in cids:
            for k, v in stats(cid, draw).items():
                store[cid][k].append(v)
    return {cid: {k: Est(v, np.array(store[cid][k])) for k, v in obs[cid].items()} for cid in cids}


# ── contrasts, supplementary estimates, descriptive blocks ───────────────────────────────────


@dataclass
class Ctx:
    """Everything a contrast reads: scheme-W and scheme-P results, scheme-B estimates, Q4 estimates."""

    W: Results
    P: Results
    bb_obs: dict[str, dict[str, float]]
    bb_reps: dict[str, dict[str, np.ndarray]]
    q4: dict[str, dict[str, Est]]

    def B(self, key: str, cid: str) -> Est:
        return Est(self.bb_obs[cid][key], self.bb_reps[cid][key])


def gain(res: Results, key: str, lo_cid: str, hi_cid: str) -> Est:
    """``hi_cid`` minus ``lo_cid`` of one metric: paired, both come from the same resamples."""
    return res.est(key, hi_cid) - res.est(key, lo_cid)


def contrast_definitions(ctx: Ctx) -> dict[str, tuple[str, Est]]:
    """id -> (scheme, estimate).  The ids and families are fixed by the pre-registered config."""
    W, P = ctx.W, ctx.P
    t0, t2 = "oat:tfl:x0", "oat:tfl:x2"
    p0, p2 = "oat:pd:x0", "oat:pd:x2"
    out: dict[str, tuple[str, Est]] = {}
    out["Q1.1"] = ("W", gain(W, "DT.p12", t0, t2) - gain(W, "EDGE.p12", t0, t2))
    out["Q1.2"] = ("W", gain(W, "DT.p25_36", t0, t2) - gain(W, "EDGE.p25_36", t0, t2))
    out["Q1.3"] = ("W", gain(W, "DL.top36_DT", t0, t2))
    out["Q2.1"] = ("W", gain(W, "CB.p12", p0, p2) - gain(W, "CB.p37_48", p0, p2))
    out["Q2.2"] = ("W", gain(W, "CB.sep", p0, p2))
    out["Q2.3"] = ("P", gain(P, "split:CB|oos_sep", p0, p2))
    out["Q2.4"] = ("P", gain(P, "split:CB|split_half", p0, p2))
    out["Q2.5"] = ("W", gain(W, "CB.p12", p0, p2) - gain(W, "S.p12", p0, p2))
    for tag, other in (("a", "DL"), ("b", "DB")):
        out[f"Q3.1{tag}"] = (
            "W",
            W.est("LB.rel_gap_fa", "actual") - W.est(f"{other}.rel_gap_fa", "actual"),
        )
        out[f"Q3.2{tag}"] = (
            "W",
            W.est("LB.rel_gap_rank", "actual") - W.est(f"{other}.rel_gap_rank", "actual"),
        )
        out[f"Q3.3{tag}"] = ("W", W.est("LB.cv_med", "actual") - W.est(f"{other}.cv_med", "actual"))
        out[f"Q3.4{tag}"] = (
            "B",
            ctx.B("LB.bb_starters", "actual") - ctx.B(f"{other}.bb_starters", "actual"),
        )
    out["Q4.1"] = ("P", ctx.q4["actual"]["q41"])
    out["Q4.2"] = ("P", ctx.q4["actual"]["q42"])
    out["Q4.3"] = ("P", ctx.q4["actual"]["q43"])
    out["Q4.4"] = ("P", ctx.q4["ref:big_play"]["q41"] - ctx.q4["ref:tackle_heavy_balanced"]["q41"])
    return out


def replicate_bias(e: Est) -> float:
    """Mean of the replicates minus the observed value: the inflation re-ranking adds to a selected tier."""
    return float("nan") if e.reps is None else float(_quiet(np.nanmean, e.reps)) - e.obs


def contrast_family(cid: str) -> str:
    return cid.split(".")[0]


def evaluate_contrasts(ctx: Ctx, cfg: Mapping[str, Any]) -> dict[str, dict[str, Any]]:
    defs = contrast_definitions(ctx)
    fam_size = Counter(contrast_family(k) for k in defs)
    text = {
        item["id"]: item["definition"]
        for q in cfg["analysis"]["contrasts"].values()
        for item in q["items"]
    }
    out: dict[str, dict[str, Any]] = {}
    for cid, (scheme, est) in defs.items():
        m = fam_size[contrast_family(cid)]
        lo, hi = est.ci(0.05)
        blo, bhi = est.ci(0.05 / m)
        out[cid] = {
            "family": contrast_family(cid),
            "scheme": scheme,
            "definition": text.get(cid.rstrip("ab"), text.get(cid, "")),
            "estimate": est.obs,
            "bias": replicate_bias(est),
            "ci95": [lo, hi],
            "ciBonferroni": [blo, bhi],
            "familySize": m,
            "replicates": 0 if est.reps is None else int(est.reps.shape[0]),
            "excludesZero95": bool(np.isfinite(lo) and (lo > 0 or hi < 0)),
            "excludesZeroBonferroni": bool(np.isfinite(blo) and (blo > 0 or bhi < 0)),
        }
    return out


def supplementary_estimates(ctx: Ctx) -> dict[str, dict[str, Any]]:
    """Exploratory estimates added AFTER the pre-registered families were run.  Labelled as such.

    The in-sample elite-tier means carry a selection effect that the pre-registered week bootstrap
    cannot remove, so the held-out (within-2026 split) and forward (season-over-season) versions of the
    TFL and PD responses are reported beside them.
    """
    W, P = ctx.W, ctx.P
    out: dict[str, Est] = {}
    for tag, lo, hi, pools in (
        ("tfl", "oat:tfl:x0", "oat:tfl:x2", ("DL", "DT", "EDGE")),
        ("pd", "oat:pd:x0", "oat:pd:x2", ("DB", "CB", "S")),
    ):
        for pool in pools:
            for metric in ("p12", "p25_36", "p37_48", "starters", "sep", "gap_rank"):
                out[f"{tag}.W.{pool}.{metric}"] = gain(W, f"{pool}.{metric}", lo, hi)
            if f"split:{pool}|oos_p12" in P.obs:
                for metric in ("oos_p12", "oos_p25_36", "oos_sep", "split_half"):
                    out[f"{tag}.P.{pool}.{metric}"] = gain(P, f"split:{pool}|{metric}", lo, hi)
            for span in ("yoy2425", "yoy2526"):
                key = f"{span}:{pool}|fwd_p12"
                if key in P.obs:
                    for metric in ("fwd_p12", "fwd_p25_36", "fwd_sep", "yoy"):
                        out[f"{tag}.{span}.{pool}.{metric}"] = gain(
                            P, f"{span}:{pool}|{metric}", lo, hi
                        )
    for tag, lo, hi, pools in (
        ("tfl", "oat:tfl:x0", "oat:tfl:x2", ("DL", "DT", "EDGE")),
        ("pd", "oat:pd:x0", "oat:pd:x2", ("DB", "CB", "S")),
    ):
        for pool in pools:
            for metric in ("bb_p12", "bb_p25_36", "bb_starters"):
                out[f"{tag}.B.{pool}.{metric}"] = ctx.B(f"{pool}.{metric}", hi) - ctx.B(
                    f"{pool}.{metric}", lo
                )
    res = {}
    for k, e in out.items():
        lo_, hi_ = e.ci(0.05)
        res[k] = {"estimate": e.obs, "bias": replicate_bias(e), "ci95": [lo_, hi_]}
    return res


def cross_position(ctx: Ctx, key_cfgs: Sequence[str]) -> dict[str, Any]:
    """Elite-tier utility of each IDP group beside each offense position, per key configuration.

    Two ratios, same procedure for every position: the best-ball marginal of the elite tier (scheme B),
    and the elite tier's points per game over the free-agent replacement level (scheme W; QB has no
    qualified free agent, so no points-over-replacement ratio exists for QB).  Raw fantasy-point
    utility: NOT a dynasty value, NOT a market price.
    """
    out: dict[str, Any] = {}
    for cid in key_cfgs:
        row: dict[str, Any] = {}
        for g in IDP_GROUPS:
            gb = ctx.B(f"{g}.bb_p12", cid)
            gpar = ctx.W.est(f"{g}.p12", cid) - ctx.W.est(f"{g}.repl_fa", cid)
            r: dict[str, Any] = {
                "bbElite": triple(gb),
                "parElite": triple(gpar),
            }
            for o in OFFENSE_GROUPS:
                ob = ctx.B(f"{o}.bb_p12", cid)
                r[f"bbRatioTo{o}"] = triple(gb / ob)
                if o != "QB":
                    opar = ctx.W.est(f"{o}.p12", cid) - ctx.W.est(f"{o}.repl_fa", cid)
                    r[f"parRatioTo{o}"] = triple(gpar / opar)
            row[g] = r
        out[cid] = row
    out["offense"] = {
        o: {
            "bbElite": triple(ctx.B(f"{o}.bb_p12", "actual")),
            "parElite": (
                triple(ctx.W.est(f"{o}.p12", "actual") - ctx.W.est(f"{o}.repl_fa", "actual"))
                if o != "QB"
                else None
            ),
        }
        for o in OFFENSE_GROUPS
    }
    return out


def deltas_vs_actual(
    W: Results, cfg_ids: Sequence[str]
) -> dict[str, dict[str, dict[str, list[float]]]]:
    """Every configuration minus the actual card on the headline metrics, with paired intervals."""
    pools = [k.split(".")[0] for k in W.obs if k.endswith(".p12")]
    metrics = ("p12", "p25_36", "starters", "sep", "gap_rank", "gap_fa", "share")
    out: dict[str, dict[str, dict[str, list[float]]]] = {}
    for cid in cfg_ids:
        if cid == "actual":
            continue
        out[cid] = {}
        for pool in pools:
            row = {}
            for m in metrics:
                key = f"{pool}.{m}"
                if key not in W.obs:
                    continue
                e = gain(W, key, "actual", cid)
                lo, hi = e.ci(0.05)
                row[m] = [e.obs, lo, hi]
            out[cid][pool] = row
    return out


def named_movers(study: Study, pool: str, lo_cid: str, hi_cid: str, k: int = 6) -> dict[str, Any]:
    """The players whose rank in ``pool`` moves most between two configurations (NFL names only)."""
    u = study.universe
    idx = study.pools(4)[pool]
    ppg = u.mF[:, None] + u.mC @ study.R
    a = ppg[idx, study.cidx[lo_cid]]
    b = ppg[idx, study.cidx[hi_cid]]
    ra = rankdata(-a, method="min")
    rb = rankdata(-b, method="min")
    move = ra - rb  # positive = moves up when going lo -> hi
    order = np.argsort(-move, kind="stable")

    def row(i: int) -> dict[str, Any]:
        return {
            "name": u.name[idx[i]],
            "archetype": str(u.arch[idx[i]]),
            f"rank_{lo_cid}": int(ra[i]),
            f"rank_{hi_cid}": int(rb[i]),
            f"ppg_{lo_cid}": float(a[i]),
            f"ppg_{hi_cid}": float(b[i]),
        }

    return {
        "pool": pool,
        "from": lo_cid,
        "to": hi_cid,
        "risers": [row(i) for i in order[:k]],
        "fallers": [row(i) for i in order[::-1][:k]],
    }


def pool_card_rates(card: Mapping[str, float], cfg: Mapping[str, Any]) -> dict[str, float]:
    return {sk: float(card.get(ck, 0.0)) for sk, ck in cfg["studyKeys"].items()}


def point_w_contrasts(W: Results) -> dict[str, float]:
    """Point estimates of the W-scheme contrasts for a bootstrap-free Results (stability variants)."""
    t0, t2 = "oat:tfl:x0", "oat:tfl:x2"
    p0, p2 = "oat:pd:x0", "oat:pd:x2"

    def g(key, lo, hi):
        return W.point(key, hi) - W.point(key, lo)

    return {
        "Q1.1": g("DT.p12", t0, t2) - g("EDGE.p12", t0, t2),
        "Q1.2": g("DT.p25_36", t0, t2) - g("EDGE.p25_36", t0, t2),
        "Q1.3": g("DL.top36_DT", t0, t2),
        "Q2.1": g("CB.p12", p0, p2) - g("CB.p37_48", p0, p2),
        "Q2.2": g("CB.sep", p0, p2),
        "Q2.5": g("CB.p12", p0, p2) - g("S.p12", p0, p2),
    }


# ── evidence assembly ────────────────────────────────────────────────────────────────────────


def git_sha() -> str:
    try:
        return subprocess.check_output(
            ["git", "rev-parse", "HEAD"], cwd=REPO, text=True, stderr=subprocess.DEVNULL
        ).strip()
    except Exception:  # noqa: BLE001 - provenance only
        return "UNKNOWN"


def triple(e: Est) -> list[float]:
    lo, hi = e.ci(0.05)
    return [e.obs, lo, hi]


def run_all(args: argparse.Namespace) -> dict[str, Any]:
    t_start = time.time()
    cfg = load_config()
    seed = int(cfg["analysis"]["seed"])
    reps_w = args.reps_w or cfg["analysis"]["bootstrap"]["replicates"]["W"]
    reps_p = args.reps_p or cfg["analysis"]["bootstrap"]["replicates"]["P"]
    reps_b = (
        args.reps_b if args.reps_b is not None else cfg["analysis"]["bootstrap"]["replicates"]["B"]
    )
    key_cfgs = list(cfg["analysis"]["keyConfigs"])
    inp = load_inputs(offline=args.offline)
    if inp.fingerprint != cfg["league"]["pinnedScoringFingerprint"]:
        raise RuntimeError(f"scoring fingerprint moved: {inp.fingerprint}")
    for k, v in cfg["expectedActualIdpBlock"].items():
        if abs(inp.card.get(k, 0.0) - v) > 1e-9:
            raise RuntimeError(f"actual card differs from the pre-registered block at {k}")
    for season, rid in (("2025", "league_2025_actual"), ("2024", "league_2024_actual")):
        blk = next(r for r in cfg["reference"] if r["id"] == rid)["idpBlock"]
        for k, v in blk.items():
            if abs(inp.prior_cards[season].get(k, 0.0) - v) > 1e-9:
                raise RuntimeError(f"{rid} differs from the fetched {season} league card at {k}")
    study = Study(inp, cfg)
    fetch = Fetcher(offline=True)
    lid = cfg["league"]["sleeperLeagueId"]
    stats26 = {w: fetch.sleeper(f"stats/nfl/regular/2026/{w}") for w in STUDY_WEEKS}
    matchups = {w: fetch.sleeper(f"league/{lid}/matchups/{w}") for w in STUDY_WEEKS}
    parity = verify_parity(study, stats26, matchups, seed=seed)
    print(f"[{time.time() - t_start:6.0f}s] parity {parity['vsSleeperAwarded']}", flush=True)

    W = run_w(study, reps_w, seed)
    print(f"[{time.time() - t_start:6.0f}s] scheme W done ({reps_w})", flush=True)
    P, pair_n = run_p(study, reps_p, seed, args.workers)
    print(f"[{time.time() - t_start:6.0f}s] scheme P done ({reps_p})", flush=True)
    world, bb_obs, bb_tables, bb_reps = run_bb(study, seed, reps_b, args.workers, key_cfgs)
    print(f"[{time.time() - t_start:6.0f}s] best ball done ({reps_b})", flush=True)

    # ex-ante premium tables for the configurations Q4 reads
    oos = {cid: oos_premium_tables(study, world, cid, bb_tables["actual"]) for cid in key_cfgs}
    print(f"[{time.time() - t_start:6.0f}s] ex-ante premium tables done", flush=True)
    q4 = q4_estimates(bb_tables, oos, study.cfg_ids, reps_p, seed)

    if reps_b > 0:
        ctx = Ctx(W, P, bb_obs, bb_reps, q4)
        contrasts = evaluate_contrasts(ctx, cfg)
        supp = supplementary_estimates(ctx)
        xpos = cross_position(ctx, key_cfgs)
    else:
        contrasts, supp, xpos = {}, {}, {}

    # per-configuration tables ---------------------------------------------------------------
    configs: dict[str, Any] = {}
    for cid in study.cfg_ids:
        block: dict[str, Any] = {"W": {}, "P": {}, "BB": {}}
        for key in W.obs:
            pool, _, metric = key.partition(".")
            e = W.est(key, cid)
            bias = replicate_bias(e)
            block["W"].setdefault(pool, {})[metric] = triple(e) + [bias]
        for key in P.obs:
            if key.startswith(("esplit", "eyoy")):
                continue
            pk, _, metric = key.partition("|")
            kind, _, pool = pk.partition(":")
            block["P"].setdefault(kind, {}).setdefault(pool, {})[metric] = triple(P.est(key, cid))
        for key, val in bb_obs[cid].items():
            pool, _, metric = key.partition(".")
            if cid in bb_reps:
                ci = Est(val, bb_reps[cid][key]).ci(0.05)
                block["BB"].setdefault(pool, {})[metric] = [val, ci[0], ci[1]]
            else:
                block["BB"].setdefault(pool, {})[metric] = [val]
        q = q4[cid]
        block["Q4"] = {k: triple(v) if cid in key_cfgs else [v.obs] for k, v in q.items()}
        configs[cid] = block

    # events (config-free) ---------------------------------------------------------------------
    events: dict[str, Any] = {}
    for g in IDP_GROUPS:
        for kind, key, metric in (
            ("splitHalf", f"esplit:{g}", "split_half"),
            ("yoy2425", f"eyoy2425:{g}", "yoy"),
        ):
            obs = P.obs[f"{key}|{metric}"]
            reps_arr = P.reps[f"{key}|{metric}"]
            lo, hi = basic_ci(obs, reps_arr)
            events.setdefault(g, {})[kind] = {
                ev: [float(obs[i]), float(lo[i]), float(hi[i])] for i, ev in enumerate(EVENT_KEYS)
            }

    # descriptive --------------------------------------------------------------------------------
    pools4 = study.pools(4)
    tiers = {
        "elite": (0, 12),
        "averageStarter": (24, 36),
        "firstBench": (36, 48),
        "pool": (0, 10**6),
    }
    descriptive = {
        pool: component_profile(study, pools4[pool], tiers)
        for pool in ("DL", "LB", "DB", "EDGE", "DT", "ILB", "CB", "S")
    }

    # stability: pool-size variants --------------------------------------------------------------
    stability: dict[str, Any] = {}
    for mg in cfg["analysis"]["pool"]["minPlayedGamesSensitivity"]:
        Wv = run_w(study, 0, seed, min_games=mg, bootstrap=False)
        stability[f"minGames{mg}"] = {
            "contrastPoints": point_w_contrasts(Wv),
            "actual": {
                pool: {
                    m: Wv.point(f"{pool}.{m}", "actual")
                    for m in (
                        "n",
                        "p12",
                        "p25_36",
                        "starters",
                        "sep",
                        "gap_rank",
                        "gap_fa",
                        "cv_med",
                    )
                    if f"{pool}.{m}" in Wv.obs
                }
                for pool in IDP_GROUPS + ("DT", "EDGE", "CB", "S")
            },
        }
    stability["minGames4"] = {"contrastPoints": point_w_contrasts(W)}
    # Best-ball replacement sensitivity (actual card): the LEVEL of a marginal depends on who replaces
    # the player; the free-agent level is hindsight-selected, so deeper free agents and the roster-only
    # counterfactual are published beside it.
    rates_actual = study.R[:, study.cidx["actual"]]
    X_act = world.weekly(rates_actual)
    bb_repl: dict[str, Any] = {}
    for label, ranks in (
        ("freeAgentRank1to5", (1, 2, 3, 4, 5)),
        ("freeAgentRank6to10", (6, 7, 8, 9, 10)),
        ("rosterCounterfactual", ()),
    ):
        idp_m = bb_marginals(world, X_act, world.Am.T, subs=("idp",), cand_ranks=ranks)
        off_m = bb_marginals(world, X_act, world.Am.T, subs=("off",), cand_ranks=ranks)
        marg = {
            "bb": np.where(np.isnan(idp_m["bb"]), off_m["bb"], idp_m["bb"]),
            "det": np.where(np.isnan(idp_m["det"]), off_m["det"], idp_m["det"]),
        }
        met = bb_pool_metrics(world, X_act, world.Pm.T, marg, world.pool_ents)
        bb_repl[label] = {
            k: v
            for k, v in met.items()
            if k.split(".")[0] in IDP_GROUPS + OFFENSE_GROUPS
            and k.split(".")[1] in ("bb_p12", "bb_p25_36", "bb_starters", "det_p12", "det_starters")
        }
    stability["bbReplacement"] = bb_repl

    movers = {
        "tflDL": named_movers(study, "DL", "oat:tfl:x0", "oat:tfl:x2"),
        "pdDB": named_movers(study, "DB", "oat:pd:x0", "oat:pd:x2"),
        "tacklesLB": named_movers(study, "LB", "joint:tackles_down", "joint:tackles_up"),
    }

    u = study.universe
    evidence = {
        "schema": "idp_scoring_sensitivity_v1",
        "status": "RESEARCH_EVIDENCE_NOT_FOR_PROMOTION",
        "provenance": {
            "gitHead": git_sha(),
            "configSha256": config_sha256(),
            "preRegistrationCommit": args.prereg_commit,
            "league": cfg["league"],
            "scoringFingerprint": inp.fingerprint,
            "slots": inp.slots,
            "priorLeagueIds": inp.prior_league_ids,
            "seed": seed,
            "replicates": {"W": reps_w, "P": reps_p, "B": reps_b},
            "datasets": inp.receipts,
            "generatedAtUtc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            "runSeconds": round(time.time() - t_start, 1),
        },
        "parity": parity,
        "cards": {
            cid: {
                "label": card_label(cid),
                "kind": cid.split(":")[0],
                "rates": pool_card_rates(study.cards[cid], cfg),
                "idpBlock": idp_block(study.cards[cid], cfg["idpCardKeys"]),
            }
            for cid in study.cfg_ids
        },
        "design": {
            "configurations": len(study.cfg_ids),
            "universePlayers": int(u.n.shape[0]),
            "poolsMinGames4": {k: int(v.size) for k, v in pools4.items()},
            "freeAgentsQualified": {k: int(v.size) for k, v in study.fa_rows().items()},
            "pairCounts": pair_n,
            "bestBall": {
                "entities": len(world.pids),
                "rostered": int(sum(o is not None for o in world.owner)),
                "qualifiedFreeAgents": int(world.fa.sum()),
                "excludedTwoWay": [world.names[i] for i, s in enumerate(world.sub) if s is None],
            },
            "keyConfigs": key_cfgs,
            "configOrder": list(study.cfg_ids),
        },
        "configs": configs,
        "deltasVsActual": deltas_vs_actual(W, study.cfg_ids),
        "eventStability": events,
        "contrasts": contrasts,
        "supplementary": supp,
        "crossPosition": xpos,
        "descriptive": descriptive,
        "stability": stability,
        "namedPlayers": movers,
    }
    return _clean(evidence)


def main(argv: Sequence[str] | None = None) -> int:
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    sub = ap.add_subparsers(dest="cmd", required=True)
    r = sub.add_parser("run", help="run the experiment and write the evidence file")
    r.add_argument("--offline", action="store_true", help="never fetch; use the cache only")
    r.add_argument("--workers", type=int, default=max(1, (os.cpu_count() or 2) - 2))
    r.add_argument("--reps-w", type=int, default=0)
    r.add_argument("--reps-p", type=int, default=0)
    r.add_argument("--reps-b", type=int, default=None)
    r.add_argument("--out", type=Path, default=EVIDENCE_PATH)
    r.add_argument("--prereg-commit", default="9a6a82851")
    sub.add_parser("tables", help="print the report tables rendered from the evidence file")
    sub.add_parser("render-doc", help="refresh the generated tables inside the write-up")
    args = ap.parse_args(argv)
    if args.cmd == "run":
        evidence = run_all(args)
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(json.dumps(evidence, indent=1, sort_keys=True) + "\n", encoding="utf-8")
        print(f"wrote {args.out} ({args.out.stat().st_size / 1e6:.2f} MB)")
        return 0
    evidence = json.loads(EVIDENCE_PATH.read_text(encoding="utf-8"))
    if args.cmd == "render-doc":
        text = DOC_PATH.read_text(encoding="utf-8")
        DOC_PATH.write_text(inject_blocks(text, render_blocks(evidence)), encoding="utf-8")
        print(f"refreshed the generated tables in {DOC_PATH}")
        return 0
    print(render_tables(evidence))
    return 0


# ── report tables rendered from the evidence file ────────────────────────────────────────────
#
# Every number in the write-up's tables comes from ``render_blocks``; a test re-renders them and fails if
# the page drifts from the evidence.  Prose numbers are copied from these tables.

POOL_ORDER = ("DL", "LB", "DB", "DT", "EDGE", "ILB", "CB", "S")
OFFENSE_ORDER = ("QB", "RB", "WR", "TE")
CONTRAST_LABELS = {
    "Q1.1": "DT minus EDGE: elite-tier ppg gain from TFL x2 vs x0",
    "Q1.2": "DT minus EDGE: average-starter-tier ppg gain, TFL x2 vs x0",
    "Q1.3": "change in DT among the 36 best DL, TFL x2 vs x0",
    "Q2.1": "CB elite-tier gain minus CB first-bench gain, PD x2 vs x0",
    "Q2.2": "change in CB elite separation (in-sample), PD x2 vs x0",
    "Q2.3": "change in CB held-out elite separation, PD x2 vs x0",
    "Q2.4": "change in CB split-half reliability, PD x2 vs x0",
    "Q2.5": "CB minus S elite-tier gain, PD x2 vs x0",
    "Q3.1a": "relative FA-based gap, LB minus DL",
    "Q3.1b": "relative FA-based gap, LB minus DB",
    "Q3.2a": "relative rank-based gap, LB minus DL",
    "Q3.2b": "relative rank-based gap, LB minus DB",
    "Q3.3a": "weekly CV of the 36 starters, LB minus DL",
    "Q3.3b": "weekly CV of the 36 starters, LB minus DB",
    "Q3.4a": "best-ball marginal of the 36 starters (pts/wk), LB minus DL",
    "Q3.4b": "best-ball marginal of the 36 starters (pts/wk), LB minus DB",
    "Q4.1": "premium-on-CV slope (in-sample), actual card",
    "Q4.2": "premium-on-CV slope (ex ante), actual card",
    "Q4.3": "Spearman of deterministic vs best-ball marginal",
    "Q4.4": "premium-on-CV slope, big-play minus tackle-heavy card",
}


def _fmt(x: Any, nd: int = 2) -> str:
    if x is None or (isinstance(x, float) and not math.isfinite(x)):
        return "n/a"
    return f"{x:.{nd}f}"


def _fci(t: Sequence[Any] | None, nd: int = 2) -> str:
    """``est [lo, hi]``; a point-only entry prints the estimate alone."""
    if not t or t[0] is None:
        return "n/a"
    if len(t) < 3 or t[1] is None or t[2] is None:
        return _fmt(t[0], nd)
    return f"{t[0]:.{nd}f} [{t[1]:.{nd}f}, {t[2]:.{nd}f}]"


def _bc(t: Sequence[Any] | None, nd: int = 2) -> str:
    """Selection-corrected estimate (observed minus bootstrap bias) with its basic 95 percent interval."""
    if not t or t[0] is None or len(t) < 4 or t[3] is None or t[1] is None:
        return _fci(t, nd) if t else "n/a"
    return f"{t[0] - t[3]:.{nd}f} [{t[1]:.{nd}f}, {t[2]:.{nd}f}]"


def _row(cells: Sequence[str]) -> str:
    return "| " + " | ".join(cells) + " |"


def _table(header: Sequence[str], rows: Sequence[Sequence[str]]) -> str:
    lines = [_row(header), _row(["---"] + ["---:"] * (len(header) - 1))]
    lines += [_row(r) for r in rows]
    return "\n".join(lines)


def _w(ev, cid, pool, metric):
    return ev["configs"][cid]["W"].get(pool, {}).get(metric)


def _p(ev, cid, kind, pool, metric):
    return ev["configs"][cid]["P"].get(kind, {}).get(pool, {}).get(metric)


def _bb(ev, cid, pool, metric):
    return ev["configs"][cid]["BB"].get(pool, {}).get(metric)


def render_blocks(ev: Mapping[str, Any]) -> dict[str, str]:  # noqa: C901 - one flat list of tables
    """Every generated table of the write-up, by block name."""
    out: dict[str, str] = {}
    pools = POOL_ORDER + OFFENSE_ORDER
    a = "actual"

    # -- baseline ---------------------------------------------------------------------------
    rows = []
    for pool in pools:
        rows.append(
            [
                pool,
                _fmt(_w(ev, a, pool, "n")[0], 0),
                _fmt(_w(ev, a, pool, "starters")[0], 1),
                _fmt(_w(ev, a, pool, "p12")[0], 1),
                _fmt(_w(ev, a, pool, "p25_36")[0], 1),
                _fmt(_w(ev, a, pool, "sep")[0], 1),
                _bc(_w(ev, a, pool, "sep"), 1),
                _fci(_p(ev, a, "split", pool, "oos_sep"), 1),
                _fci(_p(ev, a, "yoy2425", pool, "fwd_sep"), 1),
                _fci(_p(ev, a, "yoy2526", pool, "fwd_sep"), 1),
            ]
        )
    out["baseline_separation"] = _table(
        [
            "pool", "n", "36 starters ppg", "elite 1-12 ppg", "avg starter 25-36 ppg",
            "in-sample separation", "selection-corrected separation [CI]",
            "held-out separation, 2026 halves [CI]",
            "forward separation 2024 to 2025 [CI]", "forward separation 2025 to 2026 [CI]",
        ],
        rows,
    )  # fmt: skip

    rows = []
    for pool in pools:
        fa = _w(ev, a, pool, "rel_gap_fa")
        rows.append(
            [
                pool,
                _fmt(_w(ev, a, pool, "gap_rank")[0], 1),
                _fmt(_w(ev, a, pool, "rel_gap_rank")[0], 2),
                _fmt(_w(ev, a, pool, "repl_fa")[0], 1) if fa else "n/a",
                _fmt(fa[0], 2) if fa else "n/a",
                _fci(_p(ev, a, "split", pool, "split_half"), 2),
                _fci(_p(ev, a, "yoy2425", pool, "yoy"), 2),
                _fmt(_w(ev, a, pool, "cv_med")[0], 2),
                _fmt(_w(ev, a, pool, "icc")[0], 2),
                _fci(_bb(ev, a, pool, "bb_p12"), 1) if _bb(ev, a, pool, "bb_p12") else "n/a",
            ]
        )
    out["baseline_gaps"] = _table(
        [
            "pool", "rank gap (ppg)", "rank gap / starters", "free-agent level (ppg)", "FA gap / starters",
            "split-half r (SB) [CI]", "year-over-year r 2024-25 [CI]", "weekly CV (36 starters)",
            "weekly ICC", "best-ball marginal, elite tier (pts/wk) [CI]",
        ],
        rows,
    )  # fmt: skip

    # -- scoring components ---------------------------------------------------------------
    for tier, label in (("elite", "elite"), ("averageStarter", "avg_starter")):
        rows = []
        for pool in POOL_ORDER:
            d = ev["descriptive"][pool][tier]
            rows.append(
                [pool, _fmt(d["ppg"], 1)]
                + [
                    _fmt(d[k], 1)
                    for k in (
                        "tackles_pts",
                        "tfl_pts",
                        "sack_and_yards_pts",
                        "qb_hit_pts",
                        "pass_defended_pts",
                        "interception_pts",
                        "forced_fumble_pts",
                        "fumble_recovery_pts",
                        "defensive_td_pts",
                        "other_pts",
                    )
                ]  # fmt: skip
            )
        out[f"components_{label}"] = _table(
            [
                "pool",
                "ppg",
                "tackles",
                "TFL",
                "sacks + yds",
                "QB hit",
                "PD",
                "INT",
                "FF",
                "FR",
                "TD",
                "other",
            ],
            rows,
        )

    # -- responses to every configuration ---------------------------------------------------
    cfg_ids = [
        c
        for c in ev["design"]["configOrder"]
        if not (c.startswith("oat:") and c.endswith(("x0.5", "x1.5")))
    ]
    rows = []
    for cid in cfg_ids:
        r = [ev["cards"][cid]["label"]]
        for g in IDP_GROUPS:
            r.append(_fmt(100 * _w(ev, cid, g, "share")[0], 1))
        for g in IDP_GROUPS:
            r.append(_fmt(_w(ev, cid, g, "sep")[0], 1))
        for g in IDP_GROUPS:
            r.append(_fmt(_w(ev, cid, g, "gap_rank")[0], 1))
        for g in IDP_GROUPS:
            r.append(_fmt(_p(ev, cid, "split", g, "oos_sep")[0], 1))
        rows.append(r)
    out["responses"] = _table(
        ["configuration"]
        + [f"{g} share %" for g in IDP_GROUPS]
        + [f"{g} separation" for g in IDP_GROUPS]
        + [f"{g} rank gap" for g in IDP_GROUPS]
        + [f"{g} held-out sep" for g in IDP_GROUPS],
        rows,
    )

    # -- Q1 TFL -----------------------------------------------------------------------------
    rows = []
    for cid in ("oat:tfl:x0", "actual", "oat:tfl:x2"):
        rows.append(
            [
                ev["cards"][cid]["label"],
                _fmt(_w(ev, cid, "DT", "p12")[0], 1),
                _fmt(_w(ev, cid, "EDGE", "p12")[0], 1),
                _fmt(_w(ev, cid, "DT", "p25_36")[0], 1),
                _fmt(_w(ev, cid, "EDGE", "p25_36")[0], 1),
                _fmt(_w(ev, cid, "DL", "top36_DT")[0], 0),
                _fmt(_p(ev, cid, "split", "DT", "oos_p12")[0], 1),
                _fmt(_p(ev, cid, "split", "EDGE", "oos_p12")[0], 1),
                _fmt(_p(ev, cid, "yoy2425", "DT", "fwd_p12")[0], 1),
                _fmt(_p(ev, cid, "yoy2425", "EDGE", "fwd_p12")[0], 1),
            ]
        )
    out["q1_table"] = _table(
        [
            "TFL rate", "DT elite ppg", "EDGE elite ppg", "DT avg-starter ppg", "EDGE avg-starter ppg",
            "DT among best 36 DL", "DT held-out elite ppg", "EDGE held-out elite ppg",
            "DT forward elite ppg 24-25", "EDGE forward elite ppg 24-25",
        ],
        rows,
    )  # fmt: skip

    # -- Q2 PD ------------------------------------------------------------------------------
    rows = []
    for cid in ("oat:pd:x0", "actual", "oat:pd:x2"):
        rows.append(
            [
                ev["cards"][cid]["label"],
                _fmt(_w(ev, cid, "CB", "p12")[0], 1),
                _fmt(_w(ev, cid, "CB", "p25_36")[0], 1),
                _fmt(_w(ev, cid, "CB", "p37_48")[0], 1),
                _fmt(_w(ev, cid, "CB", "sep")[0], 1),
                _fmt(_p(ev, cid, "split", "CB", "oos_sep")[0], 1),
                _fmt(_p(ev, cid, "split", "CB", "split_half")[0], 2),
                _fmt(_p(ev, cid, "yoy2425", "CB", "fwd_sep")[0], 1),
                _fmt(_p(ev, cid, "yoy2526", "CB", "fwd_sep")[0], 1),
                _fmt(_w(ev, cid, "S", "p12")[0], 1),
                _fmt(_p(ev, cid, "split", "S", "oos_sep")[0], 1),
            ]
        )
    out["q2_table"] = _table(
        [
            "PD rate", "CB elite ppg", "CB avg-starter ppg", "CB first-bench ppg", "CB separation",
            "CB held-out separation", "CB split-half r", "CB forward sep 24-25", "CB forward sep 25-26",
            "S elite ppg", "S held-out separation",
        ],
        rows,
    )  # fmt: skip

    # -- Q3 LB ------------------------------------------------------------------------------
    rows = []
    for pool in ("DL", "LB", "DB", "ILB"):
        fa = _w(ev, a, pool, "rel_gap_fa")
        rows.append(
            [
                pool,
                _fmt(_w(ev, a, pool, "starters")[0], 1),
                _fmt(_w(ev, a, pool, "rel_gap_rank")[0], 2),
                _fmt(fa[0], 2) if fa else "n/a",
                _fmt(_w(ev, a, pool, "cv_med")[0], 2),
                _fmt(_bb(ev, a, pool, "bb_starters")[0], 2),
                _fmt(_bb(ev, a, pool, "det_starters")[0], 2),
                _fmt(_p(ev, a, "split", pool, "oos_gap")[0], 2),
            ]
        )
    out["q3_table"] = _table(
        [
            "pool", "36 starters ppg", "rank gap / starters", "FA gap / starters", "weekly CV",
            "best-ball marginal, 36 starters (pts/wk)", "deterministic-lineup marginal (pts/wk)",
            "held-out starter-minus-bench gap (ppg)",
        ],
        rows,
    )  # fmt: skip
    rows = []
    for cid in (
        "joint:tackles_down",
        "actual",
        "joint:tackles_up",
        "joint:tackles_only",
        "joint:playmaking_only",
    ):
        rows.append(
            [ev["cards"][cid]["label"]]
            + [_fmt(100 * _w(ev, cid, g, "share")[0], 1) for g in IDP_GROUPS]
            + [
                _fmt(_w(ev, cid, "LB", "starters")[0], 1),
                _fmt(_w(ev, cid, "LB", "rel_gap_fa")[0], 2),
            ]
            + [_fmt(_w(ev, cid, g, "gap_rank")[0], 1) for g in IDP_GROUPS]
        )
    out["q3_lb_cards"] = _table(
        ["configuration"]
        + [f"{g} share of IDP starter points %" for g in IDP_GROUPS]
        + ["LB 36 starters ppg", "LB FA gap / starters"]
        + [f"{g} rank gap (ppg)" for g in IDP_GROUPS],
        rows,
    )

    # -- Q4 best ball -----------------------------------------------------------------------
    def premium(cid: str, g: str) -> str:
        bb_, det_ = _bb(ev, cid, g, "bb_starters"), _bb(ev, cid, g, "det_starters")
        return _fmt(bb_[0] - det_[0], 2) if bb_ and det_ else "n/a"

    rows = []
    for cid in ev["design"]["keyConfigs"]:
        q = ev["configs"][cid]["Q4"]
        rows.append(
            [
                ev["cards"][cid]["label"],
                _fci(q.get("q41"), 2),
                _fci(q.get("q42"), 2) if q.get("q42") else "n/a",
                _fci(q.get("q43"), 2),
                _fci(q.get("q43_start"), 2),
            ]
            + [premium(cid, g) for g in IDP_GROUPS]
        )
    out["q4_table"] = _table(
        [
            "configuration", "slope in-sample [CI]", "slope ex ante [CI]", "Spearman det vs best ball [CI]",
            "Spearman, deterministic starters only [CI]",
            "DL mean premium, 36 starters", "LB mean premium", "DB mean premium",
        ],
        rows,
    )  # fmt: skip

    # -- contrasts --------------------------------------------------------------------------
    rows = []
    for cid, c in ev["contrasts"].items():
        rows.append(
            [
                cid,
                CONTRAST_LABELS.get(cid, c["definition"]),
                c["scheme"],
                _fmt(c["estimate"], 2),
                _fmt(c["estimate"] - c["bias"], 2) if c.get("bias") is not None else "n/a",
                f"[{_fmt(c['ci95'][0], 2)}, {_fmt(c['ci95'][1], 2)}]",
                f"[{_fmt(c['ciBonferroni'][0], 2)}, {_fmt(c['ciBonferroni'][1], 2)}] (m={c['familySize']})",
                "yes"
                if c["excludesZeroBonferroni"]
                else ("95% only" if c["excludesZero95"] else "no"),
            ]
        )
    out["contrasts"] = _table(
        [
            "id",
            "contrast",
            "scheme",
            "estimate",
            "bias-corrected",
            "95% CI",
            "Bonferroni CI",
            "excludes 0",
        ],
        rows,
    )

    # -- cross position ---------------------------------------------------------------------
    xp = ev["crossPosition"]
    rows = []
    for o in OFFENSE_ORDER:
        d = xp["offense"][o]
        rows.append(
            [
                o,
                "offense, actual card",
                _fci(d["bbElite"], 1),
                _fci(d["parElite"], 1) if d["parElite"] else "n/a",
            ]
        )
    for cid in (
        "actual",
        "oat:tfl:x0",
        "oat:pd:x0",
        "joint:bigplay_up",
        "ref:tackle_heavy_balanced",
        "ref:big_play",
    ):
        for g in IDP_GROUPS:
            d = xp[cid][g]
            rows.append(
                [g, ev["cards"][cid]["label"], _fci(d["bbElite"], 1), _fci(d["parElite"], 1)]
            )
    out["cross_position"] = _table(
        [
            "pool",
            "card",
            "best-ball marginal, elite 1-12 (pts/wk) [CI]",
            "elite ppg over free-agent level [CI]",
        ],
        rows,
    )
    rows = []
    for cid in ("actual", "ref:tackle_heavy_balanced", "ref:big_play"):
        for g in IDP_GROUPS:
            d = xp[cid][g]
            rows.append(
                [ev["cards"][cid]["label"], g]
                + [_fci(d[f"bbRatioTo{o}"], 2) for o in OFFENSE_ORDER]
                + [_fci(d[f"parRatioTo{o}"], 2) for o in ("RB", "WR", "TE")]
            )
    out["cross_ratios"] = _table(
        ["card", "IDP elite"]
        + [f"bb ratio to {o}" for o in OFFENSE_ORDER]
        + [f"ppg-over-FA ratio to {o}" for o in ("RB", "WR", "TE")],
        rows,
    )

    # -- cards ------------------------------------------------------------------------------
    keys = list(CFG_KEYS)
    rows = []
    for cid in ev["cards"]:
        if cid.startswith("oat:"):
            continue
        rows.append(
            [ev["cards"][cid]["label"]] + [_fmt(ev["cards"][cid]["rates"][k], 2) for k in keys]
        )
    out["cards"] = _table(["card"] + keys, rows)

    # -- supplementary TFL / PD gains ----------------------------------------------------------
    sup = ev["supplementary"]
    rows = []
    for pool in ("DT", "EDGE", "DL"):
        rows.append(
            [
                pool,
                _bc(_sup(sup, f"tfl.W.{pool}.p12"), 2),
                _bc(_sup(sup, f"tfl.W.{pool}.p25_36"), 2),
                _bc(_sup(sup, f"tfl.W.{pool}.p37_48"), 2),
                _fci(_sup(sup, f"tfl.P.{pool}.oos_p12"), 2),
                _fci(_sup(sup, f"tfl.yoy2425.{pool}.fwd_p12"), 2),
                _fci(_sup(sup, f"tfl.yoy2526.{pool}.fwd_p12"), 2),
                _fci(_sup(sup, f"tfl.B.{pool}.bb_p12"), 2),
            ]
        )
    out["supp_tfl"] = _table(
        [
            "pool", "elite ppg gain", "avg-starter ppg gain", "first-bench ppg gain", "held-out elite gain",
            "forward elite gain 24-25", "forward elite gain 25-26", "best-ball elite gain (pts/wk)",
        ],
        rows,
    )  # fmt: skip
    rows = []
    for pool in ("CB", "S", "DB"):
        rows.append(
            [
                pool,
                _bc(_sup(sup, f"pd.W.{pool}.p12"), 2),
                _bc(_sup(sup, f"pd.W.{pool}.p25_36"), 2),
                _bc(_sup(sup, f"pd.W.{pool}.p37_48"), 2),
                _fci(_sup(sup, f"pd.P.{pool}.oos_p12"), 2),
                _fci(_sup(sup, f"pd.yoy2425.{pool}.fwd_p12"), 2),
                _fci(_sup(sup, f"pd.yoy2526.{pool}.fwd_p12"), 2),
                _fci(_sup(sup, f"pd.B.{pool}.bb_p12"), 2),
            ]
        )
    out["supp_pd"] = _table(
        [
            "pool", "elite ppg gain", "avg-starter ppg gain", "first-bench ppg gain", "held-out elite gain",
            "forward elite gain 24-25", "forward elite gain 25-26", "best-ball elite gain (pts/wk)",
        ],
        rows,
    )  # fmt: skip

    # -- mechanism: where TFL and PD points come from ----------------------------------------
    d = ev["descriptive"]
    rows = []
    for pool in ("DT", "EDGE", "DL", "ILB", "LB"):
        for tier, label in (("elite", "elite 1-12"), ("averageStarter", "avg starter 25-36")):
            r = d[pool][tier]
            rows.append(
                [
                    pool,
                    label,
                    _fmt(r["idp_tkl_loss_per_game"], 2),
                    _fmt(r["idp_sack_per_game"], 2),
                    _fmt(r["tfl_beyond_sacks_per_game"], 2),
                    _fmt(r["tfl_pts"], 1),
                    _fmt(100 * r["tfl_pts"] / r["ppg"], 0),
                ]
            )
    out["tfl_profile"] = _table(
        [
            "pool", "tier", "TFL / game", "sacks / game", "TFL beyond sacks / game", "TFL points / game",
            "TFL share of ppg %",
        ],
        rows,
    )  # fmt: skip
    rows = []
    for pool in ("CB", "S", "DB"):
        for tier, label in (
            ("elite", "elite 1-12"),
            ("averageStarter", "avg starter 25-36"),
            ("firstBench", "first bench 37-48"),
        ):
            r = d[pool][tier]
            rows.append(
                [
                    pool,
                    label,
                    _fmt(r["idp_pd_per_game"], 2),
                    _fmt(r["idp_int_per_game"], 2),
                    _fmt(r["pass_defended_pts"], 1),
                    _fmt(100 * r["pass_defended_pts"] / r["ppg"], 0),
                    _fmt(r["tackles_pts"], 1),
                ]
            )
    out["pd_profile"] = _table(
        [
            "pool", "tier", "PD / game", "INT / game", "PD points / game", "PD share of ppg %",
            "tackle points / game",
        ],
        rows,
    )  # fmt: skip

    # -- events -----------------------------------------------------------------------------
    rows = []
    for g in IDP_GROUPS:
        for kind in ("splitHalf", "yoy2425"):
            rows.append(
                [g, "split-half" if kind == "splitHalf" else "2024 to 2025"]
                + [_fmt(ev["eventStability"][g][kind][e][0], 2) for e in EVENT_KEYS]
            )
    out["events"] = _table(
        ["group", "measure"] + ["solo", "assist", "TFL", "sack", "QB hit", "PD", "INT", "FF", "FR"],
        rows,
    )

    # -- stability --------------------------------------------------------------------------
    rows = []
    for variant in ("minGames3", "minGames4", "minGames5"):
        cp = ev["stability"][variant]["contrastPoints"]
        rows.append(
            [variant.replace("minGames", "at least ") + " games"]
            + [_fmt(cp[k], 2) for k in ("Q1.1", "Q1.2", "Q1.3", "Q2.1", "Q2.2", "Q2.5")]
        )
    out["stability_pools"] = _table(
        ["pool rule", "Q1.1", "Q1.2", "Q1.3", "Q2.1", "Q2.2", "Q2.5"], rows
    )
    rows = []
    for label, name in (
        ("free agents ranked 1-5 (primary)", "freeAgentRank1to5"),
        ("free agents ranked 6-10", "freeAgentRank6to10"),
        ("roster only (no free agent)", "rosterCounterfactual"),
    ):
        d = ev["stability"]["bbReplacement"][name]
        rows.append(
            [label] + [_fmt(d[f"{g}.bb_starters"], 2) for g in IDP_GROUPS + OFFENSE_ORDER[1:]]
        )
    out["stability_replacement"] = _table(
        ["replacement"] + [f"{g} 36 starters" for g in IDP_GROUPS + OFFENSE_ORDER[1:]], rows
    )

    # -- parity -----------------------------------------------------------------------------
    p = ev["parity"]
    out["parity"] = _table(
        ["check", "result"],
        [
            [
                "actual card, linear vs production scorer",
                f"{p['actualCardVsProductionScorer']['playerWeeks']:,} player-weeks, max abs diff {p['actualCardVsProductionScorer']['maxAbsDiff']:.1e}",
            ],
            [
                "8 sampled perturbed cards, linear vs production scorer",
                f"{p['perturbedCardsVsProductionScorer']['comparisons']:,} comparisons, max abs diff {p['perturbedCardsVsProductionScorer']['maxAbsDiff']:.1e}",
            ],
            [
                "actual card vs Sleeper awarded points (rostered)",
                f"{p['vsSleeperAwarded']['within0.01']:,} of {p['vsSleeperAwarded']['playerWeeks']:,} within 0.01, max abs diff {p['vsSleeperAwarded']['maxAbsDiff']:.4f}",
            ],
            [
                "sack plays carrying a TFL or QB hit",
                f"{p['stacking']['awardedMatchesStacked']} of {p['stacking']['sackPlayerWeeksWithTflOrHit']} match the stacked total, {p['stacking']['awardedMatchesUnstacked']} the un-stacked alternative",
            ],
        ],
    )
    return out


CFG_KEYS = ("solo", "assist", "tfl", "sack", "sack_yd", "qb_hit", "pd", "int", "ff", "fr", "def_td")


def _sup(sup: Mapping[str, Any], key: str):
    d = sup.get(key)
    return None if d is None else [d["estimate"], d["ci95"][0], d["ci95"][1], d.get("bias")]


def render_tables(evidence: Mapping[str, Any]) -> str:
    return "\n\n".join(
        f"<!-- table:{k} -->\n{v}\n<!-- /table:{k} -->" for k, v in render_blocks(evidence).items()
    )


_BLOCK_RE = re.compile(r"(<!-- table:(\w+) -->\n)(.*?)(\n<!-- /table:\2 -->)", re.S)


def extract_blocks(doc_text: str) -> dict[str, str]:
    """The generated tables embedded in the write-up, by block name."""
    return {m.group(2): m.group(3).strip("\n") for m in _BLOCK_RE.finditer(doc_text)}


def inject_blocks(doc_text: str, blocks: Mapping[str, str]) -> str:
    """Replace the body of every ``<!-- table:NAME -->`` marker pair with the rendered table."""

    def repl(m: re.Match[str]) -> str:
        return f"{m.group(1)}{blocks[m.group(2)]}{m.group(4)}"

    return _BLOCK_RE.sub(repl, doc_text)


if __name__ == "__main__":
    sys.exit(main())
