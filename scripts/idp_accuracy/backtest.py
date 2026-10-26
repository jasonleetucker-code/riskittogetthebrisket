#!/usr/bin/env python3
"""IDP accuracy Lane G: the near-term retrospective backtest (SHADOW, research only).

Executes ``docs/valuation/idp_accuracy/G_PREREGISTRATION.md`` (frozen at commit
``4c53736fb``, blob ``a60ae89c8``) exactly as written.  Nothing here changes a served
value, rank, flag, source weight, anchor or behaviour; no production module imports it;
every artifact carries ``promotes: false``.

Two stages, in the preregistered order (section 12):

``stage1``  BLIND.  Resolves the cutoff, builds every admissible input, computes every
            candidate score, the reference R0 and the cohort, and writes
            ``g_stage1_manifest.json`` + ``g_stage1_scores.json``.  No 2026 week 1-6
            outcome is loaded into the process: the Sleeper fetcher REFUSES the
            outcome URLs while stage 1 runs.
``stage2``  UNBLIND, once.  Checks the scorer and lineup preconditions, verifies the
            score-vector hashes against the committed manifest, joins the outcomes and
            computes every metric, test, guard, stability variant and slice.

Public artifacts carry aggregates and public NFL player names only
(``assert_public_artifact``); per-team detail never leaves the gitignored cache.

The shadow modules are loaded BY FILE PATH because ``tests/league_valuation/test_isolation.py``
pins that no ``scripts/`` file contains an ``import`` of ``src.league_valuation`` (the same
arrangement as ``scripts/idp_accuracy/replacement_report.py``).  ``src/bestball`` is not
used: ``tests/bestball/test_import_graph.py`` forbids importing it from ``scripts/``, and
preregistration section 4.5 defines D without a waiver-replacement scenario, so the exact
solver in ``src/ros/lineup.py`` is called directly.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import importlib.util
import json
import math
import os
import re
import subprocess
import sys
import time
import zipfile
from collections import Counter, defaultdict
from collections.abc import Mapping, Sequence
from concurrent.futures import ProcessPoolExecutor
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

import numpy as np

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO))

# ── pinned identities (the preregistration, section 0 / 15) ───────────────────

PREREG_PATH = "docs/valuation/idp_accuracy/G_PREREGISTRATION.md"
PREREG_COMMIT = "4c53736fb478cf0d158f86185db0eb82c67f03e9"
PREREG_BLOB = "a60ae89c80617c2837a5ed1d8a0fe90248d9751e"
# PR #1942 was squash-merged, so on ``main`` the preregistration's first commit
# is the squash commit below, not ``PREREG_COMMIT``. ``PREREG_COMMIT``, which
# sits before the blind stage and the results, stays auditable in PR #1942's
# commit list. The blob pin and the unchanged-since check are what freeze the
# content, and both still apply.
PREREG_SQUASH_COMMIT = "22a2ac8f8ce61c5a9ef994b14c67caf04a0e84d5"
LABEL = "retrospective_point_in_time"
LEAGUE_KEY = "dynasty_main"
LEAGUE_ID = "1312006700437352448"
SEASON = 2026
SLEEPER = "https://api.sleeper.app/v1"
CACHE_DIR = REPO / "data/idp_accuracy/cache"
SCRATCH_DIR = REPO / "data/idp_accuracy/g_scratch"
EVIDENCE_DIR = REPO / "docs/valuation/idp_accuracy/evidence"
MANIFEST_PATH = EVIDENCE_DIR / "g_stage1_manifest.json"
SCORES_PATH = EVIDENCE_DIR / "g_stage1_scores.json"
F_EVIDENCE_PATH = EVIDENCE_DIR / "f_structural_level_invariance.json"
RESULT_PATH = EVIDENCE_DIR / "g_backtest_2026w1_6.json"
GAMES_CSV = CACHE_DIR / "nflverse" / "schedules__games.csv"
TEAM_LABEL_SALT = "idp-g-v1-teams"
LANE_A_PINNED_ARCHIVE = "exports/archive/dynasty_export_20261025_120337.zip"
LANE_A_PINNED_SHA256 = "50fb251a79bc79abac54bcbcfc98c3018fc6b105115eb6dbd7928e3b6c8dc8f6"

POSITIONS = ("QB", "RB", "WR", "TE", "DL", "LB", "DB")
OFFENSE = ("QB", "RB", "WR", "TE")
IDP = ("DL", "LB", "DB")
HOLD_OUT_WEEKS = tuple(range(1, 7))
MIN_N_PER_POSITION = 20
MIN_QUALIFYING = {"total": 5, "offense": 3, "idp": 2}
MIN_N_PER_POPULATION_CROSS = 50
BOOT_B = 2000
BOOT_SEED = 20261026
SIM_WEEKS = 200
SIM_SEED = 20261027
PSEUDO_GAMES = 4.0
MIN_OWN_RESIDUALS = 6
HISTORY_SEASON = 2025
HISTORY_WEEKS = tuple(range(1, 19))
NFLVERSE_TEAM_ALIAS = {"LAR": "LA"}


def _load_by_path(name: str, rel: str):
    """Load a shadow module by file path (see the module docstring)."""
    if name in sys.modules:
        return sys.modules[name]
    spec = importlib.util.spec_from_file_location(name, REPO / rel)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


rs = _load_by_path(
    "src.league_valuation.replacement_shadow", "src/league_valuation/replacement_shadow.py"
)
cp = _load_by_path("src.league_valuation.cross_position", "src/league_valuation/cross_position.py")


# ── the injected lineup owner ────────────────────────────────────────────────


class SolverPort:
    """``src.ros.lineup.solve_optimal_assignment`` behind ``LineupPort`` (exact; no fallback).

    The only addition is a per-shape cache of slot eligibility.  Eligibility depends on a
    player's ``position`` and ``fantasy_positions`` and the slot list, never on his score, so
    handing the solver the identical per-pair answer it would otherwise recompute is the
    owner's own documented optimisation (``precompute_slot_eligibility``), not a second
    engine.  Verified against the un-cached call in ``tests/idp_accuracy/test_backtest.py``.
    """

    def __init__(self) -> None:
        from src.ros import lineup  # noqa: PLC0415

        self._lu = lineup
        self._shape_cache: dict[tuple[tuple[str, ...], str, tuple[str, ...]], tuple[int, ...]] = {}
        self._tag_cache: dict[tuple[str, ...], Any] = {}

    def _eligibility(self, slots: tuple[str, ...], position: str, fps: tuple[str, ...]):
        key = (slots, position, fps)
        hit = self._shape_cache.get(key)
        if hit is None:
            lu = self._lu
            probe = lu.RosterPlayer("_", "_", position, 0.0, fantasy_positions=fps)
            hit = lu.precompute_slot_eligibility([probe], list(slots))["_"]
            self._shape_cache[key] = hit
        return hit

    def _empty_map(self, slots: tuple[str, ...]):
        """An empty map of the type ``precompute_slot_eligibility`` returns, carrying the
        rule tag it derives for these slots, so the solver reads it as its own answer."""
        proto = self._tag_cache.get(slots)
        if proto is None:
            proto = self._lu.precompute_slot_eligibility([], list(slots))
            self._tag_cache[slots] = proto
        fresh = type(proto)()
        fresh.derived_for = proto.derived_for
        return fresh

    def solve(self, players: Sequence[Any], slots: Sequence[str]) -> Mapping[int, str]:
        lu = self._lu
        slots_t = tuple(slots)
        pool = []
        elig = self._empty_map(slots_t)
        for p in players:
            fps = tuple(p.fantasy_positions)
            pool.append(
                lu.RosterPlayer(
                    player_id=p.player_id,
                    canonical_name=p.player_id,
                    position=p.position,
                    ros_value=float(p.points),
                    fantasy_positions=fps,
                )
            )
            elig[p.player_id] = self._eligibility(slots_t, p.position, fps)
        got = lu.solve_optimal_assignment(
            pool,
            list(slots_t),
            objective=lu.OBJECTIVE_REALIZED_POINTS,
            precomputed_eligibility=elig,
        )
        return {int(i): rp.player_id for i, rp in got.items()}

    def solve_uncached(self, players: Sequence[Any], slots: Sequence[str]) -> Mapping[int, str]:
        """The owner's own per-call eligibility (used only to verify the cache)."""
        lu = self._lu
        pool = [
            lu.RosterPlayer(
                player_id=p.player_id,
                canonical_name=p.player_id,
                position=p.position,
                ros_value=float(p.points),
                fantasy_positions=tuple(p.fantasy_positions),
            )
            for p in players
        ]
        got = lu.solve_optimal_assignment(pool, list(slots), objective=lu.OBJECTIVE_REALIZED_POINTS)
        return {int(i): rp.player_id for i, rp in got.items()}

    def slot_family(self, slot: str) -> str:
        return self._lu.normalize_slot(slot)


# ── generic helpers ──────────────────────────────────────────────────────────


def sha256_bytes(b: bytes) -> str:
    return hashlib.sha256(b).hexdigest()


def sha256_file(path: Path) -> str:
    return sha256_bytes(path.read_bytes())


def vector_hash(values: Mapping[str, float | None], nd: int = 9) -> str:
    """Order-independent sha256 of a ``player -> value`` map (a score-vector pin)."""
    return cp.stable_hash({k: v for k, v in values.items() if v is not None}, nd=nd)


def ids_hash(ids: Sequence[str]) -> str:
    return sha256_bytes("\n".join(sorted(str(i) for i in ids)).encode("utf-8"))


def rnd(x: Any, nd: int = 4) -> Any:
    return None if x is None else round(float(x), nd)


def git(*args: str) -> str:
    return subprocess.run(
        ["git", *args], cwd=REPO, capture_output=True, text=True, check=True
    ).stdout.strip()


def anonymous_team_labels(roster_ids: Sequence[Any]) -> dict[Any, str]:
    """``roster_id -> T01..`` in an order that carries no identity."""
    order = sorted(
        roster_ids, key=lambda r: hashlib.sha256(f"{TEAM_LABEL_SALT}:{r}".encode()).hexdigest()
    )
    return {r: f"T{i + 1:02d}" for i, r in enumerate(order)}


def position_of(raw: str | None) -> str:
    """A listed position in the one lineup vocabulary (POSITION_ALIASES first)."""
    from src.ros.lineup import lineup_position  # noqa: PLC0415
    from src.utils.name_clean import POSITION_ALIASES  # noqa: PLC0415

    p = str(raw or "").strip().upper()
    if not p:
        return ""
    folded = POSITION_ALIASES.get(p) or lineup_position(p)
    return "RB" if folded == "FB" else folded


# ── cached, throttled, outcome-guarded Sleeper reads ─────────────────────────


class OutcomeGuardError(RuntimeError):
    """Raised when blind-stage code tries to read a 2026 outcome."""


class Fetcher:
    """Cached GET of public Sleeper endpoints.  A cached body is REUSED byte for byte.

    ``blind=True`` (stage 1) refuses every URL that could carry a 2026 outcome: the
    2026 stat dumps and every matchup endpoint.  Stage 1 therefore cannot load an
    outcome even by accident.
    """

    MIN_INTERVAL_S = 0.25

    def __init__(self, cache_dir: Path = CACHE_DIR, *, blind: bool, offline: bool = False) -> None:
        self.cache_dir = cache_dir
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        self.blind = blind
        self.offline = offline
        self._last = 0.0
        self.receipts: dict[str, dict[str, Any]] = {}

    def _path(self, url: str) -> Path:
        return self.cache_dir / f"{hashlib.sha256(url.encode()).hexdigest()[:24]}.json"

    def get(self, url: str) -> Any:
        if self.blind and ("/regular/2026/" in url or "/matchups/" in url):
            raise OutcomeGuardError(f"blind stage refuses to read an outcome endpoint: {url}")
        path = self._path(url)
        if not path.exists():
            if self.offline:
                raise RuntimeError(f"offline and not cached: {url}")
            import requests  # noqa: PLC0415

            wait = self.MIN_INTERVAL_S - (time.time() - self._last)
            if wait > 0:
                time.sleep(wait)
            resp = requests.get(url, timeout=60)
            self._last = time.time()
            resp.raise_for_status()
            path.write_bytes(resp.content)
        blob = path.read_bytes()
        self.receipts[url] = {"sha256": sha256_bytes(blob), "bytes": len(blob)}
        return json.loads(blob)


# ── time: kickoff, archive, cutoff (section 2.2) ─────────────────────────────


def kickoff_utc(season: int, week: int, games_csv: Path = GAMES_CSV) -> dict[str, Any]:
    """The first kickoff of ``week`` (UTC), from the pinned nflverse schedule (ET clock)."""
    et = ZoneInfo("America/New_York")
    best: tuple[datetime, str] | None = None
    with games_csv.open(encoding="utf-8") as fh:
        for r in csv.DictReader(fh):
            if r["season"] != str(season) or r["game_type"] != "REG" or r["week"] != str(week):
                continue
            local = datetime.fromisoformat(f"{r['gameday']}T{r['gametime']}:00").replace(tzinfo=et)
            when = local.astimezone(timezone.utc)
            if best is None or when < best[0]:
                best = (when, r["game_id"])
    if best is None:
        raise RuntimeError(f"no {season} REG week {week} game in {games_csv}")
    return {
        "kickoffUtc": best[0].isoformat(),
        "gameId": best[1],
        "clock": "nflverse gametime is US Eastern",
    }


def archive_filename_stamp(name: str) -> datetime:
    m = re.search(r"dynasty_export_(\d{8})_(\d{6})", name)
    if not m:
        raise ValueError(name)
    return datetime.strptime(m.group(1) + m.group(2), "%Y%m%d%H%M%S").replace(tzinfo=timezone.utc)


def archive_generation(path: Path) -> dict[str, Any]:
    """``g(A)``: the archive's internal tz-aware ``scrapeTimestamp`` (manifest and filename
    stamps are recorded as cross-checks)."""
    with zipfile.ZipFile(path) as z:
        member = next(n for n in z.namelist() if re.match(r"dynasty_data_.*\.json$", n))
        raw = json.loads(z.read(member))
        manifest = json.loads(z.read("manifest.json")) if "manifest.json" in z.namelist() else {}
    scrape = raw.get("scrapeTimestamp")
    internal = datetime.fromisoformat(str(scrape).replace("Z", "+00:00")) if scrape else None
    if internal is not None and internal.tzinfo is None:
        internal = internal.replace(tzinfo=timezone.utc)
    return {
        "g": internal,
        "source": "payload.scrapeTimestamp" if internal else "filename_stamp",
        "manifestGeneratedAt": manifest.get("generatedAt"),
        "filenameStamp": archive_filename_stamp(path.name).isoformat(),
    }


def select_archive(kickoff: datetime) -> dict[str, Any]:
    """The archive whose generation instant is the latest strictly before ``kickoff``."""
    arch_dir = REPO / "exports" / "archive"
    named = sorted(arch_dir.glob("dynasty_export_*.zip"))
    # filename stamps are within seconds of the internal instant; look at the last few
    # archives stamped up to a day past the kickoff, then decide on the INTERNAL instant
    horizon = kickoff + timedelta(days=1)
    near = [p for p in named if archive_filename_stamp(p.name) < horizon]
    rows = []
    for p in near[-4:]:
        gen = archive_generation(p)
        g = gen["g"] or archive_filename_stamp(p.name)
        rows.append((g, p, gen))
    eligible = [r for r in rows if r[0] < kickoff]
    if not eligible:
        raise RuntimeError("no archive strictly before the kickoff")
    g, path, gen = max(eligible, key=lambda r: r[0])
    return {
        "path": path,
        "name": path.name,
        "sha256": sha256_file(path),
        "g": g,
        "generation": gen,
        "later": sorted(r[1].name for r in rows if r[0] >= kickoff),
        "countArchives": len(named),
    }


def read_archive_payload(path: Path) -> dict[str, Any]:
    with zipfile.ZipFile(path) as z:
        member = next(n for n in z.namelist() if re.match(r"dynasty_data_.*\.json$", n))
        return json.loads(z.read(member))


# ── the champion: ledger read, then champion-rebuilt (section 4.1) ───────────


def ledger_probe(
    keys: Sequence[str], cutoff: datetime, knowledge_cutoff: datetime
) -> dict[str, Any]:
    """Read the served board through ``batch_known_before`` exactly as the preregistration says.

    The ledger file is the production store ``data/temporal_ledger.sqlite``.  When it is
    absent every read is ``unavailable`` and coverage is 0, which is the preregistered
    trigger for ``champion-rebuilt``.
    """
    from src.history import asof, store  # noqa: PLC0415

    path = Path(store.DB_PATH)
    exists = path.exists()
    res = asof.batch_known_before(
        [(k, cutoff) for k in keys], knowledge_cutoff=knowledge_cutoff, path=None
    )
    summary = res["summary"]
    reasons = Counter(r.get("missingReason") for r in res["results"] if r.get("value") is None)
    return {
        "reader": "src.history.asof.batch_known_before",
        "lane": "canonical_board",
        "ledgerPath": "data/temporal_ledger.sqlite",
        "ledgerFileExists": exists,
        "ledgerFileSha256": sha256_file(path) if exists else None,
        "knowledgeCutoff": knowledge_cutoff.isoformat(),
        "cutoffInstant": cutoff.isoformat(),
        "maxAgeDays": None,
        "requested": len(keys),
        "available": int(summary["exact"] + summary["nearestPrior"]),
        "coverage": float(summary["coverage"]),
        "unavailableReasons": dict(sorted((str(k), v) for k, v in reasons.items())),
        "coverageThreshold": 0.95,
    }


def extract_site_raw_tree(archive: Path, scratch: Path) -> Path:
    """Lay the archive's ``site_raw`` CSVs out where the contract builder reads them
    (``<root>/CSVs/site_raw``), with each file's original mtime, so the board's source
    freshness is measured against the archive and not against today."""
    root = scratch / archive.stem
    target = root / "CSVs" / "site_raw"
    target.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(archive) as z:
        for info in z.infolist():
            if info.filename.startswith("site_raw/") and info.filename.endswith(".csv"):
                out = target / Path(info.filename).name
                out.write_bytes(z.read(info))
                when = datetime(*info.date_time, tzinfo=timezone.utc).timestamp()
                os.utime(out, (when, when))
    return root


def rebuild_champion(raw: dict[str, Any], archive: Path) -> tuple[dict[str, Any], dict[str, Any]]:
    """``build_api_data_contract`` at HEAD on the archive's own raw payload (champion-rebuilt).

    Point-in-time hygiene: ``csv_root`` is the archive's own ``site_raw`` tree, the league
    context (roster count, TE bonus) is read from the archive's own ``sleeper`` block
    instead of a live Sleeper call, and the board's freshness clock is the payload's own
    ``scrapeTimestamp`` (the builder's documented as-of).  What cannot be reproduced is
    declared: the dataset-state directory that drives freshness/health weighting is not
    archived, so every source votes at full base authority.
    """
    from src.api import data_contract as dc  # noqa: PLC0415

    sl = raw.get("sleeper") or {}
    ls = sl.get("leagueSettings") or {}
    ctx = {
        "roster_count": int(ls.get("num_teams") or 12),
        "bonus_rec_te": float((sl.get("scoringSettings") or {}).get("bonus_rec_te") or 0.0),
        "fetched_from_sleeper": True,
    }
    original = dc._resolve_league_context
    dc._resolve_league_context = lambda default_roster_count=12: dict(ctx)  # type: ignore[assignment]
    try:
        root = extract_site_raw_tree(archive, SCRATCH_DIR)
        contract = dc.build_api_data_contract(raw, csv_root=root)
    finally:
        dc._resolve_league_context = original  # type: ignore[assignment]
    notes = {
        "mode": "champion_rebuilt",
        "label": "champion_methodology_at_head",
        "builder": "src.api.data_contract.build_api_data_contract",
        "leagueContext": ctx,
        "csvRoot": "archive site_raw tree (original mtimes)",
        "sourceWeighting": (contract.get("sourceWeighting") or {}).get("unavailableReason")
        if isinstance(contract.get("sourceWeighting"), dict)
        else None,
        "sourceFilesInArchive": sorted(p.name for p in (root / "CSVs" / "site_raw").glob("*.csv")),
    }
    return contract, notes


def board_rows(contract: Mapping[str, Any]) -> dict[str, dict[str, Any]]:
    """Sleeper id -> board facts for every PLAYER row carrying a champion value."""
    out: dict[str, dict[str, Any]] = {}
    for r in contract.get("playersArray") or []:
        if str(r.get("assetClass") or "") == "pick":
            continue
        pid = r.get("playerId")
        if not pid or not str(pid).isdigit():
            continue
        v = r.get("rankDerivedValue")
        out[str(pid)] = {
            "name": r.get("displayName") or r.get("canonicalName"),
            "canonicalName": r.get("canonicalName") or r.get("displayName"),
            "value": float(v) if isinstance(v, (int, float)) and v > 0 else None,
            "rank": r.get("canonicalConsensusRank"),
            "position": str(r.get("position") or "").upper(),
            "team": r.get("team"),
            "age": r.get("age"),
            "yearsExp": r.get("yearsExp"),
            "rookie": bool(r.get("rookie")),
            "quarantined": bool(r.get("quarantined")),
            "assetClass": r.get("assetClass"),
            "offCapValue": bool(r.get("offCapPlayerValue")),
        }
    return out


# ── the cutoff universe: rosters, positions, eligibility ─────────────────────


