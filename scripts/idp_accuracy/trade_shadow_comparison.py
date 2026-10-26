#!/usr/bin/env python
"""IDP accuracy, Lane H: a SHADOW trade comparison that keeps three quantities apart.

Authority: ``docs/owner/IDP_VALUATION_ACCURACY_DIRECTIVE_2026-10-25.md`` section 12 under its
section 13 production-safety rules.  This script is research only.  It changes no served value,
rank, flag, weight, scoring rule, package model, fairness band, route or public output, writes only
its own evidence file and the gitignored cache, and nothing under ``src/`` imports it.

For a handful of example trades on the pinned board and the league's public Sleeper rosters it
prints three SEPARATELY NAMED quantities for each of the two teams.  They are never summed, scaled
into one another or reduced to an Accept/Decline answer:

``marketPrice``
    What the canonical market board says (``rankDerivedValue``), run through the existing package
    model (``src.valuation_math.package_model``, ACTIVE ``geom_q078_v1``) and the existing
    fairness bands.  Read only.  Value units.

``leagueUtility``
    What owning the player is expected to contribute under THIS league's scoring and lineup rules:
    shadow candidates C (projected points per game over the weakest started player) and D
    (expected league-average marginal best-ball points per week) from Lane F/G, as of the
    2026-09-09 cutoff, veterans only.  Uncalibrated, labelled SHADOW, per asset.  A player the
    candidates cannot score (a rookie has no prior-season production) is UNAVAILABLE, never 0.

``teamTransactionImpact``
    What the trade does to THIS roster: the whole-roster optimal best-ball lineup before and
    after, replayed over the league's real weeks 1-6 with the exact solver
    (``src.ros.lineup.solve_optimal_assignment``), plus the forced drops the existing capacity
    owner (``src.trade.roster_capacity``) names.  Hindsight replay, not a forecast.  Players
    compete for the same slots, so a package is never a sum of single-player effects, and the
    script shows how far the two differ.

The three have different units and different evidence.  Where they disagree, the disagreement is
the finding; the script does not arbitrate it.

Reproduce::

    python scripts/idp_accuracy/trade_shadow_comparison.py            # network once, then cached
    python scripts/idp_accuracy/trade_shadow_comparison.py --offline  # reuse the cache
    python scripts/idp_accuracy/trade_shadow_comparison.py --render-md

Artifacts hold aggregates and public NFL player names only: no manager, team, owner or roster
identifier and no raw Sleeper league id (``assert_public_safe``).
"""

from __future__ import annotations

import argparse
import hashlib
import json
import random
import subprocess
import sys
import tarfile
import tempfile
import time
import zipfile
from collections import Counter
from dataclasses import dataclass
from io import BytesIO
from pathlib import Path
from typing import Any, Callable, Iterable, Mapping, Sequence

REPO = Path(__file__).resolve().parents[2]
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

from src.draft.context import index_contract_rows  # noqa: E402
from src.league_comparison.sleeper_scoring import scoring_fingerprint  # noqa: E402
from src.nfl_data.realized_points import compute_weekly_points  # noqa: E402
from src.packages.construction import PackageAsset, topology_is_allowed  # noqa: E402
from src.ros.lineup import (  # noqa: E402
    OBJECTIVE_REALIZED_POINTS,
    RosterPlayer,
    lineup_position,
    solve_optimal_assignment,
    starter_slots_from_roster_positions,
)
from src.trade import roster_capacity as rc  # noqa: E402
from src.valuation_math import fairness_bands, package_model  # noqa: E402

# ── pins (task + Lane A manifest, PR #1931; change only with a new manifest) ──────────────────
LEAGUE_KEY = "dynasty_main"
SEASON = 2026
WEEKS = (1, 2, 3, 4, 5, 6)  # week 7 was in progress on 2026-10-25 and is excluded
ARCHIVE_NAME = "dynasty_export_20261025_120337.zip"
LANE_A_PINS = {
    "archiveSha256": "50fb251a79bc79abac54bcbcfc98c3018fc6b105115eb6dbd7928e3b6c8dc8f6",
    "servedBoardSha256": "4e6ba1f5c1695f5968e33d69aa26d5776e9587872e438ea8ea179baeed7d8712",
    "scoringFingerprint": "sf1:9e51824690d091f9",
    "repoSha": "bdbc83a1fba1b1278c7862362f9a18a2da69b970",
}
SEED = 20261026
SLEEPER = "https://api.sleeper.app/v1"
OFFENSE = ("QB", "RB", "WR", "TE")
IDP = ("DL", "LB", "DB")
EVIDENCE_PATH = REPO / "docs/valuation/idp_accuracy/evidence/h_trade_shadow_comparison.json"
DEFAULT_CACHE = REPO / "data/idp_accuracy/cache"
G_SCORES_REL = "docs/valuation/idp_accuracy/evidence/g_stage1_scores.json"
G_MANIFEST_REL = "docs/valuation/idp_accuracy/evidence/g_stage1_manifest.json"
G_BRANCH_REF = "origin/claude/idp-g-backtest"

#: Declared PRIORs of the example selection, all outcome-free (set before any result was read).
MIN_ASSET_VALUE = 2000.0  # a starter-relevant asset, in rankDerivedValue units
MIN_STAR_VALUE = 4000.0
MIN_DEPTH_VALUE = 1500.0
MIN_IDP_ROOKIE_VALUE = 3000.0
MAX_DRAWS = 400_000
KEEP_FAIR = 64
#: A team delta smaller than this many lineup points per week is reported as "no change".
NO_CHANGE_PTS = 0.05

SCARCITY_NOTE = "research: league scarcity not read (the live multiplier is inert at 1.0)"


# ── data classes ──────────────────────────────────────────────────────────────────────────────
@dataclass(frozen=True)
class Asset:
    """One rostered player as the three quantities see him."""

    sid: str
    name: str
    position: str  # lineup vocabulary: QB RB WR TE K DL LB DB (or "" when unknown)
    fantasy_positions: tuple[str, ...]
    value: float | None  # canonical rankDerivedValue; None = the board declined to price him
    rank: int | None
    confidence: str | None
    quarantined: bool
    #: the board row that the capacity owner would find by NAME is this same player
    name_join_safe: bool

    @property
    def is_offense(self) -> bool:
        return self.position in OFFENSE

    @property
    def is_idp(self) -> bool:
        return self.position in IDP


@dataclass(frozen=True)
class Roster:
    index: int  # internal only, never published
    assets: tuple[Asset, ...]
    team: Mapping[str, Any]  # aligned {"players": names, "playerIds": ids} for the capacity owner


@dataclass(frozen=True)
class LeagueRules:
    slots: tuple[str, ...]
    slot_eligibility: Mapping[str, Any] | None
    roster_limit: int | None
    #: the league's roster settings, handed to the capacity owner explicitly (it would otherwise
    #: look them up by key, which a hermetic test registry cannot answer)
    roster_settings: Mapping[str, Any] | None = None


@dataclass(frozen=True)
class Trade:
    spec_id: str
    a_index: int  # roster of side A (gives ``give``, receives ``recv``)
    b_index: int
    give: tuple[Asset, ...]
    recv: tuple[Asset, ...]

    @property
    def key(self) -> str:
        g = ",".join(sorted(a.sid for a in self.give))
        r = ",".join(sorted(a.sid for a in self.recv))
        return f"{self.spec_id}|{self.a_index}|{g}>{self.b_index}|{r}"


# ── polite cached public GETs ─────────────────────────────────────────────────────────────────
class Fetcher:
    """Public, unauthenticated Sleeper GETs, throttled under 5/s, each body cached once."""

    MIN_INTERVAL_S = 0.25

    def __init__(self, cache_dir: Path, league_id: str, *, offline: bool = False) -> None:
        self.cache_dir = cache_dir
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        self.league_id = league_id
        self.offline = offline
        self._session: Any = None
        self._last = 0.0
        self.receipts: dict[str, dict[str, Any]] = {}

    def _path(self, url: str) -> Path:
        return self.cache_dir / f"{hashlib.sha256(url.encode()).hexdigest()[:24]}.json"

    def get(self, url: str, label: str) -> Any:
        path = self._path(url)
        if not path.exists():
            if self.offline:
                raise RuntimeError(f"offline and not cached: {label}")
            import requests  # noqa: PLC0415 — only when the network is actually used

            self._session = self._session or requests.Session()
            wait = self.MIN_INTERVAL_S - (time.time() - self._last)
            if wait > 0:
                time.sleep(wait)
            resp = self._session.get(url, timeout=60)
            self._last = time.time()
            resp.raise_for_status()
            path.write_bytes(resp.content)
        blob = path.read_bytes()
        # the receipt names the endpoint, never the URL: the URL carries the league id
        self.receipts[label] = {
            "sha256": hashlib.sha256(blob).hexdigest(),
            "bytes": len(blob),
            "cachedAtUtc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(path.stat().st_mtime)),
        }
        return json.loads(blob)

    def stats(self, week: int) -> dict:
        return self.get(f"{SLEEPER}/stats/nfl/regular/{SEASON}/{week}", f"stats/{SEASON}/{week}")

    def matchups(self, week: int) -> list:
        return self.get(f"{SLEEPER}/league/{self.league_id}/matchups/{week}", f"matchups/{week}")

    def rosters(self) -> list:
        return self.get(f"{SLEEPER}/league/{self.league_id}/rosters", "rosters")


