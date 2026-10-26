"""Preregistered study: a ``build_calibration`` points model against the fallback constants.

Research and shadow only (RPA-LGI-008). The preregistration is
``docs/league-intelligence/SIM_CALIBRATION_PREREGISTRATION_2026-10-26.md``; it was committed before
anything here was run, and this script implements it. Nothing in ``src/`` or ``server.py`` imports this
file. It writes ONLY under ``docs/league-intelligence/evidence/sim_calibration/`` (or a path the caller
names), and it REFUSES any path inside ``data/league_intel/``: a file there auto-loads into served
playoff odds, Game Day, best-ball marginal utility and the forecast archive, and writing one is
owner-reserved.

What it does:

1. Loads public Sleeper bodies through a cache shared with the IDP-accuracy lanes
   (``data/idp_accuracy/cache/``, key ``sha256(url)[:24]``). The live card's scoring fingerprint must
   equal ``sf1:9e51824690d091f9``, or the run aborts.
2. Scores every rostered player-week with the host-native scorer,
   ``compute_weekly_points(..., source="sleeper")``. Missing is never zero: no row, no appearance, a
   team entry, an unknown position and no point-in-time rosValue are each excluded and counted.
3. Fits the candidate with two calls to ``sim_calibration.build_calibration``: a variance call over
   2025 weeks 1-17 and 2026 weeks 1-4, and a scale call over 2026 weeks 1-4 with preseason rosValue.
   There is no second calibration owner; host-native points enter as a one-key, unit-rate line.
4. Evaluates the candidate, loaded back through ``load_points_model(path=...)``, against
   ``PointsModel()`` on 2026 weeks 5-6. Player level uses log score, CRPS, coverage and PIT; team-week
   uses production's ``_bestball_weekly_score``. It then applies the preregistered gates SC-G1..SC-G5.

Every output carries ``promotes: false``, the code SHA, the card fingerprint and input hashes.

Reproduce::

    python scripts/sim_calibration_study.py                 # primary run (fit + weeks 5-6)
    python scripts/sim_calibration_study.py --offline       # cache only, never the network
    python scripts/sim_calibration_study.py --frozen-candidate \
        docs/league-intelligence/evidence/sim_calibration/candidate_sim_points_model.json \
        --eval-weeks 7 --out-name evaluation_week7.json     # confirmation, no refit

Exit codes: 0 when the run completed (whatever the verdict), 2 when it refused (a fingerprint
mismatch, a week that is not final, a forbidden output path), 1 on an unexpected error.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import io
import json
import math
import random
import statistics
import subprocess
import sys
import time
import urllib.request
from collections import Counter, defaultdict
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Iterable, Mapping, Sequence
from zoneinfo import ZoneInfo

REPO = Path(__file__).resolve().parents[1]
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

from src.league_comparison.sleeper_scoring import scoring_fingerprint  # noqa: E402
from src.league_intel import sim_calibration as sc  # noqa: E402
from src.league_intel.scorer import score_stat_line  # noqa: E402
from src.nfl_data.realized_points import compute_weekly_points  # noqa: E402
from src.ros import playoff_sim  # noqa: E402
from src.ros.lineup import (  # noqa: E402
    RosterPlayer,
    lineup_position,
    solve_optimal_assignment,
    starter_slots_from_roster_positions,
)
from src.ros.team_strength import compute_team_strength, hydrate_roster_players  # noqa: E402

# ── preregistered constants (change only with a dated addendum to the preregistration) ──────────

PREREGISTRATION = "docs/league-intelligence/SIM_CALIBRATION_PREREGISTRATION_2026-10-26.md"
PREREGISTRATION_COMMIT = "d86f30238e0a63ebb48e24f5b92a1e8610b7b376"

LEAGUE_KEY = "dynasty_main"
LEAGUE_ID = "1312006700437352448"
PINNED_SCORING_FINGERPRINT = "sf1:9e51824690d091f9"

FIT_2025_WEEKS: tuple[int, ...] = tuple(range(1, 18))
FIT_2026_WEEKS: tuple[int, ...] = (1, 2, 3, 4)
HOLDOUT_2026_WEEKS: tuple[int, ...] = (5, 6)
CONFIRM_2026_WEEKS: tuple[int, ...] = (7,)
SEASON = 2026

#: Lineup families this league's slots use (``lineup_position`` vocabulary).  The sim draws a player
#: under his RAW directory position (``cv_for("CB")``, ``cv_for("DE")`` ...), and the directory
#: carries fine IDP positions (CB, DE, DT, NT) and FB for ~68 rostered player-weeks a week, so
#: eligibility is decided on the family, never on the raw label (deviation 1, results doc).
SIM_FAMILIES = frozenset({"QB", "RB", "WR", "TE", "K", "DL", "LB", "DB"})
FAMILY_ORDER = ("QB", "RB", "WR", "TE", "K", "DL", "LB", "DB")

SEED = 20261026
BOOTSTRAP_B = 2000
TEAM_WEEK_DRAWS = 2000
GATE_MIN_N = 50

#: SC-G1..SC-G5 thresholds, exactly as preregistered (§6).
G1_COV80 = (0.75, 0.85)
G1_COV95 = (0.90, 1.00)
G4_MAX_KS_D = 0.08
G5_COV80 = (0.65, 0.95)
G5_MIN_COV95 = 0.85

#: One-key, unit-rate line that carries a host-native total through ``build_calibration`` unchanged.
POINTS_KEY = "hostNativePoints"
UNIT_CONFIG: Mapping[str, float] = {POINTS_KEY: 1.0}

SLEEPER = "https://api.sleeper.app/v1"
NFLVERSE_GAMES = "https://github.com/nflverse/nflverse-data/releases/download/schedules/games.csv"
CACHE_DIR = REPO / "data" / "idp_accuracy" / "cache"
GAMES_CACHE = CACHE_DIR / "nflverse" / "schedules__games.csv"
ROS_HISTORY_DIR = REPO / "data" / "ros" / "aggregate" / "history"
OUT_DIR = REPO / "docs" / "league-intelligence" / "evidence" / "sim_calibration"
CANDIDATE_NAME = "candidate_sim_points_model.json"

#: The directory whose files auto-load into served numbers.  Never written by this study.
FORBIDDEN_OUTPUT_DIR = sc.DATA_DIR

ET = ZoneInfo("America/New_York")
SQRT2 = math.sqrt(2.0)
SQRT_PI = math.sqrt(math.pi)
LOG_SQRT_2PI = 0.5 * math.log(2.0 * math.pi)


class StudyRefusal(RuntimeError):
    """A preregistered precondition failed; the run stops rather than produce void numbers."""


class UnsafeOutputPath(StudyRefusal):
    """The requested output would land where the served loader reads."""


# ── output-path guard ──────────────────────────────────────────────────────────────────────────


def assert_safe_output(path: Path) -> Path:
    """Return ``path`` resolved, or refuse it.

    Refused: anything at or inside ``data/league_intel/`` (the loader's directory), and any file
    named like the served artifact (``sim_points_model.json``) wherever it is, so a careless
    ``--out-dir`` cannot create a file someone later copies into place by name.
    """
    resolved = Path(path).resolve()
    forbidden = FORBIDDEN_OUTPUT_DIR.resolve()
    if resolved == forbidden or forbidden in resolved.parents:
        raise UnsafeOutputPath(
            f"refusing to write {resolved}: it is inside {forbidden}, which load_points_model() "
            "reads into served numbers (owner-reserved)"
        )
    if resolved.name == sc.MODEL_PATH.name:
        raise UnsafeOutputPath(
            f"refusing to write a file named {sc.MODEL_PATH.name!r}: that is the served artifact name"
        )
    return resolved


def write_json(path: Path, payload: Any) -> Path:
    target = assert_safe_output(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    tmp = target.with_suffix(target.suffix + ".tmp")
    tmp.write_text(json.dumps(payload, indent=2, sort_keys=False) + "\n", encoding="utf-8")
    tmp.replace(target)
    return target


# ── split ──────────────────────────────────────────────────────────────────────────────────────


@dataclass(frozen=True)
class Split:
    fit: tuple[tuple[int, int], ...]
    holdout: tuple[tuple[int, int], ...]
    confirm: tuple[tuple[int, int], ...]


def preregistered_split() -> Split:
    fit = tuple((2025, w) for w in FIT_2025_WEEKS) + tuple((SEASON, w) for w in FIT_2026_WEEKS)
    split = Split(
        fit=fit,
        holdout=tuple((SEASON, w) for w in HOLDOUT_2026_WEEKS),
        confirm=tuple((SEASON, w) for w in CONFIRM_2026_WEEKS),
    )
    assert_split_integrity(split)
    return split


def assert_split_integrity(split: Split) -> None:
    """No evaluated week may be a fit week, and every fit week precedes every evaluated week."""
    fit = set(split.fit)
    evaluated = set(split.holdout) | set(split.confirm)
    overlap = fit & evaluated
    if overlap:
        raise StudyRefusal(f"split overlap: {sorted(overlap)} are both fit and evaluated")
    if fit and evaluated and max(fit) >= min(evaluated):
        raise StudyRefusal(
            f"split order: last fit week {max(fit)} is not before first evaluated week {min(evaluated)}"
        )


def week_key(season: int, week: int) -> int:
    """Season-qualified week key: ``build_calibration`` takes one int per week, and seasons collide."""
    return int(season) * 100 + int(week)


# ── hashing / provenance ───────────────────────────────────────────────────────────────────────


def sha256_bytes(blob: bytes) -> str:
    return hashlib.sha256(blob).hexdigest()


def sha256_file(path: Path) -> str:
    return sha256_bytes(Path(path).read_bytes())


def code_identity() -> dict[str, Any]:
    """Commit SHA + whether the study's code differs from it, + this file's own hash."""

    def _git(*args: str) -> str | None:
        try:
            out = subprocess.run(
                ["git", *args], cwd=REPO, capture_output=True, text=True, timeout=30, check=True
            )
        except (OSError, subprocess.SubprocessError):
            return None
        return out.stdout.strip()

    sha = _git("rev-parse", "HEAD")
    dirty = _git("status", "--porcelain", "--", "scripts/sim_calibration_study.py", "src")
    return {
        "codeSha": sha or "UNKNOWN",
        "studyCodeDirty": None if dirty is None else bool(dirty),
        "scriptSha256": sha256_file(Path(__file__)),
    }


# ── cached public fetcher ──────────────────────────────────────────────────────────────────────


class CachedFetcher:
    """Throttled public GET with a write-once cache; a cached body is reused, never refreshed."""

    MIN_INTERVAL_S = 0.25

    def __init__(self, cache_dir: Path = CACHE_DIR, *, offline: bool = False) -> None:
        self.cache_dir = Path(cache_dir)
        self.offline = offline
        self._last = 0.0
        self.receipts: dict[str, dict[str, Any]] = {}
        self.network_calls = 0

    def _http(self, url: str) -> bytes:
        if self.offline:
            raise StudyRefusal(f"offline and not cached: {url}")
        wait = self.MIN_INTERVAL_S - (time.time() - self._last)
        if wait > 0:
            time.sleep(wait)
        req = urllib.request.Request(
            url, headers={"User-Agent": "brisket-sim-calibration-study/1.0"}
        )
        with urllib.request.urlopen(req, timeout=120) as resp:  # noqa: S310 - public https GET
            blob = resp.read()
        self._last = time.time()
        self.network_calls += 1
        return blob

    def _body(self, url: str, cache: Path) -> bytes:
        if not cache.exists():
            cache.parent.mkdir(parents=True, exist_ok=True)
            cache.write_bytes(self._http(url))
        blob = cache.read_bytes()
        self.receipts[url] = {
            "sha256": sha256_bytes(blob),
            "bytes": len(blob),
            "cachedAtUtc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(cache.stat().st_mtime)),
        }
        return blob

    def get_json(self, url: str) -> Any:
        key = hashlib.sha256(url.encode()).hexdigest()[:24]
        return json.loads(self._body(url, self.cache_dir / f"{key}.json"))

    def get_csv(self, url: str, cache: Path) -> list[dict[str, str]]:
        return list(csv.DictReader(io.StringIO(self._body(url, cache).decode("utf-8"))))


# ── schedule ───────────────────────────────────────────────────────────────────────────────────


@dataclass(frozen=True)
class WeekSchedule:
    first_kickoff_utc: datetime
    games: int
    final_games: int

    @property
    def is_final(self) -> bool:
        return self.games > 0 and self.final_games == self.games


def schedule_by_week(games: Iterable[Mapping[str, str]], season: int) -> dict[int, WeekSchedule]:
    by_week: dict[int, list[Mapping[str, str]]] = defaultdict(list)
    for g in games:
        if str(g.get("season")) == str(season) and g.get("game_type") == "REG":
            by_week[int(g["week"])].append(g)
    out: dict[int, WeekSchedule] = {}
    for wk, rows in by_week.items():
        kicks = [
            datetime.strptime(f"{r['gameday']} {r['gametime']}", "%Y-%m-%d %H:%M")
            .replace(tzinfo=ET)
            .astimezone(timezone.utc)
            for r in rows
        ]
        out[wk] = WeekSchedule(
            first_kickoff_utc=min(kicks),
            games=len(rows),
            final_games=sum(1 for r in rows if str(r.get("result") or "").strip() != ""),
        )
    return out


# ── point-in-time rosValue ─────────────────────────────────────────────────────────────────────


def snapshot_timestamp(name: str) -> datetime:
    """``2026-09-09T21-17-37.092580+00-00.json`` -> aware UTC datetime."""
    stem = name[: -len(".json")] if name.endswith(".json") else name
    date, _, rest = stem.partition("T")
    clock, _, _tz = rest.partition("+")
    hh, mm, ss = clock.split("-", 2)
    return datetime.fromisoformat(f"{date}T{hh}:{mm}:{ss}+00:00")


def snapshot_before(cutoff: datetime, history_dir: Path = ROS_HISTORY_DIR) -> Path:
    """Latest snapshot STRICTLY before ``cutoff``; refuses when none exists."""
    best: tuple[datetime, Path] | None = None
    for p in Path(history_dir).glob("*.json"):
        try:
            ts = snapshot_timestamp(p.name)
        except ValueError:
            continue
        if ts < cutoff and (best is None or ts > best[0]):
            best = (ts, p)
    if best is None:
        raise StudyRefusal(f"no rosValue snapshot before {cutoff.isoformat()}")
    return best[1]


def load_snapshot_players(path: Path) -> list[dict[str, Any]]:
    blob = json.loads(Path(path).read_text(encoding="utf-8"))
    players = blob.get("players") if isinstance(blob, dict) else None
    return players if isinstance(players, list) else []


def as_of_full_rosters(
    rosters: Mapping[int, Sequence[str]],
    directory: Mapping[str, Any],
    snapshot_players: list[dict[str, Any]],
    slots: list[str],
) -> dict[int, list[dict[str, Any]]]:
    """``{roster_id: fullRoster rows}`` through the production join (no private matcher)."""
    teams = [
        {
            "ownerId": str(rid),
            "rosterId": rid,
            "teamName": "",
            "players": hydrate_roster_players(list(pids), directory),  # type: ignore[arg-type]
        }
        for rid, pids in rosters.items()
    ]
    rows = compute_team_strength(teams, aggregated_players=snapshot_players, starter_slots=slots)
    return {int(r["rosterId"]): list(r.get("fullRoster") or []) for r in rows}


# ── scoring and the population ─────────────────────────────────────────────────────────────────


def _num(v: Any) -> float:
    if isinstance(v, bool) or v is None:
        return 0.0
    try:
        x = float(v)
    except (TypeError, ValueError):
        return 0.0
    return x if math.isfinite(x) else 0.0


APPEARED = "appeared"
NO_STAT_LINE = "no_stat_line"
NO_APPEARANCE = "no_appearance"
TEAM_ENTRY = "team_entry"
UNKNOWN_POSITION = "unknown_position"
UNPRICED = "unpriced"


@dataclass(frozen=True)
class PlayerWeek:
    season: int
    week: int
    pid: str
    position: str  # RAW directory position: the key the sim's ``cv_for`` is asked
    status: str
    points: float | None  # host-native; None unless a row was scored
    family: str = ""  # lineup family (``lineup_position``), "" when there is none


def lineup_family(meta: Mapping[str, Any] | None) -> str | None:
    """The lineup family a player can fill, or ``None``.

    ``lineup_position(position)`` first (CB -> DB, DE/DT/NT -> DL); when the raw position has no
    family (FB), the first of his ``fantasy_positions`` that has one — the same field the exact
    solver reads for slot eligibility.
    """
    if not meta:
        return None
    fam = lineup_position(str(meta.get("position") or ""))
    if fam in SIM_FAMILIES:
        return fam
    for fp in meta.get("fantasy_positions") or ():
        fam = lineup_position(str(fp or ""))
        if fam in SIM_FAMILIES:
            return fam
    return None


def classify_player_week(
    pid: str,
    row: Mapping[str, Any] | None,
    meta: Mapping[str, Any] | None,
    card: Mapping[str, Any],
    season: int,
    week: int,
) -> PlayerWeek:
    """One rostered player-week, classified; points only from the host-native scorer."""
    position = str((meta or {}).get("position") or "").upper()
    family = lineup_family(meta)
    if family is None:
        return PlayerWeek(season, week, pid, position, UNKNOWN_POSITION, None)
    if row is None:
        return PlayerWeek(season, week, pid, position, NO_STAT_LINE, None, family)
    res = compute_weekly_points(
        {**row, "player_id": pid, "season": season, "week": week},
        dict(card),
        position=family,
        source="sleeper",
    )
    if res is None:
        return PlayerWeek(season, week, pid, position, TEAM_ENTRY, None, family)
    pts = float(res.fantasy_points)
    appeared = (
        _num(row.get("gp")) > 0
        or _num(row.get("off_snp")) > 0
        or _num(row.get("def_snp")) > 0
        or abs(pts) > 1e-9
    )
    status = APPEARED if appeared else NO_APPEARANCE
    return PlayerWeek(season, week, pid, position, status, pts, family)


def rostered_by_week(matchups: Sequence[Mapping[str, Any]] | None) -> dict[int, list[str]]:
    out: dict[int, list[str]] = {}
    for m in matchups or []:
        rid = m.get("roster_id")
        if rid is None:
            continue
        out[int(rid)] = [str(p) for p in (m.get("players") or []) if p]
    return out


# ── candidate fit (build_calibration, reused) ──────────────────────────────────────────────────


def fit_candidate(
    player_weeks: Iterable[PlayerWeek],
    preseason_ros: Mapping[str, float],
    split: Split,
    *,
    builder: Callable[..., dict[str, Any]] | None = None,
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Two ``build_calibration`` calls, composed as preregistered §3.

    Only fit weeks reach the builder; a holdout or confirmation week arriving here is filtered out,
    and the assembled inputs are re-checked so a future edit cannot leak one in silently.
    """
    build = builder or sc.build_calibration
    fit_weeks = set(split.fit)
    evaluated_keys = {week_key(s, w) for s, w in (*split.holdout, *split.confirm)}
    appeared_fit = [
        pw for pw in player_weeks if pw.status == APPEARED and (pw.season, pw.week) in fit_weeks
    ]

    lines_v: dict[int, dict[str, dict[str, float]]] = defaultdict(dict)
    positions: dict[str, str] = {}
    for pw in appeared_fit:
        lines_v[week_key(pw.season, pw.week)][pw.pid] = {POINTS_KEY: float(pw.points or 0.0)}
        positions[pw.pid] = pw.position

    lines_s: dict[int, dict[str, dict[str, float]]] = defaultdict(dict)
    ros_s: dict[str, float] = {}
    unpriced_scale = 0
    for pw in appeared_fit:
        if pw.season != SEASON:
            continue
        rv = float(preseason_ros.get(pw.pid) or 0.0)
        if rv <= 0:
            unpriced_scale += 1
            continue
        lines_s[week_key(pw.season, pw.week)][pw.pid] = {POINTS_KEY: float(pw.points or 0.0)}
        ros_s[pw.pid] = rv

    leaked = (set(lines_v) | set(lines_s)) & evaluated_keys
    if leaked:
        raise StudyRefusal(f"evaluated weeks reached the fit: {sorted(leaked)}")

    v = build(
        stat_lines_by_week=dict(lines_v),
        positions=positions,
        ros_values={},
        config=dict(UNIT_CONFIG),
        season="2025+2026",
    )
    s = build(
        stat_lines_by_week=dict(lines_s),
        positions={pid: positions[pid] for pid in ros_s},
        ros_values=ros_s,
        config=dict(UNIT_CONFIG),
        season=str(SEASON),
    )
    candidate = dict(v)
    candidate["scale"] = dict(s["scale"])
    receipts = {
        "varianceCall": {
            "weeks": v.get("weeks"),
            "sampleSize": v.get("sampleSize"),
            "scaleDiscarded": v.get("scale"),
        },
        "scaleCall": {
            "weeks": s.get("weeks"),
            "sampleSize": s.get("sampleSize"),
            "scale": s.get("scale"),
            "pricedPlayers": len(ros_s),
            "unpricedPlayerWeeksExcluded": unpriced_scale,
        },
    }
    return candidate, receipts


# ── metrics (pure) ─────────────────────────────────────────────────────────────────────────────


def norm_cdf(z: float) -> float:
    return 0.5 * math.erfc(-z / SQRT2)


def norm_pdf(z: float) -> float:
    return math.exp(-0.5 * z * z) / math.sqrt(2.0 * math.pi)


def log_norm_cdf(z: float) -> float:
    if z > -30.0:
        return math.log(max(norm_cdf(z), 1e-300))
    # Asymptotic tail (never reached at sigma >= 0.5 and cv >= 0.15, kept for safety).
    return -0.5 * z * z - math.log(-z) - LOG_SQRT_2PI + math.log1p(-1.0 / (z * z))


_INV = statistics.NormalDist()


def predictive_params(
    model: sc.PointsModel, ros_value: float, position: str
) -> tuple[float, float]:
    """``(mu, sigma)`` exactly as ``PointsModel.draw`` uses them."""
    mu = model.mean_points(ros_value)
    sigma = max(0.5, mu * model.cv_for(position))
    return mu, sigma


def censored_log_score(y: float, mu: float, sigma: float) -> float:
    """Tobit log-likelihood of ``max(0, y)`` under ``max(0, N(mu, sigma^2))`` (higher is better)."""
    ys = max(0.0, y)
    if ys <= 0.0:
        return log_norm_cdf(-mu / sigma)
    z = (ys - mu) / sigma
    return -0.5 * z * z - math.log(sigma) - LOG_SQRT_2PI


def _g_int_phi_sq(lv: float) -> float:
    """``∫_{-inf}^{l} Φ(t)^2 dt`` in closed form."""
    phi_l = norm_cdf(lv)
    return lv * phi_l * phi_l + 2.0 * phi_l * norm_pdf(lv) - norm_cdf(SQRT2 * lv) / SQRT_PI


def censored_crps(y: float, mu: float, sigma: float) -> float:
    """CRPS of ``max(0, N(mu, sigma^2))`` at ``y`` (lower is better); ``y < 0`` adds ``-y``."""
    if y < 0.0:
        return -y + censored_crps(0.0, mu, sigma)
    z = (y - mu) / sigma
    normal = sigma * (z * (2.0 * norm_cdf(z) - 1.0) + 2.0 * norm_pdf(z) - 1.0 / SQRT_PI)
    return normal - sigma * _g_int_phi_sq(-mu / sigma)


def censored_interval(mu: float, sigma: float, level: float) -> tuple[float, float]:
    lo_q = (1.0 - level) / 2.0
    return (
        max(0.0, mu + sigma * _INV.inv_cdf(lo_q)),
        max(0.0, mu + sigma * _INV.inv_cdf(1.0 - lo_q)),
    )


def covered(y: float, mu: float, sigma: float, level: float) -> bool:
    lo, hi = censored_interval(mu, sigma, level)
    ys = max(0.0, y)
    return lo - 1e-12 <= ys <= hi + 1e-12


def interval_content(mu: float, sigma: float, level: float) -> float:
    """Model probability that ``X = max(0, N(mu, sigma^2))`` falls in the preregistered interval.

    POST-HOC, NON-GATING (deviation 2, results doc).  When the lower bound is censored to 0 the
    interval also holds the point mass at 0, so its content is ``P(Y <= hi)`` — 0.975 for the
    "95%" interval — not ``level``.  The preregistered SC-G1 compares observed coverage with
    ``level``; this reports what a calibrated model would actually show.
    """
    lo, hi = censored_interval(mu, sigma, level)
    upper = norm_cdf((hi - mu) / sigma)
    if lo <= 0.0:
        return upper
    return upper - norm_cdf((lo - mu) / sigma)


def censored_pit(y: float, mu: float, sigma: float, u: float) -> float:
    ys = max(0.0, y)
    if ys <= 0.0:
        return u * norm_cdf(-mu / sigma)
    return norm_cdf((ys - mu) / sigma)


def kolmogorov_p(d: float, n: int) -> float:
    """Asymptotic Kolmogorov p-value with Stephens' small-sample correction."""
    if n <= 0:
        return float("nan")
    root = math.sqrt(n)
    lam = (root + 0.12 + 0.11 / root) * d
    if lam < 1e-3:
        return 1.0
    total = 0.0
    for k in range(1, 101):
        term = 2.0 * (-1.0) ** (k - 1) * math.exp(-2.0 * k * k * lam * lam)
        total += term
        if abs(term) < 1e-12:
            break
    return min(1.0, max(0.0, total))


def ks_uniform(values: Sequence[float]) -> dict[str, Any]:
    u = sorted(values)
    n = len(u)
    if n == 0:
        return {"n": 0, "ksD": None, "ksP": None, "hist10": []}
    d = 0.0
    for i, x in enumerate(u, start=1):
        d = max(d, i / n - x, x - (i - 1) / n)
    hist = [0] * 10
    for x in u:
        hist[min(9, max(0, int(x * 10)))] += 1
    return {"n": n, "ksD": round(d, 5), "ksP": round(kolmogorov_p(d, n), 6), "hist10": hist}


def sample_crps(draws: Sequence[float], y: float) -> float:
    x = sorted(draws)
    n = len(x)
    if n == 0:
        return float("nan")
    e_xy = sum(abs(v - y) for v in x) / n
    e_xx = 2.0 * sum((2 * i - n - 1) * v for i, v in enumerate(x, start=1)) / (n * n)
    return e_xy - 0.5 * e_xx


def sample_quantile(sorted_x: Sequence[float], q: float) -> float:
    """Type-7 (linear) quantile of an already-sorted sample."""
    n = len(sorted_x)
    if n == 1:
        return float(sorted_x[0])
    h = (n - 1) * q
    lo = math.floor(h)
    hi = min(n - 1, lo + 1)
    return float(sorted_x[lo] + (h - lo) * (sorted_x[hi] - sorted_x[lo]))


def sample_pit(draws: Sequence[float], y: float, u: float) -> float:
    n = len(draws)
    below = sum(1 for v in draws if v < y)
    ties = sum(1 for v in draws if v == y)
    return (below + u * ties) / n


def cluster_bootstrap(
    values: Sequence[float], clusters: Sequence[str], *, b: int, seed: int
) -> dict[str, Any]:
    """Mean of ``values`` with a 95% percentile CI, resampling clusters with replacement."""
    if not values:
        return {"n": 0, "clusters": 0, "mean": None, "ci95": [None, None]}
    sums: dict[str, float] = defaultdict(float)
    counts: dict[str, int] = defaultdict(int)
    for v, c in zip(values, clusters):
        sums[c] += float(v)
        counts[c] += 1
    keys = sorted(sums)
    s = [sums[k] for k in keys]
    n = [counts[k] for k in keys]
    rng = random.Random(seed)
    m = len(keys)
    stats = []
    for _ in range(b):
        tot = 0.0
        cnt = 0
        for _j in range(m):
            k = rng.randrange(m)
            tot += s[k]
            cnt += n[k]
        stats.append(tot / cnt)
    stats.sort()
    mean = sum(values) / len(values)
    return {
        "n": len(values),
        "clusters": m,
        "mean": round(mean, 6),
        "ci95": [round(sample_quantile(stats, 0.025), 6), round(sample_quantile(stats, 0.975), 6)],
    }


# ── evaluation ─────────────────────────────────────────────────────────────────────────────────


@dataclass
class Scored:
    pid: str
    week: int
    family: str
    position: str
    ros_value: float
    y: float
    mu: dict[str, float]
    sigma: dict[str, float]
    ls: dict[str, float]
    crps: dict[str, float]
    cov80: dict[str, bool]
    cov95: dict[str, bool]
    pit: dict[str, float]


def score_predictions(
    rows: Iterable[tuple[str, int, str, str, float, float]],
    models: Mapping[str, sc.PointsModel],
    *,
    seed: int = SEED,
) -> list[Scored]:
    """``rows`` are ``(pid, week, raw position, family, rosValue, y)``; one uniform per row (CRN).

    The CV is looked up under the RAW position, exactly as the sim's ``cv_for`` is asked.
    """
    rng = random.Random(seed)
    out: list[Scored] = []
    for pid, week, position, family, ros_value, y in rows:
        u = rng.random()
        rec = Scored(pid, week, family, position, ros_value, y, {}, {}, {}, {}, {}, {}, {})
        for name, model in models.items():
            mu, sigma = predictive_params(model, ros_value, position)
            rec.mu[name] = mu
            rec.sigma[name] = sigma
            rec.ls[name] = censored_log_score(y, mu, sigma)
            rec.crps[name] = censored_crps(y, mu, sigma)
            rec.cov80[name] = covered(y, mu, sigma, 0.80)
            rec.cov95[name] = covered(y, mu, sigma, 0.95)
            rec.pit[name] = censored_pit(y, mu, sigma, u)
        out.append(rec)
    return out


def summarize_group(recs: list[Scored], *, b: int, seed: int) -> dict[str, Any]:
    if not recs:
        return {"n": 0}
    clusters = [r.pid for r in recs]
    out: dict[str, Any] = {"n": len(recs), "players": len(set(clusters))}
    for m in ("C", "F"):
        ys = [max(0.0, r.y) for r in recs]
        mus = [r.mu[m] for r in recs]
        out[m] = {
            "meanLogScore": round(statistics.fmean(r.ls[m] for r in recs), 5),
            "meanCrps": round(statistics.fmean(r.crps[m] for r in recs), 5),
            "coverage80": round(statistics.fmean(1.0 if r.cov80[m] else 0.0 for r in recs), 5),
            "coverage95": round(statistics.fmean(1.0 if r.cov95[m] else 0.0 for r in recs), 5),
            # POST-HOC, NON-GATING (deviation 2): what the preregistered interval would cover under
            # the model itself, and coverage of the exact-content PIT intervals.
            "postHoc": {
                "coverage80ModelImplied": round(
                    statistics.fmean(interval_content(r.mu[m], r.sigma[m], 0.80) for r in recs), 5
                ),
                "coverage95ModelImplied": round(
                    statistics.fmean(interval_content(r.mu[m], r.sigma[m], 0.95) for r in recs), 5
                ),
                "pitCoverage80": round(
                    statistics.fmean(1.0 if 0.10 <= r.pit[m] <= 0.90 else 0.0 for r in recs), 5
                ),
                "pitCoverage95": round(
                    statistics.fmean(1.0 if 0.025 <= r.pit[m] <= 0.975 else 0.0 for r in recs), 5
                ),
            },
            "pit": ks_uniform([r.pit[m] for r in recs]),
            "meanPredictedMean": round(statistics.fmean(mus), 4),
            "meanRealized": round(statistics.fmean(ys), 4),
            "meanBias": round(statistics.fmean(mu - y for mu, y in zip(mus, ys)), 4),
            "realizedOverPredicted": round(statistics.fmean(ys) / statistics.fmean(mus), 4)
            if statistics.fmean(mus) > 0
            else None,
            "observedZeroShare": round(statistics.fmean(1.0 if y <= 0 else 0.0 for y in ys), 5),
            "predictedZeroMass": round(
                statistics.fmean(norm_cdf(-r.mu[m] / r.sigma[m]) for r in recs), 5
            ),
        }
    out["deltaLogScore"] = cluster_bootstrap(
        [r.ls["C"] - r.ls["F"] for r in recs], clusters, b=b, seed=seed
    )
    out["deltaCrps"] = cluster_bootstrap(
        [r.crps["F"] - r.crps["C"] for r in recs], clusters, b=b, seed=seed
    )
    return out


def realized_best_ball_total(
    roster_pids: Sequence[str],
    points_by_pid: Mapping[str, float],
    directory: Mapping[str, Any],
    slots: list[str],
) -> float:
    pool = []
    for pid in roster_pids:
        if pid not in points_by_pid:
            continue
        meta = directory.get(pid) or {}
        pool.append(
            RosterPlayer(
                player_id=pid,
                canonical_name=str(meta.get("full_name") or pid),
                position=str(meta.get("position") or "").upper(),
                ros_value=float(points_by_pid[pid]),
                fantasy_positions=tuple(
                    str(p).upper() for p in (meta.get("fantasy_positions") or ())
                ),
            )
        )
    assignment = solve_optimal_assignment(pool, slots)
    return float(sum(p.ros_value for p in assignment.values()))


def team_week_seed(week: int, roster_id: int) -> int:
    return int(hashlib.sha256(f"{SEED}:{week}:{roster_id}".encode()).hexdigest()[:12], 16)


def simulate_team_week(
    pool_rows: list[dict[str, Any]],
    slots: list[str],
    model: sc.PointsModel,
    seed: int,
    draws: int,
) -> list[float]:
    rng = random.Random(seed)
    return [playoff_sim._bestball_weekly_score(pool_rows, slots, rng, model) for _ in range(draws)]


def team_week_metrics(results: list[dict[str, Any]]) -> dict[str, Any]:
    """``results`` items: ``{"realized": y, "draws": {"C": [...], "F": [...]}}``."""
    rng = random.Random(SEED + 1)
    out: dict[str, Any] = {"n": len(results)}
    us = [rng.random() for _ in results]
    for m in ("C", "F"):
        crps, pits, c80, c95, bias = [], [], [], [], []
        for item, u in zip(results, us):
            x = sorted(item["draws"][m])
            y = float(item["realized"])
            crps.append(sample_crps(x, y))
            pits.append(sample_pit(x, y, u))
            c80.append(sample_quantile(x, 0.10) <= y <= sample_quantile(x, 0.90))
            c95.append(sample_quantile(x, 0.025) <= y <= sample_quantile(x, 0.975))
            bias.append(statistics.fmean(x) - y)
        out[m] = {
            "meanCrps": round(statistics.fmean(crps), 4) if crps else None,
            "coverage80": round(statistics.fmean(1.0 if c else 0.0 for c in c80), 5)
            if c80
            else None,
            "coverage95": round(statistics.fmean(1.0 if c else 0.0 for c in c95), 5)
            if c95
            else None,
            "meanBias": round(statistics.fmean(bias), 4) if bias else None,
            "pitSorted": [round(p, 4) for p in sorted(pits)],
            "pit": ks_uniform(pits),
        }
    return out


# ── gates ──────────────────────────────────────────────────────────────────────────────────────


def _within(x: float | None, band: tuple[float, float]) -> bool:
    return x is not None and band[0] - 1e-9 <= x <= band[1] + 1e-9


def apply_gates(player: dict[str, Any], team: dict[str, Any]) -> dict[str, Any]:
    fams = player["byFamily"]
    gated = [f for f in FAMILY_ORDER if fams.get(f, {}).get("n", 0) >= GATE_MIN_N]
    pooled = player["pooled"]

    g1_fail = [
        f
        for f in gated
        if not (
            _within(fams[f]["C"]["coverage80"], G1_COV80)
            and _within(fams[f]["C"]["coverage95"], G1_COV95)
        )
    ]

    def _ci_gate(key: str) -> tuple[bool, list[str], dict[str, Any]]:
        pooled_ci = pooled[key]["ci95"]
        pooled_ok = pooled[key]["mean"] is not None and pooled[key]["mean"] > 0 and pooled_ci[0] > 0
        worse = [f for f in gated if fams[f][key]["ci95"][1] < 0]
        return pooled_ok and not worse, worse, {"pooled": pooled[key]}

    g2_pass, g2_worse, g2_detail = _ci_gate("deltaLogScore")
    g3_pass, g3_worse, g3_detail = _ci_gate("deltaCrps")

    g4_fail = [f for f in gated if (fams[f]["C"]["pit"]["ksD"] or 1.0) > G4_MAX_KS_D]
    g4_pooled_ok = pooled["C"]["pit"]["ksD"] < pooled["F"]["pit"]["ksD"]

    tc, tf = team["C"], team["F"]
    g5_pass = (
        _within(tc["coverage80"], G5_COV80)
        and tc["coverage95"] is not None
        and tc["coverage95"] >= G5_MIN_COV95 - 1e-9
        and tc["meanCrps"] is not None
        and tf["meanCrps"] is not None
        and tc["meanCrps"] <= tf["meanCrps"]
    )

    gates = {
        "SC-G1": {
            "pass": not g1_fail,
            "gatedFamilies": gated,
            "failingFamilies": g1_fail,
            "rule": f"C coverage80 in {list(G1_COV80)} and coverage95 in {list(G1_COV95)}, every gated family",
        },
        "SC-G2": {
            "pass": g2_pass,
            "familiesSignificantlyWorse": g2_worse,
            **g2_detail,
            "rule": "pooled mean dLS > 0, CI lower > 0; no gated family CI upper < 0",
        },
        "SC-G3": {
            "pass": g3_pass,
            "familiesSignificantlyWorse": g3_worse,
            **g3_detail,
            "rule": "pooled mean dCRPS > 0, CI lower > 0; no gated family CI upper < 0",
        },
        "SC-G4": {
            "pass": not g4_fail and g4_pooled_ok,
            "failingFamilies": g4_fail,
            "pooledKsD": {"C": pooled["C"]["pit"]["ksD"], "F": pooled["F"]["pit"]["ksD"]},
            "rule": f"C ks D <= {G4_MAX_KS_D} every gated family; pooled D_C < D_F",
        },
        "SC-G5": {
            "pass": bool(g5_pass),
            "C": {k: tc[k] for k in ("coverage80", "coverage95", "meanCrps")},
            "F": {k: tf[k] for k in ("coverage80", "coverage95", "meanCrps")},
            "n": team["n"],
            "rule": f"C coverage80 in {list(G5_COV80)}, coverage95 >= {G5_MIN_COV95}, meanCrps_C <= F",
        },
    }
    all_pass = all(g["pass"] for g in gates.values())
    return {
        "gates": gates,
        "verdict": "CANDIDATE_BEATS_FALLBACK" if all_pass else "CANDIDATE_DOES_NOT_BEAT_FALLBACK",
        "failingGates": [k for k, g in gates.items() if not g["pass"]],
    }


# ── descriptive analyses ───────────────────────────────────────────────────────────────────────


def within_player_cv(player_weeks: Iterable[PlayerWeek], min_weeks: int = 4) -> dict[str, Any]:
    """D2: n-weighted mean of each (player, season)'s own-weeks CV, by family."""
    groups: dict[tuple[str, int], list[float]] = defaultdict(list)
    fam: dict[str, str] = {}
    for pw in player_weeks:
        if pw.status != APPEARED:
            continue
        groups[(pw.pid, pw.season)].append(float(pw.points or 0.0))
        fam[pw.pid] = pw.family
    acc: dict[str, list[tuple[float, int]]] = defaultdict(list)
    for (pid, _season), pts in groups.items():
        if len(pts) < min_weeks:
            continue
        mean = statistics.fmean(pts)
        if mean <= 0:
            continue
        acc[fam[pid]].append((statistics.pstdev(pts) / mean, len(pts)))
    out = {}
    for f in FAMILY_ORDER:
        items = acc.get(f) or []
        if not items:
            continue
        w = sum(n for _, n in items)
        out[f] = {
            "withinPlayerCv": round(sum(cv * n for cv, n in items) / w, 4),
            "playerSeasons": len(items),
            "playerWeeks": w,
        }
    return out


def scale_check_by_family(
    player_weeks: Iterable[PlayerWeek],
    ros: Mapping[str, float],
    k: float,
    weeks: set[tuple[int, int]],
) -> dict[str, Any]:
    """D6 (fit window): realized mean over ``mean(rosValue / k)`` by family — one scale for all?"""
    acc: dict[str, list[tuple[float, float]]] = defaultdict(list)
    for pw in player_weeks:
        if pw.status != APPEARED or (pw.season, pw.week) not in weeks:
            continue
        rv = float(ros.get(pw.pid) or 0.0)
        if rv <= 0:
            continue
        acc[pw.family].append((float(pw.points or 0.0), rv / k))
    out = {}
    for f in FAMILY_ORDER:
        items = acc.get(f) or []
        if not items:
            continue
        real = statistics.fmean(p for p, _ in items)
        pred = statistics.fmean(m for _, m in items)
        out[f] = {
            "n": len(items),
            "meanRealized": round(real, 3),
            "meanPredicted": round(pred, 3),
            "realizedOverPredicted": round(real / pred, 4) if pred > 0 else None,
        }
    return out


def raw_path_parity(
    rows: Iterable[tuple[Mapping[str, Any], float]], card: Mapping[str, Any]
) -> dict[str, Any]:
    """D3: ``score_stat_line(raw row, raw card)`` against host-native points."""
    n = 0
    off = 0
    max_abs = 0.0
    for row, host_pts in rows:
        n += 1
        raw = score_stat_line(row, card).total_points
        d = abs(raw - host_pts)
        max_abs = max(max_abs, d)
        if d > 0.01:
            off += 1
    return {"rows": n, "rowsOffBy>0.01": off, "maxAbsDelta": round(max_abs, 4)}


# ── driver ─────────────────────────────────────────────────────────────────────────────────────


def _census(player_weeks: Iterable[PlayerWeek]) -> dict[str, Any]:
    by_week: dict[str, Counter] = defaultdict(Counter)
    for pw in player_weeks:
        by_week[f"{pw.season}-w{pw.week:02d}"][pw.status] += 1
    total: Counter = Counter()
    for c in by_week.values():
        total.update(c)
    return {"total": dict(total), "byWeek": {k: dict(v) for k, v in sorted(by_week.items())}}


def run(args: argparse.Namespace) -> dict[str, Any]:
    split = preregistered_split()
    eval_weeks = tuple(int(w) for w in args.eval_weeks)
    for w in eval_weeks:
        if (SEASON, w) in set(split.fit):
            raise StudyRefusal(f"eval week {w} is a fit week")
    out_dir = assert_safe_output(Path(args.out_dir))
    candidate_path = assert_safe_output(out_dir / CANDIDATE_NAME)
    eval_path = assert_safe_output(out_dir / args.out_name)

    f = CachedFetcher(Path(args.cache_dir), offline=args.offline)
    league = f.get_json(f"{SLEEPER}/league/{LEAGUE_ID}")
    card = {str(k): float(v) for k, v in (league.get("scoring_settings") or {}).items()}
    fingerprint = scoring_fingerprint(league.get("scoring_settings"))
    if fingerprint != PINNED_SCORING_FINGERPRINT:
        raise StudyRefusal(
            f"live card fingerprint {fingerprint} != pinned {PINNED_SCORING_FINGERPRINT}: numbers void"
        )
    slots = starter_slots_from_roster_positions(league.get("roster_positions"))
    prev_id = str(league.get("previous_league_id") or "")
    if not prev_id:
        raise StudyRefusal("live league carries no previous_league_id; 2025 rosters unavailable")

    games = f.get_csv(NFLVERSE_GAMES, GAMES_CACHE)
    sched = schedule_by_week(games, SEASON)
    for w in eval_weeks:
        if w not in sched or not sched[w].is_final:
            s = sched.get(w)
            raise StudyRefusal(
                f"2026 week {w} is not final ({s.final_games if s else 0}/{s.games if s else 0} games): "
                "preregistration §2 admits only final weeks"
            )

    directory = f.get_json(f"{SLEEPER}/players/nfl")

    weeks_needed: list[tuple[int, int]] = list(split.fit) if not args.frozen_candidate else []
    weeks_needed += [(SEASON, w) for w in eval_weeks]
    stats: dict[tuple[int, int], dict[str, Any]] = {}
    for season in sorted({s for s, _ in weeks_needed}):
        wks = [w for s, w in weeks_needed if s == season]
        got = sc.fetch_stat_lines(str(season), wks, fetcher=f.get_json, sleep_s=0.0)
        missing = sorted(set(wks) - set(got))
        if missing:
            raise StudyRefusal(f"stat lines unavailable for {season} weeks {missing}")
        for w, body in got.items():
            stats[(season, w)] = body

    rosters: dict[tuple[int, int], dict[int, list[str]]] = {}
    for season, w in weeks_needed:
        lid = LEAGUE_ID if season == SEASON else prev_id
        rosters[(season, w)] = rostered_by_week(f.get_json(f"{SLEEPER}/league/{lid}/matchups/{w}"))

    player_weeks: list[PlayerWeek] = []
    raw_rows: dict[tuple[int, int, str], Mapping[str, Any]] = {}
    no_roster_weeks: list[str] = []
    for season, w in weeks_needed:
        body = stats[(season, w)]
        pids = sorted({p for lst in rosters[(season, w)].values() for p in lst})
        if not pids:
            no_roster_weeks.append(f"{season}-w{w:02d}")
            continue
        for pid in pids:
            row = body.get(pid)
            pw = classify_player_week(pid, row, directory.get(pid), card, season, w)
            player_weeks.append(pw)
            if row is not None:
                raw_rows[(season, w, pid)] = row

    snapshots: dict[str, dict[str, Any]] = {}

    def _snap(label: str, cutoff: datetime) -> list[dict[str, Any]]:
        p = snapshot_before(cutoff)
        snapshots[label] = {
            "file": p.relative_to(REPO).as_posix(),
            "sha256": sha256_file(p),
            "cutoffUtc": cutoff.isoformat(),
        }
        return load_snapshot_players(p)

    code = code_identity()
    if args.frozen_candidate:
        cand_src = Path(args.frozen_candidate)
        cand_sha = sha256_file(cand_src)
        if args.expect_sha256 and cand_sha != args.expect_sha256:
            raise StudyRefusal(
                f"frozen candidate sha256 {cand_sha} != expected {args.expect_sha256}"
            )
        candidate_model = sc.load_points_model(cand_src)
        candidate_record = {"path": cand_src.as_posix(), "sha256": cand_sha, "frozen": True}
        fit_block: dict[str, Any] = {"refit": False}
    else:
        pre_players = _snap("preseason", sched[1].first_kickoff_utc)
        fit26 = [(SEASON, w) for w in FIT_2026_WEEKS]
        preseason_ros: dict[str, float] = {}
        for key in fit26:
            for rows in as_of_full_rosters(rosters[key], directory, pre_players, slots).values():
                for r in rows:
                    if float(r.get("rosValue") or 0.0) > 0:
                        preseason_ros[str(r["playerId"])] = float(r["rosValue"])
        candidate, call_receipts = fit_candidate(player_weeks, preseason_ros, split)
        candidate["study"] = {
            "promotes": False,
            "status": "RESEARCH_CANDIDATE_NOT_SERVED",
            "preregistration": PREREGISTRATION,
            "preregistrationCommit": PREREGISTRATION_COMMIT,
            "cardFingerprint": fingerprint,
            "scorer": (
                "compute_weekly_points(source='sleeper'); the total enters build_calibration as the "
                f"one-key line {{{POINTS_KEY!r}: P}} with a unit rate, so score_stat_line returns P"
            ),
            "fitWeeks": [f"{s}-w{w:02d}" for s, w in split.fit],
            "composition": "byPosition from the variance call; scale from the scale call",
            "calls": call_receipts,
            "rosSnapshot": snapshots["preseason"],
            **code,
        }
        write_json(candidate_path, candidate)
        candidate_model = sc.load_points_model(candidate_path)
        candidate_record = {
            "path": candidate_path.relative_to(REPO).as_posix()
            if REPO in candidate_path.parents
            else candidate_path.as_posix(),
            "sha256": sha256_file(candidate_path),
            "frozen": False,
            "loadedSource": candidate_model.source,
        }
        fit_rows = [
            (raw_rows[(pw.season, pw.week, pw.pid)], float(pw.points or 0.0))
            for pw in player_weeks
            if pw.status == APPEARED and (pw.season, pw.week) in set(split.fit)
        ]
        fit_block = {
            "refit": True,
            "scale": candidate["scale"],
            "byPosition": candidate["byPosition"],
            "sampleSize": candidate["sampleSize"],
            "calls": call_receipts,
            "D2_withinPlayerCv": within_player_cv(
                pw for pw in player_weeks if (pw.season, pw.week) in set(split.fit)
            ),
            "D3_rawPathParity": raw_path_parity(fit_rows, card),
            "D6_scaleByFamilyFitWindow": {
                m: scale_check_by_family(player_weeks, preseason_ros, k, set(fit26))
                for m, k in (
                    ("C", float(candidate["scale"]["rosValuePerPoint"])),
                    ("F", sc.FALLBACK_ROS_VALUE_PER_POINT),
                )
            },
        }

    if candidate_model.source != "calibrated":
        raise StudyRefusal(
            f"candidate did not load as calibrated (source={candidate_model.source})"
        )
    fallback = sc.PointsModel()
    models = {"C": candidate_model, "F": fallback}

    # Point-in-time rosValue per evaluated week, via the production join.
    eval_rows: list[tuple[str, int, str, float, float]] = []
    unpriced = Counter()
    team_results: list[dict[str, Any]] = []
    team_results_all: list[dict[str, Any]] = []
    realized_checks = {"teamWeeks": 0, "matchWithin0.01": 0, "maxAbsDelta": 0.0}
    status_by = {(pw.season, pw.week, pw.pid): pw for pw in player_weeks}
    for w in eval_weeks:
        snap_players = _snap(f"week{w}", sched[w].first_kickoff_utc)
        full = as_of_full_rosters(rosters[(SEASON, w)], directory, snap_players, slots)
        matchups = f.get_json(f"{SLEEPER}/league/{LEAGUE_ID}/matchups/{w}")
        awarded = {int(m["roster_id"]): float(m.get("points") or 0.0) for m in matchups}
        for rid, rows in sorted(full.items()):
            roster_pids = rosters[(SEASON, w)][rid]
            # Realized cross-check: every rostered player with a scored host row (a DNP row is a
            # real 0 in best ball); a player with no row cannot have filled a slot with points.
            pts_by_pid = {
                pid: float(status_by[(SEASON, w, pid)].points)
                for pid in roster_pids
                if (SEASON, w, pid) in status_by and status_by[(SEASON, w, pid)].points is not None
            }
            pool_appeared = []
            for r in rows:
                pid = str(r["playerId"])
                pw = status_by.get((SEASON, w, pid))
                if pw is None or pw.status != APPEARED:
                    continue
                pool_appeared.append(r)
                rv = float(r.get("rosValue") or 0.0)
                if rv <= 0:
                    unpriced[f"{SEASON}-w{w:02d}"] += 1
                    continue
                eval_rows.append(
                    (
                        pid,
                        w,
                        str(r.get("position") or pw.position).upper(),
                        pw.family,
                        rv,
                        float(pw.points),
                    )
                )
            own = realized_best_ball_total(roster_pids, pts_by_pid, directory, slots)
            d = abs(own - awarded.get(rid, float("nan")))
            realized_checks["teamWeeks"] += 1
            if d <= 0.01:
                realized_checks["matchWithin0.01"] += 1
            realized_checks["maxAbsDelta"] = round(max(realized_checks["maxAbsDelta"], d), 4)
            seed = team_week_seed(w, rid)
            team_results.append(
                {
                    "realized": awarded[rid],
                    "draws": {
                        m: simulate_team_week(pool_appeared, slots, mod, seed, args.draws)
                        for m, mod in models.items()
                    },
                }
            )
            if not args.skip_sensitivity:
                team_results_all.append(
                    {
                        "realized": awarded[rid],
                        "draws": {
                            m: simulate_team_week(rows, slots, mod, seed, args.draws)
                            for m, mod in models.items()
                        },
                    }
                )

    scored = score_predictions(eval_rows, models)
    by_fam: dict[str, list[Scored]] = defaultdict(list)
    for r in scored:
        by_fam[r.family].append(r)
    player = {
        "pooled": summarize_group(scored, b=args.bootstrap, seed=SEED),
        "byFamily": {
            fam: summarize_group(by_fam[fam], b=args.bootstrap, seed=SEED)
            for fam in FAMILY_ORDER
            if by_fam.get(fam)
        },
    }
    team = team_week_metrics(team_results)
    decision = apply_gates(player, team)

    evaluation = {
        "schema": "sim-calibration-study/1",
        "promotes": False,
        "status": "RESEARCH_EVIDENCE_NOT_FOR_PROMOTION",
        "generatedAtUtc": datetime.now(timezone.utc).isoformat(),
        "preregistration": {"path": PREREGISTRATION, "commit": PREREGISTRATION_COMMIT},
        **code,
        "card": {
            "leagueKey": LEAGUE_KEY,
            "fingerprint": fingerprint,
            "pinned": PINNED_SCORING_FINGERPRINT,
            "source": f"GET /v1/league/{LEAGUE_ID} scoring_settings",
        },
        "split": {
            "fit": [f"{s}-w{w:02d}" for s, w in split.fit],
            "evaluated": [f"{SEASON}-w{w:02d}" for w in eval_weeks],
            "confirmation": [f"{s}-w{w:02d}" for s, w in split.confirm],
            "rostersWithoutPlayersExcludedWeeks": no_roster_weeks,
        },
        "seeds": {
            "seed": SEED,
            "bootstrapB": args.bootstrap,
            "teamWeekDraws": args.draws,
            "teamWeekSeed": "int(sha256(f'{seed}:{week}:{rosterId}')[:12], 16), shared by C and F",
        },
        "candidate": candidate_record,
        "models": {"C": candidate_model.to_dict(), "F": fallback.to_dict()},
        "fit": fit_block,
        "census": {
            "D5": _census(player_weeks),
            "evaluatedPlayerWeeks": len(scored),
            "unpricedEvaluatedPlayerWeeks": dict(unpriced),
        },
        "playerLevel": player,
        "teamWeek": {
            "pool": "oracle availability: rostered players who appeared that week",
            "realizedCrossCheck": realized_checks,
            **team,
        },
        "D4_teamWeekNoAvailabilityFilter": team_week_metrics(team_results_all)
        if team_results_all
        else None,
        **decision,
        "inputs": {
            "sleeperAndNflverseBodies": dict(sorted(f.receipts.items())),
            "rosSnapshots": snapshots,
            "networkCalls": f.network_calls,
        },
    }
    write_json(eval_path, evaluation)
    return evaluation


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    p.add_argument("--out-dir", default=str(OUT_DIR))
    p.add_argument("--out-name", default="evaluation.json")
    p.add_argument("--cache-dir", default=str(CACHE_DIR))
    p.add_argument("--offline", action="store_true", help="never touch the network")
    p.add_argument("--eval-weeks", nargs="+", type=int, default=list(HOLDOUT_2026_WEEKS))
    p.add_argument("--frozen-candidate", default=None, help="evaluate this file; no refit")
    p.add_argument(
        "--expect-sha256", default=None, help="refuse unless the frozen file hashes to this"
    )
    p.add_argument("--draws", type=int, default=TEAM_WEEK_DRAWS)
    p.add_argument("--bootstrap", type=int, default=BOOTSTRAP_B)
    p.add_argument("--skip-sensitivity", action="store_true", help="skip D4 (debug only)")
    return p


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        ev = run(args)
    except StudyRefusal as exc:
        print(f"REFUSED: {exc}", file=sys.stderr)
        return 2
    print(f"verdict: {ev['verdict']}  failing: {ev['failingGates']}")
    for k, g in ev["gates"].items():
        print(f"  {k}: {'PASS' if g['pass'] else 'FAIL'}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