def build_universe(
    raw: Mapping[str, Any], board: Mapping[str, Mapping[str, Any]]
) -> dict[str, Any]:
    """Rosters (anonymised), per-player facts and the starter slots, all from the archive."""
    from src.ros.lineup import resolve_starter_slots  # noqa: PLC0415

    sl = raw["sleeper"]
    id_to_name = {str(k): v for k, v in (sl.get("idToPlayer") or {}).items()}
    positions = sl.get("positions") or {}
    fpos = sl.get("fantasyPositions") or {}
    players_by_name = raw.get("players") or {}
    labels = anonymous_team_labels([t["roster_id"] for t in sl["teams"]])
    teams = {
        labels[t["roster_id"]]: [str(x) for x in (t.get("playerIds") or [])] for t in sl["teams"]
    }
    rostered = {pid for ids in teams.values() for pid in ids}
    slots, slot_source = resolve_starter_slots(
        roster_positions=sl.get("rosterPositions"), roster_settings=None
    )
    ids = sorted(rostered | set(board))
    info: dict[str, dict[str, Any]] = {}
    for pid in ids:
        brow = board.get(pid)
        name = (brow or {}).get("canonicalName") or id_to_name.get(pid) or pid
        arch_name = id_to_name.get(pid) or name
        listed = positions.get(arch_name) or positions.get(name)
        pos = position_of((brow or {}).get("position") or listed)
        fps: list[str] = []
        for p in fpos.get(arch_name) or fpos.get(name) or []:
            q = position_of(p)
            if q and q not in fps:
                fps.append(q)
        if pos and pos not in fps:
            fps.insert(0, pos)
        pl = players_by_name.get(arch_name) or players_by_name.get(name) or {}
        info[pid] = {
            "id": pid,
            "name": str(name),
            "archiveName": str(arch_name),
            "position": pos,
            "listedPosition": listed,
            "fantasyPositions": tuple(fps),
            "team": (brow or {}).get("team") or pl.get("team"),
            "age": (brow or {}).get("age")
            if (brow or {}).get("age") is not None
            else pl.get("age"),
            "yearsExp": (brow or {}).get("yearsExp")
            if (brow or {}).get("yearsExp") is not None
            else pl.get("_yearsExp"),
            "rostered": pid in rostered,
            "onBoard": pid in board,
        }
    return {
        "teams": teams,
        "labels": labels,
        "rostered": rostered,
        "slots": list(slots),
        "slotSource": slot_source,
        "info": info,
        "rosterSizes": sorted(len(v) for v in teams.values()),
        "rosterCap": len(sl.get("rosterPositions") or []) or None,
    }


# ── admissible history: host-scored games before the cutoff ──────────────────


def team_game_weeks(season: int, games_csv: Path = GAMES_CSV) -> dict[str, frozenset[int]]:
    """NFL team -> regular-season weeks it played (nflverse abbreviations)."""
    out: dict[str, set[int]] = defaultdict(set)
    with games_csv.open(encoding="utf-8") as fh:
        for r in csv.DictReader(fh):
            if r["season"] == str(season) and r["game_type"] == "REG":
                out[r["home_team"]].add(int(r["week"]))
                out[r["away_team"]].add(int(r["week"]))
    return {t: frozenset(w) for t, w in out.items()}


def score_dump(
    dump: Mapping[str, Any],
    pos_by_id: Mapping[str, str],
    card: Mapping[str, float],
    *,
    season: int,
    week: int,
    only_ids: set[str] | None = None,
) -> dict[str, float]:
    """Host-scored league points per player for one stat dump (``source="sleeper"``)."""
    from src.nfl_data.realized_points import compute_weekly_points  # noqa: PLC0415

    out: dict[str, float] = {}
    for sid, line in (dump or {}).items():
        sid = str(sid)
        if only_ids is not None and sid not in only_ids:
            continue
        if float(line.get("gp") or 0) <= 0:
            continue
        pos = pos_by_id.get(sid)
        if not pos:
            continue
        res = compute_weekly_points(
            {**line, "player_id": sid, "season": season, "week": week},
            dict(card),
            position=pos,
            source="sleeper",
        )
        if res is not None:
            out[sid] = float(res.fantasy_points)
    return out


def numeric_card(card: Mapping[str, Any]) -> dict[str, float]:
    return {k: float(v) for k, v in card.items() if isinstance(v, (int, float))}


def history_for(
    fetch: Fetcher,
    ids: set[str],
    pos_by_id: Mapping[str, str],
    card: Mapping[str, float],
    *,
    through: Sequence[tuple[int, int]],
) -> dict[str, dict[tuple[int, int], float]]:
    """Admissible host-scored games for ``ids`` over the ``(season, week)`` pairs given."""
    hist: dict[str, dict[tuple[int, int], float]] = defaultdict(dict)
    for season, week in through:
        dump = fetch.get(f"{SLEEPER}/stats/nfl/regular/{season}/{week}")
        for sid, pts in score_dump(
            dump, pos_by_id, card, season=season, week=week, only_ids=ids
        ).items():
            hist[sid][(season, week)] = pts
    return dict(hist)


# ── projections (P), candidate A and the BDVM adapter (sections 3.1, 4.2) ────


def build_bdvm(
    contract: Mapping[str, Any],
    raw: Mapping[str, Any],
    cutoff_date: str,
    *,
    actuals: tuple[int | None, Mapping[str, list[tuple[int, float]]]] | None = None,
    age_variants: bool = True,
) -> dict[str, Any]:
    """BDVM at the cutoff: the A-proxy reconstructed baseline, then ``run_valuation``.

    The call chain is the one ``scripts/bdvm_build_baseline.py`` runs
    (``fetch_and_build_baseline`` over the three seasons before 2026 with the
    play-by-play supplement), invoked as a library so ``as_of`` is the CUTOFF date
    rather than today (the CLI stamps today and writes to the default snapshot
    directory).  There is no prior snapshot to carry forward, no event is loaded and
    no in-season actuals are used for the W0 origin (preregistration 2.3 / 4.2).
    """
    from src.api import league_registry  # noqa: PLC0415
    from src.bdvm.baseline import fetch_and_build_baseline  # noqa: PLC0415
    from src.bdvm.context import fetch_and_build_context  # noqa: PLC0415
    from src.bdvm.params import load_param_set  # noqa: PLC0415
    from src.bdvm.projections import blend_consensus  # noqa: PLC0415
    from src.bdvm.service import run_valuation  # noqa: PLC0415
    from src.nfl_data.pbp_weekly import SeasonPbpIndex  # noqa: PLC0415

    card = (raw.get("sleeper") or {}).get("scoringSettings") or {}
    idx = SeasonPbpIndex()
    records, summary = fetch_and_build_baseline(
        season=SEASON,
        as_of=cutoff_date,
        scoring_settings=card,
        seasons_back=3,
        pbp_for_season=idx.for_season,
    )
    params = load_param_set()
    ctx = fetch_and_build_context(SEASON, seasons_back=6, include_snaps=True)
    roster_settings = league_registry.get_league_roster_settings(LEAGUE_KEY)

    def _run(c: Mapping[str, Any]) -> dict[str, Any]:
        return run_valuation(
            c,
            league_key=LEAGUE_KEY,
            params=params,
            registry_roster_settings=roster_settings,
            idp_enabled=True,
            scoring_profile="superflex_tep15_ppr1",
            projection_records=records,
            snapshot_as_of=cutoff_date,
            season=SEASON,
            context=ctx,
            events=[],
            schedule_weeks=None,
            actuals=actuals,
        )

    payloads = {"base": _run(contract)}
    for shift, tag in ((1, "age_plus1"), (-1, "age_minus1")) if age_variants else ():
        shifted = dict(contract)
        rows = []
        for r in contract.get("playersArray") or []:
            r2 = dict(r)
            if isinstance(r2.get("age"), (int, float)) and r2["age"] > 0:
                r2["age"] = r2["age"] + shift
            rows.append(r2)
        shifted["playersArray"] = rows
        payloads[tag] = _run(shifted)
    by_player: dict[str, list[Any]] = defaultdict(list)
    for r in records:
        by_player[r.player_key].append(r)
    consensus = {}
    for key, recs in by_player.items():
        blended = blend_consensus(
            recs, scoring_settings=card, snapshot_as_of=cutoff_date, params=params
        )
        if blended is not None:
            consensus[key] = blended
    if actuals is not None and actuals[0] is not None and actuals[1]:
        # The section 8.4 posterior, applied to P exactly as ``run_valuation`` applies it
        # (lines "in-season posterior update"): the same two BDVM functions, the same
        # arguments.  Only the Wb origin passes actuals.
        import dataclasses  # noqa: PLC0415

        from src.bdvm.ros import blend_ros_mu, ros_projection_weight  # noqa: PLC0415
        from src.bdvm.scoring import is_idp_position  # noqa: PLC0415

        _week, by_key = actuals
        for key, blended in list(consensus.items()):
            samples = by_key.get(key)
            if not samples:
                continue
            played = float(len(samples))
            recent = sum(pts for _wk, pts in samples) / played
            idp = is_idp_position(blended.position)
            mu_post = blend_ros_mu(blended.mu_fpg, recent, played, is_idp=idp, params=params)
            w_prior = ros_projection_weight(played, is_idp=idp, params=params)
            consensus[key] = dataclasses.replace(
                blended, mu_fpg=mu_post, sigma_source=blended.sigma_source * math.sqrt(w_prior)
            )
    from src.utils.name_clean import normalize_player_name  # noqa: PLC0415

    return {
        "records": records,
        "summary": summary,
        "pbpSeasonsMissing": list(idx.seasons_missing),
        "params": params,
        "paramSetId": params.param_set_id,
        "payloads": payloads,
        "consensus": consensus,
        "normalize": normalize_player_name,
        "contextPlayers": len(ctx),
        "tier": "A-proxy",
    }


def a_scores(payload: Mapping[str, Any]) -> tuple[dict[str, tuple[float, float]], dict[str, str]]:
    """``player id -> (balanced DV, signed points over replacement)`` and the unpriced reasons."""
    out: dict[str, tuple[float, float]] = {}
    for e in payload.get("players") or []:
        pid = str(e.get("playerId") or "")
        if not pid.isdigit():
            continue
        dv = (e.get("fundamental") or {}).get("balanced")
        vorg = (e.get("raw") or {}).get("vorg")
        if isinstance(dv, (int, float)) and isinstance(vorg, (int, float)):
            out[pid] = (float(dv), float(vorg))
    reasons = {str(u.get("name")): str(u.get("reason")) for u in payload.get("unpriced") or []}
    return out, reasons


def a_trade_values(payload: Mapping[str, Any]) -> dict[str, float]:
    """BDVM's balanced-strategy trade value per player (feeds ``package_value`` in 9.2 only)."""
    out: dict[str, float] = {}
    for e in payload.get("players") or []:
        pid = str(e.get("playerId") or "")
        tv = (e.get("tradeValue") or {}).get("balanced")
        if pid.isdigit() and isinstance(tv, (int, float)):
            out[pid] = float(tv)
    return out


def project_mu(
    bd: Mapping[str, Any], universe: Mapping[str, Any], board: Mapping[str, Mapping[str, Any]]
) -> dict[str, Any]:
    """P: each Sleeper id's projected league ppg, joined to BDVM's consensus by normalised name.

    BDVM's own join is by normalised name; two ids sharing a normalised name would receive
    one record, so both are left MISSING (never a guess).  A player whose only record is a
    rookie draft-slot prior has no prior-season production: he is UNKNOWN to the ex-ante
    environments (preregistration 3.5) and is not in the veteran cohort.
    """
    norm = bd["normalize"]
    consensus = bd["consensus"]
    info = universe["info"]
    key_of: dict[str, str] = {}
    by_key: dict[str, list[str]] = defaultdict(list)
    for pid, i in info.items():
        nm = (board.get(pid) or {}).get("canonicalName") or i["name"]
        k = norm(str(nm))
        key_of[pid] = k
        by_key[k].append(pid)
    mu: dict[str, float] = {}
    sources: dict[str, tuple[str, ...]] = {}
    status: dict[str, str] = {}
    for pid, k in key_of.items():
        if len(by_key[k]) > 1:
            status[pid] = "name_collision"
            continue
        c = consensus.get(k)
        if c is None:
            status[pid] = "no_projection"
            continue
        if tuple(c.sources) == ("rookieDraftSlotPrior",):
            status[pid] = "rookie_prior_only"
            continue
        mu[pid] = float(c.mu_fpg)
        sources[pid] = tuple(c.sources)
        status[pid] = "projected"
    return {"mu": mu, "sources": sources, "status": status, "keyOf": key_of}


# ── cohort building blocks (section 5) ───────────────────────────────────────


def stratum_ok(info: Mapping[str, Any]) -> bool:
    return info["position"] in POSITIONS


def availability_inputs(
    universe: Mapping[str, Any],
    hist: Mapping[str, Mapping[tuple[int, int], float]],
    provisional: Sequence[str],
    *,
    window: Sequence[tuple[int, int]],
) -> dict[str, Any]:
    """g, G, a-bar_p and residual sets from admissible history only."""
    info = universe["info"]
    tw_by_season = {s: team_game_weeks(s) for s in {s for s, _ in window}}
    g: dict[str, int] = {}
    G: dict[str, int | None] = {}
    for pid, i in info.items():
        team = i.get("team")
        nf = NFLVERSE_TEAM_ALIAS.get(str(team), str(team)) if team else None
        played = hist.get(pid, {})
        g[pid] = sum(1 for sw in window if sw in played)
        if nf is None:
            G[pid] = None
            continue
        games = 0
        known = True
        for s, w in window:
            weeks = tw_by_season[s].get(nf)
            if weeks is None:
                known = False
                break
            games += 1 if w in weeks else 0
        G[pid] = games if known else None
    ratio: dict[str, list[float]] = defaultdict(list)
    for pid in provisional:
        gg = G.get(pid)
        if gg and gg > 0:
            ratio[info[pid]["position"]].append(min(1.0, g[pid] / gg))
    abar = {p: float(np.mean(v)) for p, v in ratio.items() if v}
    own = {pid: cp.residuals_of(list(hist.get(pid, {}).values())) for pid in info}
    stratum = {pid: info[pid]["position"] for pid in info}
    pooled = cp.pooled_residual_sets(
        own, stratum, eligible_ids=provisional, min_own=MIN_OWN_RESIDUALS
    )
    return {"g": g, "G": G, "abar": abar, "own": own, "pooled": pooled, "stratum": stratum}


def availability_for(avail: Mapping[str, Any], pid: str, pseudo: float) -> float | None:
    G = avail["G"].get(pid)
    abar = avail["abar"].get(avail["stratum"].get(pid))
    if G is None or abar is None:
        return None
    if G + pseudo <= 0:
        return None
    return cp.availability_rate(avail["g"][pid], G, abar, pseudo)


# ── parallel simulation of D ─────────────────────────────────────────────────

_W: dict[str, Any] = {}


def _worker_init(spec: dict[str, Any]) -> None:
    """Build the worker's private copy of the inputs and the exact solver."""
    _W["inputs"] = cp.SimInputs(
        mu=spec["mu"],
        availability=spec["availability"],
        own_residuals={k: tuple(v) for k, v in spec["own"].items()},
        pooled={k: tuple(v) for k, v in spec["pooled"].items()},
        stratum=spec["stratum"],
        position=spec["position"],
        fantasy_positions={k: tuple(v) for k, v in spec["fantasy_positions"].items()},
        teams=spec["teams"],
        slots=spec["slots"],
    )
    _W["port"] = SolverPort()
    _W["ids"] = spec["evaluate"]
    _W["sigma"] = spec["sigma"]
    _W["own_team_only"] = spec["own_team_only"]
    _W["seed"] = spec["seed"]


def _worker_weeks(weeks: list[int]) -> list[tuple[int, dict[str, float]]]:
    out = []
    for s in weeks:
        wk = cp.simulate_week(
            _W["inputs"],
            _W["port"],
            s,
            _W["ids"],
            seed=_W["seed"],
            sigma=_W["sigma"],
            own_team_only=_W["own_team_only"],
        )
        out.append((wk.week, dict(wk.marginal)))
    return out


def run_d(spec: dict[str, Any], *, weeks: int = SIM_WEEKS, workers: int | None = None) -> Any:
    """Candidate D over ``weeks`` simulated weeks, chunked across worker processes.

    The result is a function of the seed alone (each week owns its own child stream), so
    the chunking cannot change it; ``workers=1`` runs in-process and must give the same
    numbers (pinned by a test).
    """
    n = int(workers if workers is not None else max(1, min(16, (os.cpu_count() or 2) - 2)))
    idx = list(range(int(weeks)))
    if n <= 1:
        _worker_init(spec)
        done = _worker_weeks(idx)
    else:
        chunks = [idx[i :: n * 4] for i in range(n * 4) if idx[i :: n * 4]]
        done = []
        with ProcessPoolExecutor(max_workers=n, initializer=_worker_init, initargs=(spec,)) as ex:
            for part in ex.map(_worker_weeks, chunks):
                done.extend(part)
    done.sort(key=lambda t: t[0])
    return cp.summarize_weeks(
        [cp.WeekMarginals(week=w, marginal=m) for w, m in done], seed=spec["seed"]
    )


def sim_spec(
    universe: Mapping[str, Any],
    mu: Mapping[str, float],
    avail: Mapping[str, Any],
    pseudo: float,
    evaluate: Sequence[str],
    *,
    sigma: bool = True,
    own_team_only: bool = False,
    placeholders: Mapping[str, tuple[float, float]] | None = None,
) -> tuple[dict[str, Any], dict[str, str]]:
    """The picklable description of one D run.  Returns ``(spec, reasons_unsimulable)``.

    ``placeholders`` (stability S7) maps an otherwise-unprojected rostered id to
    ``(mu, availability)``; they live in the environment but are never evaluated.
    """
    info = universe["info"]
    use_mu: dict[str, float] = {}
    use_a: dict[str, float] = {}
    reasons: dict[str, str] = {}
    for pid, m in mu.items():
        a = availability_for(avail, pid, pseudo)
        if a is None:
            reasons[pid] = "no_availability"
            continue
        use_mu[pid] = float(m)
        use_a[pid] = a
    for pid, (m, a) in (placeholders or {}).items():
        use_mu[pid] = float(m)
        use_a[pid] = float(a)
    spec = {
        "mu": use_mu,
        "availability": use_a,
        "own": {k: list(v) for k, v in avail["own"].items()},
        "pooled": {k: list(v) for k, v in avail["pooled"].items()},
        "stratum": avail["stratum"],
        "position": {pid: info[pid]["position"] for pid in info},
        "fantasy_positions": {pid: list(info[pid]["fantasyPositions"]) for pid in info},
        "teams": {k: list(v) for k, v in universe["teams"].items()},
        "slots": list(universe["slots"]),
        "evaluate": [e for e in evaluate if e in use_mu],
        "sigma": sigma,
        "own_team_only": own_team_only,
        "seed": SIM_SEED,
    }
    inputs = cp.SimInputs(
        mu=use_mu,
        availability=use_a,
        own_residuals={k: tuple(v) for k, v in avail["own"].items()},
        pooled={k: tuple(v) for k, v in avail["pooled"].items()},
        stratum=avail["stratum"],
        position=spec["position"],
        fantasy_positions={k: tuple(v) for k, v in spec["fantasy_positions"].items()},
        teams=spec["teams"],
        slots=spec["slots"],
    )
    for pid, why in inputs.unsimulable().items():
        reasons.setdefault(pid, why)
    # an unsimulable player is not drawn, so he is not evaluated either
    spec["evaluate"] = [e for e in spec["evaluate"] if e not in reasons]
    return spec, reasons


# ── candidate C (section 4.4) ────────────────────────────────────────────────


def player_records(universe: Mapping[str, Any]) -> dict[str, Any]:
    return {
        pid: rs.PlayerRecord(
            player_id=pid,
            name=i["name"],
            position=i["position"],
            fantasy_positions=tuple(i["fantasyPositions"]),
            nfl_team=i.get("team"),
        )
        for pid, i in universe["info"].items()
    }


def d1_thresholds(
    universe: Mapping[str, Any], records: Mapping[str, Any], port: SolverPort, value_of
) -> dict[str, float | None]:
    """D1 at each lineup-family position: the median over teams of the weakest starter."""
    th = rs.starter_thresholds(
        universe["teams"], records, port, universe["slots"], value_of=value_of
    )
    return {
        p: th.by_position[p].median_marginal() if p in th.by_position else None for p in POSITIONS
    }


def c_scores(
    mu: Mapping[str, float], universe: Mapping[str, Any], levels: Mapping[str, float | None]
) -> tuple[dict[str, float], dict[str, str]]:
    """``V^C_i = max over eligible p of (mu_i - R_p)`` and the position that attains it."""
    out: dict[str, float] = {}
    pi: dict[str, str] = {}
    for pid, m in mu.items():
        best: tuple[float, str] | None = None
        for p in universe["info"][pid]["fantasyPositions"]:
            r = levels.get(p)
            if r is None:
                continue
            cand = (m - r, p)
            if best is None or cand[0] > best[0]:
                best = cand
        if best is not None:
            out[pid] = best[0]
            pi[pid] = best[1]
    return out, pi


def s3_levels(
    universe: Mapping[str, Any],
    hist: Mapping[str, Mapping[tuple[int, int], float]],
    port: SolverPort,
    d1: Mapping[str, float | None],
) -> dict[str, Any]:
    """Stability S3: the free-agent replacement definitions D2 and D4 for candidate C.

    Built from ADMISSIBLE history only (2025 host-scored games), with Lane B's empirical-Bayes
    winner's-curse correction (``estimator=eb``) whose hyper-parameters are estimated only
    from those pre-cutoff player-weeks.  The free-agent pool is the unrostered players the
    cutoff board prices (health cannot be reconstructed at the cutoff, so the health filter
    is declared not applied).  A level that is undefined at a position falls back to D1 there
    and says so.  D5 is not evaluable: on one pseudo-week of expected ppg the allocation
    degenerates to a single claim (Lane B, ``B_REPLACEMENT.md`` section 0 item 4).
    """
    cfg = rs.load_config()
    info = universe["info"]
    recs = {}
    for pid, i in info.items():
        weekly = {w: pts for (s, w), pts in hist.get(pid, {}).items() if s == HISTORY_SEASON}
        recs[pid] = rs.PlayerRecord(
            player_id=pid,
            name=i["name"],
            position=i["position"],
            fantasy_positions=tuple(i["fantasyPositions"]),
            nfl_team=i.get("team"),
            weekly=weekly,
        )
    flat = rs.compute_level_set(
        recs,
        universe["teams"],
        port,
        universe["slots"],
        weeks=HISTORY_WEEKS,
        cfg=cfg,
        rule=rs.PoolRule(health="none"),
        estimator=rs.EST_EB,
    )
    rank = int(cfg["levels"]["rank"]["value"])
    out: dict[str, Any] = {"D2": {}, "D4": {}, "fallback": {}, "rank": rank}
    for p in POSITIONS:
        m = flat.get(p) or {}
        for tag, key in (("D2", "d2_bestPpg"), ("D4", f"d4_rank{rank}Ppg")):
            v = m.get(key)
            if v is None:
                out[tag][p] = d1.get(p)
                out["fallback"][f"{tag}:{p}"] = "undefined_falls_back_to_D1"
            else:
                out[tag][p] = float(v)
    out["D5"] = "not_evaluable: degenerate_one_pseudo_week_allocation (Lane B finding)"
    out["healthFilter"] = "not_applied_at_cutoff"
    return out