# ── the pinned served board ───────────────────────────────────────────────────────────────────
_BOARD_RUNNER = """\
import json, sys, zipfile
from pathlib import Path
tree, archive, out = Path(sys.argv[1]), Path(sys.argv[2]), Path(sys.argv[3])
sys.path.insert(0, str(tree))
with zipfile.ZipFile(archive) as zf:
    name = next(n for n in zf.namelist() if n.startswith("dynasty_data_") and n.endswith(".json"))
    raw = json.loads(zf.read(name))
from src.api.data_contract import build_api_data_contract
out.write_text(json.dumps(build_api_data_contract(raw), default=str), encoding="utf-8")
"""


class PinnedTreeUnavailable(RuntimeError):
    """The pinned commit cannot be reached, so the pinned board cannot be rebuilt."""


def sha256_bytes(blob: bytes) -> str:
    return hashlib.sha256(blob).hexdigest()


def read_archive_raw(path: Path) -> dict:
    with zipfile.ZipFile(path) as zf:
        name = next(
            n for n in zf.namelist() if n.startswith("dynasty_data_") and n.endswith(".json")
        )
        return json.loads(zf.read(name))


def build_contract_at_tree(archive: Path, tree_sha: str) -> dict:
    """Rebuild the served board from the archive under the repository tree of ``tree_sha``.

    The contract builder reads ``CSVs/``, ``config/`` and the dataset-state directory from its own
    tree, and the tree moves every two hours (CSV refreshes, Hill promotions).  Lane A pinned the
    board by building it in a clean worktree at ``tree_sha``; this does the same from a ``git
    archive`` of exactly the four paths the build reads, in a subprocess so the pinned ``src`` never
    mixes with this checkout's.  The result is a plain JSON dict.
    """
    with tempfile.TemporaryDirectory(prefix="idp_h_board_") as td:
        work = Path(td)
        tree = work / "tree"
        tree.mkdir()
        proc = subprocess.run(
            [
                "git",
                "archive",
                "--format=tar",
                tree_sha,
                "src",
                "config",
                "CSVs",
                "data/scrape_state",
            ],
            cwd=REPO,
            capture_output=True,
            check=False,
        )
        if proc.returncode != 0:
            raise PinnedTreeUnavailable(
                f"git archive {tree_sha[:9]} failed: {proc.stderr.decode(errors='replace')[:200]}"
            )
        with tarfile.open(fileobj=BytesIO(proc.stdout)) as tf:
            tf.extractall(tree, filter="data")  # our own archive output, not untrusted input
        runner = work / "board_runner.py"
        runner.write_text(_BOARD_RUNNER, encoding="utf-8")
        out = work / "contract.json"
        env = {"PYTHONUTF8": "1", "PYTHONPATH": str(tree), "PATH": _env("PATH")}
        for key in ("SystemRoot", "TEMP", "TMP", "HOME", "USERPROFILE"):
            if _env(key):
                env[key] = _env(key)
        run = subprocess.run(
            [sys.executable, str(runner), str(tree), str(archive), str(out)],
            cwd=tree,
            env=env,
            capture_output=True,
            check=False,
        )
        if run.returncode != 0 or not out.exists():
            raise PinnedTreeUnavailable(
                f"pinned board build failed: {run.stderr.decode(errors='replace')[-300:]}"
            )
        return json.loads(out.read_text(encoding="utf-8"))


def _env(key: str) -> str:
    import os  # noqa: PLC0415

    return os.environ.get(key, "")


def build_contract_here(archive: Path) -> dict:
    """The board as THIS checkout's tree builds it (drifts with every data refresh)."""
    from src.api.data_contract import build_api_data_contract  # noqa: PLC0415

    return build_api_data_contract(read_archive_raw(archive))


def served_board_sha256(contract: Mapping[str, Any]) -> str:
    """Lane A's ``servedBoardSha256`` definition, so the two pins are comparable."""
    rows = contract.get("playersArray") or []
    key = sorted(
        (
            str(r.get("displayName")),
            str(r.get("playerId") or ""),
            r.get("rankDerivedValue"),
            r.get("canonicalConsensusRank"),
            r.get("confidenceBucket"),
            bool(r.get("quarantined")),
        )
        for r in rows
    )
    return sha256_bytes(json.dumps(key, sort_keys=True, separators=(",", ":")).encode())


# ── rosters and assets ────────────────────────────────────────────────────────────────────────
def _norm(value: Any) -> str:
    return str(value or "").strip().lower()


def load_assets(contract: Mapping[str, Any]) -> tuple[dict[str, Asset], list[Roster], dict]:
    """Every rostered player as an :class:`Asset`, joined by Sleeper ID and never by name.

    ``sleeper.teams[].players`` (names) and ``playerIds`` are not parallel lists in the contract, so
    the names handed to the capacity owner are rebuilt from the ids through ``sleeper.idToPlayer``.
    """
    sl = contract.get("sleeper") or {}
    id_to_name = {str(k): str(v) for k, v in (sl.get("idToPlayer") or {}).items()}
    dup_names = {n for n, c in Counter(id_to_name.values()).items() if c > 1}
    by_id, by_name = index_contract_rows(contract)
    positions = sl.get("positions") or {}
    fantasy = sl.get("fantasyPositions") or {}

    assets: dict[str, Asset] = {}
    rosters: list[Roster] = []
    census = Counter()
    teams = sorted(
        (t for t in (sl.get("teams") or []) if isinstance(t, Mapping)),
        key=lambda t: (int(t.get("roster_id") or 0), str(t.get("ownerId") or "")),
    )
    for idx, team in enumerate(teams):
        ids = [str(i) for i in (team.get("playerIds") or []) if str(i or "").strip()]
        members: list[Asset] = []
        names: list[str] = []
        for sid in ids:
            asset = assets.get(sid)
            if asset is None:
                name = id_to_name.get(sid, sid)
                row = by_id.get(_norm(sid))
                pos_raw = (row or {}).get("position") if row else None
                if not pos_raw and name not in dup_names:
                    pos_raw = positions.get(name)
                position = lineup_position(str(pos_raw or ""))
                fp_raw = (row or {}).get("fantasyPositions") if row else None
                if not fp_raw and name not in dup_names:
                    fp_raw = fantasy.get(name)
                fp = (
                    tuple(str(p).upper() for p in fp_raw)
                    if isinstance(fp_raw, (list, tuple))
                    else ()
                )
                value = (row or {}).get("rankDerivedValue") if row else None
                priced = (
                    isinstance(value, (int, float)) and not isinstance(value, bool) and value > 0
                )
                name_row = by_name.get(_norm(row.get("displayName") if row else name))
                safe = bool(row) and name_row is not None and str(name_row.get("playerId")) == sid
                asset = Asset(
                    sid=sid,
                    name=str((row or {}).get("displayName") or name) if row else name,
                    position=position,
                    fantasy_positions=fp,
                    value=float(value) if priced else None,
                    rank=(row or {}).get("canonicalConsensusRank") if row else None,
                    confidence=(row or {}).get("confidenceBucket") if row else None,
                    quarantined=bool((row or {}).get("quarantined")) if row else False,
                    name_join_safe=safe,
                )
                assets[sid] = asset
                census["rostered"] += 1
                census["priced"] += int(priced)
                census["noBoardRow"] += int(row is None)
                census["positionUnknown"] += int(not position)
                census["nameJoinDisagrees"] += int(not safe)
            members.append(asset)
            names.append(asset.name)
        rosters.append(
            Roster(
                index=idx,
                assets=tuple(members),
                team={"players": names, "playerIds": ids},
            )
        )
    return assets, rosters, dict(census)


# ── weekly points (host-native scorer over Sleeper's own stat lines) ──────────────────────────
@dataclass(frozen=True)
class PointsTable:
    by_week: Mapping[int, Mapping[str, float]]
    played: Mapping[int, frozenset[str]]

    def ppg(self, sid: str) -> float | None:
        """Points per game PLAYED; ``None`` (not 0) for a player with no game in the window."""
        vals = [self.by_week[w][sid] for w in self.by_week if sid in self.played[w]]
        return sum(vals) / len(vals) if vals else None


