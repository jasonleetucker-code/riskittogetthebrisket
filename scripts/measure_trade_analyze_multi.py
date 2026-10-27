#!/usr/bin/env python3
"""Local latency / memory measurement for the N-team trade engine (Lane E).

Spec ``docs/trade/NTEAM_TRADE_ENGINE_SPEC.md`` §2.11 ("Lane A implements,
Lane E measures") and the Lane E row of §7: measure p50 / p95 / p99 for
representative and worst-case VALID 2 / 3 / 4-team requests, in every mode,
locally -- **never against production**.

Surfaces measured (one process, one archived board):

* ``engine`` -- ``trade_ledger.snapshot_for`` + ``validate_ledger`` +
  ``analyze_service.analyze_trade_n`` in ``team_context``, ``asset_only`` and
  ``market_fairness``;
* ``route`` -- ``POST /api/trade/analyze-multi`` through FastAPI's in-process
  ``TestClient`` with the private flag forced ON in THIS process
  (``team_context`` and ``asset_only``; the private route has no
  ``market_fairness`` mode -- that is the public advisor's mode).

Two request SHAPES per team count (2 / 3 / 4):

* ``representative`` -- several seeded ledgers of 1-3 assets per team over the
  board's priced, clean assets (``tests.trade.multi_team_support.random_ledger``
  with ``send_and_receive``);
* ``worst_case`` -- the largest valid ledger (``config/trade/multi_team.json``
  ``maxLegs``), every team sending AND receiving, every asset priced and clean,
  so the full success path (not an evidence gate) runs.

Cold = the ledger snapshot memo and the best-ball before-roster cache cleared
before every sample (so each sample rebuilds the snapshot).  Warm = memo
primed.  Process-level import / lazy-init costs are paid once by an untimed
warm-up whose duration is reported as ``processWarmupMs``.

Memory = ``tracemalloc`` peak of Python allocations per call (a separate pass,
because tracing slows the call), plus the process peak working set when the
platform exposes it.

Budgets (the ``budgets`` block of the output).  Spec §2.11 states STRUCTURAL
budgets and no numeric latency or memory figure:

* ``S*`` structural (spec §2.11, counted by wrapping the real functions in a
  dedicated pass): one snapshot per request, at most one posture bundle read
  per request and none in ``market_fairness``, one league scarcity read per
  request, ``market_fairness`` skips capacity / final-roster / utility work and
  never touches the before-roster cache, comparables are not computed at
  N >= 3;
* ``L*`` / ``M*`` numeric, DERIVED from the repo's own bounds and labelled so:
  the per-route caller deadlines of ``config/trade/analyze_admission.json``
  (spec §6.3, PENDING OWNER CONFIRMATION), the public ``responseFloorMs`` when
  one is set, and a memory allowance of ``--memory-limit-mb`` minus
  ``--baseline-rss-mb`` (reference figures from
  ``docs/trade/advisor_evidence/PERFORMANCE.md``; not an owner budget).

Local-only by construction:

* the transport is in-process -- no socket is opened for the route;
* every non-loopback ``connect`` and every non-loopback name resolution is
  REFUSED for the whole run, so neither production nor Sleeper can be reached
  even by a code path that would fetch;
* ``--base-url`` (the TestClient's base URL) accepts only loopback hosts or
  the TestClient default and refuses the production host by name (exit 2);
* the env guards the unit suite uses (no uptime probe, no scrape scheduler, no
  overlay warm, runtime data redirected, decision receipts under a temp dir)
  are applied before ``server`` is imported.

Team Context inputs that would otherwise need the network or box-local data
(the posture bundle and the league scarcity read) are answered by LABELLED
stubs, so ``team_context`` numbers are a LOWER bound; the output states which
of the roster-utility / comparables paths actually ran.

Exit codes: 0 measured, no budget breached; 1 measured, at least one budget
breached; 2 refused (non-local target) or bad arguments; 3 the measurement
could not complete (no board, an engine failure, a non-200 from the route).

This script writes no tracked file and changes no flag default, config or
production code.  (Importing ``server`` and starting its lifespan creates the
usual gitignored ``data/*.sqlite`` stores, exactly as the route tests do.)
"""

from __future__ import annotations

import argparse
import collections
import contextlib
import gc
import hashlib
import ipaddress
import json
import logging
import math
import os
import platform
import random
import socket
import statistics
import subprocess
import sys
import tempfile
import time
import tracemalloc
import zipfile
from dataclasses import dataclass, field, replace
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace
from typing import Any, Callable, Iterator, Mapping, Sequence
from urllib.parse import urlparse

REPO = Path(__file__).resolve().parents[1]
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

TOOL = "measure_trade_analyze_multi"
TOOL_VERSION = 1
MODES = ("team_context", "asset_only", "market_fairness")
#: The private route has two modes (``useTeamContext`` true / false);
#: ``market_fairness`` is the public advisor's mode and has no private route.
ROUTE_MODES = ("team_context", "asset_only")
TEAM_COUNTS = (2, 3, 4)
SHAPES = ("representative", "worst_case")
LEAGUE_KEY = "dynasty_main"
SYNTH_LEAGUE_KEY = "synth"
DEFAULT_ARCHIVE = "exports/archive/dynasty_export_20261025_120337.zip"
DEFAULT_BASE_URL = "http://testserver"
NOT_COMPUTED_COMPARABLES = {"state": "not_computed_multi_team"}

EXIT_OK = 0
EXIT_BUDGET_BREACH = 1
EXIT_REFUSED = 2
EXIT_MEASUREMENT_FAILED = 3

#: Hosts that are production.  Refused by name even before the loopback rule,
#: so the message says why.  The deploy target is a secret (``DEPLOY_HOST``)
#: and is never named in the repo; it is refused when the env names it.
PRODUCTION_HOSTS = frozenset({"chaseupside.com", "www.chaseupside.com"})
#: The TestClient's own default origin: not a real host, never resolved.
TESTCLIENT_HOSTS = frozenset({"testserver"})

#: Reference memory figures (``docs/trade/advisor_evidence/PERFORMANCE.md``
#: §2 config A and §1): production ``MemoryHigh`` and the production web
#: process baseline RSS.  A reference, not an owner budget.
REFERENCE_MEMORY_LIMIT_MB = 2560.0
REFERENCE_BASELINE_RSS_MB = 1838.0
REFERENCE_MEMORY_SOURCE = (
    "docs/trade/advisor_evidence/PERFORMANCE.md (production MemoryHigh 2,560 MB; "
    "production web RSS 1,838 MB)"
)
#: The method of spec §6.3 (P1): the response floor is the worst-case valid
#: ``market_fairness`` request's p99, rounded up to the next 50 ms step.
FLOOR_STEP_MS = 50

#: Env guards set before ``server`` / ``src`` import, mirroring
#: ``tests/conftest.py`` but FORCED (see :func:`isolation_env`).
_ENV_GUARDS = {
    "ALLOW_DEFAULT_LOGIN_DEV": "1",
    "UPTIME_CHECK_ENABLED": "0",
    "SCRAPE_SCHEDULER_ENABLED": "0",
    "SLEEPER_OVERLAY_WARM_ENABLED": "0",
    # ``server``'s lifespan otherwise starts a background public-league rebuild
    # that retries Sleeper in a loop for the whole run (measured: ~1,400 refused
    # attempts in 11 minutes) -- background noise in a latency measurement.
    "PUBLIC_LEAGUE_WARMUP_AT_STARTUP": "0",
    "PUBLIC_LEAGUE_PERSIST_SNAPSHOT": "0",
    "RISKIT_FEATURE_GAME_DAY_LIVE_GAME_STATE": "0",
    "RISKIT_FEATURE_SLEEPER_WEEKLY_PROJECTIONS": "0",
}
_ENV_TEMP_DIRS = (
    "RISKIT_RETENTION_DIR",
    "RISKIT_NEWS_ARCHIVE_DIR",
    "RISKIT_INJURY_HISTORY_DIR",
    "RISKIT_TRADE_DECISION_LOG_DIR",
)
PRIVATE_FLAG_ENV = "RISKIT_FEATURE_TRADE_MULTI_TEAM_ANALYSIS"
PUBLIC_FLAG_ENV = "RISKIT_FEATURE_BRISKET_TRADE_ADVISOR"
PUBLIC_ANALYZE_PATH = "/api/public/league/trade-advisor/analyze"


class TargetRefused(ValueError):
    """``--base-url`` names a host this script may not measure."""


class MeasurementFailed(RuntimeError):
    """The measurement could not complete honestly."""


# ── Local-only guards ──────────────────────────────────────────────────────


def is_loopback_host(host: str) -> bool:
    host = str(host or "").strip().lower().strip("[]").rstrip(".")
    if host == "localhost" or host.endswith(".localhost"):
        return True
    try:
        return ipaddress.ip_address(host).is_loopback
    except ValueError:
        return False


def assert_local_target(url: str) -> str:
    """Return ``url`` normalised when it names a LOOPBACK (or the TestClient
    default) http(s) origin; raise :class:`TargetRefused` otherwise.
    Production hosts -- and the ``DEPLOY_HOST`` secret when the env carries it
    -- are refused by name; any other non-loopback host is refused by rule.
    No name is ever resolved."""
    parsed = urlparse(str(url or "").strip())
    if parsed.scheme not in ("http", "https"):
        raise TargetRefused(f"--base-url must be http(s), got {parsed.scheme or 'nothing'!r}")
    host = (parsed.hostname or "").strip().lower().rstrip(".")
    if not host:
        raise TargetRefused("--base-url has no host")
    deploy_host = os.environ.get("DEPLOY_HOST", "").strip().lower().rstrip(".")
    if (
        host in PRODUCTION_HOSTS
        or host.endswith(".chaseupside.com")
        or (deploy_host and host == deploy_host)
    ):
        raise TargetRefused(f"refusing to measure production host {host!r}")
    if host not in TESTCLIENT_HOSTS and not is_loopback_host(host):
        raise TargetRefused(f"refusing non-loopback host {host!r}: this script is local-only")
    return f"{parsed.scheme}://{parsed.netloc}"


def _address_is_local(address: Any) -> bool:
    if isinstance(address, (str, bytes)):  # AF_UNIX path
        return True
    if isinstance(address, tuple) and address:
        return is_loopback_host(str(address[0]))
    return False