# ── reference quantities that need no outcome ────────────────────────────────


def noise_ceiling(
    hist: Mapping[str, Mapping[tuple[int, int], float]],
    ids: Sequence[str],
    info: Mapping[str, Mapping[str, Any]],
) -> dict[str, Any]:
    """Spearman between two disjoint 6-week windows of 2025 host-scored ppg, per position."""
    from scipy.stats import spearmanr  # noqa: PLC0415

    pairs = {
        "w1-6_vs_w7-12": (range(1, 7), range(7, 13)),
        "w7-12_vs_w13-18": (range(7, 13), range(13, 19)),
    }
    out: dict[str, Any] = {}
    for tag, (wa, wb) in pairs.items():
        per: dict[str, Any] = {}
        for p in POSITIONS:
            xs, ys = [], []
            for pid in ids:
                if info[pid]["position"] != p:
                    continue
                a = [hist.get(pid, {}).get((HISTORY_SEASON, w)) for w in wa]
                b = [hist.get(pid, {}).get((HISTORY_SEASON, w)) for w in wb]
                a = [v for v in a if v is not None]
                b = [v for v in b if v is not None]
                if len(a) >= 3 and len(b) >= 3:
                    xs.append(float(np.mean(a)))
                    ys.append(float(np.mean(b)))
            per[p] = {
                "n": len(xs),
                "spearman": rnd(spearmanr(xs, ys).statistic, 4) if len(xs) >= 5 else None,
            }
        out[tag] = per
    out["note"] = (
        "pre-cutoff 2025 host-scored ppg only (players with >= 3 games in each window): how "
        "much ordering any candidate could achieve at best from production persistence alone"
    )
    return out


def power_note(n_by_pos: Mapping[str, int], *, reps: int = 1500) -> dict[str, Any]:
    """Informational design power from cohort sizes alone (section 8.1).

    Assumes rho_s = 0.40 between each score and the outcome and 0.8 between the champion
    and the candidate score (stated assumptions, no outcome data).  Reports the null SD of
    the equal-weight pooled within-position delta and the effect it could detect at 80%
    power.  Changes no threshold.
    """
    from scipy.stats import rankdata  # noqa: PLC0415

    rho_s = 0.40
    r = 2.0 * math.sin(math.pi * rho_s / 6.0)  # Pearson that gives Spearman 0.40 (normal)
    r12 = 0.8
    # corr(Y, V0) = corr(Y, Vc) = r ; corr(V0, Vc) = r12
    cov = np.array([[1.0, r, r], [r, 1.0, r12], [r, r12, 1.0]])
    chol = np.linalg.cholesky(cov)
    rng = np.random.Generator(np.random.PCG64(20261028))  # separate from bootstrap and D
    qual = {p: n for p, n in n_by_pos.items() if n >= MIN_N_PER_POSITION}
    if not qual:
        return {"state": "no_qualifying_position"}
    deltas = np.zeros((reps, len(qual)))
    for j, (p, n) in enumerate(sorted(qual.items())):
        for b in range(reps):
            z = rng.standard_normal((n, 3)) @ chol.T
            y, v0, vc = z[:, 0], z[:, 1], z[:, 2]
            ry = rankdata(y)
            deltas[b, j] = np.corrcoef(rankdata(vc), ry)[0, 1] - np.corrcoef(rankdata(v0), ry)[0, 1]
    pooled = deltas.mean(axis=1)
    sd = float(np.std(pooled, ddof=1))
    return {
        "assumptions": {"rhoS": rho_s, "championCandidateScoreCorrelation": r12, "reps": reps},
        "qualifyingPositions": dict(sorted(qual.items())),
        "nullSdPooledDelta1": rnd(sd, 4),
        "detectableDelta1At80Power": rnd(2.8 * sd, 4),
        "minimumMeaningfulDelta1": 0.05,
        "note": "informational; changes no threshold",
    }


def f_structural(
    rows: Sequence[Mapping[str, Any]],
    order_by_id: Mapping[str, Mapping[str, float]],
    *,
    label: str,
) -> dict[str, Any]:
    """F finding: can ``league_fair_value_v1_shadow`` correct an overall IDP-vs-offense level error?

    For each utility ORDER offered (any order at all: the structural claim does not depend on
    it) the challenger is run on the real board under the shipped configuration and under a
    k = 1, full-quality configuration, and the per-scope value multisets and the cross-scope
    level statistics are compared before and after.  Evidence is admitted by construction here
    (fresh, non-proxy), which is a measurement of the model, not a claim about BDVM's inputs.
    """
    import copy  # noqa: PLC0415

    ch = _load_by_path("src.league_valuation.challenger", "src/league_valuation/challenger.py")
    ct = _load_by_path("src.league_valuation.contracts", "src/league_valuation/contracts.py")
    pop = _load_by_path("src.league_valuation.population", "src/league_valuation/population.py")

    ship = ct.load_params()
    k1 = copy.deepcopy(ship)
    k1["kMax"]["value"] = 1.0
    k1["quality"]["byProjectionFamilies"] = {"0": 0.0, "1": 1.0, "2": 1.0, "3": 1.0}
    k1["paramSetId"] = ct.param_set_id_for(k1)
    pins_for = lambda p: {  # noqa: E731
        "leagueKey": LEAGUE_KEY,
        "scoringFingerprint": "sf1:structural_measurement",
        "formatFingerprint": "tmf1:structural_measurement",
        "contractScrapeTimestamp": label,
        "contractVersion": "2026-03-10.v2",
        "bdvmModelVersion": "structural_measurement",
        "bdvmParamSetId": "structural_measurement",
        "bdvmSnapshotAsOf": label,
        "challengerVersion": ct.MODEL_VERSION,
        "challengerParamSetId": str(p["paramSetId"]),
    }
    populations, _structural = pop.eligible_rows(list(rows))
    keyed = {
        scope: [(pop.row_key(r, -1), r, int(pop.market_value_of(r))) for r in rs_]
        for scope, rs_ in populations.items()
    }
    before = {s: sorted((v for _k, _r, v in members), reverse=True) for s, members in keyed.items()}
    # A utility TIE block is replaced by the log-mean of the value block it spans (the model's
    # documented rule), which preserves the log-sum but not the exact multiset.  The
    # measurement is of the unavoidable structure, so every order is made tie-free first by a
    # deterministic perturbation far below any real difference in the order.
    tiebreak = {
        key: 1e-9 * i
        for i, key in enumerate(sorted(k for ms in keyed.values() for k, _r, _v in ms))
    }

    def util_of(key: str, row: Mapping[str, Any], order: Mapping[str, float]) -> float:
        return float(order.get(str(row.get("playerId")), -1e6)) + tiebreak[key]

    def stats(scope_values: Mapping[str, Sequence[float]]) -> dict[str, Any]:
        off = sorted(scope_values["OFFENSE"], reverse=True)
        idp = sorted(scope_values["IDP"], reverse=True)
        union = sorted([(v, "OFFENSE") for v in off] + [(v, "IDP") for v in idp], reverse=True)
        top36 = union[:36]
        return {
            "offenseN": len(off),
            "idpN": len(idp),
            "offenseMean": rnd(np.mean(off), 3),
            "idpMean": rnd(np.mean(idp), 3),
            "offenseTop12Mean": rnd(np.mean(off[:12]), 3),
            "idpTop12Mean": rnd(np.mean(idp[:12]), 3),
            "levelRatioOffenseOverIdpTop12": rnd(np.mean(off[:12]) / np.mean(idp[:12]), 4),
            "idpInTop36": sum(1 for _v, s in top36 if s == "IDP"),
        }

    out: dict[str, Any] = {"board": label, "before": stats(before), "orders": {}}
    for order_name, order in order_by_id.items():
        results: dict[str, Any] = {}
        evidence = {}
        for scope, members in keyed.items():
            for key, row, _v in members:
                pid = str(row.get("playerId"))
                u = util_of(key, row, order)
                evidence[key] = ct.UtilityEvidence(
                    asset_key=key,
                    player_id=pid,
                    position=str(row.get("position") or ""),
                    scope=scope,
                    points_over_replacement=u,
                    projection_families=3,
                    is_proxy=False,
                    as_of=label,
                    freshness="fresh",
                    quality=1.0,
                    lineage_ids=(),
                    state="available",
                    reason=None,
                    balanced_dv=u,
                )
        for cfg_name, params in (("shipped", ship), ("k1_full_quality", k1)):
            board = ch.compute_fair_values(
                list(rows), evidence, params=params, pins=pins_for(params)
            )
            after_scope = {"OFFENSE": [], "IDP": []}
            for scope, members in keyed.items():
                for key, _r, _v in members:
                    after_scope[scope].append(float(board.values[key].fair_value_exact))
            multiset_equal = {
                s: bool(
                    np.allclose(
                        sorted(after_scope[s]),
                        sorted(float(v) for v in before[s]),
                        rtol=0,
                        atol=1e-6,
                    )
                )
                for s in after_scope
            }
            moved = sum(
                1
                for v in board.values.values()
                if v.state == "available" and v.fair_value != v.market_value
            )
            results[cfg_name] = {
                "kMax": params["kMax"]["value"],
                "scopeValueMultisetUnchanged": multiset_equal,
                "rowsMoved": moved,
                "after": stats(after_scope),
                "idpFanOutGate": board.diagnostics["scopes"]["IDP"].get("idpFanOut", {})
                and {
                    "stable": board.diagnostics["scopes"]["IDP"]["idpFanOut"]["stable"],
                    "kForced": board.diagnostics["scopes"]["IDP"]["kForced"],
                },
                "logDriftSum": {
                    s: rnd(board.diagnostics["scopes"][s]["logDrift"]["sum"], 6)
                    for s in ("OFFENSE", "IDP")
                },
            }
        # the bare math, gate bypassed: quantile matching at k = 1 per scope
        bare = {"OFFENSE": [], "IDP": []}
        for scope, members in keyed.items():
            mv = [v for _k, _r, v in members]
            util = [(util_of(k, r, order),) for k, r, _v in members]
            matched, _ranks = ch.quantile_match(mv, util)
            bare[scope] = matched
        results["bareQuantileMatchK1"] = {
            "scopeValueMultisetUnchanged": {
                s: bool(
                    np.allclose(sorted(bare[s]), sorted(float(v) for v in before[s]), atol=1e-6)
                )
                for s in bare
            },
            "after": stats(bare),
        }
        out["orders"][order_name] = results
    # a hypothetical level error: the whole IDP scope priced 25% too high / too low
    hyp: dict[str, Any] = {}
    for tag, scale in (("idp_priced_25pct_too_high", 1.25), ("idp_priced_20pct_too_low", 0.8)):
        scaled = {
            "OFFENSE": [float(v) for v in before["OFFENSE"]],
            "IDP": [float(v) * scale for v in before["IDP"]],
        }
        order = next(iter(order_by_id.values()))
        mv_idp = [v * scale for _k, _r, v in keyed["IDP"]]
        util = [(util_of(k, r, order),) for k, r, _v in keyed["IDP"]]
        matched, _ = ch.quantile_match(mv_idp, util)
        scaled_after = {"OFFENSE": scaled["OFFENSE"], "IDP": matched}
        hyp[tag] = {"before": stats(scaled), "afterBareQuantileMatchK1": stats(scaled_after)}
    out["hypotheticalLevelErrors"] = hyp
    out["conclusion"] = (
        "Per scope, the challenger returns a rearrangement of that scope's own market values "
        "(exact at k=1; a bounded interpolation between two members of the same scope at k<1). "
        "Any statistic of a scope's value multiset, and so any offense-versus-IDP level "
        "statistic, is therefore unchanged by construction, whatever utility order it is shown."
    )
    return out


# ── STAGE 1: blind ───────────────────────────────────────────────────────────


def stage1_code_hash() -> str:
    """sha256 of every line of this script ABOVE the stage 2 section.

    Stage 1 pins it; stage 2 recomputes it and refuses to run if it moved.  Bug fixes to the
    evaluator therefore stay possible (they live below the marker) while the code that
    produced the blind artifact cannot change unnoticed.  The marker is built by
    concatenation so that this very function does not contain it."""
    marker = "# ── STAGE 2" + ": unblind, once"
    text = Path(__file__).read_text(encoding="utf-8")
    if marker not in text:
        raise RuntimeError("stage 2 marker missing")
    return sha256_bytes(text.split(marker)[0].encode("utf-8"))


def check_preregistration() -> dict[str, Any]:
    """The evaluator's own freeze check (same idea as
    ``model_registry.independent_validation.git_preregistration_committed``)."""
    blob = git("hash-object", PREREG_PATH)
    first = git("log", "--diff-filter=A", "--format=%H", "--", PREREG_PATH).splitlines()
    first_commit = first[-1] if first else None
    accepted_first = {PREREG_COMMIT, PREREG_SQUASH_COMMIT}
    changed_since = (
        [
            c
            for c in git(
                "log", "--format=%H", f"{first_commit}..HEAD", "--", PREREG_PATH
            ).splitlines()
            if c
        ]
        if first_commit
        else []
    )
    ok = blob == PREREG_BLOB and first_commit in accepted_first and not changed_since
    if not ok:
        raise SystemExit(
            f"preregistration is not frozen: blob={blob} first={first_commit} changed={changed_since}"
        )
    return {"path": PREREG_PATH, "blob": blob, "firstCommit": first_commit, "unchangedSince": True}


def _fair_value_param_id() -> str:
    ct = _load_by_path("src.league_valuation.contracts", "src/league_valuation/contracts.py")
    return str(ct.load_params()["paramSetId"])


def _scoring_fingerprint(card: Mapping[str, Any]) -> str | None:
    from src.league_comparison.sleeper_scoring import scoring_fingerprint  # noqa: PLC0415

    return scoring_fingerprint(dict(card))


def b_degeneracy(
    contract: Mapping[str, Any], bd: Mapping[str, Any], cutoff: datetime
) -> dict[str, Any]:
    """Section 4.3: is ``league_fair_value_v1_shadow`` degenerate on this input?

    Run B's own code unchanged on the cutoff board with A's output as its utility evidence.
    Under a proxy-only A every row's evidence is ``partial`` (``proxy_projection_only``), so
    ``k = 0`` and ``fairValue == marketValue`` exactly: B is the champion.
    """
    ch = _load_by_path("src.league_valuation.challenger", "src/league_valuation/challenger.py")
    ct = _load_by_path("src.league_valuation.contracts", "src/league_valuation/contracts.py")
    evd = _load_by_path("src.league_valuation.evidence", "src/league_valuation/evidence.py")
    params = ct.load_params()
    evidence = evd.utility_evidence_from_bdvm(bd["payloads"]["base"], now=cutoff, params=params)
    pins = {
        "leagueKey": LEAGUE_KEY,
        "scoringFingerprint": str(_scoring_fingerprint(contract["sleeper"]["scoringSettings"])),
        "formatFingerprint": "tmf1:not_used_by_the_backtest",
        "contractScrapeTimestamp": str(contract.get("scrapeTimestamp") or cutoff.isoformat()),
        "contractVersion": str(contract.get("contractVersion")),
        "bdvmModelVersion": str(bd["payloads"]["base"]["meta"].get("modelVersion")),
        "bdvmParamSetId": str(bd["paramSetId"]),
        "bdvmSnapshotAsOf": str(bd["payloads"]["base"]["meta"]["projectionSnapshot"]["asOf"]),
        "challengerVersion": ct.MODEL_VERSION,
        "challengerParamSetId": str(params["paramSetId"]),
    }
    board = ch.compute_fair_values(
        list(contract["playersArray"]), evidence, params=params, pins=pins
    )
    states = Counter(v.state for v in board.values.values())
    moved = sum(1 for v in board.values.values() if v.fair_value != v.market_value)
    ks = [v.k for v in board.values.values() if v.state == "available"]
    reasons = Counter((v.excluded_reason or v.reason or "available") for v in board.values.values())
    degenerate = moved == 0 and (not ks or max(ks) == 0.0)
    return {
        "evaluable": not degenerate,
        "status": "not_evaluable: degenerate_market_exact" if degenerate else "evaluable",
        "anchor": "champion-rebuilt (no served contract in the archive)",
        "rowsAvailable": states.get("available", 0),
        "rowsExcluded": states.get("excluded", 0),
        "rowsMoved": moved,
        "evidenceStates": dict(Counter(e.state for e in evidence.values())),
        "topExclusionReasons": dict(reasons.most_common(8)),
        "configUnchanged": True,
        "paramSetId": params["paramSetId"],
    }


def f_structural_pinned() -> dict[str, Any]:
    """The same structural measurement on Lane A's pinned board (2026-10-25)."""
    path = REPO / LANE_A_PINNED_ARCHIVE
    if not path.exists() or sha256_file(path) != LANE_A_PINNED_SHA256:
        return {
            "state": "unavailable",
            "reason": "Lane A pinned archive missing or sha256 mismatch",
        }
    raw = read_archive_payload(path)
    contract, _notes = rebuild_champion(raw, path)
    board = board_rows(contract)
    rng = np.random.Generator(np.random.PCG64(20261030))
    ids = sorted(board)
    perm = {pid: float(x) for pid, x in zip(ids, rng.permutation(len(ids)))}
    rev = {pid: -float(b["value"] or 0.0) for pid, b in board.items()}
    out = f_structural(
        list(contract["playersArray"]),
        {"random_permutation": perm, "reversed_market": rev},
        label="Lane A pinned board (2026-10-25)",
    )
    out["archiveSha256"] = LANE_A_PINNED_SHA256
    return out


def family_sizes(
    n_by_pos: Mapping[str, int], n_candidates: int
) -> tuple[dict[str, Any], list[str], bool, bool]:
    """Test-family sizes fixed from cohort sizes alone (section 7.5)."""
    qualifying = [p for p in POSITIONS if n_by_pos.get(p, 0) >= MIN_N_PER_POSITION]
    q_off = sum(1 for p in qualifying if p in OFFENSE)
    q_idp = sum(1 for p in qualifying if p in IDP)
    within_ok = (
        len(qualifying) >= MIN_QUALIFYING["total"]
        and q_off >= MIN_QUALIFYING["offense"]
        and q_idp >= MIN_QUALIFYING["idp"]
    )
    n_off = sum(n_by_pos.get(p, 0) for p in OFFENSE)
    n_idp = sum(n_by_pos.get(p, 0) for p in IDP)
    cross_ok = n_off >= MIN_N_PER_POPULATION_CROSS and n_idp >= MIN_N_PER_POPULATION_CROSS
    fam = {
        "F1": {
            "m": n_candidates * (int(within_ok) + int(cross_ok)),
            "withinAxis": "tested" if within_ok else "insufficient_sample:cohort_size",
            "crossAxis": "tested" if cross_ok else "insufficient_sample:cohort_size",
        },
        "F2": {"m": len(qualifying) * n_candidates},
        "F3": {"m": 2 * n_candidates},
    }
    return fam, qualifying, within_ok, cross_ok