def score_weeks(
    fetcher: Fetcher,
    scoring: Mapping[str, Any],
    assets: Mapping[str, Asset],
    weeks: Sequence[int] = WEEKS,
) -> tuple[PointsTable, dict]:
    """League-scored points for every rostered player and week.

    A rostered player with no stat line that week scores 0.0: the host's own lineup rule (Lane A:
    461 rostered player-weeks without a line were all awarded 0.0, and the solver reproduces the
    host's best-ball totals only with it).  It is modelled for REALISED weeks only and is counted.
    """
    by_week: dict[int, dict[str, float]] = {}
    played: dict[int, frozenset[str]] = {}
    no_line = scored = 0
    for w in weeks:
        stats = fetcher.stats(w) or {}
        pts: dict[str, float] = {}
        seen: set[str] = set()
        for sid, asset in assets.items():
            line = stats.get(sid)
            gp = (line or {}).get("gp") if line else None
            if not line or (gp is not None and float(gp) <= 0):
                pts[sid] = 0.0
                no_line += 1
                continue
            row = dict(line)
            row.update({"player_id": sid, "season": SEASON, "week": w})
            res = compute_weekly_points(
                row, dict(scoring), position=asset.position, source="sleeper"
            )
            if res is None:
                pts[sid] = 0.0
                no_line += 1
                continue
            pts[sid] = float(res.fantasy_points)
            seen.add(sid)
            scored += 1
        by_week[w] = pts
        played[w] = frozenset(seen)
    return PointsTable(by_week, played), {
        "scoredPlayerWeeks": scored,
        "zeroFilledPlayerWeeks": no_line,
    }


# ── lineup replay (the exact owner solver; no second engine) ──────────────────────────────────
def _assign(
    assets: Iterable[Asset], values: Mapping[str, float | None], rules: LeagueRules
) -> Mapping[int, RosterPlayer]:
    pool = [
        RosterPlayer(
            player_id=a.sid,
            canonical_name=a.name,
            position=a.position,
            ros_value=values.get(a.sid),
            fantasy_positions=a.fantasy_positions,
        )
        for a in assets
    ]
    return solve_optimal_assignment(
        pool,
        list(rules.slots),
        slot_eligibility=rules.slot_eligibility,
        objective=OBJECTIVE_REALIZED_POINTS,
    )


def lineup_solve(
    assets: Iterable[Asset], values: Mapping[str, float | None], rules: LeagueRules
) -> tuple[float, list[str]]:
    """``(total, started ids)`` of the optimal best-ball lineup for ``values``.

    ``None`` is an UNKNOWN objective: that player is not assignable, never a zero.
    """
    assignment = _assign(assets, values, rules)
    started = [p.player_id for p in assignment.values()]
    return sum(float(p.ros_value) for p in assignment.values()), started


def lineup_filled(
    assets: Iterable[Asset], values: Mapping[str, float | None], rules: LeagueRules
) -> int:
    """How many starting slots the roster can fill (the ladder's own legality measure)."""
    return len(_assign(assets, values, rules))


def replay(
    assets: Sequence[Asset], points: PointsTable, rules: LeagueRules
) -> tuple[list[float], list[list[str]]]:
    totals: list[float] = []
    started: list[list[str]] = []
    for w in sorted(points.by_week):
        total, ids = lineup_solve(assets, points.by_week[w], rules)
        totals.append(total)
        started.append(ids)
    return totals, started


def _mean(xs: Sequence[float]) -> float:
    return sum(xs) / len(xs)


def _without(roster: Sequence[Asset], remove: Sequence[Asset]) -> list[Asset]:
    """Remove by multiplicity: two entries sharing an id are two spots, one removal takes one."""
    pending = Counter(a.sid for a in remove)
    kept: list[Asset] = []
    for a in roster:
        if pending.get(a.sid, 0) > 0:
            pending[a.sid] -= 1
            continue
        kept.append(a)
    return kept


def sum_of_single_moves(
    before: Sequence[Asset],
    give: Sequence[Asset],
    recv: Sequence[Asset],
    points: PointsTable,
    rules: LeagueRules,
    before_totals: Sequence[float],
) -> list[float]:
    """Per week, the sum of each move taken ALONE from the same starting roster.

    Adding one received player to the unchanged roster, plus removing one given player from the
    unchanged roster, summed.  Players that compete for a slot do not add, so this differs from
    the whole-roster delta exactly when the package interacts with itself.
    """
    out: list[float] = []
    for w_i, w in enumerate(sorted(points.by_week)):
        wk = points.by_week[w]
        per_week = 0.0
        for a in recv:
            per_week += lineup_solve([*before, a], wk, rules)[0] - before_totals[w_i]
        for g in give:
            per_week += lineup_solve(_without(before, [g]), wk, rules)[0] - before_totals[w_i]
        out.append(per_week)
    return out


# ── the three quantities ──────────────────────────────────────────────────────────────────────
def market_price(give: Sequence[Asset], recv: Sequence[Asset]) -> dict:
    """Quantity 1: the canonical market reading, from this team's own perspective.

    ``adjusted_pair_totals(G, R)`` is the same call the live engines make; the gap is
    ``receiveAdjusted - sendAdjusted``.  An unpriced asset refuses the reading (never a zero).
    """
    block: dict[str, Any] = {
        "quantity": "Market Price",
        "status": "canonical, read-only (rankDerivedValue through the live package model)",
        "valueScale": "rankDerivedValue (1-9999)",
        "packageModel": package_model.receipt()["id"],
        "fairnessBands": fairness_bands.receipt().get("version", None),
    }
    unpriced = [a.name for a in (*give, *recv) if a.value is None]
    if unpriced:
        return {**block, "state": "unpriced_asset", "unpricedAssets": unpriced}
    gv = [a.value for a in give]
    rv = [a.value for a in recv]
    send_adj, recv_adj, send_va, recv_va = package_model.adjusted_pair_totals(gv, rv)
    gap = recv_adj - send_adj
    band = fairness_bands.classify_packages(gap, gv, rv)
    return {
        **block,
        "state": "priced",
        "sendRaw": round(sum(gv), 1),
        "receiveRaw": round(sum(rv), 1),
        "sendValueAdjustment": round(send_va, 1),
        "receiveValueAdjustment": round(recv_va, 1),
        "sendAdjusted": round(send_adj, 1),
        "receiveAdjusted": round(recv_adj, 1),
        "gap": round(gap, 1),
        "gapMeaning": "receiveAdjusted - sendAdjusted; positive = this team receives more",
        "band": {k: band[k] for k in ("level", "label", "relativePct")},
    }


@dataclass(frozen=True)
class UtilityRow:
    sid: str
    c: float | None
    d: float | None
    d_se: float | None
    reason: str | None  # why it is unavailable (None when scored)


def load_league_utility(
    scores_path: Path | None = None, git_ref: str | None = None
) -> tuple[dict[str, UtilityRow], dict]:
    """Candidate C and D scores from Lane G's blind-stage vectors (cutoff 2026-09-09).

    Read from ``scores_path`` if given, else this checkout's copy, else ``git show <git_ref>``.
    Returns ``({}, source with state "unavailable")`` when none exists: the caller then reports
    League Utility as unavailable for every asset rather than inventing numbers.
    """
    blob: bytes | None = None
    origin = ""
    candidates = [scores_path] if scores_path else [REPO / G_SCORES_REL]
    for path in candidates:
        if path and Path(path).exists():
            blob, origin = Path(path).read_bytes(), str(Path(path).as_posix()).split("/")[-1]
            break
    if blob is None and git_ref:
        proc = subprocess.run(
            ["git", "show", f"{git_ref}:{G_SCORES_REL}"], cwd=REPO, capture_output=True, check=False
        )
        if proc.returncode == 0 and proc.stdout:
            blob, origin = proc.stdout, f"git:{git_ref}"
    if blob is None:
        return {}, {"state": "unavailable", "reason": "Lane G score vectors not found"}
    return parse_league_utility(blob, origin)


def parse_league_utility(blob: bytes, origin: str) -> tuple[dict[str, UtilityRow], dict]:
    data = json.loads(blob)
    vectors = data.get("vectors") or {}
    c_vec, d_vec, se_vec = vectors.get("C") or {}, vectors.get("D") or {}, vectors.get("D_se") or {}
    table: dict[str, UtilityRow] = {}
    for p in data.get("players") or []:
        sid = str(p.get("id"))
        c, d = c_vec.get(sid), d_vec.get(sid)
        reason = None
        if d is None:
            reason = str(p.get("projectionStatus") or "not_scored")
            if p.get("projectionStatus") == "projected":
                reason = "D_undefined_no_team_schedule"
        table[sid] = UtilityRow(sid, c, d, se_vec.get(sid), reason)
    return table, {
        "state": "available",
        "origin": origin,
        "sha256": sha256_bytes(blob),
        "preregistration": data.get("preregistration"),
        "window": data.get("window"),
        "promotes": data.get("promotes"),
        "candidates": "C = projected ppg over the D1 starter threshold; "
        "D = expected league-average marginal best-ball points per week",
        "cutoff": "2026-09-09 (latest archive before the first 2026 kickoff); veterans only",
        "vectorsFile": data.get("vectorSha256", {}).get("D"),
        "scoredC": len(c_vec),
        "scoredD": len(d_vec),
        "players": len(table),
    }


def utility_for(sid: str, table: Mapping[str, UtilityRow]) -> UtilityRow:
    row = table.get(sid)
    if row is not None:
        return row
    return UtilityRow(sid, None, None, None, "not_in_cutoff_universe")