@contextlib.contextmanager
def network_guard() -> Iterator[None]:
    """Refuse every non-loopback ``connect`` / ``connect_ex`` and every
    non-loopback name resolution for the duration of the block.  Best effort
    defence in depth: the route is measured in-process and opens no socket."""
    real_connect = socket.socket.connect
    real_connect_ex = socket.socket.connect_ex
    real_getaddrinfo = socket.getaddrinfo

    def _connect(self, address):  # type: ignore[no-untyped-def]
        if not _address_is_local(address):
            raise OSError(f"{TOOL}: network blocked (non-loopback connect to {address!r})")
        return real_connect(self, address)

    def _connect_ex(self, address):  # type: ignore[no-untyped-def]
        if not _address_is_local(address):
            raise OSError(f"{TOOL}: network blocked (non-loopback connect to {address!r})")
        return real_connect_ex(self, address)

    def _getaddrinfo(host, *args, **kwargs):  # type: ignore[no-untyped-def]
        if host not in (None, "") and not is_loopback_host(str(host)):
            raise OSError(f"{TOOL}: network blocked (non-loopback lookup of {host!r})")
        return real_getaddrinfo(host, *args, **kwargs)

    socket.socket.connect = _connect  # type: ignore[method-assign]
    socket.socket.connect_ex = _connect_ex  # type: ignore[method-assign]
    socket.getaddrinfo = _getaddrinfo  # type: ignore[assignment]
    try:
        yield
    finally:
        socket.socket.connect = real_connect  # type: ignore[method-assign]
        socket.socket.connect_ex = real_connect_ex  # type: ignore[method-assign]
        socket.getaddrinfo = real_getaddrinfo  # type: ignore[assignment]


class Patches:
    """setattr-with-undo, duck-typed like pytest's ``monkeypatch.setattr`` so
    the test suite's own helpers (``pin_league_scarcity``) can be reused."""

    def __init__(self) -> None:
        self._undo: list[tuple[Any, str, Any]] = []

    def setattr(self, obj: Any, name: str, value: Any) -> None:
        self._undo.append((obj, name, getattr(obj, name)))
        setattr(obj, name, value)

    def undo(self) -> None:
        while self._undo:
            obj, name, old = self._undo.pop()
            setattr(obj, name, old)


@contextlib.contextmanager
def env_overrides(values: Mapping[str, str | None]) -> Iterator[None]:
    """Set (or, for ``None``, remove) env vars; restore them on exit."""
    previous = {k: os.environ.get(k) for k in values}
    for key, value in values.items():
        if value is None:
            os.environ.pop(key, None)
        else:
            os.environ[key] = value
    try:
        yield
    finally:
        for key, value in previous.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value


def isolation_env(temp_root: Path) -> dict[str, str | None]:
    """The suite's isolation env vars, FORCED: unlike the test suite (which
    keeps an operator's explicit value), a measurement run writes ~hundreds of
    decision receipts and must never reach a real store or the network because
    of what happens to be exported in the operator's shell."""
    out: dict[str, str | None] = dict(_ENV_GUARDS)
    for key in _ENV_TEMP_DIRS:
        out[key] = str(temp_root / key.lower())
    # No live Sleeper league context and no real registry while the board is
    # built (tests/conftest.py does the same).
    out["SLEEPER_LEAGUE_ID"] = None
    out["LEAGUE_REGISTRY_PATH"] = "/nonexistent/path/for/tests.json"
    return out


def isolate_runtime_data(temp_root: Path) -> None:
    """Point the gitignored runtime stores at ``temp_root`` unless the test
    suite's own isolation is already active in this process."""
    from tests import runtime_data_isolation as rdi  # noqa: PLC0415

    if rdi._state["root"] is None:  # noqa: SLF001
        rdi.install()
        rdi.activate(temp_root / "runtime")


# ── Statistics ─────────────────────────────────────────────────────────────


def percentile(values: Sequence[float], q: float) -> float | None:
    """Linear-interpolated percentile (``q`` in [0, 100]); ``None`` when empty
    -- an unmeasured cell is missing, never 0."""
    data = sorted(float(v) for v in values)
    if not data:
        return None
    if not 0.0 <= q <= 100.0:
        raise ValueError("q must be within [0, 100]")
    if len(data) == 1:
        return data[0]
    pos = (len(data) - 1) * (q / 100.0)
    lo = int(pos)
    hi = min(lo + 1, len(data) - 1)
    return data[lo] + (data[hi] - data[lo]) * (pos - lo)


def summarize(values: Sequence[float], *, digits: int = 2) -> dict[str, Any]:
    data = [float(v) for v in values]
    if not data:
        return {"n": 0, "p50": None, "p95": None, "p99": None, "max": None, "mean": None}

    def r(v: float | None) -> float | None:
        return None if v is None else round(v, digits)

    return {
        "n": len(data),
        "p50": r(percentile(data, 50)),
        "p95": r(percentile(data, 95)),
        "p99": r(percentile(data, 99)),
        "max": r(max(data)),
        "mean": r(statistics.fmean(data)),
    }


def process_rss_mb() -> dict[str, float | None]:
    """``{"current", "peak"}`` working set in MB where the platform says."""
    try:
        import resource  # noqa: PLC0415 -- POSIX only

        peak = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
        scale = 1024 * 1024 if sys.platform == "darwin" else 1024
        current = None
        statm = Path("/proc/self/statm")
        if statm.exists():
            current = int(statm.read_text().split()[1]) * os.sysconf("SC_PAGE_SIZE") / 1048576
        return {"current": current, "peak": round(peak / scale, 1)}
    except ImportError:
        pass
    if os.name == "nt":
        try:
            import ctypes  # noqa: PLC0415
            from ctypes import wintypes  # noqa: PLC0415

            class _Counters(ctypes.Structure):
                _fields_ = [
                    ("cb", wintypes.DWORD),
                    ("PageFaultCount", wintypes.DWORD),
                    ("PeakWorkingSetSize", ctypes.c_size_t),
                    ("WorkingSetSize", ctypes.c_size_t),
                    ("QuotaPeakPagedPoolUsage", ctypes.c_size_t),
                    ("QuotaPagedPoolUsage", ctypes.c_size_t),
                    ("QuotaPeakNonPagedPoolUsage", ctypes.c_size_t),
                    ("QuotaNonPagedPoolUsage", ctypes.c_size_t),
                    ("PagefileUsage", ctypes.c_size_t),
                    ("PeakPagefileUsage", ctypes.c_size_t),
                ]

            counters = _Counters()
            counters.cb = ctypes.sizeof(counters)
            kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
            psapi = ctypes.WinDLL("psapi", use_last_error=True)
            kernel32.GetCurrentProcess.restype = wintypes.HANDLE
            psapi.GetProcessMemoryInfo.argtypes = [
                wintypes.HANDLE,
                ctypes.POINTER(_Counters),
                wintypes.DWORD,
            ]
            handle = kernel32.GetCurrentProcess()
            if psapi.GetProcessMemoryInfo(handle, ctypes.byref(counters), counters.cb):
                return {
                    "current": round(counters.WorkingSetSize / 1048576, 1),
                    "peak": round(counters.PeakWorkingSetSize / 1048576, 1),
                }
        except Exception:  # noqa: BLE001 -- memory facts are best effort
            pass
    return {"current": None, "peak": None}


# ── Scenarios ──────────────────────────────────────────────────────────────


@dataclass(frozen=True)
class Scenario:
    name: str
    shape: str
    team_count: int
    teams: tuple[int, ...]
    legs: tuple[tuple[str, int, int], ...]  # (assetId, from, to)
    all_priced: bool = True

    def legs_payload(self) -> list[dict[str, Any]]:
        return [{"id": a, "from": f, "to": t} for a, f, t in self.legs]

    def describe(self) -> dict[str, Any]:
        sends: dict[int, int] = {t: 0 for t in self.teams}
        for _a, f, _t in self.legs:
            sends[f] += 1
        return {
            "name": self.name,
            "shape": self.shape,
            "teamCount": self.team_count,
            "teams": list(self.teams),
            "legs": len(self.legs),
            "legsSentByTeam": {str(k): v for k, v in sorted(sends.items())},
            "players": sum(1 for a, _f, _t in self.legs if a.startswith("p:")),
            "picks": sum(1 for a, _f, _t in self.legs if not a.startswith("p:")),
            "allAssetsPriced": self.all_priced,
        }