def prepare_window(args: argparse.Namespace, log, *, variants: bool = True) -> dict[str, Any]:
    """Everything the W0 candidates are made of, from admissible inputs only.

    Shared by stage 1 (which writes the blind artifact) and stage 2 (which RE-COMPUTES the
    base vectors and refuses to continue unless they hash identically to the committed
    ones).  It never reads a 2026 outcome: the Sleeper fetcher is created ``blind=True``.
    ``variants=False`` runs only the base D simulation (stage 2 reads the variant vectors
    from the committed file, whose hashes it has verified).
    """
    # ---- 1. cutoff -----------------------------------------------------------
    k0 = kickoff_utc(SEASON, 1)
    kb = kickoff_utc(SEASON, 4)
    K0 = datetime.fromisoformat(k0["kickoffUtc"])
    arch0 = select_archive(K0)
    archb = select_archive(datetime.fromisoformat(kb["kickoffUtc"]))
    cutoff = arch0["g"]
    kc = K0 - timedelta(seconds=1)
    cutoff_date = cutoff.date().isoformat()
    log(f"W0 kickoff {K0.isoformat()}  archive {arch0['name']}  C_w {cutoff.isoformat()}")

    raw = read_archive_payload(arch0["path"])
    sl = raw["sleeper"]

    # ---- 2. the champion: ledger read, then champion-rebuilt ---------------------
    contract, champ_notes = rebuild_champion(raw, arch0["path"])
    board = board_rows(contract)
    priced_ids = [pid for pid, b in board.items() if b["value"]]
    probe = ledger_probe([f"player:{pid}" for pid in priced_ids], cutoff, kc)
    champion_mode = (
        "ledger" if probe["coverage"] >= probe["coverageThreshold"] else "champion_rebuilt"
    )
    if champion_mode == "ledger":
        raise SystemExit(
            "a ledger covering >= 95% of the priced rows exists on this machine; the ledger "
            "path of section 4.1 is not exercised by this run (no ledger existed when this "
            "script was written). Resolve before continuing."
        )
    log(
        f"champion mode {champion_mode} (ledger coverage {probe['coverage']:.2f}); "
        f"{len(priced_ids)} priced"
    )

    universe = build_universe(raw, board)
    info = universe["info"]
    card = numeric_card(sl["scoringSettings"])
    fetch = Fetcher(blind=True, offline=args.offline)
    league = fetch.get(f"{SLEEPER}/league/{LEAGUE_ID}")
    league_card = numeric_card(league.get("scoring_settings") or {})
    card_diff = {
        k: (card.get(k), league_card.get(k))
        for k in set(card) | set(league_card)
        if card.get(k) != league_card.get(k)
    }

    def veteran(i: Mapping[str, Any]) -> bool:
        ye = i.get("yearsExp")
        return not (isinstance(ye, (int, float)) and ye < 1)

    support = [pid for pid, i in info.items() if board.get(pid, {}).get("value") and stratum_ok(i)]
    provisional = [pid for pid in support if veteran(info[pid])]

    # ---- 3. admissible history ---------------------------------------------------
    pos_by_id = {pid: i["position"] for pid, i in info.items() if i["position"]}
    window = [(HISTORY_SEASON, w) for w in HISTORY_WEEKS]
    hist = history_for(fetch, set(info), pos_by_id, card, through=window)
    avail = availability_inputs(universe, hist, provisional, window=window)
    log(f"history: {sum(len(v) for v in hist.values())} player-games for {len(hist)} players")

    # ---- 4. BDVM: A-proxy, P, A -----------------------------------------------------
    bd = build_bdvm(contract, raw, cutoff_date)
    pm = project_mu(bd, universe, board)
    mu = pm["mu"]
    a_base, a_unpriced = a_scores(bd["payloads"]["base"])
    a_plus, _ = a_scores(bd["payloads"]["age_plus1"])
    a_minus, _ = a_scores(bd["payloads"]["age_minus1"])
    mismatch = 0
    checked = 0
    max_diff = 0.0
    for e in bd["payloads"]["base"].get("players") or []:
        pid = str(e.get("playerId") or "")
        if pid in mu:
            checked += 1
            diff = abs(float((e.get("projection") or {}).get("fpg")) - mu[pid])
            max_diff = max(max_diff, diff)
            if diff > 5.1e-4:  # the payload publishes fpg rounded to 3 decimals
                mismatch += 1
    if mismatch:
        raise SystemExit(
            f"P disagrees with BDVM's own consensus for {mismatch} of {checked} players"
        )
    log(f"BDVM: {len(bd['records'])} proxy records, {len(a_base)} priced, mu for {len(mu)} ids")

    # ---- 5. B: degenerate? ----------------------------------------------------------
    b_status = b_degeneracy(contract, bd, cutoff)
    log(f"B: {b_status['status']}")

    # ---- 6. C ------------------------------------------------------------------------
    port = SolverPort()
    records = player_records(universe)
    d1 = d1_thresholds(universe, records, port, lambda r: mu.get(r.player_id))
    c_base, pi_c = c_scores(mu, universe, d1)
    s3 = s3_levels(universe, hist, port, d1)
    c_d2, _ = c_scores(mu, universe, {p: s3["D2"].get(p) for p in POSITIONS})
    c_d4, _ = c_scores(mu, universe, {p: s3["D4"].get(p) for p in POSITIONS})
    unknown_rostered = [pid for pid in universe["rostered"] if pid not in mu]
    placeholders: dict[str, tuple[float, float]] = {}
    for pid in unknown_rostered:
        p = info[pid]["position"]
        if p in POSITIONS and d1.get(p) is not None and avail["abar"].get(p) is not None:
            placeholders[pid] = (float(d1[p]), float(avail["abar"][p]))
    mu_ph = {**mu, **{pid: v[0] for pid, v in placeholders.items()}}
    d1_ph = d1_thresholds(universe, records, port, lambda r: mu_ph.get(r.player_id))
    c_ph, _ = c_scores(mu, universe, d1_ph)
    log("C: D1 " + ", ".join(f"{p} {rnd(v, 2)}" for p, v in d1.items()))

    # ---- 7. D ------------------------------------------------------------------------
    evaluate = sorted(pid for pid in provisional if pid in mu)
    d_runs: dict[str, Any] = {}
    d_reasons: dict[str, dict[str, str]] = {}
    runs: list[tuple[str, dict[str, Any]]] = [("base", dict(pseudo=PSEUDO_GAMES))]
    if variants:
        runs += [
            ("sigma0", dict(pseudo=PSEUDO_GAMES, sigma=False)),
            ("ownteam", dict(pseudo=PSEUDO_GAMES, own_team_only=True)),
            ("pc0", dict(pseudo=0.0)),
            ("pc16", dict(pseudo=16.0)),
            ("placeholder", dict(pseudo=PSEUDO_GAMES, placeholders=placeholders)),
        ]
    specs: dict[str, dict[str, Any]] = {}
    for name, kw in runs:
        spec, reasons = sim_spec(
            universe,
            mu,
            avail,
            kw["pseudo"],
            evaluate,
            sigma=kw.get("sigma", True),
            own_team_only=kw.get("own_team_only", False),
            placeholders=kw.get("placeholders"),
        )
        specs[name] = spec
        d_runs[name] = run_d(spec, workers=args.workers)
        d_reasons[name] = reasons
        log(f"D[{name}]: {len(d_runs[name].value)} values, {len(reasons)} unsimulable")

    return {
        "k0": k0,
        "kb": kb,
        "K0": K0,
        "arch0": arch0,
        "archb": archb,
        "cutoff": cutoff,
        "kc": kc,
        "cutoff_date": cutoff_date,
        "raw": raw,
        "sl": sl,
        "contract": contract,
        "champ_notes": champ_notes,
        "board": board,
        "priced_ids": priced_ids,
        "probe": probe,
        "champion_mode": champion_mode,
        "universe": universe,
        "info": info,
        "card": card,
        "card_diff": card_diff,
        "support": support,
        "provisional": provisional,
        "hist": hist,
        "avail": avail,
        "bd": bd,
        "pm": pm,
        "mu": mu,
        "a_base": a_base,
        "a_unpriced": a_unpriced,
        "a_plus": a_plus,
        "a_minus": a_minus,
        "checked": checked,
        "mismatch": mismatch,
        "b_status": b_status,
        "port": port,
        "records": records,
        "d1": d1,
        "c_base": c_base,
        "pi_c": pi_c,
        "s3": s3,
        "c_d2": c_d2,
        "c_d4": c_d4,
        "unknown_rostered": unknown_rostered,
        "placeholders": placeholders,
        "d1_ph": d1_ph,
        "c_ph": c_ph,
        "evaluate": evaluate,
        "d_runs": d_runs,
        "d_reasons": d_reasons,
        "specs": specs,
    }


def stage1(args: argparse.Namespace) -> int:
    t0 = time.time()

    def log(msg: str) -> None:
        print(f"[{time.time() - t0:7.1f}s] {msg}", file=sys.stderr, flush=True)

    prereg = check_preregistration()
    code_sha = git("rev-parse", "HEAD")
    dirty = git("status", "--porcelain", "--untracked-files=no")
    if dirty and not args.allow_dirty:
        raise SystemExit(
            f"working tree has tracked modifications; commit first (code pin):\n{dirty}"
        )
    P = prepare_window(args, log, variants=True)
    (
        k0,
        kb,
        arch0,
        archb,
        cutoff,
        kc,
        cutoff_date,
        sl,
        contract,
        champ_notes,
        board,
        priced_ids,
        probe,
        champion_mode,
        universe,
        info,
        card,
        card_diff,
        support,
        provisional,
        hist,
        avail,
        bd,
        pm,
        mu,
        a_base,
        a_unpriced,
        a_plus,
        a_minus,
        checked,
        mismatch,
        b_status,
        d1,
        c_base,
        pi_c,
        s3,
        c_d2,
        c_d4,
        unknown_rostered,
        placeholders,
        d1_ph,
        c_ph,
        d_runs,
        d_reasons,
    ) = (
        P[k]
        for k in (
            "k0",
            "kb",
            "arch0",
            "archb",
            "cutoff",
            "kc",
            "cutoff_date",
            "sl",
            "contract",
            "champ_notes",
            "board",
            "priced_ids",
            "probe",
            "champion_mode",
            "universe",
            "info",
            "card",
            "card_diff",
            "support",
            "provisional",
            "hist",
            "avail",
            "bd",
            "pm",
            "mu",
            "a_base",
            "a_unpriced",
            "a_plus",
            "a_minus",
            "checked",
            "mismatch",
            "b_status",
            "d1",
            "c_base",
            "pi_c",
            "s3",
            "c_d2",
            "c_d4",
            "unknown_rostered",
            "placeholders",
            "d1_ph",
            "c_ph",
            "d_runs",
            "d_reasons",
        )
    )

    # ---- 8. the cohort ---------------------------------------------------------------
    evaluable = {"A": True, "C": True, "D": True}
    if b_status["evaluable"]:
        evaluable["B"] = True
    census: Counter = Counter()
    per_candidate_missing: Counter = Counter()
    cohort: list[str] = []
    rows_without_id = sum(
        1
        for r in contract.get("playersArray") or []
        if str(r.get("assetClass") or "") != "pick" and not str(r.get("playerId") or "").isdigit()
    )
    for pid in sorted(info):
        i = info[pid]
        b = board.get(pid)
        if not b or not b["value"]:
            census["no_champion_value"] += 1
            continue
        if not stratum_ok(i):
            census["position_out_of_scope"] += 1
            continue
        st = pm["status"].get(pid)
        if st != "projected":
            census[f"no_projection:{st}"] += 1
            continue
        why = None
        if pid not in a_base:
            why = "A_undefined"
            per_candidate_missing["A"] += 1
        if pid not in c_base:
            why = why or "C_undefined"
            per_candidate_missing["C"] += 1
        if pid not in d_runs["base"].value:
            why = why or "D_undefined:" + d_reasons["base"].get(pid, "not_evaluated")
            per_candidate_missing["D"] += 1
        if why:
            census[why] += 1
            continue
        cohort.append(pid)
    cohort_set = set(cohort)
    n_by_pos = Counter(info[pid]["position"] for pid in cohort)
    n_off = sum(n_by_pos[p] for p in OFFENSE)
    n_idp = sum(n_by_pos[p] for p in IDP)
    e_list = sorted(evaluable)
    families, qualifying, within_ok, cross_ok = family_sizes(n_by_pos, len(e_list))
    log(
        f"cohort {len(cohort)} by position {dict(n_by_pos)}; "
        f"within {'OK' if within_ok else 'INSUFFICIENT'}, cross {'OK' if cross_ok else 'INSUFFICIENT'}"
    )

    # ---- 9. score vectors, hashes -------------------------------------------------------
    def vec(d: Mapping[str, Any]) -> dict[str, float]:
        return {pid: round(float(d[pid]), 9) for pid in support if pid in d}

    vectors: dict[str, dict[str, float]] = {
        "champion": {pid: float(board[pid]["value"]) for pid in support},
        "A_dv": vec({k: v[0] for k, v in a_base.items()}),
        "A_vorg": vec({k: v[1] for k, v in a_base.items()}),
        "A_tradeValue": vec(a_trade_values(bd["payloads"]["base"])),
        "A_dv_age_plus1": vec({k: v[0] for k, v in a_plus.items()}),
        "A_vorg_age_plus1": vec({k: v[1] for k, v in a_plus.items()}),
        "A_dv_age_minus1": vec({k: v[0] for k, v in a_minus.items()}),
        "A_vorg_age_minus1": vec({k: v[1] for k, v in a_minus.items()}),
        "R0_mu": vec(mu),
        "C": vec(c_base),
        "C_D2": vec(c_d2),
        "C_D4": vec(c_d4),
        "C_placeholder": vec(c_ph),
        "D": vec(d_runs["base"].value),
        "D_se": vec(d_runs["base"].mc_se),
        "D_sigma0": vec(d_runs["sigma0"].value),
        "D_ownteam": vec(d_runs["ownteam"].value),
        "D_pc0": vec(d_runs["pc0"].value),
        "D_pc16": vec(d_runs["pc16"].value),
        "D_placeholder": vec(d_runs["placeholder"].value),
    }
    hashes = {k: vector_hash(v) for k, v in vectors.items()}
    cohort_hash = ids_hash(cohort)

    players_table = []
    for pid in support:
        i = info[pid]
        b = board[pid]
        players_table.append(
            {
                "id": pid,
                "name": i["name"],
                "pos": i["position"],
                "fantasyPositions": list(i["fantasyPositions"]),
                "hybridDlLb": ("DL" in i["fantasyPositions"] and "LB" in i["fantasyPositions"]),
                "rostered": i["rostered"],
                "nflTeam": i.get("team"),
                "age": i.get("age"),
                "yearsExp": i.get("yearsExp"),
                "champRank": b["rank"],
                "offCapValue": b["offCapValue"],
                "projectionStatus": pm["status"].get(pid),
                "projectionSources": list(pm["sources"].get(pid, ())),
                "piC": pi_c.get(pid),
                "gamesHistory": avail["g"].get(pid),
                "teamGamesHistory": avail["G"].get(pid),
                "availabilityBase": rnd(availability_for(avail, pid, PSEUDO_GAMES), 6),
                "ownResiduals": len(avail["own"].get(pid, ())),
                "inCohort": pid in cohort_set,
            }
        )

    manifest = {
        "preregistration": "idp_accuracy_G_v1",
        "label": LABEL,
        "promotes": False,
        "stage": 1,
        "blind": True,
        "outcomesLoaded": False,
        "outcomeGuard": "Fetcher(blind=True) refuses /regular/2026/ and /matchups/ URLs",
        "pins": {
            "preregistration": prereg,
            "codeSha": code_sha,
            "scriptSha256": sha256_file(Path(__file__)),
            "stage1CodeSha256": stage1_code_hash(),
            "crossPositionSha256": sha256_file(REPO / "src/league_valuation/cross_position.py"),
            "replacementShadowSha256": sha256_file(
                REPO / "src/league_valuation/replacement_shadow.py"
            ),
            "lineupSha256": sha256_file(REPO / "src/ros/lineup.py"),
            "bdvmParamSetId": bd["paramSetId"],
            "replacementShadowParamSetId": rs.load_config()["paramSetId"],
            "fairValueParamSetId": _fair_value_param_id(),
            "packageModel": "geom_q078_v1 (config/trade/package_model.json)",
            "seeds": {
                "bootstrap": BOOT_SEED,
                "simulationD": SIM_SEED,
                "B": BOOT_B,
                "simWeeks": SIM_WEEKS,
            },
            "scoringFingerprint": _scoring_fingerprint(sl["scoringSettings"]),
        },
        "windows": {
            "W0": {
                "role": "primary",
                "outcomeWeeks": list(HOLD_OUT_WEEKS),
                "firstKickoff": k0,
                "archive": {
                    "name": arch0["name"],
                    "sha256": arch0["sha256"],
                    "generationInstantUsed": cutoff.isoformat(),
                    "generationSource": arch0["generation"]["source"],
                    "manifestGeneratedAt": arch0["generation"]["manifestGeneratedAt"],
                    "filenameStamp": arch0["generation"]["filenameStamp"],
                    "archivesAfterKickoffSeenAsNeighbours": arch0["later"],
                },
                "cutoffInstant": cutoff.isoformat(),
                "knowledgeCutoff": kc.isoformat(),
            },
            "Wa": {"role": "stability", "sameOriginAs": "W0", "outcomeWeeks": [1, 2, 3]},
            "Wb": {
                "role": "stability",
                "outcomeWeeks": [4, 5, 6],
                "firstKickoff": kb,
                "archive": {"name": archb["name"], "sha256": archb["sha256"]},
                "cutoffInstant": archb["g"].isoformat(),
                "candidateVectors": "NOT_COMPUTED_IN_STAGE_1",
                "reason": (
                    "its admissible inputs include 2026 REG weeks 1-3 (section 2.3), which are "
                    "outcome weeks of W0 and may not be loaded in the blind stage (section 12.1). "
                    "Declared here, before any outcome is joined, as a deviation: Wb is built in "
                    "stage 2 after W0 is unblinded, from weeks 1-3 only, and labelled exploratory."
                ),
            },
        },
        "champion": {
            "mode": champion_mode,
            "servedContractInArchive": False,
            "ledger": probe,
            "rebuilt": champ_notes,
            "servedVersusRebuiltDrift": (
                "not computable: no served board exists for this cutoff in this repository"
            ),
            "claimLabel": (
                "the comparator is today's market method on point-in-time inputs, "
                "not the board users saw"
            ),
            "pricedPlayerRows": len(priced_ids),
        },
        "inputs": {
            "scoringCardKeys": len(card),
            "scoringCardVersusSleeperLeagueNow": {
                "differences": len(card_diff),
                "keys": sorted(card_diff)[:20],
            },
            "starterSlots": universe["slots"],
            "starterSlotsSource": universe["slotSource"],
            "rosterSizes": universe["rosterSizes"],
            "rosterCap": universe["rosterCap"],
            "teams": len(universe["teams"]),
            "historyWindow": f"{HISTORY_SEASON} REG weeks 1-18 (host-scored, source=sleeper)",
            "historyPlayerGames": int(sum(len(v) for v in hist.values())),
            "eligibility": "archive sleeper.fantasyPositions (cutoff point-in-time)",
            "injuryStatus": "not used (cannot be reconstructed point-in-time)",
            "bdvm": {
                "tier": bd["tier"],
                "tierWhy": (
                    "no box snapshot with an immutable creation stamp <= C_w exists in this "
                    "repository; the clean reconstructed baseline is the declared substitute"
                ),
                "baselineSummary": {
                    k: v for k, v in bd["summary"].items() if k != "rookieBucketSamples"
                },
                "pbpSeasonsMissing": bd["pbpSeasonsMissing"],
                "records": len(bd["records"]),
                "allRecordsProxy": all(r.is_proxy for r in bd["records"]),
                "pricedByA": len(a_base),
                "unpricedReasons": dict(Counter(a_unpriced.values())),
                "contextPlayers": bd["contextPlayers"],
                "events": "none (no pre-cutoff dated events)",
                "actuals": None,
                "asOfStamp": f"{cutoff_date} (the cutoff date; the CLI would stamp today)",
                "muMatchesBdvmConsensus": {"checked": checked, "mismatches": mismatch},
            },
            "projectionStatus": dict(Counter(pm["status"].values())),
            "unknownRosteredInEnvironments": len(unknown_rostered),
        },
        "candidates": {
            "champion": {"evaluable": True, "mode": champion_mode},
            "A": {"evaluable": True, "tier": bd["tier"], "pricedPlayers": len(a_base)},
            "B": b_status,
            "C": {
                "evaluable": True,
                "replacement": "D1 median marginal starter (Lane B), from mu on the 12 cutoff rosters",
                "d1ByPosition": {p: rnd(v, 4) for p, v in d1.items()},
                "d1Interpretation": (
                    "section 4.4 'league-wide starter threshold' = "
                    "PositionThreshold.median_marginal (what the weakest starter produces)"
                ),
                "s3": {
                    k: ({p: rnd(x, 4) for p, x in v.items()} if k in ("D2", "D4") else v)
                    for k, v in s3.items()
                },
                "d1WithPlaceholders": {p: rnd(v, 4) for p, v in d1_ph.items()},
            },
            "D": {
                "evaluable": True,
                "weeks": SIM_WEEKS,
                "seed": SIM_SEED,
                "pseudoGames": PSEUDO_GAMES,
                "availabilityPositionMean": {
                    p: rnd(v, 4) for p, v in sorted(avail["abar"].items())
                },
                "pooledResidualSetSizes": {p: len(v) for p, v in avail["pooled"].items()},
                "unsimulable": {k: dict(Counter(v.values())) for k, v in d_reasons.items()},
                "mcStandardErrorMedian": rnd(
                    float(
                        np.median([x for x in d_runs["base"].mc_se.values() if math.isfinite(x)])
                    ),
                    4,
                ),
                "placeholdersUsedS7": len(placeholders),
            },
            "R0": {"reference": True, "outsideEveryFamily": True},
            "evaluableSet": e_list,
        },
        "cohort": {
            "size": len(cohort),
            "idsSha256": cohort_hash,
            "byPosition": {p: n_by_pos[p] for p in POSITIONS},
            "offense": n_off,
            "idp": n_idp,
            "qualifyingPositions": qualifying,
            "minNPerPosition": MIN_N_PER_POSITION,
            "withinAxisSufficient": within_ok,
            "crossAxisSufficient": cross_ok,
            "reducedFamily": len(qualifying) < len(POSITIONS),
            "exclusionCensus": dict(sorted(census.items())),
            "perCandidateMissingAmongProjected": dict(per_candidate_missing),
            "rowsWithoutSleeperId": rows_without_id,
            "rookies": (
                "excluded: a rookie's only projection is a draft-slot prior (no prior-season "
                "production); this experiment says nothing about rookies"
            ),
        },
        "families": families,
        "scoreVectorSha256": hashes,
        "scoreVectorFile": "docs/valuation/idp_accuracy/evidence/g_stage1_scores.json",
        "noiseCeiling": noise_ceiling(hist, provisional, info),
        "powerNote": power_note(dict(n_by_pos)),
        "timingsSec": round(time.time() - t0, 1),
    }
    scores = {
        "preregistration": "idp_accuracy_G_v1",
        "window": "W0",
        "promotes": False,
        "decimals": 9,
        "vectors": vectors,
        "vectorSha256": hashes,
        "cohort": sorted(cohort),
        "players": players_table,
    }
    rs.assert_public_artifact(manifest, forbidden_values=[LEAGUE_ID])
    rs.assert_public_artifact(scores, forbidden_values=[LEAGUE_ID])

    # ---- 10. the F structural measurement (blind, outcome-free) -------------------------
    rng = np.random.Generator(np.random.PCG64(20261029))
    ids_sorted = sorted(board)
    perm = {pid: float(x) for pid, x in zip(ids_sorted, rng.permutation(len(ids_sorted)))}
    market_reversed = {pid: -float(b["value"] or 0.0) for pid, b in board.items()}
    f_w0 = f_structural(
        list(contract["playersArray"]),
        {
            "D_expected_lineup_points": dict(vectors["D"]),
            "random_permutation": perm,
            "reversed_market": market_reversed,
        },
        label="W0 champion-rebuilt board",
    )
    f_doc = {
        "preregistration": "idp_accuracy_G_v1",
        "promotes": False,
        "w0Board": f_w0,
        "laneAPinnedBoard": f_structural_pinned(),
    }
    rs.assert_public_artifact(f_doc, forbidden_values=[LEAGUE_ID])

    if not args.dry_run:
        EVIDENCE_DIR.mkdir(parents=True, exist_ok=True)
        MANIFEST_PATH.write_text(
            json.dumps(manifest, indent=1, default=str) + "\n", encoding="utf-8"
        )
        SCORES_PATH.write_text(
            json.dumps(scores, separators=(",", ":"), default=str) + "\n", encoding="utf-8"
        )
        F_EVIDENCE_PATH.write_text(
            json.dumps(f_doc, indent=1, default=str) + "\n", encoding="utf-8"
        )
        print(
            json.dumps(
                {
                    "manifest": str(MANIFEST_PATH),
                    "scores": str(SCORES_PATH),
                    "f": str(F_EVIDENCE_PATH),
                    "cohort": len(cohort),
                }
            )
        )
    else:
        print(json.dumps({"dryRun": True, "cohort": len(cohort), "hashes": hashes}, indent=1))
    return 0