def league_utility(
    give: Sequence[Asset], recv: Sequence[Asset], table: Mapping[str, UtilityRow]
) -> dict:
    """Quantity 2: shadow league utility per asset, never summed into a verdict.

    The side totals are the NAIVE sum of per-asset values, shown only because they are the
    asset-level quantity; they are not roster-aware (players compete for the same slots) and they
    are withheld whenever any asset on either side is unscored.
    """

    def per_asset(a: Asset) -> dict:
        row = utility_for(a.sid, table)
        return {
            "name": a.name,
            "position": a.position,
            "state": "scored" if row.d is not None else "unavailable",
            "C": None if row.c is None else round(row.c, 2),
            "D": None if row.d is None else round(row.d, 2),
            "DStandardError": None if row.d_se is None else round(row.d_se, 2),
            "reason": row.reason,
        }

    gives = [per_asset(a) for a in give]
    recvs = [per_asset(a) for a in recv]
    complete = all(x["state"] == "scored" for x in (*gives, *recvs))
    counts_differ = len(gives) != len(recvs)
    c_complete = complete and all(x["C"] is not None for x in (*gives, *recvs))
    net_d = net_c = None
    if complete:
        net_d = round(sum(x["D"] for x in recvs) - sum(x["D"] for x in gives), 2)
    if c_complete:
        net_c = round(sum(x["C"] for x in recvs) - sum(x["C"] for x in gives), 2)
    return {
        "quantity": "League Utility",
        "status": "SHADOW, uncalibrated, not served (Lane F/G candidates C and D)",
        "units": {
            "C": "projected league points per game over the weakest started player at the position",
            "D": "expected league-average marginal best-ball points per week",
        },
        "give": gives,
        "receive": recvs,
        "complete": complete,
        "net": {
            "D": net_d,
            "C": net_c,
            "additive": False,
            "countsDiffer": counts_differ,
            "meaning": "receive minus give of per-asset values; NOT roster-aware, so a naive sum"
            if complete
            else "withheld: an asset on one side has no score (unavailable is never zero)",
            "bias": "players competing for the same slots have diminishing returns, so a naive "
            "sum favours the side that receives more players; read Team Transaction Impact"
            if counts_differ
            else None,
        },
    }


def team_transaction_impact(
    contract: Mapping[str, Any],
    roster: Roster,
    give: Sequence[Asset],
    recv: Sequence[Asset],
    assets: Mapping[str, Asset],
    points: PointsTable,
    rules: LeagueRules,
) -> dict:
    """Quantity 3: what the trade does to ONE roster, with the existing owners read-only."""
    ctx = rc.build_capacity_context(
        contract,
        LEAGUE_KEY,
        roster.team,
        roster_settings=rules.roster_settings,
        scarcity_reading=(None, SCARCITY_NOTE),
    )
    out_names = rc.outgoing_roster_names(ctx, [a.name for a in give], [a.sid for a in give])
    in_names = [a.name for a in recv]
    cap = rc.assess_roster_capacity(ctx, incoming_players=in_names, outgoing_players=out_names)

    before = list(roster.assets)
    landed = [*_without(before, give), *recv]
    drops: list[dict] = []
    drop_assets: list[Asset] = []
    for d in cap.forced_drops:
        drops.append(_forced_drop_row(d, assets))
        asset = assets.get(str(d.player_id))
        if asset is not None and any(x.sid == asset.sid for x in landed):
            drop_assets.append(asset)
    final = _without(landed, drop_assets)

    b_tot, b_start = replay(before, points, rules)
    l_tot, _ = replay(landed, points, rules)
    f_tot, f_start = replay(final, points, rules)
    weekly = [round(f - b, 2) for f, b in zip(f_tot, b_tot)]

    single_deltas = sum_of_single_moves(before, give, recv, points, rules, b_tot)

    ppg = {a.sid: points.ppg(a.sid) for a in {*before, *landed}}
    avg_before = lineup_solve(before, ppg, rules)[0]
    avg_final = lineup_solve(final, ppg, rules)[0]
    n_weeks = len(b_tot)
    return {
        "quantity": "Team Transaction Impact",
        "status": "read-only replay of the league's real weeks 1-6 on the exact solver (hindsight)",
        "unit": "optimal best-ball lineup points per week, mean of weeks 1-6",
        "bestBallReplay": {
            "rosterSizes": {"before": len(before), "landed": len(landed), "final": len(final)},
            "before": round(_mean(b_tot), 2),
            "landed": round(_mean(l_tot), 2),
            "final": round(_mean(f_tot), 2),
            "delta": round(_mean(f_tot) - _mean(b_tot), 2),
            "deltaBeforeCleanup": round(_mean(l_tot) - _mean(b_tot), 2),
            "weeklyDelta": weekly,
            "weeksImproved": sum(1 for x in weekly if x > NO_CHANGE_PTS),
            "weeksWorsened": sum(1 for x in weekly if x < -NO_CHANGE_PTS),
            "weeks": n_weeks,
            "sumOfSingleMoveDeltas": round(_mean(single_deltas), 2),
            "packageMinusSum": round(_mean(l_tot) - _mean(b_tot) - _mean(single_deltas), 2),
        },
        "averageWeekReading": {
            "before": round(avg_before, 2),
            "final": round(avg_final, 2),
            "delta": round(avg_final - avg_before, 2),
            "note": "each player at his points per game played: no weekly spread, so no "
            "best-ball depth value (a player with no game is unassignable, not zero)",
        },
        "startedWeeks": {
            **{a.name: sum(a.sid in ids for ids in b_start) for a in give},
            **{a.name: sum(a.sid in ids for ids in f_start) for a in recv},
        },
        "startedWeeksMeaning": "weeks (of 6) each gave-away player started for the BEFORE roster "
        "and each received player starts for the FINAL roster",
        "capacity": {
            "rosterLimit": cap.roster_limit,
            "sizeBefore": cap.size_before,
            "sizeAfter": cap.size_after,
            "overLimitAfter": cap.over_limit_after,
            "requiresDrops": cap.requires_drops,
            "certainty": cap.certainty,
            "forcedDrops": drops,
            "forcedDropsMissingFromRoster": len(cap.forced_drops) - len(drop_assets),
            "rungOrderWasTied": bool(cap.rung_order_was_tied),
            "selectionRule": cap.selection_rule,
            "owner": "src.trade.roster_capacity.assess_roster_capacity (read-only)",
        },
        "isVerdict": False,
    }


def _forced_drop_row(d: Any, assets: Mapping[str, Asset]) -> dict:
    asset = assets.get(str(d.player_id))
    return {
        "name": d.name,
        "position": d.position,
        "boardValue": None if d.value is None else round(float(d.value), 1),
        "releaseCost": round(float(d.release_cost), 1),
        "effectiveCutCost": round(float(d.effective_cut_cost), 1),
        "valueBasis": d.value_basis,
        "rung": d.rung,
        "acquiredInTrade": bool(d.acquired_in_trade),
        "rosterIdKnown": asset is not None,
    }


# ── example categories and seeded selection ───────────────────────────────────────────────────
@dataclass(frozen=True)
class CategorySpec:
    id: str
    label: str
    n_give: int
    n_recv: int
    give_ok: Callable[[Asset, Mapping[str, UtilityRow]], bool]
    recv_ok: Callable[[Asset, Mapping[str, UtilityRow]], bool]
    joint_ok: Callable[[Sequence[Asset], Sequence[Asset]], bool] | None = None
    #: side A must already be at the roster limit, so the trade forces a cut
    needs_full_roster: bool = False


def _scored(a: Asset, u: Mapping[str, UtilityRow]) -> bool:
    return utility_for(a.sid, u).d is not None


def _unscored(a: Asset, u: Mapping[str, UtilityRow]) -> bool:
    return utility_for(a.sid, u).d is None


def _at_least(a: Asset, floor: float) -> bool:
    return a.value is not None and a.value >= floor


def _same_group(give: Sequence[Asset], recv: Sequence[Asset]) -> bool:
    groups = {lineup_position(a.position) for a in (*give, *recv)}
    return len(groups) == 1 and next(iter(groups)) != ""


def _upgrade(give: Sequence[Asset], recv: Sequence[Asset]) -> bool:
    return _same_group(give, recv) and recv[0].value > max(a.value for a in give)


def _depth(give: Sequence[Asset], recv: Sequence[Asset]) -> bool:
    return all(r.value < give[0].value for r in recv)