def water_fill(caps: Mapping[int, int], total: int) -> dict[int, int]:
    """Spread ``total`` over the teams as evenly as their caps allow."""
    alloc = {rid: 0 for rid in caps}
    remaining = min(int(total), sum(int(c) for c in caps.values()))
    active = sorted(rid for rid, c in caps.items() if c > 0)
    while remaining > 0 and active:
        share = max(1, remaining // len(active))
        for rid in list(active):
            take = min(share, caps[rid] - alloc[rid], remaining)
            alloc[rid] += take
            remaining -= take
            if alloc[rid] >= caps[rid]:
                active.remove(rid)
            if remaining == 0:
                break
    return alloc


def clean_view(snap: Any, exclude: set[str]) -> Any:
    """A read-only view of ``snap`` whose rosters omit the ``exclude``d assets,
    so the shared generators (``multi_team_support.team_assets`` /
    ``random_ledger``) draw only assets the engine prices."""
    teams: dict[int, dict[str, Any]] = {}
    for rid, team in snap.teams_by_roster_id.items():
        t = dict(team)
        t["playerIds"] = [p for p in team.get("playerIds") or [] if f"p:{p}" not in exclude]
        details = team.get("pickDetails")
        t["pickDetails"] = [d for d in details or [] if str(d.get("assetId")) not in exclude]
        teams[rid] = t
    return SimpleNamespace(
        teams_by_roster_id=teams,
        player_owners=snap.player_owners,
        pick_owner_index=snap.pick_owner_index,
        league_key=snap.league_key,
    )


def worst_case_ledger(
    view: Any, n_teams: int, max_legs: int, rng: random.Random
) -> tuple[list[int], list[dict[str, Any]]]:
    """The largest valid ledger over the ``n_teams`` richest teams: up to
    ``max_legs`` legs, every team sends AND receives (fan-out)."""
    from tests.trade import multi_team_support as mts  # noqa: PLC0415

    pools = {rid: mts.team_assets(view, rid) for rid in sorted(view.teams_by_roster_id)}
    richest = sorted(pools, key=lambda r: (-len(pools[r]), r))[:n_teams]
    teams = sorted(richest)
    alloc = water_fill({rid: len(pools[rid]) for rid in teams}, max_legs)
    legs: list[dict[str, Any]] = []
    for rid in teams:
        others = [t for t in teams if t != rid]
        chosen = rng.sample(pools[rid], alloc[rid])
        for i, aid in enumerate(chosen):
            legs.append({"id": aid, "from": rid, "to": others[i % len(others)]})
    return teams, legs


def _scenario(name: str, shape: str, teams: list[int], legs: list[dict[str, Any]]) -> Scenario:
    return Scenario(
        name=name,
        shape=shape,
        team_count=len(teams),
        teams=tuple(sorted(teams)),
        legs=tuple((leg["id"], leg["from"], leg["to"]) for leg in legs),
    )


# ── Context: board, stubs, counters ────────────────────────────────────────


class Counters:
    """Call counters for the structural budgets (one dict per request)."""

    def __init__(self) -> None:
        self._counts: collections.Counter[str] = collections.Counter()
        self.posture_build_flags: list[bool] = []

    def hit(self, key: str, n: int = 1) -> None:
        self._counts[key] += n

    def reset(self) -> None:
        self._counts.clear()
        self.posture_build_flags.clear()

    def snapshot(self) -> dict[str, Any]:
        out: dict[str, Any] = dict(sorted(self._counts.items()))
        out["posture_build_if_missing_true"] = sum(1 for f in self.posture_build_flags if f)
        out["posture_build_if_missing_false"] = sum(1 for f in self.posture_build_flags if not f)
        return out


@dataclass
class Context:
    contract: dict[str, Any]
    league_key: str
    roster_settings: dict[str, Any]
    policy: Any
    label: str
    board_kind: str
    counters: Counters = field(default_factory=Counters)
    scarcity_reads: list[Any] = field(default_factory=list)
    snap: Any = None
    stubs: list[str] = field(default_factory=list)


def restamp_rosters(contract: dict[str, Any], *, now: datetime | None = None) -> None:
    """Mark the rosters ``live`` and just fetched, so ownership is provable
    (the same stamp the multi-team tests apply).  Without it every team is
    honestly UNABLE and the engine never reaches its success path."""
    when = (now or datetime.now(timezone.utc)) - timedelta(minutes=1)
    contract.setdefault("sleeper", {})["rosterSource"] = "live"
    contract["sleeper"]["rosterFetchedAt"] = when.isoformat()


def dynasty_main_settings() -> dict[str, Any]:
    from tests.trade import multi_team_support as mts  # noqa: PLC0415

    return mts._dynasty_main_settings()  # noqa: SLF001


def load_raw_payload(archive: Path) -> dict[str, Any]:
    with zipfile.ZipFile(archive) as zf:
        names = [n for n in zf.namelist() if n.startswith("dynasty_data_") and n.endswith(".json")]
        if not names:
            raise MeasurementFailed(f"{archive} holds no dynasty_data_*.json")
        payload = json.loads(zf.read(sorted(names)[0]))
    if not isinstance(payload, dict):
        raise MeasurementFailed(f"{archive}: payload is not an object")
    return payload


def build_context(args: argparse.Namespace) -> Context:
    from src.trade import trade_ledger as tl  # noqa: PLC0415

    policy = tl.private_policy()
    if args.synthetic:
        from tests.trade import multi_team_support as mts  # noqa: PLC0415

        contract = mts.synthetic_league()
        restamp_rosters(contract)
        ctx = Context(
            contract=contract,
            league_key=mts.SYNTH_KEY,
            roster_settings=dict(mts.SYNTH_SETTINGS),
            policy=policy,
            label="synthetic 4-team league (LABELLED, multi_team_support.synthetic_league)",
            board_kind="synthetic",
        )
    else:
        from src.api.data_contract import build_api_data_contract  # noqa: PLC0415

        archive = Path(args.archive) if args.archive else REPO / DEFAULT_ARCHIVE
        if archive.is_file():
            raw, label = load_raw_payload(archive), archive.name
        else:
            from tests.archive_fixtures import newest_complete_raw_payload  # noqa: PLC0415

            raw, label = newest_complete_raw_payload()
            if raw is None:
                raise MeasurementFailed(f"{archive} is absent and no complete archive exists")
        contract = build_api_data_contract(raw)
        if len((contract.get("sleeper") or {}).get("teams") or []) < max(TEAM_COUNTS):
            raise MeasurementFailed(f"board {label} carries fewer than {max(TEAM_COUNTS)} rosters")
        restamp_rosters(contract)
        contract.setdefault("meta", {})["leagueKey"] = LEAGUE_KEY
        ctx = Context(
            contract=contract,
            league_key=LEAGUE_KEY,
            roster_settings=dynasty_main_settings(),
            policy=policy,
            label=str(label),
            board_kind="archive",
        )
    ctx.snap = tl.snapshot_for(
        ctx.contract, league_key=ctx.league_key, roster_settings=ctx.roster_settings
    )
    if ctx.snap.rosters_state != "current":
        raise MeasurementFailed(f"rosters are {ctx.snap.rosters_state!r}, not current")
    return ctx


class _StubPosture:
    """A LABELLED synthetic posture object (``.to_dict()`` like the owner's)."""

    def to_dict(self) -> dict[str, Any]:
        return {
            "label": "HOLD",
            "probabilities": {"PUSH": 0.3, "HOLD": 0.4, "RETOOL": 0.2, "REBUILD": 0.1},
            "confidence": "LOW",
            "paramsVersion": "posture_v1_prior",
            "notes": ["LABELLED synthetic posture (measure_trade_analyze_multi)"],
        }


#: LABELLED synthetic points-per-game for the roster-utility Monte Carlo:
#: ``floor + span * value / 9999``.  Invented to give the REAL utility code a
#: projection basis; the cost it measures depends on roster size and draws,
#: not on these numbers.  Never a measured value.
LABELLED_PPG_FLOOR = 2.0
LABELLED_PPG_SPAN = 18.0
ROSTER_UTILITY_CHOICES = ("labelled", "real")


def install_stubs(ctx: Context, patches: Patches, *, roster_utility: str = "labelled") -> None:
    """Answer the network / box-local reads with LABELLED stubs: the league
    posture bundle, the league scarcity and (``roster_utility="labelled"``) the
    league-scored projection basis, so the REAL best-ball Monte Carlo runs.
    With ``"real"`` the projection basis is whatever this machine holds -- on a
    machine with no projection snapshot the utility reports unavailable and
    Team Context ends early, which is far cheaper than production."""
    from src.api import gameplan  # noqa: PLC0415
    from src.roster_intel import best_ball_utility as bbu  # noqa: PLC0415
    from tests.trade import multi_team_support as mts  # noqa: PLC0415

    owners = {str(t.get("ownerId") or "") for t in ctx.contract["sleeper"]["teams"]} - {""}
    counters = ctx.counters

    def _postures(league_key, profile, contract, *, build_if_missing):  # noqa: ANN001
        counters.hit("posture_bundle_reads")
        counters.posture_build_flags.append(bool(build_if_missing))
        return {o: _StubPosture() for o in owners}, {"bundleFreshness": "fresh"}

    patches.setattr(gameplan, "league_competitive_postures", _postures)
    ctx.scarcity_reads = mts.pin_league_scarcity(patches)
    ctx.stubs = [
        "gameplan.league_competitive_postures -> LABELLED synthetic HOLD posture per owner",
        "roster_capacity._league_scarcity -> LABELLED fixed positional scarcity "
        "(multi_team_support.PINNED_WAIVER_SCARCITY)",
    ]
    if roster_utility == "labelled":

        def _ppg(player_ids, *, season, scoring_settings):  # noqa: ANN001
            out: dict[str, float] = {}
            for pid in player_ids:
                row = ctx.snap.rows_by_player_id.get(str(pid))
                value = row.get("rankDerivedValue") if isinstance(row, Mapping) else None
                if isinstance(value, (int, float)) and not isinstance(value, bool) and value > 0:
                    out[str(pid)] = LABELLED_PPG_FLOOR + LABELLED_PPG_SPAN * min(value, 9999) / 9999
            return out, {"state": "available", "reason": None, "source": "LABELLED synthetic ppg"}

        patches.setattr(bbu, "league_scored_ppg_by_id", _ppg)
        ctx.stubs.append(
            "best_ball_utility.league_scored_ppg_by_id -> LABELLED synthetic ppg "
            f"({LABELLED_PPG_FLOOR} + {LABELLED_PPG_SPAN} * value / 9999); the Monte Carlo is REAL"
        )
    else:
        ctx.stubs.append(
            "roster utility basis: whatever this machine holds (no stub); an unavailable basis "
            "ends Team Context early"
        )


def install_counting_wrappers(ctx: Context, patches: Patches) -> None:
    """Wrap the real functions the structural budgets talk about so a request
    counts how often each runs.  Installed only for the dedicated counted
    pass, so timed samples carry no wrapper cost."""
    from src.roster_intel import best_ball_utility as bbu  # noqa: PLC0415
    from src.trade import comparable_trades, roster_capacity  # noqa: PLC0415
    from src.trade import trade_decision_log as decision_log  # noqa: PLC0415
    from src.trade import trade_ledger as tl  # noqa: PLC0415

    counters = ctx.counters

    def wrap(obj: Any, name: str, key: str) -> None:
        original = getattr(obj, name)

        def _counted(*a: Any, **kw: Any) -> Any:
            counters.hit(key)
            return original(*a, **kw)

        patches.setattr(obj, name, _counted)

    wrap(tl, "build_trade_snapshot", "snapshot_builds")
    wrap(roster_capacity, "build_capacity_context", "capacity_builds")
    wrap(roster_capacity, "simulate_final_legal_roster", "final_roster_simulations")
    wrap(roster_capacity, "evaluate_final_roster_utility", "roster_utility_calls")
    wrap(bbu, "evaluate_trade_utility", "utility_evaluations")
    wrap(comparable_trades, "comparable_trades", "comparables_lookups")
    wrap(decision_log, "record_decision", "decision_receipts")


# ── Engine runner ──────────────────────────────────────────────────────────


def stage_categories(stages: Sequence[tuple[str, float]]) -> dict[str, float]:
    """Sum stage times by kind: ``team:<rid>:posture`` -> ``posture`` ..."""
    out: dict[str, float] = collections.defaultdict(float)
    for name, ms in stages:
        parts = str(name).split(":")
        key = parts[2] if len(parts) == 3 and parts[0] == "team" else str(name)
        out[key] += float(ms)
    return dict(out)


@dataclass
class Sample:
    total_ms: float
    parts: dict[str, float] = field(default_factory=dict)
    stages: dict[str, float] = field(default_factory=dict)
    info: dict[str, Any] = field(default_factory=dict)


RunFn = Callable[["Scenario", bool], Sample]


def counterfactuals_for(mode: str) -> bool:
    """The route default for the private modes; the public path's value for
    ``market_fairness`` (``public_advisor`` passes ``counterfactuals=False``)."""
    return mode != "market_fairness"


def comparables_provider_like_the_route(ctx: Context) -> Callable[[Any, dict[str, Any]], Any]:
    """The route's own ``_comparables`` closure (``server.py``), so the N = 2
    engine numbers carry the same lookup the route does."""

    def _provider(flows: Any, simulation: dict[str, Any]) -> Any:
        from src.trade import comparable_trades as comparable  # noqa: PLC0415

        names: dict[str, dict[str, Any]] = {}
        for row in ctx.contract.get("playersArray") or []:
            sid = str(row.get("playerId") or "").strip()
            if sid and sid not in names:
                names[sid] = {
                    "name": row.get("canonicalName") or row.get("displayName"),
                    "position": row.get("position"),
                }
        return comparable.comparable_trades(
            ctx.league_key,
            side_a=comparable.side_refs_from_assets(simulation.get("receiving") or []),
            side_b=comparable.side_refs_from_assets(simulation.get("sending") or []),
            names=names,
        )

    return _provider


def describe_outcome(teams: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    """What path a request took: decision categories, fairness states, the
    per-leg value states, and whether the roster-utility / comparables paths
    actually ran (an evidence gate or a missing local input short-circuits
    them, and a reader must be able to tell)."""
    categories: collections.Counter[str] = collections.Counter()
    fairness: collections.Counter[str] = collections.Counter()
    value_states: collections.Counter[str] = collections.Counter()
    utility: collections.Counter[str] = collections.Counter()
    comparables: collections.Counter[str] = collections.Counter()
    for team in teams:
        categories[str(team.get("category"))] += 1
        fairness[str((team.get("fairness") or {}).get("state"))] += 1
        for side in ("gives", "receives"):
            for row in team.get(side) or []:
                value_states[str(row.get("valueState"))] += 1
        sim = team.get("simulation") or {}
        ru = sim.get("rosterUtility")
        if isinstance(ru, Mapping):
            utility["available" if ru.get("available") else str(ru.get("unavailableReason"))] += 1
        else:
            utility["not_requested"] += 1
        comp = team.get("comparables")
        comparables[str(comp.get("state")) if isinstance(comp, Mapping) else "lens"] += 1
    non_priced = sum(v for k, v in value_states.items() if k != "priced")
    return {
        "categories": dict(categories),
        "fairnessStates": dict(fairness),
        "valueStates": dict(value_states),
        "evidenceGated": bool(non_priced),
        "rosterUtility": dict(utility),
        "comparables": dict(comparables),
    }


def make_engine_runner(ctx: Context, mode: str) -> RunFn:
    from src.api.trade_analyze_runtime import StageClock  # noqa: PLC0415
    from src.trade import analyze_service as svc  # noqa: PLC0415
    from src.trade import trade_ledger as tl  # noqa: PLC0415

    provider = None if mode == "market_fairness" else comparables_provider_like_the_route(ctx)

    def _run(scn: Scenario, keep_info: bool) -> Sample:
        clock = StageClock()
        t0 = time.perf_counter()
        snap = tl.snapshot_for(
            ctx.contract, league_key=ctx.league_key, roster_settings=ctx.roster_settings
        )
        t1 = time.perf_counter()
        ledger = tl.validate_ledger(
            snap, teams=list(scn.teams), legs=scn.legs_payload(), policy=ctx.policy
        )
        t2 = time.perf_counter()
        out = svc.analyze_trade_n(
            snap,
            ledger,
            mode=mode,
            counterfactuals=counterfactuals_for(mode),
            comparables_provider=provider,
            stage=clock.stage,
        )
        t3 = time.perf_counter()
        sample = Sample(
            total_ms=(t3 - t0) * 1000.0,
            parts={
                "snapshot": (t1 - t0) * 1000.0,
                "validate": (t2 - t1) * 1000.0,
                "analyze": (t3 - t2) * 1000.0,
            },
            stages=stage_categories(clock.stages()),
        )
        if keep_info:
            sample.info = {"teams": list(out["teams"].values())}
        return sample

    return _run


# ── Route runner (in-process TestClient) ───────────────────────────────────


#: A LABELLED synthetic signed-in (non-guest) session.
TEST_SESSION = {"username": "tester", "sleeper_user_id": "u1"}


@contextlib.contextmanager
def route_client(ctx: Context, base_url: str, temp_root: Path) -> Iterator[Any]:
    """``POST /api/trade/analyze-multi`` through FastAPI's in-process
    ``TestClient``: the private flag forced ON in this process only, a registry
    holding just the real ``dynasty_main`` entry, the archived contract
    injected as the live one, a signed-in test session."""
    from src.api import feature_flags, league_registry  # noqa: PLC0415

    registry = json.loads((REPO / "config/leagues/registry.json").read_text(encoding="utf-8"))
    main = next(lg for lg in registry["leagues"] if lg["key"] == LEAGUE_KEY)
    reg_path = temp_root / "registry.json"
    reg_path.write_text(
        json.dumps({"schemaVersion": 1, "defaultLeagueKey": LEAGUE_KEY, "leagues": [main]}),
        encoding="utf-8",
    )
    patches = Patches()
    quiet_loggers = [
        logging.getLogger(n) for n in ("httpx", "httpcore", "uvicorn", "uvicorn.error")
    ]
    previous_levels = [lg.level for lg in quiet_loggers]
    for lg in quiet_loggers:
        lg.setLevel(logging.WARNING)
    with env_overrides({PRIVATE_FLAG_ENV: "1", "LEAGUE_REGISTRY_PATH": str(reg_path)}):
        league_registry.reload_registry()
        feature_flags.reload()
        try:
            # Imported with the registry and the flag already in place, so
            # nothing it reads at import names the real league registry.
            import server  # noqa: PLC0415
            from fastapi.testclient import TestClient  # noqa: PLC0415

            patches.setattr(server, "latest_contract_data", ctx.contract)
            patches.setattr(server, "_get_auth_session", lambda _r: dict(TEST_SESSION))
            with TestClient(server.app, base_url=base_url, raise_server_exceptions=True) as client:
                # The lifespan may prime its own contract; the archived board
                # is the one measured.
                server.latest_contract_data = ctx.contract
                yield client
        finally:
            patches.undo()
            league_registry.reload_registry()
            for lg, level in zip(quiet_loggers, previous_levels):
                lg.setLevel(level)
    feature_flags.reload()


def make_route_runner(client: Any, ctx: Context, mode: str) -> RunFn:
    def _run(scn: Scenario, keep_info: bool) -> Sample:
        body = {
            "leagueKey": ctx.league_key,
            "teams": list(scn.teams),
            "assets": scn.legs_payload(),
            "useTeamContext": mode == "team_context",
            "counterfactuals": counterfactuals_for(mode),
        }
        t0 = time.perf_counter()
        res = client.post("/api/trade/analyze-multi", json=body)
        total = (time.perf_counter() - t0) * 1000.0
        if res.status_code != 200:
            raise MeasurementFailed(
                f"route answered {res.status_code} for {scn.name}/{mode}: {res.text[:240]}"
            )
        payload = res.json()
        timing = payload.get("analysisTiming") or {}
        stages = stage_categories(
            [(s.get("stage"), s.get("ms", 0.0)) for s in timing.get("stages") or []]
        )
        sample = Sample(
            total_ms=total,
            parts={"serverTotal": float(timing.get("totalMs") or 0.0)},
            stages=stages,
            info={"responseBytes": len(res.content)},
        )
        if keep_info:
            sample.info["teams"] = list(payload.get("teams") or [])
        return sample

    return _run


# ── Public route runner (opt-in: --public-route) ───────────────────────────


@contextlib.contextmanager
def public_route_client(ctx: Context, base_url: str, temp_root: Path) -> Iterator[Any]:
    """``POST /api/public/league/trade-advisor/analyze`` through the in-process
    ``TestClient``: the ``brisket_trade_advisor`` flag forced ON in THIS process
    only and the launch gate opened IN-PROCESS ONLY (``_launch_gate_reason``
    patched; ``config/trade/public_advisor.json`` is untouched, so its
    ``responseFloorMs`` stays unset and NO floor is applied -- the raw route
    latency the floor must cover is what gets measured).  The public limiter is
    reset before every request, outside the timed window, so the samples
    measure the analyze path rather than a 429."""
    from src.api import feature_flags, league_registry  # noqa: PLC0415

    registry = json.loads((REPO / "config/leagues/registry.json").read_text(encoding="utf-8"))
    main = next(lg for lg in registry["leagues"] if lg["key"] == LEAGUE_KEY)
    reg_path = temp_root / "registry-public.json"
    reg_path.write_text(
        json.dumps({"schemaVersion": 1, "defaultLeagueKey": LEAGUE_KEY, "leagues": [main]}),
        encoding="utf-8",
    )
    patches = Patches()
    quiet_loggers = [
        logging.getLogger(n) for n in ("httpx", "httpcore", "uvicorn", "uvicorn.error")
    ]
    previous_levels = [lg.level for lg in quiet_loggers]
    for lg in quiet_loggers:
        lg.setLevel(logging.WARNING)
    try:
        with env_overrides({PUBLIC_FLAG_ENV: "1", "LEAGUE_REGISTRY_PATH": str(reg_path)}):
            league_registry.reload_registry()
            feature_flags.reload()
            try:
                import server  # noqa: PLC0415
                from fastapi.testclient import TestClient  # noqa: PLC0415

                from src.api import public_trade_advisor_api as api  # noqa: PLC0415

                api.reset_for_tests()
                patches.setattr(server, "latest_contract_data", ctx.contract)
                patches.setattr(api, "_launch_gate_reason", lambda: None)
                patches.setattr(api, "_public_league_key", lambda: ctx.league_key)
                with TestClient(
                    server.app, base_url=base_url, raise_server_exceptions=True
                ) as client:
                    server.latest_contract_data = ctx.contract
                    if api.advisor_config().get("responseFloorMs") is not None:
                        raise MeasurementFailed(
                            "responseFloorMs is set: the public route would be held to it, so its "
                            "raw latency cannot be measured"
                        )
                    yield client
            finally:
                patches.undo()
    finally:
        # Reload only AFTER env_overrides has restored the caller's
        # environment, so the registry and flags re-read the ORIGINAL values
        # rather than the temporary override, and do both even when the
        # measurement raised.
        try:
            league_registry.reload_registry()
        finally:
            feature_flags.reload()
            for lg, level in zip(quiet_loggers, previous_levels):
                lg.setLevel(level)


def make_public_route_runner(client: Any, ctx: Context, mode: str) -> RunFn:
    from src.api import public_trade_advisor_api as api  # noqa: PLC0415
    from src.api import rate_limit  # noqa: PLC0415

    def _run(scn: Scenario, keep_info: bool) -> Sample:
        body = {
            "perspectiveRosterId": int(scn.teams[0]),
            "teams": list(scn.teams),
            "assets": scn.legs_payload(),
        }
        # Outside the timed window: the advisor's own limiter and the
        # site-wide public limiter, so a long run measures analyze, not 429.
        api._limiter().reset()
        rate_limit.reset_for_tests()
        t0 = time.perf_counter()
        res = client.post(PUBLIC_ANALYZE_PATH, json=body)
        total = (time.perf_counter() - t0) * 1000.0
        if res.status_code != 200:
            raise MeasurementFailed(
                f"public route answered {res.status_code} for {scn.name}: {res.text[:240]}"
            )
        payload = res.json()
        sample = Sample(
            total_ms=total,
            parts={},
            stages={},
            info={"responseBytes": len(res.content)},
        )
        if keep_info:
            sample.info["overall"] = (payload.get("overall") or {}).get("result")
            sample.info["teams"] = [
                {"rosterId": t.get("rosterId"), "result": t.get("result")}
                for t in payload.get("teams") or []
            ]
        return sample

    return _run


# ── Cell measurement (surface-agnostic) ────────────────────────────────────


def prep_cold(*_: Any) -> None:
    """Cold = no ledger snapshot memo and no reused before-roster entry."""
    from src.roster_intel import best_ball_utility as bbu  # noqa: PLC0415
    from src.trade import trade_ledger as tl  # noqa: PLC0415

    tl.clear_snapshot_memo()
    bbu.clear_before_side_cache()


def _timed(
    run: RunFn, scenarios: Sequence[Scenario], n: int, prep: Callable[[], None] | None
) -> dict[str, Any]:
    totals: list[float] = []
    parts: dict[str, list[float]] = collections.defaultdict(list)
    stages: dict[str, list[float]] = collections.defaultdict(list)
    for i in range(n):
        scn = scenarios[i % len(scenarios)]
        if prep is not None:
            prep()
        sample = run(scn, False)
        totals.append(sample.total_ms)
        for k, v in sample.parts.items():
            parts[k].append(v)
        for k, v in sample.stages.items():
            stages[k].append(v)
    return {
        "totalMs": summarize(totals),
        "partsP50Ms": {k: round(percentile(v, 50) or 0.0, 2) for k, v in sorted(parts.items())},
        "stagesP50Ms": {k: round(percentile(v, 50) or 0.0, 2) for k, v in sorted(stages.items())},
    }


def _peak_alloc_mb(
    run: RunFn, scenarios: Sequence[Scenario], n: int, prep: Callable[[], None] | None
) -> dict[str, Any]:
    if n <= 0:
        return {"n": 0, "p50": None, "max": None}
    peaks: list[float] = []
    tracemalloc.start()
    try:
        for i in range(n):
            scn = scenarios[i % len(scenarios)]
            if prep is not None:
                prep()
            tracemalloc.reset_peak()
            base = tracemalloc.get_traced_memory()[0]
            run(scn, False)
            peaks.append((tracemalloc.get_traced_memory()[1] - base) / 1048576.0)
    finally:
        tracemalloc.stop()
    return {
        "n": len(peaks),
        "p50": round(percentile(peaks, 50) or 0.0, 2),
        "max": round(max(peaks), 2),
    }


def measure_cell(
    run: RunFn,
    scenarios: Sequence[Scenario],
    *,
    cold_samples: int,
    warm_samples: int,
    memory_samples: int,
    prep: Callable[[], None] = prep_cold,
) -> dict[str, Any]:
    """Timed cold / warm samples (scenarios round-robin) and the per-call
    ``tracemalloc`` peak.  Pure over ``run``: a fake runner measures the
    plumbing without any engine."""
    gc.collect()
    out: dict[str, Any] = {"scenarios": [s.name for s in scenarios]}
    out["cold"] = _timed(run, scenarios, cold_samples, prep)
    run(scenarios[0], False)  # prime the snapshot memo for the warm samples
    out["warm"] = _timed(run, scenarios, warm_samples, None)
    out["memory"] = {
        "unit": "MB",
        "basis": "tracemalloc peak of Python allocations per call",
        "cold": _peak_alloc_mb(run, scenarios, memory_samples, prep),
        "warm": _peak_alloc_mb(run, scenarios, memory_samples, None),
        "processRssMb": process_rss_mb(),
    }
    return out


def counted_pass(ctx: Context, run: RunFn, scn: Scenario, patches: Patches) -> dict[str, Any]:
    """One cold request, one warm request and one repeat of the warm request,
    with the structural counters installed.  Returns per-request counters and
    the outcome (from the cold request)."""
    from src.roster_intel import best_ball_utility as bbu  # noqa: PLC0415

    install_counting_wrappers(ctx, patches)
    try:
        requests: dict[str, Any] = {}
        outcome: dict[str, Any] = {}
        for label, cold in (("cold", True), ("warm", False), ("warmRepeat", False)):
            if cold:
                prep_cold()
            ctx.counters.reset()
            reads_before = len(ctx.scarcity_reads)
            before = dict(bbu.before_side_stats)
            sample = run(scn, True)
            counts = ctx.counters.snapshot()
            counts["scarcity_reads"] = len(ctx.scarcity_reads) - reads_before
            counts["before_roster_computed"] = (
                bbu.before_side_stats["computed"] - before["computed"]
            )
            counts["before_roster_reused"] = bbu.before_side_stats["reused"] - before["reused"]
            requests[label] = counts
            if label == "cold":
                outcome = describe_outcome(sample.info.get("teams") or [])
                outcome["notComputedComparables"] = sum(
                    1
                    for t in sample.info.get("teams") or []
                    if t.get("comparables") == NOT_COMPUTED_COMPARABLES
                )
                outcome["teamsAnalysed"] = len(sample.info.get("teams") or [])
        return {"requests": requests, "outcome": outcome}
    finally:
        patches.undo()


# ── Scenario construction ──────────────────────────────────────────────────


def non_priced_assets(ctx: Context, scenarios: Sequence[Scenario]) -> set[str]:
    """Asset ids any scenario leg is not ``priced`` for, read from the engine's
    own per-leg ``valueState`` (the evidence gates, not a re-derivation)."""
    from src.trade import analyze_service as svc  # noqa: PLC0415
    from src.trade import trade_ledger as tl  # noqa: PLC0415

    bad: set[str] = set()
    for scn in scenarios:
        ledger = tl.validate_ledger(
            ctx.snap, teams=list(scn.teams), legs=scn.legs_payload(), policy=ctx.policy
        )
        out = svc.analyze_trade_n(ctx.snap, ledger, mode="market_fairness", counterfactuals=False)
        for team in out["teams"].values():
            for side in ("gives", "receives"):
                for row in team.get(side) or []:
                    if row.get("valueState") != "priced":
                        bad.add(str(row.get("assetId")))
    return bad


def screen_assets(ctx: Context) -> set[str]:
    """Every asset some team holds that the engine does NOT price, found by
    sending each team's whole inventory (in chunks of ``maxLegs``) to another
    team in ``market_fairness`` and reading the engine's own per-leg
    ``valueState`` -- the evidence gates themselves, not a re-derivation."""
    from tests.trade import multi_team_support as mts  # noqa: PLC0415

    rids = sorted(ctx.snap.teams_by_roster_id)
    bad: set[str] = set()
    for i, rid in enumerate(rids):
        other = rids[(i + 1) % len(rids)]
        pool = mts.team_assets(ctx.snap, rid)
        for start in range(0, len(pool), ctx.policy.max_legs):
            chunk = pool[start : start + ctx.policy.max_legs]
            probe = _scenario(
                f"screen{rid}",
                "screen",
                [rid, other],
                [{"id": a, "from": rid, "to": other} for a in chunk],
            )
            bad |= non_priced_assets(ctx, [probe])
    return bad


def build_scenarios(
    ctx: Context, *, seed: int, ledgers: int, team_counts: Sequence[int]
) -> tuple[dict[tuple[str, int], list[Scenario]], int]:
    """``({(shape, n_teams): [Scenario, ...]}, assets_screened_out)`` -- every
    ledger validated, and
    every asset confirmed ``priced`` by the engine (unpriced / quarantined /
    stale assets are screened out first, and any that still slip through are
    excluded and the ledgers regenerated, so the timed path is the full
    success path)."""
    from src.trade import trade_ledger as tl  # noqa: PLC0415
    from tests.trade import multi_team_support as mts  # noqa: PLC0415

    exclude: set[str] = screen_assets(ctx)
    plan: dict[tuple[str, int], list[Scenario]] = {}
    for _attempt in range(6):
        view = clean_view(ctx.snap, exclude)
        plan = {}
        for n in team_counts:
            reps = []
            for i in range(ledgers):
                rng = random.Random(f"{seed}:rep:{n}:{i}")
                teams, legs = mts.random_ledger(
                    view, rng, n_teams=n, max_per_team=3, send_and_receive=True
                )
                reps.append(_scenario(f"rep{n}_{i}", "representative", teams, legs))
            plan[("representative", n)] = reps
            teams, legs = worst_case_ledger(
                view, n, ctx.policy.max_legs, random.Random(f"{seed}:worst:{n}")
            )
            plan[("worst_case", n)] = [_scenario(f"worst{n}", "worst_case", teams, legs)]
        flat = [s for group in plan.values() for s in group]
        for s in flat:
            tl.validate_ledger(
                ctx.snap, teams=list(s.teams), legs=s.legs_payload(), policy=ctx.policy
            )
        bad = non_priced_assets(ctx, flat)
        if not bad:
            return plan, len(exclude)
        exclude |= bad
    # Could not reach an all-priced set: keep the last plan, say so per scenario.
    unpriced = {key: [replace(s, all_priced=False) for s in group] for key, group in plan.items()}
    return unpriced, len(exclude)


def measure_comparables(
    ctx: Context, plan: Mapping[tuple[str, int], Sequence[Scenario]], *, samples: int
) -> dict[str, Any]:
    """The per-team comparables lookup (the route's own ``_comparables``
    closure) timed on a 3-team representative ledger, so spec 2.11's "unless
    the per-team lookup fits the budget" has a number.  The lookup reads the
    BOX-LOCAL canonical trade ledger: without it the call answers
    ``unavailable`` quickly, and that cheap path says nothing about the
    production cost -- the ``state`` field makes that visible."""
    from src.trade import analyze_service as svc  # noqa: PLC0415
    from src.trade import trade_ledger as tl  # noqa: PLC0415

    sizes = sorted({n for (_shape, n) in plan if n >= 3}) or sorted({n for (_shape, n) in plan})
    scn = plan[("representative", sizes[0])][0]
    snap = tl.snapshot_for(
        ctx.contract, league_key=ctx.league_key, roster_settings=ctx.roster_settings
    )
    ledger = tl.validate_ledger(
        snap, teams=list(scn.teams), legs=scn.legs_payload(), policy=ctx.policy
    )
    out = svc.analyze_trade_n(snap, ledger, mode="asset_only", counterfactuals=False)
    provider = comparables_provider_like_the_route(ctx)
    times: list[float] = []
    states: collections.Counter[str] = collections.Counter()
    for rid, team in out["teams"].items():
        flows = tl.team_flows(ledger, rid)
        for _ in range(max(1, samples)):
            t0 = time.perf_counter()
            result = provider(flows, team["simulation"])
            times.append((time.perf_counter() - t0) * 1000.0)
            states[str(result.get("state")) if isinstance(result, Mapping) else "absent"] += 1
    per_lookup = summarize(times)
    built = set(states) == {"ok"}
    return {
        "teamCount": len(out["teams"]),
        "lookupState": dict(states),
        "perTeamLookupMs": per_lookup,
        "projectedExtraMsAtThisN": (
            None if per_lookup["p50"] is None else round(per_lookup["p50"] * len(out["teams"]), 2)
        ),
        "establishesProductionCost": built,
        "note": (
            "the lookup ran against a built local ledger"
            if built
            else "state 'unavailable' means the box-local canonical trade ledger is not built "
            "here, so this timing is the cheap refusal path and SD-12 cannot be decided locally"
        ),
    }


# ── Budgets ────────────────────────────────────────────────────────────────


def _cells(results: Mapping[str, Any], surface: str, **where: Any) -> list[dict[str, Any]]:
    out = []
    for cell in results.get(surface) or []:
        if all(cell.get(k) == v for k, v in where.items()):
            out.append(cell)
    return out


def _max_metric(
    cells: Sequence[Mapping[str, Any]], getter: Callable[[Mapping[str, Any]], Any]
) -> tuple[Any, str | None]:
    best, where = None, None
    for cell in cells:
        v = getter(cell)
        if isinstance(v, (int, float)) and (best is None or v > best):
            best, where = (
                v,
                f"{cell.get('surface')}/{cell.get('mode')}/N={cell.get('teams')}/{cell.get('shape')}",
            )
    return best, where


def _peak_of_cell(cell: Mapping[str, Any]) -> float | None:
    """The cell's largest measured per-call peak (``None`` when no memory
    sample was taken -- unmeasured is never 0)."""
    peaks = [((cell.get("memory") or {}).get(w) or {}).get("max") for w in ("cold", "warm")]
    peaks = [v for v in peaks if isinstance(v, (int, float))]
    return max(peaks) if peaks else None


def _status(observed: Any, limit: float | None, *, exercised: bool = True) -> str:
    if limit is None:
        return "not_set"
    if not exercised or observed is None:
        return "not_measured"
    return "breach" if observed > limit else "pass"


def _req(cell: Mapping[str, Any], which: str) -> Mapping[str, Any]:
    return ((cell.get("structural") or {}).get("requests") or {}).get(which) or {}


def evaluate_budgets(results: Mapping[str, Any], limits: Mapping[str, Any]) -> list[dict[str, Any]]:
    """Pure: measured cells + declared limits -> one entry per budget with
    ``status`` in ``pass`` / ``breach`` / ``not_measured`` / ``not_exercised`` /
    ``not_set``.  Only ``breach`` fails the run."""
    budgets: list[dict[str, Any]] = []
    all_cells = [c for s in ("engine", "route") for c in results.get(s) or []]

    def add(bid: str, kind: str, source: str, statement: str, **kw: Any) -> None:
        budgets.append({"id": bid, "kind": kind, "source": source, "statement": statement, **kw})

    # S1 -- one snapshot per request.
    route_cells = results.get("route") or []
    builds = [
        _req(c, w).get("snapshot_builds", 0)
        for c in all_cells
        if c.get("structural")
        for w in ("cold", "warm")
    ]
    worst_builds = max(builds) if builds else None
    add(
        "S1_one_snapshot_per_request",
        "structural",
        "spec 2.11 bullet 1",
        "A request builds at most one trade snapshot (cold: one; warm: none, from the memo).",
        limit=1,
        observed=worst_builds,
        status=(
            "not_measured" if worst_builds is None else "breach" if worst_builds > 1 else "pass"
        ),
        detail={"requestsChecked": len(builds)},
    )

    # S2 -- posture bundle reads.
    reads = [
        (c, w, _req(c, w).get("posture_bundle_reads", 0))
        for c in all_cells
        if c.get("structural")
        for w in ("cold", "warm")
    ]
    over = [f"{c['surface']}/{c['mode']}/N={c['teams']}" for c, _w, n in reads if n > 1]
    mf_reads = [n for c, _w, n in reads if c.get("mode") == "market_fairness" and n]
    build_in_wrong_mode = [
        f"{c['surface']}/{c['mode']}/N={c['teams']}"
        for c, w, _n in reads
        if c.get("mode") != "team_context" and _req(c, w).get("posture_build_if_missing_true", 0)
    ]
    add(
        "S2_one_posture_bundle_per_request",
        "structural",
        "spec 2.11 bullet 2, spec 2.5 (R8c)",
        "At most one posture bundle read per request; none in market_fairness; "
        "built (build_if_missing) only in team_context.",
        limit=1,
        observed=max([n for _c, _w, n in reads] or [None], key=lambda v: -1 if v is None else v),
        status=(
            "not_measured"
            if not reads
            else "breach"
            if over or mf_reads or build_in_wrong_mode
            else "pass"
        ),
        detail={
            "cellsOverOne": over,
            "marketFairnessReads": len(mf_reads),
            "builtOutsideTeamContext": build_in_wrong_mode,
        },
    )

    # S3 -- one scarcity read per request, none in market_fairness.
    sc = [
        (c, _req(c, w).get("scarcity_reads", 0))
        for c in all_cells
        if c.get("structural")
        for w in ("cold", "warm")
    ]
    sc_over = [f"{c['surface']}/{c['mode']}/N={c['teams']}" for c, n in sc if n > 1]
    sc_mf = [
        f"{c['surface']}/{c['mode']}/N={c['teams']}"
        for c, n in sc
        if c.get("mode") == "market_fairness" and n
    ]
    add(
        "S3_one_scarcity_read_per_request",
        "structural",
        "spec 2.5 (R1-1)",
        "At most one league scarcity read per request; none in market_fairness.",
        limit=1,
        observed=max([n for _c, n in sc] or [None], key=lambda v: -1 if v is None else v),
        status="not_measured" if not sc else "breach" if sc_over or sc_mf else "pass",
        detail={"cellsOverOne": sc_over, "marketFairnessReads": sc_mf},
    )

    # S4 -- market_fairness skips capacity / final roster / utility, writes nothing.
    skipped = (
        "capacity_builds",
        "final_roster_simulations",
        "roster_utility_calls",
        "utility_evaluations",
        "before_roster_computed",
        "before_roster_reused",
        "decision_receipts",
    )
    mf = [c for c in all_cells if c.get("mode") == "market_fairness" and c.get("structural")]
    violations = [
        f"{c['surface']}/N={c['teams']}/{c['shape']}:{key}={_req(c, w).get(key)}"
        for c in mf
        for w in ("cold", "warm", "warmRepeat")
        for key in skipped
        if _req(c, w).get(key, 0)
    ]
    add(
        "S4_market_fairness_skips_capacity_roster_utility",
        "structural",
        "spec 2.11 bullet 4, spec 2.5 (P1)",
        "market_fairness builds no capacity context, no final roster, no utility, "
        "never touches the before-roster cache and records no decision.",
        limit=0,
        observed=len(violations),
        status="not_measured" if not mf else "breach" if violations else "pass",
        detail={"violations": violations, "cellsChecked": len(mf)},
    )

    # S5 -- comparables not computed at N >= 3; N = 2 looks up at most once per team.
    big = [
        c
        for c in all_cells
        if c.get("mode") != "market_fairness" and (c.get("teams") or 0) >= 3 and c.get("structural")
    ]
    comp_bad = []
    for c in big:
        out = c["structural"].get("outcome") or {}
        if _req(c, "cold").get("comparables_lookups", 0) or out.get(
            "notComputedComparables"
        ) != out.get("teamsAnalysed"):
            comp_bad.append(f"{c['surface']}/{c['mode']}/N={c['teams']}/{c['shape']}")
    two = [
        c
        for c in all_cells
        if c.get("mode") != "market_fairness" and c.get("teams") == 2 and c.get("structural")
    ]
    two_bad = [
        f"{c['surface']}/{c['mode']}/{c['shape']}"
        for c in two
        if _req(c, "cold").get("comparables_lookups", 0) > 2
    ]
    add(
        "S5_comparables_not_computed_at_n_ge_3",
        "structural",
        "spec 2.11 comparables bullet (SD-12)",
        "At N >= 3 every team's comparables are stamped not_computed_multi_team and no lookup "
        "runs; at N = 2 at most one lookup per team.",
        limit=0,
        observed=len(comp_bad) + len(two_bad),
        status="not_measured" if not (big or two) else "breach" if comp_bad or two_bad else "pass",
        detail={"n3plusViolations": comp_bad, "n2Violations": two_bad},
    )

    # S6 -- before-roster cache reuse (informational unless the utility runs).
    utility_ran = [
        c
        for c in all_cells
        if c.get("mode") == "team_context"
        and c.get("structural")
        and _req(c, "cold").get("utility_evaluations", 0)
    ]
    reuse_bad = [
        f"{c['surface']}/N={c['teams']}/{c['shape']}"
        for c in utility_ran
        if _req(c, "warmRepeat").get("before_roster_computed", 0)
    ]
    add(
        "S6_before_roster_cache_reused_per_team",
        "structural",
        "spec 2.11 bullet 3",
        "A repeat private request recomputes no before-roster (reuse per team).",
        limit=0,
        observed=len(reuse_bad) if utility_ran else None,
        status="not_exercised" if not utility_ran else "breach" if reuse_bad else "pass",
        detail={
            "violations": reuse_bad,
            "note": "the roster-utility path needs league-scored projections from box-local data; "
            "'not_exercised' means it never ran here, which proves nothing either way"
            if not utility_ran
            else None,
        },
    )

    # L1 -- private route vs the private caller deadline.
    deadline_priv = limits.get("privateDeadlineMs")
    for which in ("cold", "warm"):
        priv_cells = [c for c in route_cells]
        value, where = _max_metric(
            priv_cells, lambda c, w=which: ((c.get(w) or {}).get("totalMs") or {}).get("p95")
        )
        add(
            f"L1_private_route_{which}_p95_vs_caller_deadline",
            "latency",
            "spec 6.3 admission: config/trade/analyze_admission.json trade_analyze_multi.timeoutSeconds",
            f"{which} p95 of POST /api/trade/analyze-multi stays under the private caller deadline.",
            unit="ms",
            limit=deadline_priv,
            observed=value,
            worstCell=where,
            ownerStatus=limits.get("admissionStatus"),
            status=_status(value, deadline_priv, exercised=bool(priv_cells)),
        )

    # L2 -- public path (market_fairness engine) vs the public caller deadline.
    deadline_pub = limits.get("publicDeadlineMs")
    pub_cells = _cells(results, "engine", mode="market_fairness")
    for which in ("cold", "warm"):
        value, where = _max_metric(
            pub_cells, lambda c, w=which: ((c.get(w) or {}).get("totalMs") or {}).get("p95")
        )
        add(
            f"L2_market_fairness_{which}_p95_vs_public_caller_deadline",
            "latency",
            "spec 6.3 admission: config/trade/analyze_admission.json public_advisor_analyze.timeoutSeconds",
            f"{which} p95 of snapshot + validate + analyze_trade_n(market_fairness) stays under the "
            "public caller deadline.",
            unit="ms",
            limit=deadline_pub,
            observed=value,
            worstCell=where,
            ownerStatus=limits.get("admissionStatus"),
            status=_status(value, deadline_pub, exercised=bool(pub_cells)),
        )

    # L3 -- response floor: the worst-case valid market_fairness cold p99.
    worst_pub = [c for c in pub_cells if c.get("shape") == "worst_case"]
    p99, where = _max_metric(
        worst_pub, lambda c: ((c.get("cold") or {}).get("totalMs") or {}).get("p99")
    )
    candidate = None if p99 is None else int(math.ceil(p99 / FLOOR_STEP_MS) * FLOOR_STEP_MS)
    floor = limits.get("responseFloorMs")
    add(
        "L3_public_response_floor_covers_worst_case_cold_p99",
        "latency",
        "spec 6.3 response floor calibration (P1)",
        "When responseFloorMs is set it covers the worst-case valid market_fairness cold p99. "
        "Unset today (launch gate closed); the candidate is the p99 rounded up to 50 ms.",
        unit="ms",
        limit=floor,
        observed=p99,
        worstCell=where,
        candidateFloorMs=candidate,
        status=_status(p99, floor, exercised=bool(worst_pub)),
    )

    # M1 -- memory: per-call peak x private maxConcurrent against the allowance.
    peak, where = _max_metric(
        all_cells,
        _peak_of_cell,
    )
    allowance = limits.get("memoryAllowanceMb")
    concurrency = limits.get("privateMaxConcurrent") or 1
    projected = None if peak is None else round(peak * concurrency, 2)
    add(
        "M1_peak_alloc_times_concurrency_within_memory_allowance",
        "memory",
        "spec 2.11 ('under memory/CPU limits'); reference " + str(limits.get("memorySource")),
        "Per-call tracemalloc peak x the private route's maxConcurrent stays within "
        "(memory limit - baseline RSS).",
        unit="MB",
        limit=allowance,
        observed=projected,
        perCallPeakMb=peak,
        maxConcurrent=concurrency,
        worstCell=where,
        ownerStatus="REFERENCE_NOT_AN_OWNER_BUDGET",
        status=_status(projected, allowance, exercised=peak is not None),
    )
    return budgets


def derive_limits(args: argparse.Namespace) -> dict[str, Any]:
    from src.api import compute_admission  # noqa: PLC0415

    admission_path = REPO / "config" / "trade" / "analyze_admission.json"
    public_path = REPO / "config" / "trade" / "public_advisor.json"
    try:
        status = json.loads(admission_path.read_text(encoding="utf-8")).get("status")
    except (OSError, ValueError):
        status = None
    try:
        floor = json.loads(public_path.read_text(encoding="utf-8")).get("responseFloorMs")
    except (OSError, ValueError):
        floor = None
    priv = compute_admission.spec_for(compute_admission.ROUTE_ANALYZE_MULTI)
    pub = compute_admission.spec_for(compute_admission.ROUTE_PUBLIC_ADVISOR)
    private_ms = (
        args.private_deadline_seconds * 1000.0
        if args.private_deadline_seconds is not None
        else priv.timeout_seconds * 1000.0
    )
    public_ms = (
        args.public_deadline_seconds * 1000.0
        if args.public_deadline_seconds is not None
        else pub.timeout_seconds * 1000.0
    )
    return {
        "privateDeadlineMs": private_ms,
        "publicDeadlineMs": public_ms,
        "privateMaxConcurrent": priv.max_concurrent,
        "publicMaxConcurrent": pub.max_concurrent,
        "admissionStatus": status,
        "responseFloorMs": floor if isinstance(floor, (int, float)) and floor > 0 else None,
        "memoryAllowanceMb": args.memory_limit_mb - args.baseline_rss_mb,
        "memorySource": REFERENCE_MEMORY_SOURCE,
    }


# ── Orchestration ──────────────────────────────────────────────────────────


def git_provenance() -> dict[str, Any]:
    def _git(*a: str) -> str | None:
        try:
            out = subprocess.run(
                ["git", *a], cwd=REPO, capture_output=True, text=True, timeout=10, check=False
            )
            return out.stdout.strip() or None
        except (OSError, subprocess.SubprocessError):
            return None

    return {"sha": _git("rev-parse", "HEAD"), "branch": _git("rev-parse", "--abbrev-ref", "HEAD")}


def file_sha256(path: Path) -> str | None:
    try:
        return hashlib.sha256(path.read_bytes()).hexdigest()
    except OSError:
        return None


def cell_record(
    surface: str,
    mode: str,
    n: int,
    shape: str,
    scenarios: Sequence[Scenario],
    measured: dict[str, Any],
    structural: dict[str, Any],
) -> dict[str, Any]:
    legs = [len(s.legs) for s in scenarios]
    return {
        "surface": surface,
        "mode": mode,
        "teams": n,
        "shape": shape,
        "ledgers": len(scenarios),
        "legs": {"min": min(legs), "max": max(legs)},
        "allAssetsPriced": all(s.all_priced for s in scenarios),
        **measured,
        "structural": structural,
    }


def run_measurement(args: argparse.Namespace, temp_root: Path) -> dict[str, Any]:
    started = time.perf_counter()
    ctx = build_context(args)
    patches = Patches()
    report: dict[str, Any] = {}
    try:
        install_stubs(ctx, patches, roster_utility=args.roster_utility)
        team_counts = [
            n for n in args.team_counts if n <= min(ctx.snap.team_count, ctx.policy.max_teams)
        ]
        if not team_counts:
            raise MeasurementFailed("no requested team count fits this board and policy")
        plan, screened_out = build_scenarios(
            ctx, seed=args.seed, ledgers=args.ledgers, team_counts=team_counts
        )

        engine_cells: list[dict[str, Any]] = []
        route_cells: list[dict[str, Any]] = []
        warmups: dict[str, float] = {}

        def run_cells(
            surface: str, modes: Sequence[str], make: Callable[[str], RunFn], out: list
        ) -> None:
            for mode in modes:
                run = make(mode)
                first = plan[("representative", team_counts[0])][0]
                t0 = time.perf_counter()
                prep_cold()
                run(first, False)
                warmups[f"{surface}/{mode}"] = round((time.perf_counter() - t0) * 1000.0, 1)
                for shape in SHAPES:
                    for n in team_counts:
                        scns = plan[(shape, n)]
                        structural = counted_pass(ctx, run, scns[0], Patches())
                        measured = measure_cell(
                            run,
                            scns,
                            cold_samples=args.cold_samples,
                            warm_samples=args.warm_samples,
                            memory_samples=args.memory_samples,
                        )
                        out.append(cell_record(surface, mode, n, shape, scns, measured, structural))
                        print(f"  {surface:6s} {mode:16s} N={n} {shape:14s} done", file=sys.stderr)

        if not args.skip_engine:
            run_cells("engine", MODES, lambda m: make_engine_runner(ctx, m), engine_cells)
        comparables = (
            None
            if args.skip_engine
            else measure_comparables(ctx, plan, samples=max(3, args.warm_samples // 2))
        )
        route_note = None
        if args.skip_route or args.synthetic:
            route_note = "skipped (--skip-route, or the synthetic league has no registry entry)"
        else:
            with route_client(ctx, args.base_url, temp_root) as client:
                run_cells(
                    "route", ROUTE_MODES, lambda m: make_route_runner(client, ctx, m), route_cells
                )

        public_cells: list[dict[str, Any]] = []
        if args.public_route and not args.synthetic:
            with public_route_client(ctx, args.base_url, temp_root) as client:
                run_cells(
                    "public",
                    ("market_fairness",),
                    lambda m: make_public_route_runner(client, ctx, m),
                    public_cells,
                )

        results = {"engine": engine_cells, "route": route_cells}
        if public_cells:
            results["public"] = public_cells
        limits = derive_limits(args)
        budgets = evaluate_budgets(results, limits)
        breaches = [b["id"] for b in budgets if b["status"] == "breach"]
        scenario_desc = [s.describe() for group in plan.values() for s in group]
        board_path = Path(args.archive) if args.archive else REPO / DEFAULT_ARCHIVE
        report = {
            "tool": TOOL,
            "toolVersion": TOOL_VERSION,
            "generatedAt": datetime.now(timezone.utc).isoformat(),
            "elapsedSeconds": round(time.perf_counter() - started, 1),
            "provenance": {
                "git": git_provenance(),
                "python": platform.python_version(),
                "platform": platform.platform(),
                "cpuCount": os.cpu_count(),
                "board": {
                    "kind": ctx.board_kind,
                    "label": ctx.label,
                    "archiveSha256": file_sha256(board_path)
                    if ctx.board_kind == "archive"
                    else None,
                    "generation": ctx.snap.generation,
                    "players": len(ctx.contract.get("playersArray") or []),
                    "teams": ctx.snap.team_count,
                    "rostersState": ctx.snap.rosters_state,
                },
                "policy": {
                    "maxTeams": ctx.policy.max_teams,
                    "maxLegs": ctx.policy.max_legs,
                    "participation": ctx.policy.participation,
                },
                "baseUrl": args.base_url,
            },
            "method": {
                "coldSamples": args.cold_samples,
                "warmSamples": args.warm_samples,
                "memorySamples": args.memory_samples,
                "ledgersPerRepresentativeCell": args.ledgers,
                "assetsScreenedOutAsNotPriced": screened_out,
                "seed": args.seed,
                "cold": "ledger snapshot memo + before-roster cache cleared before every sample",
                "warm": "snapshot memo primed",
                "engineIncludes": "snapshot_for + validate_ledger + analyze_trade_n",
                "routeIncludes": "TestClient.post (JSON encode, ASGI, route, JSON response)",
                "publicIncludes": (
                    "TestClient.post to the public analyze route with the flag ON and the "
                    "launch gate opened in-process only: gate, limiter charge, body cap, "
                    "strict schema, ledger validation, admission + single-flight, "
                    "public_advisor.evaluate (market_fairness + reducer + value-free "
                    "assertions), Pydantic response; no response floor (unset)"
                    if args.public_route
                    else None
                ),
                "counterfactuals": {m: counterfactuals_for(m) for m in MODES},
                "stubs": ctx.stubs,
                "stubCaveat": "team_context excludes the real posture-bundle build and the real "
                "scarcity read, and "
                + (
                    "feeds the real roster-utility Monte Carlo LABELLED synthetic projections: "
                    "its numbers are a LOWER bound on those two reads"
                    if args.roster_utility == "labelled"
                    else "uses whatever projection basis this machine holds (none -> Team "
                    "Context ends early): its numbers are NOT an upper or a representative bound"
                ),
                "routeModes": list(ROUTE_MODES),
                "routeNote": route_note,
            },
            "processWarmupMs": warmups,
            "comparables": comparables,
            "scenarios": scenario_desc,
            "results": results,
            "limits": limits,
            "budgets": budgets,
            "breaches": breaches,
            "exitCode": EXIT_BUDGET_BREACH if breaches else EXIT_OK,
        }
        report["findings"] = findings_for(report)
        return report
    finally:
        patches.undo()


def findings_for(report: Mapping[str, Any]) -> list[str]:
    out: list[str] = []
    for b in report["budgets"]:
        if b["status"] == "breach":
            out.append(f"BREACH {b['id']}: observed {b.get('observed')} vs limit {b.get('limit')}")
        elif b["status"] == "not_exercised":
            out.append(f"NOT EXERCISED {b['id']}: {(b.get('detail') or {}).get('note')}")
    results = report["results"]
    cells = [c for s in ("engine", "route", "public") for c in results.get(s) or []]
    gated = [
        c for c in cells if (c.get("structural") or {}).get("outcome", {}).get("evidenceGated")
    ]
    if gated:
        out.append(f"{len(gated)} cells ran an evidence-gated path (not every asset priced)")
    utility = collections.Counter()
    for c in cells:
        if c["mode"] == "team_context":
            for k, v in (
                (c.get("structural") or {}).get("outcome", {}).get("rosterUtility") or {}
            ).items():
                utility[k] += v
    if utility:
        out.append(f"team_context roster utility outcomes: {dict(utility)}")
    comp = report.get("comparables")
    if comp:
        out.append(
            f"comparables lookup (per team, N={comp['teamCount']}): state {comp['lookupState']}, "
            f"p50 {comp['perTeamLookupMs']['p50']} ms; {comp['note']}"
        )
    out.append(
        "spec 2.11 states no numeric latency or memory budget; L*/M* are derived from "
        "config/trade/analyze_admission.json (PENDING OWNER CONFIRMATION) and a labelled reference"
    )
    return out


def render_table(report: Mapping[str, Any]) -> str:
    rows = [
        "surface mode             N shape          legs  cold p50 / p95 ms     warm p50 / p95 ms     peak MB (cold/warm)"
    ]
    for surface in ("engine", "route", "public"):
        for c in report["results"].get(surface) or []:
            cold, warm = c["cold"]["totalMs"], c["warm"]["totalMs"]
            mem = c["memory"]
            legs = c["legs"]["max"]
            rows.append(
                f"{surface:6s} {c['mode']:16s} {c['teams']} {c['shape']:14s} {legs:4d}  "
                f"{cold['p50']:>8} / {cold['p95']:<8}   {warm['p50']:>8} / {warm['p95']:<8}   "
                f"{(mem['cold'] or {}).get('max')} / {(mem['warm'] or {}).get('max')}"
            )
    rows.append("")
    for b in report["budgets"]:
        rows.append(
            f"{b['status']:13s} {b['id']}  observed={b.get('observed')} limit={b.get('limit')}"
        )
    return "\n".join(rows)


def parse_team_counts(text: str) -> tuple[int, ...]:
    try:
        counts = tuple(sorted({int(part) for part in str(text).split(",") if part.strip()}))
    except ValueError as exc:
        raise argparse.ArgumentTypeError(f"not a list of integers: {text!r}") from exc
    if not counts or any(n not in TEAM_COUNTS for n in counts):
        raise argparse.ArgumentTypeError(f"team counts must be drawn from {list(TEAM_COUNTS)}")
    return counts


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog=TOOL,
        description="Local latency / memory measurement for the N-team trade engine "
        "(analyze_trade_n and POST /api/trade/analyze-multi). Never against production.",
    )
    p.add_argument("--archive", help=f"archived export zip (default {DEFAULT_ARCHIVE})")
    p.add_argument(
        "--synthetic",
        action="store_true",
        help="measure the LABELLED synthetic 4-team league (engine only)",
    )
    p.add_argument("--skip-route", action="store_true", help="measure the engine only")
    p.add_argument("--skip-engine", action="store_true", help="measure the route only")
    p.add_argument(
        "--public-route",
        action="store_true",
        help="also measure the PUBLIC advisor analyze route end to end (flag ON and launch "
        "gate opened in this process only; no response floor)",
    )
    p.add_argument(
        "--base-url",
        default=DEFAULT_BASE_URL,
        help="TestClient base URL; loopback / testserver only",
    )
    p.add_argument(
        "--roster-utility",
        choices=ROSTER_UTILITY_CHOICES,
        default="labelled",
        help="labelled: LABELLED synthetic projections feed the REAL best-ball Monte Carlo "
        "(default); real: whatever projection basis this machine holds",
    )
    p.add_argument(
        "--team-counts",
        type=parse_team_counts,
        default=TEAM_COUNTS,
        help="comma-separated team counts to measure (default 2,3,4)",
    )
    p.add_argument("--cold-samples", type=int, default=8)
    p.add_argument("--warm-samples", type=int, default=16)
    p.add_argument("--memory-samples", type=int, default=2)
    p.add_argument(
        "--ledgers", type=int, default=5, help="seeded representative ledgers per team count"
    )
    p.add_argument("--seed", type=int, default=20261026)
    p.add_argument(
        "--private-deadline-seconds",
        type=float,
        default=None,
        help="override the private caller deadline",
    )
    p.add_argument(
        "--public-deadline-seconds",
        type=float,
        default=None,
        help="override the public caller deadline",
    )
    p.add_argument("--memory-limit-mb", type=float, default=REFERENCE_MEMORY_LIMIT_MB)
    p.add_argument("--baseline-rss-mb", type=float, default=REFERENCE_BASELINE_RSS_MB)
    p.add_argument("--output", help="write the JSON report here (default: stdout)")
    p.add_argument("--quiet", action="store_true", help="no progress or table on stderr")
    return p


def _validate_args(args: argparse.Namespace) -> str | None:
    for name in ("cold_samples", "warm_samples", "ledgers"):
        if getattr(args, name) < 1:
            return f"--{name.replace('_', '-')} must be >= 1"
    if args.memory_samples < 0:
        return "--memory-samples must be >= 0"
    if args.memory_limit_mb <= args.baseline_rss_mb:
        return "--memory-limit-mb must exceed --baseline-rss-mb"
    return None


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        args.base_url = assert_local_target(args.base_url)
    except TargetRefused as exc:
        print(f"{TOOL}: REFUSED: {exc}", file=sys.stderr)
        return EXIT_REFUSED
    problem = _validate_args(args)
    if problem:
        print(f"{TOOL}: {problem}", file=sys.stderr)
        return EXIT_REFUSED
    if args.quiet:
        sink = open(os.devnull, "w", encoding="utf-8")  # noqa: SIM115
    else:
        sink = None
    try:
        with tempfile.TemporaryDirectory(prefix="measure-trade-") as tmp:
            temp_root = Path(tmp)
            with env_overrides(isolation_env(temp_root)), network_guard():
                isolate_runtime_data(temp_root)
                from src.api import league_registry  # noqa: PLC0415

                league_registry.reload_registry()
                with contextlib.redirect_stderr(sink) if sink else contextlib.nullcontext():
                    report = run_measurement(args, temp_root)
    except MeasurementFailed as exc:
        print(f"{TOOL}: measurement failed: {exc}", file=sys.stderr)
        return EXIT_MEASUREMENT_FAILED
    finally:
        if sink is not None:
            sink.close()
    text = json.dumps(report, indent=2, default=str)
    if args.output:
        Path(args.output).write_text(text + "\n", encoding="utf-8")
    else:
        print(text)
    if not args.quiet:
        print("\n" + render_table(report), file=sys.stderr)
    return int(report["exitCode"])


if __name__ == "__main__":
    sys.exit(main())