# ── STAGE 2: unblind, once ───────────────────────────────────────────────────
#
# Everything below is written and unit-tested on SYNTHETIC data before any outcome
# is joined; the only inputs that touch real outcomes are `outcome_inputs` and
# `stage2`.  The statistics are pure functions of arrays.

CORE_CANDIDATES = ("A", "C", "D")
REF_CANDIDATE = "R0"
ALPHA = 0.05
MIN_EFFECT = {"delta1": 0.05, "delta2": 0.02, "elite": 1.0 / 12.0}
POINT_FLOOR_PER_POSITION = -0.10
CROSS_FLOOR_FOR_WITHIN = -0.01
WITHIN_FLOOR_FOR_CROSS = -0.02


def midranks(x: np.ndarray) -> np.ndarray:
    from scipy.stats import rankdata  # noqa: PLC0415

    return rankdata(x, method="average")


def spearman(x: np.ndarray, y: np.ndarray) -> float:
    """Spearman correlation with midranks for ties.  ``nan`` when either side is constant."""
    if len(x) < 2:
        return float("nan")
    rx = midranks(x) - (len(x) + 1) / 2.0
    ry = midranks(y) - (len(y) + 1) / 2.0
    denom = math.sqrt(float((rx * rx).sum()) * float((ry * ry).sum()))
    return float((rx * ry).sum() / denom) if denom > 0 else float("nan")


def lex_rank_scores(dv: Sequence[float], vorg: Sequence[float]) -> np.ndarray:
    """Candidate A's order key: the lexicographic order of (balanced DV, signed fpg - R) as a
    dense rank (ties only for identical pairs).  Monotone, so every rank-based statistic on any
    subset or resample is exactly the lexicographic one."""
    keys = list(zip((float(v) for v in dv), (float(v) for v in vorg)))
    order = {k: r for r, k in enumerate(sorted(set(keys)))}
    return np.array([order[k] for k in keys], dtype=float)


def two_sided_p(draws: np.ndarray) -> float:
    """Section 7.4: p = min(1, 2 min(p_up, p_down)), each tail with the +1 correction."""
    b = len(draws)
    p_up = (1 + int((draws <= 0).sum())) / (b + 1)
    p_down = (1 + int((draws >= 0).sum())) / (b + 1)
    return float(min(1.0, 2.0 * min(p_up, p_down)))


def holm(pvalues: Mapping[Any, float], alpha: float = ALPHA) -> dict[Any, dict[str, Any]]:
    """Holm step-down on two-sided p-values.  ``reject`` follows the preregistered rule
    (reject the k smallest while ``p_(j) <= alpha / (m - j + 1)`` for every ``j <= k``);
    ``adjusted`` is the equivalent Holm-adjusted p-value."""
    items = sorted(pvalues.items(), key=lambda kv: (kv[1], str(kv[0])))
    m = len(items)
    out: dict[Any, dict[str, Any]] = {}
    running = 0.0
    still_rejecting = True
    for j, (key, p) in enumerate(items, start=1):
        adj = min(1.0, (m - j + 1) * p)
        running = max(running, adj)
        if still_rejecting and p <= alpha / (m - j + 1):
            reject = True
        else:
            still_rejecting = False
            reject = False
        out[key] = {"p": p, "adjusted": running, "reject": reject, "m": m, "rank": j}
    return out


def wilson(k: int, n: int, z: float = 1.959963984540054) -> tuple[float, float]:
    if n == 0:
        return (float("nan"), float("nan"))
    p = k / n
    denom = 1 + z * z / n
    centre = (p + z * z / (2 * n)) / denom
    half = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / denom
    return (centre - half, centre + half)


class Cohort:
    """Aligned arrays for one set of players (identical rows for every candidate)."""

    def __init__(
        self,
        ids: Sequence[str],
        pos: Sequence[str],
        y: Sequence[float],
        scores: Mapping[str, Sequence[float]],
        *,
        tiebreak: Sequence[float] | None = None,
        clusters: Sequence[str] | None = None,
        rostered: Sequence[bool] | None = None,
    ) -> None:
        self.ids = list(ids)
        self.pos = np.array(list(pos))
        self.y = np.asarray(y, dtype=float)
        self.scores = {k: np.asarray(v, dtype=float) for k, v in scores.items()}
        self.tiebreak = (
            np.asarray(tiebreak, dtype=float)
            if tiebreak is not None
            else self.scores.get("champion", np.zeros(len(self.ids)))
        )
        self.id_order = np.argsort(np.argsort(np.array(self.ids, dtype=object)))
        self.clusters = None if clusters is None else np.array(list(clusters))
        self.rostered = None if rostered is None else np.asarray(rostered, dtype=bool)
        self.members = {p: np.where(self.pos == p)[0] for p in POSITIONS}
        n = len(self.ids)
        for k, v in self.scores.items():
            if len(v) != n:
                raise ValueError(f"score vector {k!r} has {len(v)} rows, expected {n}")
        if len(self.y) != n or len(self.pos) != n:
            raise ValueError("outcome/position length mismatch")

    def n_by_position(self) -> dict[str, int]:
        return {p: int(len(self.members[p])) for p in POSITIONS}

    def qualifying(self, minimum: int = MIN_N_PER_POSITION) -> list[str]:
        return [p for p in POSITIONS if len(self.members[p]) >= minimum]

    def identity_selection(self) -> dict[str, np.ndarray]:
        return {p: np.arange(len(self.members[p])) for p in POSITIONS}


def top_k_rows(score: np.ndarray, tiebreak: np.ndarray, id_order: np.ndarray, k: int) -> np.ndarray:
    """The ``k`` rows with the highest score; ties broken by champion value, then id."""
    order = np.lexsort((id_order, -tiebreak, -score))
    return order[:k]


def realized_top_k(y: np.ndarray, k: int) -> np.ndarray:
    """The realized elite set: the top ``k`` by Y, every player tied at the boundary included."""
    if len(y) <= k:
        return np.arange(len(y))
    cut = np.sort(y)[::-1][k - 1]
    return np.where(y >= cut)[0]


def precision_at_k(
    score: np.ndarray, y: np.ndarray, tiebreak: np.ndarray, id_order: np.ndarray, k: int
) -> float:
    if len(y) == 0:
        return float("nan")
    pred = set(top_k_rows(score, tiebreak, id_order, k).tolist())
    real = set(realized_top_k(y, k).tolist())
    return len(pred & real) / float(min(k, max(1, len(pred))))


def cross_pair_stats(
    v_off: np.ndarray, v_idp: np.ndarray, y_off: np.ndarray, y_idp: np.ndarray
) -> dict[str, float]:
    """Section 7.2 concordance and section 9.3 level diagnostic on offense x IDP pairs."""
    dv = np.sign(v_off[:, None] - v_idp[None, :])
    dy = np.sign(y_off[:, None] - y_idp[None, :])
    valid = dy != 0
    n_valid = int(valid.sum())
    if n_valid == 0:
        return {"cc": float("nan"), "idpOverShare": float("nan"), "pairs": 0, "wrong": 0}
    conc = ((dv * dy) > 0).astype(float) + 0.5 * (dv == 0)
    cc = float(conc[valid].sum() / n_valid)
    over = int(((dv < 0) & (dy > 0)).sum())  # candidate says the defender is worth more; he was not
    under = int(((dv > 0) & (dy < 0)).sum())
    wrong = over + under
    return {
        "cc": cc,
        "idpOverShare": (over / wrong) if wrong else float("nan"),
        "pairs": n_valid,
        "wrong": wrong,
    }


def metrics_on(
    data: Cohort,
    sel: Mapping[str, np.ndarray],
    cands: Sequence[str],
    qual: Sequence[str],
) -> dict[str, Any]:
    """Every section 7 quantity on one selection (the data itself, or one resample)."""
    names = ["champion", *cands]
    rho: dict[str, dict[str, float]] = {c: {} for c in names}
    prec12: dict[str, dict[str, float]] = {c: {} for c in names}
    rows_by_pos = {p: data.members[p][sel[p]] for p in POSITIONS}
    for p in qual:
        r = rows_by_pos[p]
        y = data.y[r]
        for c in names:
            s = data.scores[c][r]
            rho[c][p] = spearman(s, y)
            prec12[c][p] = precision_at_k(s, y, data.tiebreak[r], data.id_order[r], 12)
    off = np.concatenate([rows_by_pos[p] for p in OFFENSE]) if OFFENSE else np.array([], int)
    idp = np.concatenate([rows_by_pos[p] for p in IDP])
    allr = np.concatenate([rows_by_pos[p] for p in POSITIONS])
    cc: dict[str, float] = {}
    over: dict[str, float] = {}
    prec36: dict[str, float] = {}
    for c in names:
        st = cross_pair_stats(data.scores[c][off], data.scores[c][idp], data.y[off], data.y[idp])
        cc[c] = st["cc"]
        over[c] = st["idpOverShare"]
        prec36[c] = precision_at_k(
            data.scores[c][allr], data.y[allr], data.tiebreak[allr], data.id_order[allr], 36
        )
    return {"rho": rho, "prec12": prec12, "cc": cc, "over": over, "prec36": prec36}


def draw_bootstrap_selections(
    n_by_pos: Mapping[str, int], *, b: int = BOOT_B, seed: int = BOOT_SEED
) -> list[dict[str, np.ndarray]]:
    """Section 7.4's draw order, verbatim: for b in 1..B: for p in [QB, RB, WR, TE, DL, LB, DB]:
    idx[b][p] = rng.integers(0, n_p, n_p), from one ``Generator(PCG64(seed))`` stream."""
    rng = np.random.Generator(np.random.PCG64(seed))
    out: list[dict[str, np.ndarray]] = []
    for _ in range(b):
        sel: dict[str, np.ndarray] = {}
        for p in POSITIONS:
            n = int(n_by_pos[p])
            sel[p] = rng.integers(0, n, n) if n > 0 else np.array([], dtype=np.int64)
        out.append(sel)
    return out


def nanmean_or_nan(values: Sequence[float]) -> float:
    vals = [v for v in values if v == v]
    return float(np.mean(vals)) if vals else float("nan")


def deltas_from_metrics(
    m: Mapping[str, Any], cands: Sequence[str], qual: Sequence[str]
) -> dict[str, Any]:
    """Candidate-minus-champion deltas from one ``metrics_on`` result."""
    out: dict[str, Any] = {
        "rho": {},
        "delta1": {},
        "delta2": {},
        "d3pos": {},
        "d3pool": {},
        "over": {},
    }
    for c in cands:
        per = {p: m["rho"][c][p] - m["rho"]["champion"][p] for p in qual}
        out["rho"][c] = per
        out["delta1"][c] = nanmean_or_nan(list(per.values()))
        out["delta2"][c] = m["cc"][c] - m["cc"]["champion"]
        out["d3pos"][c] = nanmean_or_nan(
            [m["prec12"][c][p] - m["prec12"]["champion"][p] for p in qual]
        )
        out["d3pool"][c] = m["prec36"][c] - m["prec36"]["champion"]
        out["over"][c] = m["over"][c]
    return out


def bootstrap_deltas(
    data: Cohort,
    cands: Sequence[str],
    qual: Sequence[str],
    *,
    b: int = BOOT_B,
    seed: int = BOOT_SEED,
) -> dict[str, Any]:
    """The paired bootstrap: one set of draws for every candidate and every metric."""
    sels = draw_bootstrap_selections(data.n_by_position(), b=b, seed=seed)
    keys = ["delta1", "delta2", "d3pos", "d3pool", "over"]
    draws: dict[str, dict[str, list[float]]] = {k: {c: [] for c in cands} for k in keys}
    draws["rho"] = {f"{c}|{p}": [] for c in cands for p in qual}
    draws["ccLevel"] = {c: [] for c in ["champion", *cands]}
    for sel in sels:
        m = metrics_on(data, sel, cands, qual)
        d = deltas_from_metrics(m, cands, qual)
        for c in cands:
            for k in keys:
                draws[k][c].append(d[k][c])
            for p in qual:
                draws["rho"][f"{c}|{p}"].append(d["rho"][c][p])
        for c in ["champion", *cands]:
            draws["ccLevel"][c].append(m["cc"][c])
    return {k: {kk: np.asarray(vv) for kk, vv in v.items()} for k, v in draws.items()}


def interval(draws: np.ndarray) -> dict[str, Any]:
    vals = draws[~np.isnan(draws)]
    if len(vals) == 0:
        return {"lo": None, "hi": None, "nValid": 0}
    return {
        "lo": rnd(np.percentile(vals, 2.5), 4),
        "hi": rnd(np.percentile(vals, 97.5), 4),
        "nValid": int(len(vals)),
    }


def holm_families(
    point: Mapping[str, Any],
    boot: Mapping[str, Any],
    cands: Sequence[str],
    qual: Sequence[str],
    *,
    within_ok: bool,
    cross_ok: bool,
) -> dict[str, Any]:
    """F1, F2, F3 with Holm correction at familywise alpha = 0.05 (section 7.5)."""
    f1: dict[str, float] = {}
    for c in cands:
        if within_ok:
            f1[f"delta1|{c}"] = two_sided_p(boot["delta1"][c])
        if cross_ok:
            f1[f"delta2|{c}"] = two_sided_p(boot["delta2"][c])
    f2 = {f"rho|{c}|{p}": two_sided_p(boot["rho"][f"{c}|{p}"]) for c in cands for p in qual}
    f3: dict[str, float] = {}
    for c in cands:
        f3[f"d3pos|{c}"] = two_sided_p(boot["d3pos"][c])
        f3[f"d3pool|{c}"] = two_sided_p(boot["d3pool"][c])
    return {"F1": holm(f1), "F2": holm(f2), "F3": holm(f3)}


def axis_verdict(
    axis: str,
    c: str,
    point: Mapping[str, Any],
    fam: Mapping[str, Any],
    qual: Sequence[str],
    stability_signs: Mapping[str, bool],
    *,
    tested: bool,
) -> dict[str, Any]:
    """Section 8.2 for one candidate on one axis.  ``axis`` is ``within`` or ``cross``."""
    if not tested:
        return {"verdict": "insufficient_sample:cohort_size", "axis": axis, "candidate": c}
    own = "delta1" if axis == "within" else "delta2"
    other = "delta2" if axis == "within" else "delta1"
    threshold = MIN_EFFECT[own]
    delta = point[own][c]
    f1 = fam["F1"].get(f"{own}|{c}")
    reject = bool(f1 and f1["reject"])
    f2_neg = [
        p
        for p in qual
        if fam["F2"].get(f"rho|{c}|{p}", {}).get("reject") and point["rho"][c][p] < 0
    ]
    floor_hits = [p for p in qual if point["rho"][c][p] < POINT_FLOOR_PER_POSITION]
    other_floor = CROSS_FLOOR_FOR_WITHIN if axis == "within" else WITHIN_FLOOR_FOR_CROSS
    other_delta = point[other][c]
    guard_ok = other_delta == other_delta and other_delta >= other_floor
    unstable = sorted(k for k, same in stability_signs.items() if not same)
    detail = {
        "axis": axis,
        "candidate": c,
        "delta": rnd(delta, 4),
        "threshold": threshold,
        "f1Reject": reject,
        "f1HolmAdjustedP": rnd(f1["adjusted"], 4) if f1 else None,
        "f2SignificantNegativePositions": f2_neg,
        "positionsBelowPointFloor": floor_hits,
        "otherAxisDelta": rnd(other_delta, 4),
        "otherAxisFloor": other_floor,
        "otherAxisGuardOk": bool(guard_ok),
        "stabilitySignChanged": unstable,
    }
    if not reject:
        return {**detail, "verdict": "no_detectable_difference"}
    if delta < 0:
        return {**detail, "verdict": "champion_better"}
    if delta < threshold:
        return {**detail, "verdict": "below_meaningful_effect"}
    if f2_neg or floor_hits or not guard_ok:
        return {**detail, "verdict": "advance_blocked_regression"}
    if unstable:
        return {**detail, "verdict": "advance_unstable"}
    return {**detail, "verdict": "advance_retrospective"}


# ── outcomes (the only place real outcomes are read) ─────────────────────────


def load_outcomes(
    fetch: Fetcher,
    card: Mapping[str, float],
    *,
    season: int = SEASON,
    weeks: Sequence[int] = HOLD_OUT_WEEKS,
    with_matchups: bool = True,
) -> dict[str, Any]:
    """Sleeper's stat dumps and matchups for ``weeks``, scored by the host-native scorer.

    The real run reads 2026 weeks 1-6.  ``--rehearsal`` points it at the PUBLIC 2025
    weeks 1-6 instead (no matchups exist for them in the cache), which exercises every
    line of stage 2 without touching a 2026 outcome."""
    pdb = fetch.get(f"{SLEEPER}/players/nfl")
    pos_pdb = {str(sid): position_of(p.get("position")) for sid, p in pdb.items()}
    fps_pdb = {
        str(sid): tuple(
            dict.fromkeys(
                [position_of(p.get("position"))]
                + [position_of(x) for x in (p.get("fantasy_positions") or [])]
            )
        )
        for sid, p in pdb.items()
    }
    stats = {w: fetch.get(f"{SLEEPER}/stats/nfl/regular/{season}/{w}") for w in weeks}
    matchups = (
        {w: fetch.get(f"{SLEEPER}/league/{LEAGUE_ID}/matchups/{w}") for w in weeks}
        if with_matchups
        else {}
    )
    pts = {w: score_dump(stats[w], pos_pdb, card, season=season, week=w) for w in weeks}
    return {"pdbPos": pos_pdb, "pdbFps": fps_pdb, "stats": stats, "matchups": matchups, "pts": pts}


def preconditions(out: Mapping[str, Any], slots: Sequence[str], port: SolverPort) -> dict[str, Any]:
    """Section 6.3, run before any metric.  Either failure stops the run."""
    diffs: list[float] = []
    unmatched_nonzero = 0
    for w, ms in out["matchups"].items():
        for m in ms or []:
            for sid, hp in (m.get("players_points") or {}).items():
                got = out["pts"][w].get(str(sid))
                if got is None:
                    if abs(float(hp)) > 1e-9:
                        unmatched_nonzero += 1
                    continue
                diffs.append(abs(got - float(hp)))
    scorer = {
        "playerWeeksCompared": len(diffs),
        "maxAbsDiff": rnd(max(diffs), 5) if diffs else None,
        "within0.0051": sum(1 for d in diffs if d <= 0.0051),
        "awardedNonzeroWithoutStatLine": unmatched_nonzero,
        "note": "Sleeper publishes player points rounded to 2 decimals; the host-native scorer is unrounded",
    }
    scorer["ok"] = bool(diffs) and scorer["within0.0051"] == len(diffs) and unmatched_nonzero == 0
    lineup_diffs: list[float] = []
    for w, ms in out["matchups"].items():
        for m in ms or []:
            ids = [str(p) for p in (m.get("players") or [])]
            if not ids or m.get("points") is None:
                continue
            scores = {sid: out["pts"][w].get(sid, 0.0) for sid in ids}
            meta = {
                sid: (out["pdbPos"].get(sid, ""), tuple(out["pdbFps"].get(sid, ()))) for sid in ids
            }
            got = cp.lineup_total(port, slots, ids, scores, meta)
            lineup_diffs.append(abs(got - float(m["points"])))
    lineup = {
        "teamWeeks": len(lineup_diffs),
        "maxAbsDiff": rnd(max(lineup_diffs), 5) if lineup_diffs else None,
        "within0.02": sum(1 for d in lineup_diffs if d < 0.02),
        "rule": "a rostered player with no stat line scores 0.0 and is startable (the host's rule)",
    }
    lineup["ok"] = bool(lineup_diffs) and lineup["within0.02"] == len(lineup_diffs)
    return {"scorer": scorer, "lineup": lineup, "ok": bool(scorer["ok"] and lineup["ok"])}


def realized_scores(
    out: Mapping[str, Any], ids: Sequence[str], weeks: Sequence[int]
) -> dict[int, dict[str, float]]:
    """Per week, every id's points; no stat line on a rostered/added player is 0.0 (host rule)."""
    return {w: {pid: out["pts"][w].get(pid, 0.0) for pid in ids} for w in weeks}


def lambc(
    port: SolverPort,
    universe: Mapping[str, Any],
    y_by_week: Mapping[int, Mapping[str, float]],
    evaluate: Sequence[str],
    weeks: Sequence[int],
) -> dict[str, float]:
    """Realized league-average marginal best-ball contribution (section 6.1)."""
    info = universe["info"]
    meta = {pid: (i["position"], tuple(i["fantasyPositions"])) for pid, i in info.items()}
    acc: dict[str, float] = defaultdict(float)
    for w in weeks:
        marg = cp.league_average_marginals(
            port, universe["slots"], universe["teams"], y_by_week[w], evaluate, meta
        )
        for pid, v in marg.items():
            acc[pid] += v
    return {pid: v / len(weeks) for pid, v in acc.items()}


def window_games(
    out: Mapping[str, Any], ids: Sequence[str], weeks: Sequence[int]
) -> dict[str, int]:
    return {pid: sum(1 for w in weeks if pid in out["pts"][w]) for pid in ids}


def realized_ppg(
    out: Mapping[str, Any], ids: Sequence[str], weeks: Sequence[int]
) -> dict[str, float | None]:
    res: dict[str, float | None] = {}
    for pid in ids:
        vals = [out["pts"][w][pid] for w in weeks if pid in out["pts"][w]]
        res[pid] = (sum(vals) / len(vals)) if vals else None
    return res