CATEGORIES: tuple[CategorySpec, ...] = (
    CategorySpec(
        "offense_for_idp_1for1",
        "offense for IDP (both scored by the shadow candidates)",
        1,
        1,
        lambda a, u: a.is_offense and _at_least(a, MIN_ASSET_VALUE) and _scored(a, u),
        lambda a, u: a.is_idp and _at_least(a, MIN_ASSET_VALUE) and _scored(a, u),
    ),
    CategorySpec(
        "offense_for_idp_rookie_1for1",
        "offense for an IDP the shadow candidates cannot score (a rookie)",
        1,
        1,
        lambda a, u: a.is_offense and _at_least(a, MIN_ASSET_VALUE) and _scored(a, u),
        lambda a, u: a.is_idp and _at_least(a, MIN_IDP_ROOKIE_VALUE) and _unscored(a, u),
    ),
    CategorySpec(
        "offense_for_idp_2for1",
        "two offense players for one IDP (consolidation across the position divide)",
        2,
        1,
        lambda a, u: a.is_offense and _at_least(a, MIN_DEPTH_VALUE) and _scored(a, u),
        lambda a, u: a.is_idp and _at_least(a, MIN_STAR_VALUE) and _scored(a, u),
    ),
    CategorySpec(
        "starter_upgrade_2for1",
        "starter upgrade: two same-position players for one better one",
        2,
        1,
        lambda a, u: a.position in (*OFFENSE, *IDP)
        and _at_least(a, MIN_ASSET_VALUE)
        and _scored(a, u),
        lambda a, u: a.position in (*OFFENSE, *IDP)
        and _at_least(a, MIN_STAR_VALUE)
        and _scored(a, u),
        joint_ok=_upgrade,
    ),
    CategorySpec(
        "depth_package_1for2",
        "depth package: one star for two mid-value players",
        1,
        2,
        lambda a, u: a.position in (*OFFENSE, *IDP)
        and _at_least(a, MIN_STAR_VALUE)
        and _scored(a, u),
        lambda a, u: a.position in (*OFFENSE, *IDP)
        and _at_least(a, MIN_DEPTH_VALUE)
        and _scored(a, u),
        joint_ok=_depth,
    ),
    CategorySpec(
        "cut_requiring_2for3",
        "cut-requiring: two for three, side A starts at the roster limit",
        2,
        3,
        lambda a, u: a.position in (*OFFENSE, *IDP)
        and _at_least(a, MIN_DEPTH_VALUE)
        and _scored(a, u),
        lambda a, u: a.position in (*OFFENSE, *IDP)
        and _at_least(a, MIN_DEPTH_VALUE)
        and _scored(a, u),
        needs_full_roster=True,
    ),
)


def _topology_ok(give: Sequence[Asset], recv: Sequence[Asset]) -> bool:
    """The live generators' shape rule (``construction.topology_is_allowed``), reused."""

    def pkg(xs: Sequence[Asset]) -> list[PackageAsset]:
        return [PackageAsset(a.sid, a.name, a.position, a.value) for a in xs]

    return topology_is_allowed(pkg(give), pkg(recv))


def sample_trade(
    spec: CategorySpec,
    rosters: Sequence[Roster],
    utility: Mapping[str, UtilityRow],
    rules: LeagueRules,
    *,
    seed: int = SEED,
    max_draws: int = MAX_DRAWS,
    keep: int = KEEP_FAIR,
) -> tuple[Trade | None, dict]:
    """A seeded, outcome-free draw of trades the market calls FAIR; the SHA-first one is taken.

    Trades are drawn uniformly from the category's structural universe (ordered pairs of rosters,
    assets passing the category's value and scoring filters), kept when the live fairness band
    calls them ``fair``, and the survivor with the smallest ``sha256(trade key)`` is the example.
    Nothing about replay outcomes, lineup movement or the size of any disagreement is read, so the
    examples are a sample, not a showcase.
    """
    rng = random.Random(f"{seed}:{spec.id}")
    give_pool = [
        sorted((a for a in r.assets if _eligible(a) and spec.give_ok(a, utility)), key=_sid_key)
        for r in rosters
    ]
    recv_pool = [
        sorted((a for a in r.assets if _eligible(a) and spec.recv_ok(a, utility)), key=_sid_key)
        for r in rosters
    ]
    full = [rules.roster_limit is not None and len(r.assets) >= rules.roster_limit for r in rosters]
    fair: list[Trade] = []
    drawn = structural = 0
    for _ in range(max_draws):
        if len(fair) >= keep:
            break
        drawn += 1
        a_i, b_i = rng.sample(range(len(rosters)), 2)
        if spec.needs_full_roster and not full[a_i]:
            continue
        if len(give_pool[a_i]) < spec.n_give or len(recv_pool[b_i]) < spec.n_recv:
            continue
        give = tuple(rng.sample(give_pool[a_i], spec.n_give))
        recv = tuple(rng.sample(recv_pool[b_i], spec.n_recv))
        if spec.joint_ok is not None and not spec.joint_ok(give, recv):
            continue
        if not _topology_ok(give, recv):
            continue
        structural += 1
        reading = market_price(give, recv)
        if reading.get("state") == "priced" and reading["band"]["level"] == "fair":
            fair.append(Trade(spec.id, a_i, b_i, give, recv))
    summary = {
        "category": spec.id,
        "seed": f"{seed}:{spec.id}",
        "draws": drawn,
        "structurallyValid": structural,
        "marketFairKept": len(fair),
        "keepLimit": keep,
    }
    if not fair:
        return None, summary
    chosen = min(fair, key=lambda t: hashlib.sha256(t.key.encode()).hexdigest())
    summary["fairCandidateSet"] = _candidate_set_summary(fair, utility)
    return chosen, summary


def _eligible(a: Asset) -> bool:
    return a.value is not None and not a.quarantined and a.name_join_safe and bool(a.position)


def _sid_key(a: Asset) -> tuple[int, str]:
    return (int(a.sid), a.sid) if a.sid.isdigit() else (10**12, a.sid)


def _candidate_set_summary(fair: Sequence[Trade], utility: Mapping[str, UtilityRow]) -> dict:
    """How the League Utility net splits across the market-fair candidates that were drawn."""
    nets = []
    for t in fair:
        block = league_utility(t.give, t.recv, utility)
        if block["net"]["D"] is not None:
            nets.append(block["net"]["D"])
    if not nets:
        return {"n": len(fair), "withNetD": 0}
    return {
        "n": len(fair),
        "withNetD": len(nets),
        "shareSideAGainsD": round(sum(1 for x in nets if x > 0) / len(nets), 3),
        "meaning": "share of the drawn market-FAIR candidates whose receive-minus-give D is "
        "positive for side A; a seeded sample, not a population estimate",
    }


# ── example assembly ──────────────────────────────────────────────────────────────────────────
def asset_row(a: Asset) -> dict:
    return {
        "name": a.name,
        "position": a.position,
        "boardValue": None if a.value is None else round(a.value, 1),
        "boardRank": a.rank,
        "confidence": a.confidence,
    }


def build_example(
    label: str,
    spec: CategorySpec,
    trade: Trade,
    contract: Mapping[str, Any],
    rosters: Sequence[Roster],
    assets: Mapping[str, Asset],
    points: PointsTable,
    utility: Mapping[str, UtilityRow],
    rules: LeagueRules,
    selection: Mapping[str, Any],
) -> dict:
    sides: dict[str, Any] = {}
    for side, idx, give, recv in (
        ("A", trade.a_index, trade.give, trade.recv),
        ("B", trade.b_index, trade.recv, trade.give),
    ):
        sides[side] = {
            "gives": [asset_row(a) for a in give],
            "receives": [asset_row(a) for a in recv],
            "marketPrice": market_price(give, recv),
            "leagueUtility": league_utility(give, recv, utility),
            "teamTransactionImpact": team_transaction_impact(
                contract, rosters[idx], give, recv, assets, points, rules
            ),
        }
    return {
        "id": label,
        "category": spec.id,
        "description": spec.label,
        "shape": f"{len(trade.give)}-for-{len(trade.recv)}",
        "selection": dict(selection),
        "sides": sides,
        "readout": readout(sides),
        "isVerdict": False,
    }


def readout(sides: Mapping[str, Mapping[str, Any]]) -> dict:
    """What each quantity says, side by side.  It compares nothing across quantities."""
    a, b = sides["A"], sides["B"]
    market = a["marketPrice"]
    lu_net = a["leagueUtility"]["net"]["D"]
    ti_a = a["teamTransactionImpact"]["bestBallReplay"]["delta"]
    ti_b = b["teamTransactionImpact"]["bestBallReplay"]["delta"]

    def sign(x: float | None) -> str:
        if x is None:
            return "unavailable"
        return "even" if abs(x) <= NO_CHANGE_PTS else ("A" if x > 0 else "B")

    market_says = (
        "unavailable"
        if market.get("state") != "priced"
        else ("even" if market["band"]["level"] == "fair" else ("A" if market["gap"] > 0 else "B"))
    )
    return {
        "marketPrice": {
            "favours": market_says,
            "band": None if market.get("state") != "priced" else market["band"]["label"],
        },
        "leagueUtilityD": {"favours": sign(lu_net), "netForA": lu_net},
        "teamTransactionImpact": {
            "deltaA": ti_a,
            "deltaB": ti_b,
            "pattern": _impact_pattern(ti_a, ti_b),
        },
        "note": "descriptive only: three different units and three different evidence bases",
    }