# ── assembling cohorts ───────────────────────────────────────────────────────


def build_arrays(
    vectors: Mapping[str, Mapping[str, float]],
    ids: Sequence[str],
    *,
    a_suffix: str = "",
    c_key: str = "C",
    d_key: str = "D",
    only: Sequence[str] | None = None,
) -> dict[str, np.ndarray]:
    """Candidate score arrays aligned to ``ids``.  A is its lexicographic order key."""
    want = set(only) if only is not None else {"champion", "A", "C", "D", "R0"}
    out: dict[str, np.ndarray] = {}
    if "champion" in want:
        out["champion"] = np.array([vectors["champion"][i] for i in ids], dtype=float)
    if "A" in want:
        out["A"] = lex_rank_scores(
            [vectors[f"A_dv{a_suffix}"][i] for i in ids],
            [vectors[f"A_vorg{a_suffix}"][i] for i in ids],
        )
    if "C" in want:
        out["C"] = np.array([vectors[c_key][i] for i in ids], dtype=float)
    if "D" in want:
        out["D"] = np.array([vectors[d_key][i] for i in ids], dtype=float)
    if "R0" in want:
        out["R0"] = np.array([vectors["R0_mu"][i] for i in ids], dtype=float)
    return out


def make_cohort(
    ids: Sequence[str],
    table: Mapping[str, Mapping[str, Any]],
    y: Mapping[str, float],
    arrays: Mapping[str, np.ndarray],
) -> Cohort:
    ids = list(ids)
    return Cohort(
        ids,
        [table[i]["pos"] for i in ids],
        [y[i] for i in ids],
        arrays,
        clusters=[str(table[i].get("nflTeam") or "NONE") for i in ids],
        rostered=[bool(table[i].get("rostered")) for i in ids],
    )


def point_summary(
    data: Cohort, cands: Sequence[str], qual: Sequence[str], *, weights: str = "equal"
) -> dict[str, Any]:
    """Point estimates of Delta1, Delta2, the level diagnostic and elite deltas (no inference)."""
    m = metrics_on(data, data.identity_selection(), cands, qual)
    d = deltas_from_metrics(m, cands, qual)
    if weights == "n":
        n_p = data.n_by_position()
        for c in cands:
            num = sum(n_p[p] * d["rho"][c][p] for p in qual if d["rho"][c][p] == d["rho"][c][p])
            den = sum(n_p[p] for p in qual if d["rho"][c][p] == d["rho"][c][p])
            d["delta1"][c] = num / den if den else float("nan")
    return {"metrics": m, "deltas": d}


# ── stability variants (section 10) ──────────────────────────────────────────


def variant_row(
    data: Cohort, cands: Sequence[str], qual: Sequence[str], **kw: Any
) -> dict[str, Any]:
    s = point_summary(data, cands, qual, **kw)
    d = s["deltas"]
    return {
        "n": len(data.ids),
        "delta1": {c: rnd(d["delta1"][c], 4) for c in cands},
        "delta2": {c: rnd(d["delta2"][c], 4) for c in cands},
        "idpOverShare": {c: rnd(d["over"][c], 4) for c in cands},
        "championIdpOverShare": rnd(s["metrics"]["over"]["champion"], 4),
    }


def cluster_bootstrap(
    data: Cohort,
    cands: Sequence[str],
    qual: Sequence[str],
    *,
    b: int = BOOT_B,
    seed: int = BOOT_SEED,
) -> dict[str, Any]:
    """S8: resample NFL teams (clusters of players), recompute the deltas."""
    if data.clusters is None:
        return {"state": "not_evaluable: no clusters"}
    teams = sorted(set(data.clusters.tolist()))
    rows_of = {t: np.where(data.clusters == t)[0] for t in teams}
    local = {p: {int(r): j for j, r in enumerate(data.members[p])} for p in POSITIONS}
    rng = np.random.Generator(np.random.PCG64(seed + 1))
    acc: dict[str, dict[str, list[float]]] = {c: {"delta1": [], "delta2": []} for c in cands}
    for _ in range(b):
        pick = rng.integers(0, len(teams), len(teams))
        rows = np.concatenate([rows_of[teams[i]] for i in pick])
        sel = {
            p: np.array([local[p][int(r)] for r in rows if int(r) in local[p]], dtype=np.int64)
            for p in POSITIONS
        }
        m = metrics_on(data, sel, cands, qual)
        d = deltas_from_metrics(m, cands, qual)
        for c in cands:
            acc[c]["delta1"].append(d["delta1"][c])
            acc[c]["delta2"].append(d["delta2"][c])
    return {c: {k: interval(np.asarray(v)) for k, v in acc[c].items()} for c in cands} | {
        "clusters": len(teams),
        "replicates": b,
    }


# ── failure-case slices (section 11) ─────────────────────────────────────────


def slice_row(
    data: Cohort, mask: np.ndarray, cands: Sequence[str], *, min_n: int = 15, min_pos: int = 8
) -> dict[str, Any]:
    n = int(mask.sum())
    if n < min_n:
        return {"n": n, "state": "unavailable: n < 15"}
    rows = np.where(mask)[0]
    out: dict[str, Any] = {
        "n": n,
        "delta_rho": {},
        "positionsUsed": {},
        "deltaCrossConcordance": {},
    }
    for c in cands:
        per = []
        used = []
        for p in POSITIONS:
            r = rows[data.pos[rows] == p]
            if len(r) >= min_pos:
                per.append(
                    spearman(data.scores[c][r], data.y[r])
                    - spearman(data.scores["champion"][r], data.y[r])
                )
                used.append(p)
        out["delta_rho"][c] = rnd(nanmean_or_nan(per), 4) if per else None
        out["positionsUsed"][c] = used
        off = rows[np.isin(data.pos[rows], OFFENSE)]
        idp = rows[np.isin(data.pos[rows], IDP)]
        if len(off) >= 5 and len(idp) >= 5:
            a = cross_pair_stats(
                data.scores[c][off], data.scores[c][idp], data.y[off], data.y[idp]
            )["cc"]
            b0 = cross_pair_stats(
                data.scores["champion"][off],
                data.scores["champion"][idp],
                data.y[off],
                data.y[idp],
            )["cc"]
            out["deltaCrossConcordance"][c] = rnd(a - b0, 4)
        else:
            out["deltaCrossConcordance"][c] = None
    return out


def worst_rank_errors(
    data: Cohort, names: Mapping[str, str], c: str, k: int = 20
) -> list[dict[str, Any]]:
    """Players with the largest increase in absolute within-position PERCENTILE rank error
    against the champion: ``|rank_c - rank_Y| - |rank_0 - rank_Y|`` (public names only)."""
    rows: list[tuple[float, str, str, float, float]] = []
    for p in POSITIONS:
        r = data.members[p]
        if len(r) < 5:
            continue
        ry = midranks(data.y[r]) / len(r)
        rc = midranks(data.scores[c][r]) / len(r)
        r0 = midranks(data.scores["champion"][r]) / len(r)
        for j, row in enumerate(r):
            rows.append(
                (
                    abs(rc[j] - ry[j]) - abs(r0[j] - ry[j]),
                    data.ids[row],
                    p,
                    float(rc[j]),
                    float(ry[j]),
                )
            )
    rows.sort(key=lambda t: (-t[0], t[1]))
    return [
        {
            "player": names[pid],
            "position": p,
            "errorIncrease": rnd(inc, 3),
            "candidatePercentileRank": rnd(rc, 3),
            "realizedPercentileRank": rnd(ry, 3),
        }
        for inc, pid, p, rc, ry in rows[:k]
    ]


def elite_separation(data: Cohort, c: str, positions: Sequence[str]) -> dict[str, Any]:
    """Section 9.4 (cardinal): mean of the top 12 / mean of ranks 13-36, for a points-scale
    candidate and for the outcome."""
    out: dict[str, Any] = {}
    for p in positions:
        r = data.members[p]
        if len(r) < 36:
            out[p] = {"state": "unavailable: fewer than 36"}
            continue
        order_c = np.argsort(-data.scores[c][r], kind="stable")
        order_y = np.argsort(-data.y[r], kind="stable")
        sc = data.scores[c][r][order_c]
        sy = data.y[r][order_y]
        out[p] = {
            "predictionRatio": rnd(sc[:12].mean() / sc[12:36].mean(), 3)
            if sc[12:36].mean() > 0
            else None,
            "outcomeRatio": rnd(sy[:12].mean() / sy[12:36].mean(), 3)
            if sy[12:36].mean() > 0
            else None,
        }
    return out


# ── roster counterfactuals (section 9.1) ─────────────────────────────────────


def lineup_meta(universe: Mapping[str, Any]) -> dict[str, tuple[str, tuple[str, ...]]]:
    return {
        pid: (i["position"], tuple(i["fantasyPositions"])) for pid, i in universe["info"].items()
    }


def swap_universe(
    universe: Mapping[str, Any], cohort: Sequence[str]
) -> dict[str, list[tuple[str, str]]]:
    """Every legal swap at the cutoff: drop ``r`` in the team's roster and cohort, add ``f`` in
    the cohort and unrostered."""
    cset = set(cohort)
    free = sorted(pid for pid in cohort if pid not in universe["rostered"])
    out: dict[str, list[tuple[str, str]]] = {}
    for t in sorted(universe["teams"]):
        drops = sorted(pid for pid in universe["teams"][t] if pid in cset)
        out[t] = [(r, f) for r in drops for f in free]
    return out


def swaps_realized(
    port: SolverPort,
    universe: Mapping[str, Any],
    y_by_week: Mapping[int, Mapping[str, float]],
    swaps: Mapping[str, Sequence[tuple[str, str]]],
    weeks: Sequence[int],
) -> dict[str, np.ndarray]:
    meta = lineup_meta(universe)
    slots = universe["slots"]
    out: dict[str, np.ndarray] = {}
    for t, lst in swaps.items():
        roster = tuple(universe["teams"][t])
        acc = np.zeros(len(lst))
        for w in weeks:
            scores = y_by_week[w]
            base = cp.lineup_total(port, slots, roster, scores, meta)
            for k, (r, f) in enumerate(lst):
                after = tuple(x for x in roster if x != r) + (f,)
                acc[k] += cp.lineup_total(port, slots, after, scores, meta) - base
        out[t] = acc
    return out


def swaps_predicted_mu(
    port: SolverPort,
    universe: Mapping[str, Any],
    mu: Mapping[str, float],
    swaps: Mapping[str, Sequence[tuple[str, str]]],
) -> dict[str, np.ndarray]:
    """Candidate C's deterministic mu-lineup change for the team."""
    meta = lineup_meta(universe)
    slots = universe["slots"]
    out: dict[str, np.ndarray] = {}
    for t, lst in swaps.items():
        roster = tuple(universe["teams"][t])
        base = cp.lineup_total(port, slots, roster, mu, meta)
        out[t] = np.array(
            [
                cp.lineup_total(port, slots, tuple(x for x in roster if x != r) + (f,), mu, meta)
                - base
                for r, f in lst
            ]
        )
    return out


def _worker_init_swaps(spec: dict[str, Any]) -> None:
    """The stage 1 worker initialiser, plus the swap universe section 9.1 needs."""
    _worker_init(spec)
    _W["swaps"] = spec["swaps"]


def _worker_swaps(weeks: list[int]) -> dict[str, list[float]]:
    inputs = _W["inputs"]
    port = _W["port"]
    swaps = _W["swaps"]
    meta = {
        pid: (inputs.position.get(pid, ""), tuple(inputs.fantasy_positions.get(pid, ())))
        for pid in set(inputs.position)
    }
    acc = {t: np.zeros(len(lst)) for t, lst in swaps.items()}
    for s in weeks:
        scores = cp.draw_week(inputs, cp.week_rng(_W["seed"], s), sigma=_W["sigma"])
        for t, lst in swaps.items():
            roster = tuple(inputs.teams[t])
            base = cp.lineup_total(port, inputs.slots, roster, scores, meta)
            for k, (r, f) in enumerate(lst):
                after = tuple(x for x in roster if x != r) + (f,)
                acc[t][k] += cp.lineup_total(port, inputs.slots, after, scores, meta) - base
    return {t: a.tolist() for t, a in acc.items()}


def swaps_predicted_d(
    spec: dict[str, Any],
    swaps: Mapping[str, Sequence[tuple[str, str]]],
    *,
    weeks: int = SIM_WEEKS,
    workers: int | None = None,
) -> dict[str, np.ndarray]:
    """Candidate D's simulated expected lineup change for the team: same S, same seed."""
    spec = {**spec, "swaps": {t: list(v) for t, v in swaps.items()}}
    n = int(workers if workers is not None else max(1, min(16, (os.cpu_count() or 2) - 2)))
    idx = list(range(int(weeks)))
    total = {t: np.zeros(len(lst)) for t, lst in swaps.items()}
    if n <= 1:
        _worker_init_swaps(spec)
        parts = [_worker_swaps(idx)]
    else:
        chunks = [idx[i :: n * 2] for i in range(n * 2) if idx[i :: n * 2]]
        with ProcessPoolExecutor(
            max_workers=n, initializer=_worker_init_swaps, initargs=(spec,)
        ) as ex:
            parts = list(ex.map(_worker_swaps, chunks))
    for part in parts:
        for t, arr in part.items():
            total[t] += np.asarray(arr)
    return {t: a / float(weeks) for t, a in total.items()}


def swap_report(
    swaps: Mapping[str, Sequence[tuple[str, str]]],
    realized: Mapping[str, np.ndarray],
    predicted: Mapping[str, Mapping[str, np.ndarray]],
    *,
    points_scale: Sequence[str],
    weeks: int,
) -> dict[str, Any]:
    """Section 9.1.  Descriptive only: 12 teams, no inferential claim."""
    out: dict[str, Any] = {
        "teams": len(swaps),
        "swapsPerTeam": {
            "min": min(len(v) for v in swaps.values()),
            "max": max(len(v) for v in swaps.values()),
        },
        "swapsTotal": int(sum(len(v) for v in swaps.values())),
        "swapsWithNonzeroRealizedGain": int(sum(int((realized[t] != 0).sum()) for t in swaps)),
        "candidates": {},
    }
    tops: dict[str, dict[str, int]] = {}
    for name, pred in predicted.items():
        correct = 0.0
        counted = 0
        top1: dict[str, tuple[float, float]] = {}
        top3: list[float] = []
        for t, lst in swaps.items():
            p = np.asarray(pred[t])
            rr = np.asarray(realized[t])
            mask = rr != 0
            counted += int(mask.sum())
            correct += float(((np.sign(p) == np.sign(rr)) & mask & (p != 0)).sum())
            correct += 0.5 * float(((p == 0) & mask).sum())
            # deterministic tie-break: highest predicted gain, then drop id, then add id
            order = sorted(range(len(lst)), key=lambda k: (-p[k], lst[k][0], lst[k][1]))
            if order:
                top1[t] = (float(rr[order[0]]), float(p[order[0]]))
                top3.extend(float(rr[k]) for k in order[:3])
        mean_top1 = float(np.mean([v[0] for v in top1.values()])) if top1 else None
        entry = {
            "pairwiseSignAccuracy": rnd(correct / counted, 4) if counted else None,
            "swapsCounted": counted,
            "topSwapMeanRealizedPointsOver6Weeks": rnd(mean_top1, 3),
            "top3MeanRealizedPointsOver6Weeks": rnd(float(np.mean(top3)), 3) if top3 else None,
        }
        if name in points_scale:
            pred_mean = float(np.mean([v[1] for v in top1.values()])) if top1 else None
            entry["topSwapMeanPredictedPointsPerWeek"] = rnd(pred_mean, 3)
            entry["predictedMinusRealizedPerWeek"] = (
                rnd(pred_mean - mean_top1 / weeks, 3)
                if pred_mean is not None and mean_top1 is not None
                else None
            )
            entry["gapNote"] = (
                "selection on predicted gain inflates the prediction; reported, never used to score"
            )
        else:
            entry["predictedGap"] = "unavailable: no_validated_points_mapping"
        out["candidates"][name] = entry
        tops[name] = {t: v[0] for t, v in top1.items()}
    base = tops.get("champion", {})
    for name in out["candidates"]:
        if name == "champion":
            continue
        out["candidates"][name]["teamsBeatingChampionTopSwap"] = sum(
            1 for t, v in tops[name].items() if v > base.get(t, float("-inf"))
        )
    return out


# ── trade examples (section 9.2) ─────────────────────────────────────────────


def trade_id(ta: str, tb: str, give_a: Sequence[str], give_b: Sequence[str]) -> str:
    return f"{ta}|{tb}|{','.join(sorted(give_a))}|{','.join(sorted(give_b))}"


def trade_hash(tid: str, salt: str = "idp-g-v1") -> str:
    return hashlib.sha256((salt + tid).encode("utf-8")).hexdigest()


def champion_calls_fair(
    give_a: Sequence[str], give_b: Sequence[str], value: Mapping[str, float]
) -> tuple[bool, float]:
    """The champion's own rule: the adjusted gap from ``geom_q078_v1`` sits inside the
    ``fairness_bands_v2`` fair band.  Returns ``(fair, gap_for_team_a)`` with
    ``gap = U(received) - U(given)`` from team A's side."""
    from src.valuation_math import fairness_bands  # noqa: PLC0415

    va = [value[p] for p in give_a]
    vb = [value[p] for p in give_b]
    u_a, u_b = fairness_bands.package_utilities(va, vb)
    gap_a = u_b - u_a
    level = fairness_bands.classify_packages(gap_a, va, vb)["level"]
    return fairness_bands.counts_as_fair_trade(level), float(gap_a)


def enumerate_trades(
    universe: Mapping[str, Any],
    cohort: Sequence[str],
    pos: Mapping[str, str],
    category: str,
    cap: int | None,
):
    """Yield ``(trade_id, ta, tb, give_a, give_b)`` for one category, ``ta < tb``."""
    cset = set(cohort)
    labels = sorted(universe["teams"])
    roster = {t: sorted(p for p in universe["teams"][t] if p in cset) for t in labels}
    size = {t: len(universe["teams"][t]) for t in labels}
    from itertools import combinations  # noqa: PLC0415

    for i, ta in enumerate(labels):
        for tb in labels[i + 1 :]:
            if category == "a":
                for a in roster[ta]:
                    for b in roster[tb]:
                        if (pos[a] in OFFENSE) != (pos[b] in OFFENSE):
                            yield trade_id(ta, tb, [a], [b]), ta, tb, (a,), (b,)
            else:
                for pair in combinations(roster[ta], 2):
                    for b in roster[tb]:
                        # team ta gives two, receives one: ta receives MORE players? no --
                        # ta gives 2 / gets 1, so tb receives the extra player
                        if category == "c" and not (cap and size[tb] + 1 > cap):
                            continue
                        yield trade_id(ta, tb, pair, [b]), ta, tb, pair, (b,)
                for pair in combinations(roster[tb], 2):
                    for a in roster[ta]:
                        if category == "c" and not (cap and size[ta] + 1 > cap):
                            continue
                        yield trade_id(ta, tb, [a], pair), ta, tb, (a,), pair


def wilson_row(k: float, n: int) -> dict[str, Any]:
    lo, hi = wilson(int(round(k)), n)
    return {
        "correct": k,
        "n": n,
        "share": rnd(k / n, 4) if n else None,
        "wilson95": [rnd(lo, 3), rnd(hi, 3)],
    }


def first_fair_by_hash(gen, value: Mapping[str, float], limit: int = 150) -> dict[str, Any]:
    """The first ``limit`` trades, in ``sha256`` order, that the champion calls fair.

    Streams the whole universe through ``heapq.nsmallest`` (bounded memory) and widens the
    window until ``limit`` fair trades are found or the universe is exhausted."""
    import heapq  # noqa: PLC0415

    keep = 8 * limit
    while True:
        total = 0

        def keyed():
            nonlocal total
            for tid, ta, tb, ga, gb in gen():
                total += 1
                yield (trade_hash(tid), tid, ta, tb, ga, gb)

        ranked = heapq.nsmallest(keep, keyed())
        picked: list[dict[str, Any]] = []
        for h, tid, ta, tb, ga, gb in ranked:
            fair, gap = champion_calls_fair(ga, gb, value)
            if fair:
                picked.append(
                    {
                        "id": tid,
                        "hash": h,
                        "ta": ta,
                        "tb": tb,
                        "giveA": ga,
                        "giveB": gb,
                        "gapA": gap,
                    }
                )
            if len(picked) >= limit:
                break
        if len(picked) >= limit or keep >= total:
            return {"trades": picked, "universeSize": total, "scanned": min(keep, total)}
        keep *= 4


def lineup_with_starters(
    port: SolverPort,
    slots: Sequence[str],
    roster: Sequence[str],
    scores: Mapping[str, float],
    meta: Mapping[str, tuple[str, tuple[str, ...]]],
) -> tuple[float, set[str]]:
    players = [
        rs.LineupPlayer(pid, meta[pid][0], meta[pid][1], float(scores[pid]))
        for pid in roster
        if pid in scores
    ]
    if not players:
        return 0.0, set()
    assignment = port.solve(players, list(slots))
    pts = {p.player_id: p.points for p in players}
    return math.fsum(pts[pid] for pid in assignment.values()), set(assignment.values())


class TradeCtx:
    """Everything section 9.2 needs, built once."""

    def __init__(
        self,
        universe: Mapping[str, Any],
        port: SolverPort,
        y_by_week: Mapping[int, Mapping[str, float]],
        weeks: Sequence[int],
        value: Mapping[str, float],
        a_key: Mapping[str, tuple[float, float]],
        a_tv: Mapping[str, float],
        bd_params: Any,
        mu: Mapping[str, float],
        sim_scores: Sequence[Mapping[str, float]],
        simulable: set[str],
    ) -> None:
        self.universe = universe
        self.port = port
        self.slots = universe["slots"]
        self.meta = lineup_meta(universe)
        self.y = y_by_week
        self.weeks = list(weeks)
        self.value = value
        self.a_key = a_key
        self.a_tv = a_tv
        self.bd_params = bd_params
        self.mu = mu
        self.sim = list(sim_scores)
        self.simulable = simulable
        self.cap = universe["rosterCap"]
        self.teams = {t: tuple(v) for t, v in universe["teams"].items()}
        self.base_real = {
            t: sum(self.L(r, self.y[w]) for w in self.weeks) for t, r in self.teams.items()
        }
        self.base_mu = {t: self.L(r, self.mu) for t, r in self.teams.items()}
        self.base_sim = {t: [self.L(r, x) for x in self.sim] for t, r in self.teams.items()}

    def L(self, roster: Sequence[str], scores: Mapping[str, float]) -> float:
        return cp.lineup_total(self.port, self.slots, roster, scores, self.meta)

    def realized_gain(self, t: str, roster: Sequence[str]) -> float:
        return sum(self.L(roster, self.y[w]) for w in self.weeks) - self.base_real[t]

    def mu_gain(self, t: str, roster: Sequence[str]) -> float:
        return self.L(roster, self.mu) - self.base_mu[t]

    def sim_gain(self, t: str, roster: Sequence[str]) -> float:
        return float(np.mean([self.L(roster, x) - b for x, b in zip(self.sim, self.base_sim[t])]))

    def cut(self, cand: str, roster: Sequence[str]) -> str | None:
        """The candidate's own cut: lowest own value (champion, A) or least expected lineup
        points lost (C, D).  Only players the candidate can score are cut candidates (an
        unknown player is never a free cut)."""
        if cand == "champion":
            pool = [(self.value[p], p) for p in roster if p in self.value]
            return min(pool)[1] if pool else None
        if cand == "A":
            pool = [(self.a_key[p], p) for p in roster if p in self.a_key]
            return min(pool)[1] if pool else None
        if cand == "C":
            base = self.L(roster, self.mu)
            pool = [
                (base - self.L(tuple(x for x in roster if x != p), self.mu), p)
                for p in roster
                if p in self.mu
            ]
            return min(pool)[1] if pool else None
        loss: dict[str, float] = defaultdict(float)
        eligible = [p for p in roster if p in self.simulable]
        for x in self.sim:
            total, starters = lineup_with_starters(self.port, self.slots, roster, x, self.meta)
            for r in starters:
                if r in self.simulable:
                    loss[r] += total - self.L(tuple(y for y in roster if y != r), x)
        pool = [(loss.get(p, 0.0), p) for p in eligible]
        return min(pool)[1] if pool else None

    def predicted_edge(
        self,
        cand: str,
        ta: str,
        tb: str,
        ga: tuple[str, ...],
        gb: tuple[str, ...],
        final: Mapping[str, Sequence[str]],
    ) -> float | None:
        """Positive means team ``ta`` is called the winner."""
        if cand == "champion":
            from src.valuation_math import fairness_bands  # noqa: PLC0415

            u_a, u_b = fairness_bands.package_utilities(
                [self.value[p] for p in ga], [self.value[p] for p in gb]
            )
            return float(u_b - u_a)
        if cand == "A":
            from src.bdvm.trade_math import package_value  # noqa: PLC0415

            if any(p not in self.a_tv for p in (*ga, *gb)):
                return None
            pa_recv = package_value([self.a_tv[p] for p in gb], self.bd_params)
            pa_give = package_value([self.a_tv[p] for p in ga], self.bd_params)
            pb_recv = package_value([self.a_tv[p] for p in ga], self.bd_params)
            pb_give = package_value([self.a_tv[p] for p in gb], self.bd_params)
            return float((pa_recv - pa_give) - (pb_recv - pb_give))
        if cand == "C":
            return self.mu_gain(ta, final[ta]) - self.mu_gain(tb, final[tb])
        return self.sim_gain(ta, final[ta]) - self.sim_gain(tb, final[tb])


def evaluate_trades(
    sample: Mapping[str, Any], ctx: TradeCtx, cands: Sequence[str], *, category: str
) -> dict[str, Any]:
    rows: dict[str, list[tuple[float, float, bool]]] = {c: [] for c in cands}
    skipped: Counter = Counter()
    for tr in sample["trades"]:
        ta, tb, ga, gb = tr["ta"], tr["tb"], tuple(tr["giveA"]), tuple(tr["giveB"])
        after = {
            ta: tuple(x for x in ctx.teams[ta] if x not in ga) + gb,
            tb: tuple(x for x in ctx.teams[tb] if x not in gb) + ga,
        }
        upgrade_is_a = len(ga) == 2  # the team that gives two receives the single player
        for c in cands:
            final = {}
            for t in (ta, tb):
                roster = after[t]
                if ctx.cap and len(roster) > ctx.cap:
                    cut = ctx.cut(c, roster)
                    if cut is not None:
                        roster = tuple(x for x in roster if x != cut)
                final[t] = roster
            edge = ctx.predicted_edge(c, ta, tb, ga, gb, final)
            if edge is None:
                skipped[f"{c}:unpriced_asset"] += 1
                continue
            real = ctx.realized_gain(ta, final[ta]) - ctx.realized_gain(tb, final[tb])
            rows[c].append((edge, real, upgrade_is_a if category == "b" else False))
    out: dict[str, Any] = {
        "category": category,
        "sampled": len(sample["trades"]),
        "universeSize": sample["universeSize"],
        "skipped": dict(skipped),
        "candidates": {},
    }
    for c, lst in rows.items():
        counted = [(e, r, up) for e, r, up in lst if r != 0]
        k = 0.0
        for e, r, _up in counted:
            k += 0.5 if e == 0 else float((e > 0) == (r > 0))
        entry = wilson_row(k, len(counted))
        entry["tradesWithRealizedWinner"] = len(counted)
        if category == "b" and counted:
            upgrade_called = sum(1 for e, _r, up in counted if (e > 0) == up and e != 0)
            upgrade_won = sum(1 for _e, r, up in counted if (r > 0) == up)
            entry["upgradeSideCalledWinner"] = upgrade_called
            entry["upgradeSideActuallyWon"] = upgrade_won
        out["candidates"][c] = entry
    return out


def analysis_block(
    data: Cohort,
    cands: Sequence[str],
    qual: Sequence[str],
    *,
    within_ok: bool,
    cross_ok: bool,
    b: int = BOOT_B,
) -> dict[str, Any]:
    """The preregistered inference on one cohort: points, intervals, p-values, Holm."""
    names = [*cands, REF_CANDIDATE]
    s = point_summary(data, names, qual)
    d = s["deltas"]
    boot = bootstrap_deltas(data, names, qual, b=b)
    fam = holm_families(d, boot, list(cands), qual, within_ok=within_ok, cross_ok=cross_ok)

    def cell(
        kind: str, c: str, *, fam_name: str | None = None, key: str | None = None
    ) -> dict[str, Any]:
        arr = boot[kind][c]
        out = {"point": rnd(d[kind][c], 4), **interval(arr)}
        if fam_name and key in fam[fam_name]:
            h = fam[fam_name][key]
            out.update(
                {"p": rnd(h["p"], 5), "holmAdjustedP": rnd(h["adjusted"], 5), "reject": h["reject"]}
            )
        return out

    per_c: dict[str, Any] = {}
    for c in names:
        in_fam = c != REF_CANDIDATE
        per_pos = {}
        for p in qual:
            arr = boot["rho"][f"{c}|{p}"]
            cellp = {"point": rnd(d["rho"][c][p], 4), **interval(arr)}
            if in_fam:
                h = fam["F2"][f"rho|{c}|{p}"]
                cellp.update(
                    {
                        "p": rnd(h["p"], 5),
                        "holmAdjustedP": rnd(h["adjusted"], 5),
                        "reject": h["reject"],
                    }
                )
            per_pos[p] = cellp
        entry = {
            "delta1_withinSpearman": cell(
                "delta1", c, fam_name="F1" if in_fam else None, key=f"delta1|{c}"
            ),
            "delta2_crossConcordance": cell(
                "delta2", c, fam_name="F1" if in_fam else None, key=f"delta2|{c}"
            ),
            "delta3pos_elitePrecision12": cell(
                "d3pos", c, fam_name="F3" if in_fam else None, key=f"d3pos|{c}"
            ),
            "delta3pool_elitePrecision36": cell(
                "d3pool", c, fam_name="F3" if in_fam else None, key=f"d3pool|{c}"
            ),
            "idpOverShareOfWrongPairs": {
                "point": rnd(d["over"][c], 4),
                **interval(boot["over"][c]),
            },
            "perPosition": per_pos,
            "rawAbsolute": {
                "spearmanByPosition": {p: rnd(s["metrics"]["rho"][c][p], 4) for p in qual},
                "crossConcordance": rnd(s["metrics"]["cc"][c], 4),
                "precision12ByPosition": {p: rnd(s["metrics"]["prec12"][c][p], 3) for p in qual},
                "precision36": rnd(s["metrics"]["prec36"][c], 3),
            },
        }
        per_c[c] = entry
    per_c["champion"] = {
        "rawAbsolute": {
            "spearmanByPosition": {p: rnd(s["metrics"]["rho"]["champion"][p], 4) for p in qual},
            "crossConcordance": rnd(s["metrics"]["cc"]["champion"], 4),
            "precision12ByPosition": {
                p: rnd(s["metrics"]["prec12"]["champion"][p], 3) for p in qual
            },
            "precision36": rnd(s["metrics"]["prec36"]["champion"], 3),
            "idpOverShareOfWrongPairs": rnd(s["metrics"]["over"]["champion"], 4),
        }
    }
    return {"summary": s, "boot": boot, "families": fam, "byCandidate": per_c}


def build_wb(
    args: argparse.Namespace,
    log,
    fetch: Fetcher,
    out_outcomes: Mapping[str, Any],
    manifest: Mapping[str, Any],
    port: SolverPort,
    *,
    stand_in_season: int | None = None,
) -> dict[str, Any]:
    """The Wb stability window (origin before week 4), built AFTER W0 is unblinded.

    ``stand_in_season`` exists only for the rehearsal: it reads weeks 1-3 of a PUBLIC earlier
    season where the real run reads 2026 weeks 1-3, so every line of this function runs
    without touching a 2026 outcome.

    Declared deviation D1: its admissible inputs include 2026 weeks 1-3 (section 2.3), which
    are W0 outcome weeks and so cannot be loaded in the blind stage (section 12.1).  Built
    here from weeks 1-3 only; weeks 4-6 outcomes are not touched until its score vectors are
    hashed.  Labelled exploratory.
    """
    kb = kickoff_utc(SEASON, 4)
    Kb = datetime.fromisoformat(kb["kickoffUtc"])
    arch = select_archive(Kb)
    cutoff = arch["g"]
    cutoff_date = cutoff.date().isoformat()
    raw = read_archive_payload(arch["path"])
    contract, notes = rebuild_champion(raw, arch["path"])
    board = board_rows(contract)
    universe = build_universe(raw, board)
    info = universe["info"]
    card = numeric_card(raw["sleeper"]["scoringSettings"])
    pos_by_id = {pid: i["position"] for pid, i in info.items() if i["position"]}
    s_in = stand_in_season or SEASON
    window = [(HISTORY_SEASON, w) for w in HISTORY_WEEKS] + [(s_in, w) for w in (1, 2, 3)]
    # weeks 1-3 only: the guard is for blind stage 1; here the dumps are read explicitly and by week
    hist: dict[str, dict[tuple[int, int], float]] = defaultdict(dict)
    for season, week in window:
        dump = fetch.get(f"{SLEEPER}/stats/nfl/regular/{season}/{week}")
        for sid, pts in score_dump(
            dump, pos_by_id, card, season=season, week=week, only_ids=set(info)
        ).items():
            hist[sid][(season, week)] = pts
    support = [pid for pid, i in info.items() if board.get(pid, {}).get("value") and stratum_ok(i)]
    provisional = [
        pid
        for pid in support
        if not (isinstance(info[pid].get("yearsExp"), (int, float)) and info[pid]["yearsExp"] < 1)
    ]
    avail = availability_inputs(universe, hist, provisional, window=window)
    # BDVM section 8.4 posterior from weeks 1-3: explicit truncated actuals
    from src.utils.name_clean import normalize_player_name as norm  # noqa: PLC0415

    by_key: dict[str, list[str]] = defaultdict(list)
    for pid, i in info.items():
        by_key[norm((board.get(pid) or {}).get("canonicalName") or i["name"])].append(pid)
    weekly_by_key: dict[str, list[tuple[int, float]]] = {}
    for k, ids in by_key.items():
        if len(ids) != 1:
            continue  # a name collision is dropped, never merged (BDVM's own policy)
        samples = [
            (w, hist[ids[0]][(s_in, w)]) for w in (1, 2, 3) if (s_in, w) in hist.get(ids[0], {})
        ]
        if samples:
            weekly_by_key[k] = samples
    bd = build_bdvm(contract, raw, cutoff_date, actuals=(4, weekly_by_key), age_variants=False)
    pm = project_mu(bd, universe, board)
    mu = pm["mu"]
    drift = max(
        (
            abs(float((e.get("projection") or {}).get("fpg")) - mu[str(e.get("playerId"))])
            for e in bd["payloads"]["base"].get("players") or []
            if str(e.get("playerId")) in mu
        ),
        default=0.0,
    )
    if drift > 5.1e-4:  # the payload publishes fpg rounded to 3 decimals
        raise SystemExit(f"Wb: P disagrees with BDVM's own posterior (max {drift})")
    a_base, _ = a_scores(bd["payloads"]["base"])
    records = player_records(universe)
    d1 = d1_thresholds(universe, records, port, lambda r: mu.get(r.player_id))
    c_base, _pi = c_scores(mu, universe, d1)
    evaluate = sorted(pid for pid in provisional if pid in mu)
    spec, reasons = sim_spec(universe, mu, avail, PSEUDO_GAMES, evaluate)
    d_res = run_d(spec, workers=args.workers)
    cohort = sorted(
        pid
        for pid in provisional
        if pm["status"].get(pid) == "projected"
        and pid in a_base
        and pid in c_base
        and pid in d_res.value
    )
    vectors = {
        "champion": {pid: float(board[pid]["value"]) for pid in support},
        "A_dv": {k: v[0] for k, v in a_base.items() if k in set(support)},
        "A_vorg": {k: v[1] for k, v in a_base.items() if k in set(support)},
        "R0_mu": {k: v for k, v in mu.items() if k in set(support)},
        "C": {k: v for k, v in c_base.items() if k in set(support)},
        "D": {k: v for k, v in d_res.value.items() if k in set(support)},
    }
    hashes = {k: vector_hash(v) for k, v in vectors.items()}
    log(f"Wb: archive {arch['name']}  cohort {len(cohort)}  hashed {list(hashes)}")
    weeks_b = (4, 5, 6)
    all_out = out_outcomes
    y_b = realized_scores(all_out, list(info), weeks_b)
    y = lambc(port, universe, y_b, cohort, weeks_b)
    table = {
        pid: {
            "pos": info[pid]["position"],
            "nflTeam": info[pid].get("team"),
            "rostered": info[pid]["rostered"],
        }
        for pid in cohort
    }
    arrays = build_arrays(vectors, cohort)
    data = make_cohort(cohort, table, y, arrays)
    return {
        "window": "Wb",
        "labelled": "exploratory (deviation D1)",
        "archive": {
            "name": arch["name"],
            "sha256": arch["sha256"],
            "cutoffInstant": cutoff.isoformat(),
        },
        "kickoff": kb,
        "champion": notes["mode"],
        "cohort": len(cohort),
        "byPosition": data.n_by_position(),
        "scoreVectorSha256": hashes,
        "vectorsHashedBeforeOutcomesJoined": True,
        "data": data,
        "qual": data.qualifying(),
    }


def load_stage1() -> tuple[dict[str, Any], dict[str, Any]]:
    """The committed blind-stage artifacts, with their internal hashes verified."""
    manifest = json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))
    scores = json.loads(SCORES_PATH.read_text(encoding="utf-8"))
    bad = [
        k
        for k, v in scores["vectors"].items()
        if vector_hash(v) != manifest["scoreVectorSha256"].get(k)
    ]
    if bad:
        raise SystemExit(f"committed score vectors do not hash to the manifest: {bad}")
    if ids_hash(scores["cohort"]) != manifest["cohort"]["idsSha256"]:
        raise SystemExit("committed cohort does not hash to the manifest")
    return manifest, scores


def recompute_base_vectors(P: Mapping[str, Any]) -> dict[str, dict[str, float]]:
    """The base score vectors from freshly prepared inputs (same rounding as stage 1)."""
    support = P["support"]

    def vec(d: Mapping[str, Any]) -> dict[str, float]:
        return {pid: round(float(d[pid]), 9) for pid in support if pid in d}

    return {
        "champion": {pid: float(P["board"][pid]["value"]) for pid in support},
        "A_dv": vec({k: v[0] for k, v in P["a_base"].items()}),
        "A_vorg": vec({k: v[1] for k, v in P["a_base"].items()}),
        "A_tradeValue": vec(a_trade_values(P["bd"]["payloads"]["base"])),
        "R0_mu": vec(P["mu"]),
        "C": vec(P["c_base"]),
        "D": vec(P["d_runs"]["base"].value),
        "D_se": vec(P["d_runs"]["base"].mc_se),
    }


def git_ancestor(a: str, b: str) -> bool:
    return (
        subprocess.run(
            ["git", "merge-base", "--is-ancestor", a, b], cwd=REPO, capture_output=True
        ).returncode
        == 0
    )


def stability_signs(
    cands: Sequence[str],
    main_deltas: Mapping[str, Any],
    variants: Mapping[str, Mapping[str, Any]],
    applies: Mapping[str, Sequence[str]],
    axis: str,
) -> dict[str, dict[str, bool]]:
    """For each candidate, whether the sign of its delta is unchanged under every applicable
    core variant (S1-S6).  A variant that is not evaluable does not block."""
    out: dict[str, dict[str, bool]] = {}
    for c in cands:
        base = main_deltas[axis][c]
        signs: dict[str, bool] = {}
        for vname, row in variants.items():
            if c not in applies.get(vname, ()):
                continue
            v = row.get(axis, {}).get(c)
            if v is None:
                continue
            signs[vname] = bool(base == base and v == v and (v > 0) == (base > 0) and v != 0)
        out[c] = signs
    return out