def _impact_pattern(da: float, db: float) -> str:
    ups = [x > NO_CHANGE_PTS for x in (da, db)]
    downs = [x < -NO_CHANGE_PTS for x in (da, db)]
    if all(ups):
        return "both rosters gain lineup points"
    if all(downs):
        return "both rosters lose lineup points"
    if ups[0] and downs[1]:
        return "A gains and B loses"
    if ups[1] and downs[0]:
        return "B gains and A loses"
    if not any(ups) and not any(downs):
        return "neither lineup moves"
    return "one lineup moves, the other does not"


# ── preconditions: the replay inputs agree with the host ──────────────────────────────────────
def reconcile_scorer(
    points: PointsTable,
    matchups: Mapping[int, Sequence[Mapping[str, Any]]],
    assets: Mapping[str, Asset],
) -> dict:
    n = within = unscored = 0
    worst = 0.0
    for w, entries in matchups.items():
        for m in entries:
            for sid, awarded in (m.get("players_points") or {}).items():
                if sid not in assets or sid not in points.by_week.get(w, {}):
                    continue
                if sid not in points.played[w]:
                    unscored += int(abs(float(awarded)) > 0.005)
                    continue
                diff = abs(points.by_week[w][sid] - float(awarded))
                n += 1
                within += int(diff <= 0.01)
                worst = max(worst, diff)
    return {
        "playerWeeksCompared": n,
        "within0_01": within,
        "maxAbsDiff": round(worst, 4),
        "hostAwardedNonzeroWithoutALine": unscored,
    }


def reconcile_solver(
    matchups: Mapping[int, Sequence[Mapping[str, Any]]],
    assets: Mapping[str, Asset],
    rules: LeagueRules,
) -> dict:
    """The exact solver, fed the host's own per-player points, against the host's team totals."""
    qualifying = matched = 0
    worst = 0.0
    for entries in matchups.values():
        for m in entries:
            ids = [str(i) for i in (m.get("players") or [])]
            if not ids or any(i not in assets for i in ids):
                continue
            values = {i: float(v) for i, v in (m.get("players_points") or {}).items()}
            total, _ = lineup_solve([assets[i] for i in ids], values, rules)
            diff = abs(total - float(m.get("points") or 0.0))
            qualifying += 1
            matched += int(diff <= 0.015)
            worst = max(worst, diff)
    return {
        "teamWeeksQualifying": qualifying,
        "within0_015": matched,
        "maxAbsDiff": round(worst, 4),
    }


# ── public-artifact hygiene ───────────────────────────────────────────────────────────────────
FORBIDDEN_KEYS = frozenset(
    {
        "ownerId",
        "owner_id",
        "roster_id",
        "rosterId",
        "sleeperTeamName",
        "teamName",
        "team_name",
        "username",
        "user_id",
        "leagueId",
        "league_id",
        "leagueName",
    }
)


def forbidden_values(contract: Mapping[str, Any]) -> list[str]:
    sl = contract.get("sleeper") or {}
    values = {str(sl.get("leagueId") or ""), str(sl.get("leagueName") or "")}
    for t in sl.get("teams") or []:
        for key in ("name", "sleeperTeamName", "ownerId"):
            values.add(str(t.get(key) or ""))
    return sorted(v for v in values if len(v) >= 5)


def assert_public_safe(payload: Any, forbidden: Iterable[str] = ()) -> None:
    """Refuse a payload that carries a manager, team, owner, roster or league identifier."""

    def walk(o: Any) -> None:
        if isinstance(o, Mapping):
            bad = FORBIDDEN_KEYS.intersection(o)
            if bad:
                raise ValueError(f"private key in public artifact: {sorted(bad)}")
            for v in o.values():
                walk(v)
        elif isinstance(o, (list, tuple)):
            for v in o:
                walk(v)

    walk(payload)
    text = json.dumps(payload, default=str)
    for value in forbidden:
        if value and value in text:
            raise ValueError("private value in public artifact")


# ── report ────────────────────────────────────────────────────────────────────────────────────
def coverage_census(
    rosters: Sequence[Roster], utility: Mapping[str, UtilityRow]
) -> dict[str, dict[str, Any]]:
    """Of the priced rostered players, how many does the shadow League Utility score?"""
    out: dict[str, dict[str, Any]] = {}
    for pos in (*OFFENSE, *IDP):
        priced = [a for r in rosters for a in r.assets if a.position == pos and a.value]
        scored = [a for a in priced if utility_for(a.sid, utility).d is not None]
        top = sorted(priced, key=lambda a: -(a.value or 0))[:25]
        out[pos] = {
            "pricedRostered": len(priced),
            "scored": len(scored),
            "scoredShare": round(len(scored) / len(priced), 3) if priced else None,
            "top25ByValueScored": sum(utility_for(a.sid, utility).d is not None for a in top),
            "top25ByValue": len(top),
        }
    return out


def cut_cost_in_lineup_points(
    base: Sequence[Asset], cut: Asset, points: PointsTable, rules: LeagueRules
) -> tuple[float, bool]:
    """``(mean lineup points a week lost by releasing ``cut``, whether the cut is slot-legal)``.

    Legal in the ladder's own sense: the surviving roster still fills as many starting slots as
    before in every replayed week.  The ladder guards that count, not the points.
    """
    after = _without(base, [cut])
    lost: list[float] = []
    legal = True
    for w in sorted(points.by_week):
        wk = points.by_week[w]
        lost.append(lineup_solve(base, wk, rules)[0] - lineup_solve(after, wk, rules)[0])
        legal = legal and lineup_filled(after, wk, rules) == lineup_filled(base, wk, rules)
    return _mean(lost), legal