def stage2(args: argparse.Namespace) -> int:
    t0 = time.time()

    def log(msg: str) -> None:
        print(f"[{time.time() - t0:7.1f}s] {msg}", file=sys.stderr, flush=True)

    rehearsal = bool(args.rehearsal)
    prereg = check_preregistration()
    manifest, scores = load_stage1()
    rel_manifest = str(MANIFEST_PATH.relative_to(REPO)).replace("\\", "/")
    stage1_commit = git("log", "-1", "--format=%H", "--", rel_manifest)
    if not stage1_commit:
        raise SystemExit("the Stage 1 manifest has not been committed: stage 2 cannot start")
    if not git_ancestor(stage1_commit, "HEAD"):
        raise SystemExit("the Stage 1 commit is not an ancestor of HEAD")
    remote = git("branch", "-r", "--contains", stage1_commit)
    if not remote and not args.allow_unpushed:
        raise SystemExit("the Stage 1 commit has not been pushed: stage 2 refuses to start")
    code_ok = manifest["pins"].get("stage1CodeSha256") == stage1_code_hash()
    if not code_ok:
        raise SystemExit("the stage 1 portion of this script changed since the blind stage")
    log(f"stage 1 commit {stage1_commit[:9]} verified (pushed={bool(remote)}, code unchanged)")

    # ---- re-derive the base vectors and compare with the committed hashes ---------------
    P = prepare_window(args, log, variants=False)
    redo = recompute_base_vectors(P)
    reproduced = {k: vector_hash(v) == manifest["scoreVectorSha256"][k] for k, v in redo.items()}
    log(f"reproduced: {reproduced}")
    if not all(reproduced.values()):
        result = {
            "preregistration": "idp_accuracy_G_v1",
            "promotes": False,
            "status": "stage1_not_reproduced",
            "reproduced": reproduced,
        }
        EVIDENCE_DIR.mkdir(parents=True, exist_ok=True)
        RESULT_PATH.write_text(json.dumps(result, indent=1) + "\n", encoding="utf-8")
        return 3

    universe = P["universe"]
    info = universe["info"]
    port = P["port"]
    slots = universe["slots"]
    vec = scores["vectors"]
    table = {p["id"]: p for p in scores["players"]}
    support = list(P["support"])
    cohort = list(scores["cohort"])
    cands = list(manifest["candidates"]["evaluableSet"])
    qual = list(manifest["cohort"]["qualifyingPositions"])
    within_ok = bool(manifest["cohort"]["withinAxisSufficient"])
    cross_ok = bool(manifest["cohort"]["crossAxisSufficient"])

    # ---- outcomes: the first and only place they are read ----------------------------------
    fetch = Fetcher(blind=False, offline=args.offline)
    weeks = HOLD_OUT_WEEKS
    if rehearsal:
        out = load_outcomes(
            fetch, P["card"], season=HISTORY_SEASON, weeks=weeks, with_matchups=False
        )
        pre = {
            "ok": True,
            "rehearsal": "2025 weeks 1-6 stand in for the outcomes; preconditions skipped",
        }
    else:
        out = load_outcomes(fetch, P["card"])
        pre = preconditions(out, slots, port)
    log(f"preconditions ok={pre['ok']}")
    base_result = {
        "preregistration": "idp_accuracy_G_v1",
        "label": LABEL,
        "promotes": False,
        "rehearsal": rehearsal,
        "stage": 2,
        "pins": {
            "preregistration": prereg,
            "stage1Commit": stage1_commit,
            "stage1CommitPushed": bool(remote),
            "stage1CodeSha256": manifest["pins"]["stage1CodeSha256"],
            "stage2Head": git("rev-parse", "HEAD"),
            "scriptSha256": sha256_file(Path(__file__)),
            "manifestSha256": sha256_file(MANIFEST_PATH),
            "scoresSha256": sha256_file(SCORES_PATH),
            "reproducedBaseVectors": reproduced,
        },
        "preconditions": pre,
    }
    if not pre["ok"]:
        base_result["status"] = "insufficient_sample: scorer_unreconciled"
        RESULT_PATH.write_text(
            json.dumps(base_result, indent=1, default=str) + "\n", encoding="utf-8"
        )
        log("preconditions FAILED: no metric computed")
        return 2

    y_all = realized_scores(out, list(info), weeks)
    lam6 = lambc(port, universe, y_all, support, weeks)
    lam_a = lambc(port, universe, y_all, support, weeks[:3])
    games6 = window_games(out, support, weeks)
    ppg6 = realized_ppg(out, support, weeks)
    log(f"outcomes joined: LAMBC for {len(lam6)} players")

    arrays = build_arrays(vec, cohort)
    data = make_cohort(cohort, table, lam6, arrays)
    names_pub = {pid: table[pid]["name"] for pid in cohort}
    main_block = analysis_block(data, cands, qual, within_ok=within_ok, cross_ok=cross_ok)
    point = main_block["summary"]["deltas"]
    log("primary analysis done")

    # ---- stability (section 10) -----------------------------------------------------------
    def variant(
        label: str,
        ids: Sequence[str],
        replace: Mapping[str, Sequence[float]],
        y: Mapping[str, float],
        which: Sequence[str],
        **kw: Any,
    ) -> dict[str, Any]:
        # only what the variant reads is built, and nothing the variant replaces is
        # read from the base vectors (a replaced candidate may be defined on other players)
        arr = build_arrays(vec, ids, only=({"champion", *which} - set(replace)))
        arr = {**arr, **replace}
        d = make_cohort(ids, table, y, arr)
        q = [p for p in qual if len(d.members[p]) >= 3]
        row = variant_row(d, which, q, **kw)
        row["qualifyingPositionsUsed"] = q
        return row

    def vec_arr(name: str, ids: Sequence[str]) -> np.ndarray:
        return np.array([vec[name][i] for i in ids], dtype=float)

    def defined(ids: Sequence[str], *names: str) -> list[str]:
        return [i for i in ids if all(i in vec[n] for n in names)]

    variants: dict[str, dict[str, Any]] = {}
    applies: dict[str, list[str]] = {}
    variants["S1_Wa_weeks1to3"] = variant("Wa", cohort, {}, lam_a, cands)
    applies["S1_Wa_weeks1to3"] = list(cands)
    for tag, suf in (("age_plus1", "_age_plus1"), ("age_minus1", "_age_minus1")):
        ids = defined(cohort, f"A_dv{suf}", f"A_vorg{suf}")
        arr_a = lex_rank_scores(
            [vec[f"A_dv{suf}"][i] for i in ids], [vec[f"A_vorg{suf}"][i] for i in ids]
        )
        variants[f"S2_{tag}"] = variant(tag, ids, {"A": arr_a}, lam6, ["A"])
        applies[f"S2_{tag}"] = ["A"] if "A" in cands else []
    for tag, key in (("D2", "C_D2"), ("D4", "C_D4")):
        ids = defined(cohort, key)
        variants[f"S3_{tag}"] = variant(tag, ids, {"C": vec_arr(key, ids)}, lam6, ["C"])
        applies[f"S3_{tag}"] = ["C"] if "C" in cands else []
    variants["S3_D5"] = {"state": "not_evaluable: degenerate_one_pseudo_week_allocation"}
    for tag, key in (("sigma0", "D_sigma0"), ("ownteam", "D_ownteam")):
        ids = defined(cohort, key)
        variants[f"S4_{tag}"] = variant(tag, ids, {"D": vec_arr(key, ids)}, lam6, ["D"])
        applies[f"S4_{tag}"] = ["D"] if "D" in cands else []
    variants["S5_projection_mix"] = {
        "state": "not_evaluable: no_real_projection_snapshot_with_a_creation_stamp_before_the_cutoff"
    }
    pair: dict[str, Any] = {}
    for c in cands:
        names_needed = {"A": ("A_dv", "A_vorg"), "C": ("C",), "D": ("D",)}[c]
        ids = [
            i
            for i in support
            if table[i]["projectionStatus"] != "rookie_prior_only"
            and i in vec["champion"]
            and all(i in vec[n] for n in names_needed)
        ]
        pair[c] = variant("pairwise", ids, {}, lam6, [c])
    variants["S6_pairwise_support"] = {
        "n": {c: pair[c]["n"] for c in cands},
        "delta1": {c: pair[c]["delta1"][c] for c in cands},
        "delta2": {c: pair[c]["delta2"][c] for c in cands},
        "idpOverShare": {c: pair[c]["idpOverShare"][c] for c in cands},
    }
    applies["S6_pairwise_support"] = list(cands)
    for tag, key_c, key_d in (("placeholder", "C_placeholder", "D_placeholder"),):
        ids = defined(cohort, key_c, key_d)
        variants[f"S7_{tag}"] = variant(
            tag,
            ids,
            {"C": vec_arr(key_c, ids), "D": vec_arr(key_d, ids)},
            lam6,
            [c for c in ("C", "D") if c in cands],
        )
    variants["S8_cluster_bootstrap"] = cluster_bootstrap(data, cands, qual)
    variants["S9_n_weighted"] = variant("nw", cohort, {}, lam6, cands, weights="n")
    ros_ids = [i for i in cohort if table[i]["rostered"]]
    variants["S9_cross_rostered_only"] = variant("ros", ros_ids, {}, lam6, cands)
    for tag, key in (("pseudo0", "D_pc0"), ("pseudo16", "D_pc16")):
        ids = defined(cohort, key)
        variants[f"S10_{tag}"] = variant(tag, ids, {"D": vec_arr(key, ids)}, lam6, ["D"])
    log("stability variants done (Wb pending)")

    # ---- Wb (exploratory; deviation D1) ---------------------------------------------------
    wb_result: dict[str, Any]
    if args.skip_wb:
        wb_result = {"state": "skipped (--skip-wb)"}
    else:
        try:
            wb = build_wb(
                args,
                log,
                fetch,
                out,
                manifest,
                port,
                stand_in_season=HISTORY_SEASON if rehearsal else None,
            )
            data_b = wb.pop("data")
            q_b = wb.pop("qual")
            row_b = variant_row(data_b, cands, [p for p in q_b if p in qual] or q_b)
            wb_result = {**wb, "result": row_b}
            variants["S1_Wb_weeks4to6"] = {
                "delta1": row_b["delta1"],
                "delta2": row_b["delta2"],
                "idpOverShare": row_b["idpOverShare"],
                "n": row_b["n"],
                "labelled": "exploratory (deviation D1)",
            }
            applies["S1_Wb_weeks4to6"] = list(cands)
        except Exception as exc:  # noqa: BLE001 - recorded, never silent
            wb_result = {"state": f"not_evaluable: {type(exc).__name__}: {exc}"}
            variants["S1_Wb_weeks4to6"] = {"state": wb_result["state"]}
    log(f"Wb: {wb_result.get('state', 'built')}")

    # ---- verdicts (section 8.2) ------------------------------------------------------------
    verdicts: dict[str, Any] = {}
    core = {k: v for k, v in variants.items() if k.startswith(("S1_", "S2_", "S3_", "S4_", "S6_"))}
    sign_within = stability_signs(cands, point, core, applies, "delta1")
    sign_cross = stability_signs(cands, point, core, applies, "delta2")
    for c in cands:
        verdicts[c] = {
            "within": axis_verdict(
                "within", c, point, main_block["families"], qual, sign_within[c], tested=within_ok
            ),
            "cross": axis_verdict(
                "cross", c, point, main_block["families"], qual, sign_cross[c], tested=cross_ok
            ),
        }
    wb_pending_effect = {
        c: {
            ax: (
                "unchanged_without_Wb"
                if all(
                    k != "S1_Wb_weeks4to6"
                    for k in (sign_within if ax == "within" else sign_cross)[c]
                )
                else "Wb sign check included (exploratory)"
            )
            for ax in ("within", "cross")
        }
        for c in cands
    }

    # ---- descriptive analyses ---------------------------------------------------------------
    sec = {}
    # 9.4 elite separation (cardinal, points-scale candidates only)
    sec["eliteSeparation"] = {c: elite_separation(data, c, qual) for c in ("C", "D") if c in cands}
    sec["eliteSeparation"]["champion_A_B"] = "unavailable: no_validated_points_mapping"
    # 9.5 secondary outcome (realized ppg) on the same machinery
    ppg_ids = [i for i in cohort if ppg6.get(i) is not None]
    data_ppg = make_cohort(
        ppg_ids, table, {i: ppg6[i] for i in ppg_ids}, build_arrays(vec, ppg_ids)
    )
    q_ppg = [p for p in qual if len(data_ppg.members[p]) >= MIN_N_PER_POSITION]
    sec["secondaryOutcomeRealizedPpg"] = {
        "n": len(ppg_ids),
        "positionsUsed": q_ppg,
        **{
            k: v
            for k, v in analysis_block(
                data_ppg, cands, q_ppg, within_ok=within_ok, cross_ok=cross_ok, b=500
            )["byCandidate"].items()
            if k in (*cands, REF_CANDIDATE)
        },
    }
    # slices (section 11)
    ages = np.array(
        [
            float(table[i]["age"]) if isinstance(table[i].get("age"), (int, float)) else np.nan
            for i in cohort
        ]
    )
    ranks = [table[i]["champRank"] for i in cohort]
    offcap = np.array([bool(table[i]["offCapValue"]) or r is None for i, r in zip(cohort, ranks)])
    rk = np.array([float(r) if r is not None else np.nan for r in ranks])
    games = np.array([games6.get(i, 0) for i in cohort])
    hybrid = np.array([bool(table[i]["hybridDlLb"]) for i in cohort])
    slices: dict[str, Any] = {}
    for p in POSITIONS:
        slices[f"position:{p}"] = slice_row(data, data.pos == p, cands)
    for lo, hi, tag in (
        (1, 50, "1-50"),
        (51, 150, "51-150"),
        (151, 300, "151-300"),
        (301, 800, "301-800"),
    ):
        slices[f"championBand:{tag}"] = slice_row(data, (~offcap) & (rk >= lo) & (rk <= hi), cands)
    slices["championBand:offCapValueOnly"] = slice_row(data, offcap, cands)
    slices["age:<=24"] = slice_row(data, ages <= 24, cands)
    slices["age:25-28"] = slice_row(data, (ages >= 25) & (ages <= 28), cands)
    slices["age:>=29"] = slice_row(data, ages >= 29, cands)
    slices["rostered"] = slice_row(data, data.rostered, cands)
    slices["unrostered"] = slice_row(data, ~data.rostered, cands)
    slices["dlLbHybrid"] = slice_row(data, hybrid, cands)
    slices["gamesPlayed<=3"] = slice_row(data, games <= 3, cands)
    sec["failureSlices"] = slices
    sec["worstRankErrorsVsChampion"] = {c: worst_rank_errors(data, names_pub, c) for c in cands}

    # 9.1 roster counterfactuals and 9.2 trade examples (descriptive, W0)
    if args.skip_counterfactuals:
        sec["rosterCounterfactuals"] = {"state": "skipped"}
        sec["tradeExamples"] = {"state": "skipped"}
    else:
        swaps = swap_universe(universe, cohort)
        real = swaps_realized(port, universe, y_all, swaps, weeks)
        mu_env = {pid: v for pid, v in P["mu"].items()}
        pred = {
            "champion": {
                t: np.array([vec["champion"][f] - vec["champion"][r] for r, f in lst])
                for t, lst in swaps.items()
            },
            "A": {
                t: np.array([vec["A_dv"][f] - vec["A_dv"][r] for r, f in lst])
                for t, lst in swaps.items()
            },
            "C": swaps_predicted_mu(port, universe, mu_env, swaps),
            "D": swaps_predicted_d(P["specs"]["base"], swaps, workers=args.workers),
        }
        sec["rosterCounterfactuals"] = swap_report(
            swaps,
            real,
            {k: v for k, v in pred.items() if k in ("champion", *cands)},
            points_scale=("C", "D"),
            weeks=len(weeks),
        )
        log("9.1 done")
        # 9.2
        inputs_d = cp.SimInputs(
            mu=P["specs"]["base"]["mu"],
            availability=P["specs"]["base"]["availability"],
            own_residuals={k: tuple(v) for k, v in P["specs"]["base"]["own"].items()},
            pooled={k: tuple(v) for k, v in P["specs"]["base"]["pooled"].items()},
            stratum=P["specs"]["base"]["stratum"],
            position=P["specs"]["base"]["position"],
            fantasy_positions={
                k: tuple(v) for k, v in P["specs"]["base"]["fantasy_positions"].items()
            },
            teams=P["specs"]["base"]["teams"],
            slots=P["specs"]["base"]["slots"],
        )
        sim_scores = [cp.draw_week(inputs_d, cp.week_rng(SIM_SEED, s)) for s in range(SIM_WEEKS)]
        ctx = TradeCtx(
            universe,
            port,
            y_all,
            weeks,
            {pid: vec["champion"][pid] for pid in vec["champion"]},
            {
                pid: (vec["A_dv"][pid], vec["A_vorg"][pid])
                for pid in vec["A_dv"]
                if pid in vec["A_vorg"]
            },
            vec["A_tradeValue"],
            P["bd"]["params"],
            mu_env,
            sim_scores,
            set(inputs_d.simulable()),
        )
        posmap = {pid: table[pid]["pos"] for pid in cohort}
        tvalue = {pid: vec["champion"][pid] for pid in cohort}
        trade_out: dict[str, Any] = {}
        for cat in ("a", "b", "c"):
            sample = first_fair_by_hash(
                lambda cat=cat: enumerate_trades(
                    universe, cohort, posmap, cat, universe["rosterCap"]
                ),
                tvalue,
            )
            trade_out[cat] = evaluate_trades(sample, ctx, ["champion", *cands], category=cat)
            log(f"9.2 category {cat}: {len(sample['trades'])} trades")
        sec["tradeExamples"] = {
            "categories": {
                "a": "offense-for-IDP 1-for-1",
                "b": "2-for-1",
                "c": "2-for-1 forcing a cut",
            },
            **trade_out,
            "note": "a dynasty trade is a multi-year bet; six weeks of lineup points cannot grade it",
        }

    result = {
        **base_result,
        "status": "completed",
        "claimsLabel": LABEL,
        "champion": manifest["champion"]["mode"],
        "cohort": {
            "size": len(cohort),
            "byPosition": data.n_by_position(),
            "qualifyingPositions": qual,
            "withinAxisTested": within_ok,
            "crossAxisTested": cross_ok,
        },
        "evaluableCandidates": cands,
        "bExcluded": manifest["candidates"]["B"],
        "outcome": {
            "primary": "LAMBC: realized league-average marginal best-ball contribution, cutoff rosters, weeks 1-6",
            "unit": "league points per week",
            "distribution": {
                "mean": rnd(float(np.mean(data.y)), 4),
                "sd": rnd(float(np.std(data.y, ddof=1)), 4),
                "zeros": int(np.sum(data.y == 0)),
            },
        },
        "families": {
            fam: {
                key: {k: (rnd(v, 5) if isinstance(v, float) else v) for k, v in cell.items()}
                for key, cell in cells.items()
            }
            for fam, cells in main_block["families"].items()
        },
        "byCandidate": main_block["byCandidate"],
        "verdicts": verdicts,
        "stability": variants,
        "stabilityApplicability": applies,
        "wb": wb_result,
        "wbEffectOnVerdict": wb_pending_effect,
        "descriptive": sec,
        "timingsSec": round(time.time() - t0, 1),
    }
    rs.assert_public_artifact(result, forbidden_values=[LEAGUE_ID])
    target = Path(args.out) if args.out else RESULT_PATH
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(result, indent=1, default=str) + "\n", encoding="utf-8")
    print(
        json.dumps(
            {
                "result": str(target),
                "verdicts": {
                    c: {a: v["verdict"] for a, v in d.items()} for c, d in verdicts.items()
                },
            }
        )
    )
    return 0


def supplement(args: argparse.Namespace) -> int:
    """The comparator's own section 9.3 interval, from the SAME resamples as the main run.

    Section 9.3 asks for each candidate's level diagnostic with a bootstrap interval from the
    same resamples.  The stage 2 run carried the intervals for A, C and D but only the champion's
    POINT value, so the claims rule "the served board overrated defenders in X% of the cross
    pairs it got wrong" had no interval.  This recomputes LAMBC deterministically (same
    inputs, same solver), checks that it reproduces the committed result's champion and
    candidate numbers, and bootstraps the identical selections (``Generator(PCG64(20261026))``).
    It tests nothing new and changes no verdict.  Declared deviation D7.
    """
    manifest, scores = load_stage1()
    main_res = json.loads(RESULT_PATH.read_text(encoding="utf-8"))
    if main_res.get("status") != "completed" or main_res.get("rehearsal"):
        raise SystemExit("the supplement needs a completed, non-rehearsal stage 2 result")
    arch = REPO / "exports" / "archive" / manifest["windows"]["W0"]["archive"]["name"]
    raw = read_archive_payload(arch)
    contract, _notes = rebuild_champion(raw, arch)
    board = board_rows(contract)
    universe = build_universe(raw, board)
    info = universe["info"]
    card = numeric_card(raw["sleeper"]["scoringSettings"])
    fetch = Fetcher(blind=False, offline=args.offline)
    out = load_outcomes(fetch, card)
    port = SolverPort()
    weeks = HOLD_OUT_WEEKS
    y_all = realized_scores(out, list(info), weeks)
    support = [pid for pid, i in info.items() if board.get(pid, {}).get("value") and stratum_ok(i)]
    lam6 = lambc(port, universe, y_all, support, weeks)
    vec = scores["vectors"]
    table = {p["id"]: p for p in scores["players"]}
    cohort = list(scores["cohort"])
    cands = list(manifest["candidates"]["evaluableSet"])
    qual = list(manifest["cohort"]["qualifyingPositions"])
    data = make_cohort(cohort, table, lam6, build_arrays(vec, cohort))
    names = ["champion", *cands]
    point = metrics_on(data, data.identity_selection(), names, qual)
    # the supplement must reproduce the committed numbers before it is believed
    expect = main_res["byCandidate"]
    checks = {
        "championCrossConcordance": abs(
            point["cc"]["champion"] - expect["champion"]["rawAbsolute"]["crossConcordance"]
        )
        < 5e-4,
        "championOverShare": abs(
            point["over"]["champion"]
            - expect["champion"]["rawAbsolute"]["idpOverShareOfWrongPairs"]
        )
        < 5e-4,
        **{
            f"{c}OverShare": abs(point["over"][c] - expect[c]["idpOverShareOfWrongPairs"]["point"])
            < 5e-4
            for c in cands
        },
    }
    if not all(checks.values()):
        raise SystemExit(f"supplement does not reproduce the committed result: {checks}")
    sels = draw_bootstrap_selections(data.n_by_position())
    over: dict[str, list[float]] = {c: [] for c in names}
    cc: dict[str, list[float]] = {c: [] for c in names}
    for sel in sels:
        m = metrics_on(data, sel, names, qual)
        for c in names:
            over[c].append(m["over"][c])
            cc[c].append(m["cc"][c])
    off = np.concatenate([data.members[p] for p in OFFENSE])
    idp = np.concatenate([data.members[p] for p in IDP])
    pairs = {
        c: cross_pair_stats(data.scores[c][off], data.scores[c][idp], data.y[off], data.y[idp])
        for c in names
    }
    result = {
        "preregistration": "idp_accuracy_G_v1",
        "promotes": False,
        "label": LABEL,
        "what": "section 9.3 level diagnostic for the champion, with an interval from the same resamples",
        "deviation": "D7",
        "reproducesCommittedResult": checks,
        "idpOverShareOfWrongPairs": {
            c: {"point": rnd(point["over"][c], 4), **interval(np.asarray(over[c]))} for c in names
        },
        "crossConcordance": {
            c: {"point": rnd(point["cc"][c], 4), **interval(np.asarray(cc[c]))} for c in names
        },
        "pairCounts": {
            c: {
                "offenseVsIdpPairsWithADifferentOutcome": pairs[c]["pairs"],
                "orderedWrongly": pairs[c]["wrong"],
            }
            for c in names
        },
        "note": (
            "idpOverShareOfWrongPairs is the share of wrongly ordered offense-vs-IDP pairs in which "
            "the candidate put the defender above the offensive player; 0.5 is no level bias, below "
            "0.5 means it undervalued defenders relative to near-term lineup contribution"
        ),
    }
    rs.assert_public_artifact(result, forbidden_values=[LEAGUE_ID])
    target = EVIDENCE_DIR / "g_backtest_supplement_champion_level.json"
    target.write_text(json.dumps(result, indent=1, default=str) + "\n", encoding="utf-8")
    print(json.dumps({"supplement": str(target), "checks": checks}))
    return 0


def main(argv: Sequence[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    sub = ap.add_subparsers(dest="stage", required=True)
    s1 = sub.add_parser("stage1", help="blind stage: candidates, cohort, hashes")
    s1.add_argument("--workers", type=int, default=None)
    s1.add_argument("--offline", action="store_true")
    s1.add_argument("--allow-dirty", action="store_true")
    s1.add_argument("--dry-run", action="store_true")
    s1.set_defaults(fn=stage1)
    s2 = sub.add_parser("stage2", help="unblind once: outcomes, metrics, tests, verdicts")
    s2.add_argument("--workers", type=int, default=None)
    s2.add_argument("--offline", action="store_true")
    s2.add_argument("--allow-unpushed", action="store_true")
    s2.add_argument("--skip-wb", action="store_true")
    s2.add_argument("--skip-counterfactuals", action="store_true")
    s2.add_argument(
        "--rehearsal",
        action="store_true",
        help="use the public 2025 weeks 1-6 as stand-in outcomes (never a 2026 outcome)",
    )
    s2.add_argument("--out", default=None, help="result path (default: the evidence file)")
    s2.set_defaults(fn=stage2)
    s3 = sub.add_parser(
        "supplement", help="champion section 9.3 interval from the same resamples (deviation D7)"
    )
    s3.add_argument("--offline", action="store_true")
    s3.set_defaults(fn=supplement)
    args = ap.parse_args(argv)
    return int(args.fn(args))


if __name__ == "__main__":
    sys.exit(main())