def cut_ladder_tie_census(
    contract: Mapping[str, Any],
    rosters: Sequence[Roster],
    assets: Mapping[str, Asset],
    points: PointsTable,
    rules: LeagueRules,
) -> dict:
    """How the incumbent cut ladder breaks ties on the 12 real rosters (owner decision, #1937).

    With the cheapest-legal flag OFF the ladder sorts by ``(effective cut cost, name)``.  Effective
    cut cost is 0 for every player at or below his position's waiver level, so on a full roster the
    first cut is the alphabetically first of a large tied set.  For each roster this asks the
    capacity owner for the real first cut (one hypothetical incoming player, nobody leaving),
    recomputes the tied set from the owner's own cost function, and compares the chosen player
    with the rest of the tied set on release cost and on replayed best-ball lineup points.
    Aggregates only: no roster is identified.
    """
    from src.draft import displacement as dis  # noqa: PLC0415
    from src.trade import forced_drop_selection as fds  # noqa: PLC0415

    values = sorted(
        (a for a in assets.values() if _eligible(a)), key=lambda a: (-(a.value or 0), a.sid)
    )
    sizes: list[int] = []
    excess: list[float] = []
    unpriced_share: list[float] = []
    chosen_lineup: list[float] = []
    cheapest_legal_lineup: list[float] = []
    matches = tied_rosters = free_alternative = 0
    for roster in rosters:
        held = {a.sid for a in roster.assets}
        probe = next((a for a in values if a.sid not in held), None)
        if probe is None:
            continue
        ctx = rc.build_capacity_context(
            contract,
            LEAGUE_KEY,
            roster.team,
            roster_settings=rules.roster_settings,
            scarcity_reading=(None, SCARCITY_NOTE),
        )
        cap = rc.assess_roster_capacity(ctx, incoming_players=[probe.name], outgoing_players=[])
        if not cap.forced_drops:
            continue
        costed = []
        for ra in ctx.assets_by_key.values():
            ecc, base, basis, _waiver, mult = dis.effective_cut_cost(
                ra, ctx.waiver_values, ctx.scarcity
            )
            costed.append((ecc, ra.name.lower(), base * mult, basis, str(ra.player_id)))
        low = min(c[0] for c in costed)
        tied = [c for c in costed if c[0] == low]
        first = min(tied, key=lambda c: c[1])
        chosen = cap.forced_drops[0]
        matches += int(chosen.name.lower() == first[1])
        if len(tied) < 2:
            continue
        tied_rosters += 1
        sizes.append(len(tied))
        excess.append(float(chosen.release_cost) - min(c[2] for c in tied))
        unpriced_share.append(sum(1 for c in tied if c[3] != "board") / len(tied))
        # the replayed lineup cost of each tied cut, on the roster AFTER the incoming player lands
        base_roster = [*roster.assets, probe]
        legal_costs = []
        chosen_cost = None
        for c in tied:
            asset = assets.get(c[4])
            if asset is None:
                continue
            cost, legal = cut_cost_in_lineup_points(base_roster, asset, points, rules)
            if legal:
                legal_costs.append(cost)
            if c[4] == str(chosen.player_id):
                chosen_cost = cost
        if chosen_cost is not None and legal_costs:
            chosen_lineup.append(chosen_cost)
            cheapest_legal_lineup.append(min(legal_costs))
            free_alternative += int(min(legal_costs) < 0.01)
    ordered = sorted(sizes)
    return {
        "rule": "incumbent ladder, flag forced_drop_cheapest_legal "
        + ("ON" if fds.enabled() else "OFF"),
        "tieBreak": "asset.name.lower() among equal effective cut cost (src/draft/displacement.py)",
        "rosters": len(rosters),
        "rostersWithATiedFirstCut": tied_rosters,
        "firstCutIsAlphabeticallyFirstOfTheTiedSet": matches,
        "tiedSetSize": {
            "min": ordered[0] if ordered else None,
            "median": ordered[len(ordered) // 2] if ordered else None,
            "max": ordered[-1] if ordered else None,
        },
        "chosenReleaseCostMinusCheapestInTiedSet": {
            "rostersWhereChosenIsNotTheCheapest": sum(1 for x in excess if x > 0.5),
            "mean": round(sum(excess) / len(excess), 1) if excess else None,
            "max": round(max(excess), 1) if excess else None,
            "unit": "rankDerivedValue (release cost = base value x scarcity multiplier 1.0)",
        },
        "replayedLineupPointsLostByTheChosenCut": {
            "rostersMeasured": len(chosen_lineup),
            "rostersWhereTheChosenCutCostsPoints": sum(1 for x in chosen_lineup if x >= 0.01),
            "mean": round(_mean(chosen_lineup), 2) if chosen_lineup else None,
            "max": round(max(chosen_lineup), 2) if chosen_lineup else None,
            "rostersWhoseTiedSetHoldsALegalCutThatCostsNothing": free_alternative,
            "cheapestLegalCutInTheTiedSetMean": (
                round(_mean(cheapest_legal_lineup), 2) if cheapest_legal_lineup else None
            ),
            "unit": "best-ball lineup points per week, weeks 1-6 replay, after the incoming "
            "player lands; legal = the roster still fills as many starting slots",
        },
        "unpricedShareOfTiedSetMean": (
            round(sum(unpriced_share) / len(unpriced_share), 3) if unpriced_share else None
        ),
        "lineupGuardIgnored": "the tied set ignores the ladder's lineup-feasibility guard, which "
        "protects the COUNT of fillable starting slots (a kicker is the usual casualty), not "
        "best-ball points; the real first cut, from the owner, is what is compared",
        "ownerSignalLimit": "capacity.rungOrderWasTied is True only when two or more FORCED drops "
        "tie each other, so a single forced drop never reports a tie even when dozens of "
        "candidates were tied; this census measures that",
        "note": "the cheapest-legal flag path already ties on player id; this is the default path, "
        "which Perfect Draft also uses",
    }


def head_sha() -> str | None:
    proc = subprocess.run(
        ["git", "rev-parse", "HEAD"], cwd=REPO, capture_output=True, text=True, check=False
    )
    return proc.stdout.strip() or None if proc.returncode == 0 else None


def build_report(args: argparse.Namespace) -> dict:
    from src.api import league_registry  # noqa: PLC0415

    archive = Path(args.archive)
    archive_sha = sha256_bytes(archive.read_bytes())
    pinned = args.board_tree != "head"
    tree_note: dict[str, Any]
    if pinned:
        try:
            contract = build_contract_at_tree(archive, args.board_tree)
            tree_note = {"tree": args.board_tree, "pinned": True}
        except PinnedTreeUnavailable as exc:
            print(f"WARNING: {exc}; falling back to this checkout's tree", file=sys.stderr)
            contract = build_contract_here(archive)
            tree_note = {"tree": "head", "pinned": False, "pinnedFailure": str(exc)[:160]}
    else:
        contract = build_contract_here(archive)
        tree_note = {"tree": "head", "pinned": False}

    sl = contract.get("sleeper") or {}
    league_id = str(sl.get("leagueId") or "")
    registry_id = league_registry.get_sleeper_league_id(LEAGUE_KEY)
    if not league_id or league_id != str(registry_id):
        raise SystemExit("the archive's league is not the registry's dynasty_main; refusing")
    scoring = sl.get("scoringSettings") or {}
    fingerprint = scoring_fingerprint(scoring)

    assets, rosters, census = load_assets(contract)
    team_sizes = sorted(len(r.assets) for r in rosters)
    roster_settings = league_registry.get_league_roster_settings(LEAGUE_KEY)
    probe = rc.build_capacity_context(
        contract,
        LEAGUE_KEY,
        rosters[0].team,
        roster_settings=roster_settings,
        scarcity_reading=(None, SCARCITY_NOTE),
    )
    rules = LeagueRules(
        probe.starter_slots, probe.slot_eligibility, probe.roster_limit, roster_settings
    )
    sleeper_slots = tuple(starter_slots_from_roster_positions(sl.get("rosterPositions")))

    fetcher = Fetcher(Path(args.cache_dir), league_id, offline=args.offline)
    points, point_meta = score_weeks(fetcher, scoring, assets)
    matchups = {w: fetcher.matchups(w) for w in WEEKS}
    live = fetcher.rosters()
    live_ids = {str(i) for r in live for i in (r.get("players") or [])}
    arch_ids = set(assets)

    utility, utility_src = load_league_utility(
        Path(args.scores) if args.scores else None, args.scores_git_ref
    )

    examples: list[dict] = []
    selections: list[dict] = []
    for n, spec in enumerate(CATEGORIES, start=1):
        trade, sel = sample_trade(spec, rosters, utility, rules)
        selections.append(sel)
        if trade is None:
            continue
        examples.append(
            build_example(
                f"T{n}", spec, trade, contract, rosters, assets, points, utility, rules, sel
            )
        )

    report = {
        "label": "H_trade_shadow_comparison",
        "promotes": False,
        "authority": "docs/owner/IDP_VALUATION_ACCURACY_DIRECTIVE_2026-10-25.md section 12",
        "generatedBy": "scripts/idp_accuracy/trade_shadow_comparison.py",
        "inputs": {
            "headShaAtRun": head_sha(),
            "archive": {"name": ARCHIVE_NAME, "sha256": archive_sha},
            "servedBoard": {
                **tree_note,
                "rows": len(contract.get("playersArray") or []),
                "pricedRows": sum(
                    1
                    for r in contract.get("playersArray") or []
                    if (r.get("rankDerivedValue") or 0) > 0
                ),
                "servedBoardSha256": served_board_sha256(contract),
            },
            "laneAPins": LANE_A_PINS,
            "laneAAgreement": {
                "archiveSha256": archive_sha == LANE_A_PINS["archiveSha256"],
                "servedBoardSha256": served_board_sha256(contract)
                == LANE_A_PINS["servedBoardSha256"],
                "scoringFingerprint": fingerprint == LANE_A_PINS["scoringFingerprint"],
            },
            "league": {
                "leagueKey": LEAGUE_KEY,
                "scoringFingerprint": fingerprint,
                "teams": len(rosters),
                "rosterSizes": team_sizes,
                "rosterLimit": rules.roster_limit,
                "rosterSettingsUsed": {
                    k: (rules.roster_settings or {}).get(k)
                    for k in ("teamCount", "rosterSize", "taxiSize", "starters")
                },
                "starterSlots": list(rules.slots),
                "slotsAgreeWithSleeperRosterPositions": tuple(rules.slots) == sleeper_slots,
            },
            "rosters": {
                "source": "the archive's Sleeper block (public /rosters, captured "
                f"{sl.get('rosterFetchedAt')})",
                "rosteredPlayers": len(assets),
                "census": census,
                "liveCrossCheck": {
                    "liveRosteredPlayers": len(live_ids),
                    "inBoth": len(live_ids & arch_ids),
                    "onlyInArchive": len(arch_ids - live_ids),
                    "onlyInLive": len(live_ids - arch_ids),
                    "note": "public /rosters fetched now vs the pinned snapshot; the examples "
                    "use the pinned snapshot so the board and the rosters agree",
                },
            },
            "weeklyPoints": {
                "weeks": list(WEEKS),
                "scorer": "src.nfl_data.realized_points.compute_weekly_points(source='sleeper')",
                **point_meta,
                "scorerCheckVsHostAwardedPoints": reconcile_scorer(points, matchups, assets),
                "solverCheckVsHostTeamTotals": reconcile_solver(matchups, assets, rules),
            },
            "leagueUtilitySource": utility_src,
            "packageModel": package_model.receipt(),
            "fairnessBands": fairness_bands.receipt(),
            "datasets": fetcher.receipts,
        },
        "leagueUtilityCoverage": coverage_census(rosters, utility),
        "cutLadderTieCensus": cut_ladder_tie_census(contract, rosters, assets, points, rules),
        "selection": {
            "method": "seeded draws of trades from each category's structural universe, kept when "
            "the live fairness band calls them FAIR; the smallest sha256 of the trade key is the "
            "example. Outcome-free: no replay result enters the choice.",
            "seed": SEED,
            "priors": {
                "minAssetValue": MIN_ASSET_VALUE,
                "minStarValue": MIN_STAR_VALUE,
                "minDepthValue": MIN_DEPTH_VALUE,
                "minIdpRookieValue": MIN_IDP_ROOKIE_VALUE,
            },
            "perCategory": selections,
        },
        "examples": examples,
        "limits": LIMITS,
    }
    assert_public_safe(report, forbidden_values(contract))
    return report


LIMITS = [
    "Examples are a seeded sample of trades the market calls FAIR, one per category; they show "
    "how the three quantities can differ, not how often.",
    "Market Price is the 2026-10-25 board; League Utility is the 2026-09-09 cutoff projection "
    "prior (veterans only; rookies and players without a prior season are UNAVAILABLE); the "
    "replay is weeks 1-6 of 2026. Three dates, three evidence bases.",
    "Team Transaction Impact is a hindsight replay of six realised weeks (Lane B measured "
    "in-sample lineup gains at about four times what walking forward realises). It is not a "
    "forecast and carries no interval.",
    "The replay uses today's rosters over weeks 1-6, so a player acquired mid-season is credited "
    "for weeks he spent elsewhere, and a missing stat line scores 0.0 as the host does.",
    "League Utility sums are naive per-asset sums, withheld when any asset is unscored, and "
    "biased toward the side that receives more players when the counts differ.",
    "Forced drops come from the live capacity owner with league scarcity unread (the live "
    "multiplier is inert at 1.0); the flag-gated cheapest-legal rule is whatever the checkout "
    "defaults to, stated per example.",
    "Nothing here is an Accept/Decline answer, a served value or a promotion.",
]


# ── markdown ──────────────────────────────────────────────────────────────────────────────────
def _fmt(x: Any, nd: int = 1, plus: bool = False) -> str:
    if x is None:
        return "n/a"
    x = round(x, nd) + 0.0  # no "-0.00"
    return f"{x:+,.{nd}f}" if plus else f"{x:,.{nd}f}"


def _names(rows: Sequence[Mapping[str, Any]]) -> str:
    return ", ".join(
        f"{r['name']} ({r['position']}"
        + (f", {r['boardValue']:,.0f}" if r.get("boardValue") else ", unpriced")
        + ")"
        for r in rows
    )


def render_markdown(report: Mapping[str, Any]) -> str:
    """The generated results block of ``H_RECOMMENDATIONS.md`` (a test pins it to the evidence)."""
    lines: list[str] = []
    for ex in report["examples"]:
        a, b = ex["sides"]["A"], ex["sides"]["B"]
        lines.append(f"**{ex['id']} - {ex['description']} ({ex['shape']})**")
        lines.append("")
        lines.append(f"Side A gives {_names(a['gives'])}; side B gives {_names(b['gives'])}.")
        lines.append("")
        lines.append("| quantity | side A | side B |")
        lines.append("|---|---|---|")
        ma, mb = a["marketPrice"], b["marketPrice"]
        if ma.get("state") == "priced":
            lines.append(
                f"| Market Price: receive minus send, adjusted (value units, canonical) | "
                f"{_fmt(ma['gap'], 0, True)} | {_fmt(mb['gap'], 0, True)} |"
            )
            lines.append(
                f"| Market Price: fairness band | {ma['band']['label']} | {mb['band']['label']} |"
            )
        la, lb = a["leagueUtility"], b["leagueUtility"]
        lines.append(
            "| League Utility (SHADOW): net D, receive minus give, pts/wk | "
            f"{_fmt(la['net']['D'], 2, True)} | {_fmt(lb['net']['D'], 2, True)} |"
        )
        ta, tb = a["teamTransactionImpact"], b["teamTransactionImpact"]
        ra, rb = ta["bestBallReplay"], tb["bestBallReplay"]
        lines.append(
            "| Team Transaction Impact: lineup pts/wk before to final (replay wk 1-6) | "
            f"{_fmt(ra['before'], 2)} to {_fmt(ra['final'], 2)} ({_fmt(ra['delta'], 2, True)}) | "
            f"{_fmt(rb['before'], 2)} to {_fmt(rb['final'], 2)} ({_fmt(rb['delta'], 2, True)}) |"
        )
        lines.append(
            "| Team Transaction Impact: weeks improved / worsened | "
            f"{ra['weeksImproved']} / {ra['weeksWorsened']} | {rb['weeksImproved']} / {rb['weeksWorsened']} |"
        )
        lines.append(
            "| Team Transaction Impact: whole package minus sum of single moves | "
            f"{_fmt(ra['packageMinusSum'], 2, True)} | {_fmt(rb['packageMinusSum'], 2, True)} |"
        )
        da, db = ta["capacity"], tb["capacity"]
        lines.append("| Forced drops (capacity owner) | " f"{_drops(da)} | {_drops(db)} |")
        lines.append("")
        if la["net"]["countsDiffer"] and la["complete"]:
            lines.append(
                "League Utility net is a naive per-asset sum; with unequal player counts it "
                "favours the side that receives more players."
            )
            lines.append("")
        unscored = [
            r["name"]
            for s in (la, lb)
            for r in (*s["give"], *s["receive"])
            if r["state"] != "scored"
        ]
        if unscored:
            lines.append(
                "League Utility is UNAVAILABLE for: "
                + ", ".join(sorted(set(unscored)))
                + " (no prior-season production; never scored as 0)."
            )
            lines.append("")
        r = ex["readout"]
        lines.append(
            f"Readout: {_market_phrase(r['marketPrice'])}; "
            f"{_utility_phrase(r['leagueUtilityD']['favours'])}; "
            f"Team Transaction Impact: {r['teamTransactionImpact']['pattern']}."
        )
        lines.append("")
    return "\n".join(lines).rstrip() + "\n"


def _market_phrase(m: Mapping[str, Any]) -> str:
    if m["favours"] == "unavailable":
        return "Market Price is unavailable"
    if m["favours"] == "even":
        return f"Market Price reads {m['band']}"
    return f"Market Price favours side {m['favours']} ({m['band']})"


def _utility_phrase(favours: str) -> str:
    if favours == "unavailable":
        return "League Utility D is unavailable"
    if favours == "even":
        return "League Utility D reads even"
    return f"League Utility D (naive sum) favours side {favours}"


def _drops(cap: Mapping[str, Any]) -> str:
    drops = cap["forcedDrops"]
    if not drops:
        return "none"
    return "; ".join(
        f"{d['name']} ({d['position']}, "
        + ("unpriced" if d["boardValue"] is None else f"{d['boardValue']:,.0f}")
        + f", rung {d['rung']})"
        for d in drops
    )


# ── CLI ───────────────────────────────────────────────────────────────────────────────────────
DOC_PATH = REPO / "docs/valuation/idp_accuracy/H_RECOMMENDATIONS.md"
DOC_START, DOC_END = "<!-- table:shadow -->", "<!-- /table:shadow -->"


def write_evidence(report: Mapping[str, Any], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(report, indent=1, ensure_ascii=False) + "\n", encoding="utf-8")


def write_doc_block(report: Mapping[str, Any], path: Path = DOC_PATH) -> None:
    """Replace the generated results block of the recommendations page with the evidence's."""
    text = path.read_text(encoding="utf-8")
    if DOC_START not in text or DOC_END not in text:
        raise SystemExit(f"{path} has no {DOC_START} block to refresh")
    head, rest = text.split(DOC_START, 1)
    _, tail = rest.split(DOC_END, 1)
    block = render_markdown(report).strip("\n")
    path.write_text(f"{head}{DOC_START}\n{block}\n{DOC_END}{tail}", encoding="utf-8")


def main(argv: Sequence[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--archive", default=str(REPO / "exports/archive" / ARCHIVE_NAME))
    ap.add_argument("--cache-dir", default=str(DEFAULT_CACHE))
    ap.add_argument("--offline", action="store_true", help="reuse cached Sleeper bodies only")
    ap.add_argument(
        "--board-tree",
        default=LANE_A_PINS["repoSha"],
        help="commit whose tree builds the served board ('head' = this checkout)",
    )
    ap.add_argument("--scores", default=None, help="path to Lane G g_stage1_scores.json")
    ap.add_argument(
        "--scores-git-ref", default=G_BRANCH_REF, help="git ref to read the scores from"
    )
    ap.add_argument("--out", default=str(EVIDENCE_PATH))
    ap.add_argument("--render-md", action="store_true", help="print the markdown results block")
    ap.add_argument("--write-doc", action="store_true", help="refresh the page's generated block")
    ap.add_argument("--no-write", action="store_true", help="do not write the evidence file")
    args = ap.parse_args(argv)

    report = build_report(args)
    if not args.no_write:
        write_evidence(report, Path(args.out))
        print(f"wrote {args.out}", file=sys.stderr)
    if args.write_doc:
        write_doc_block(report)
        print(f"refreshed {DOC_PATH}", file=sys.stderr)
    if args.render_md:
        sys.stdout.write(render_markdown(report))
    else:
        print(
            json.dumps(
                {
                    "examples": [e["id"] for e in report["examples"]],
                    "laneAAgreement": report["inputs"]["laneAAgreement"],
                },
                indent=1,
            )
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
